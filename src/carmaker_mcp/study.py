"""Parameter studies: run one test run several times with different values, one after another.

A study runs on a background thread, so the tool call that starts it returns at once and the agent
polls. Nothing is written to project files: infofile keys are applied in memory (ScriptControl
``KeyValue`` in the MATLAB-connected session, cmapi overrides for standalone runs) and MATLAB
workspace values are put back after each run.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import lock, timing
from .backend import BackendError
from .results import Erg, ErgError
from .session import Session

_KEY = re.compile(r"^[A-Za-z0-9_]+(:[A-Za-z0-9_.]+)?(\.[A-Za-z0-9_]+)*$")
_ALLOWED = {"label", "keys", "workspace", "driver"}
_TEMPLATE = "Vehicle.DriverTemplate.FName"
DEFAULT_QUANTITIES = ["Time", "Car.v"]


def check_variations(variations: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    out = []
    for i, v in enumerate(variations):
        if not isinstance(v, dict) or set(v) - _ALLOWED:
            raise BackendError(f"variation {i + 1}: use only the fields {sorted(_ALLOWED)}")
        keys, ws, drv = v.get("keys") or {}, v.get("workspace") or {}, v.get("driver") or {}
        if not isinstance(keys, dict) or not isinstance(ws, dict) or not isinstance(drv, dict):
            raise BackendError(f"variation {i + 1}: 'keys', 'workspace' and 'driver' must be objects")
        bad = [k for k in drv if not str(k).startswith("Driver.")]
        if bad:
            raise BackendError(f"variation {i + 1}: 'driver' takes Driver.* keys only, not {bad}")
        for k in keys:
            if not _KEY.match(str(k)):
                raise BackendError(f"variation {i + 1}: invalid infofile key {k!r}")
        if ws and mode == "standalone":
            raise BackendError("standalone runs have no MATLAB workspace: use 'keys' only, or mode 'cm4sl'")
        out.append({"label": str(v.get("label") or f"run {i + 1}"), "keys": dict(keys),
                    "workspace": dict(ws), "driver": dict(drv)})
    return out


_ROW = ("label", "valid", "abort_reason", "vehicle", "driver_template", "driver", "end_status",
        "sim_time_s", "distance_m", "wall_s", "sectors", "splits", "gates_on",
        "result_file", "logs_file", "stopped", "error", "logs_error", "log_errors", "log_warnings",
        "restore_errors", "missing_quantities", "result_error", "gates_error", "kept_open")
_STATS = ("min", "max", "mean", "last")


MAX_RUNS = 100


def grid_variations(grid: dict[str, dict[str, list]]) -> list[dict]:
    """Every combination of the listed values: {'keys': {k: [...]}, 'driver': {...}, 'workspace': {...}}.
    Labels name the values; a long value (a table) is named by its position, #1, #2..."""
    import itertools

    if set(grid) - {"keys", "driver", "workspace"}:
        raise BackendError("grid takes 'keys', 'driver' and 'workspace'")
    axes = []  # (group, name, values), in the order given: the labels follow it
    for group, entries in grid.items():
        for name, values in (entries or {}).items():
            if not isinstance(values, list) or not values:
                raise BackendError(f"grid {group} {name!r}: give a non-empty list of values")
            axes.append((group, name, values))
    if not axes:
        return []
    out = []
    for combo in itertools.product(*[range(len(v)) for _, _, v in axes]):
        var: dict[str, Any] = {"keys": {}, "driver": {}, "workspace": {}}
        label = []
        for (group, name, values), i in zip(axes, combo, strict=True):
            value = values[i]
            var[group][name] = value
            text = str(value)
            short = name.split(".")[-1]
            label.append(f"{short}={text}" if len(text) <= 12 and "\n" not in text else f"{short}#{i + 1}")
        var["label"] = " ".join(label)
        out.append({k: v for k, v in var.items() if v})
    return out


def licence_trouble(row: dict) -> str | None:
    """The licence message of a run that could not start for lack of a CarMaker licence."""
    for text in [row.get("error") or "", *(row.get("log_errors") or [])]:
        if "licens" in text.lower():
            return text[:300]
    return None


def abort_reason(errors: list[str]) -> str:
    """The most telling line: CarMaker's own reason (e.g. the car left the road) before library noise."""
    for key in ("leave", "left the", "spin", "stand", "abort"):
        for e in errors:
            if key in e.lower():
                return e[:160]
    return errors[0][:160]


def _brief(row: dict) -> dict:
    out: dict[str, Any] = {"label": row.get("label"), "valid": row.get("valid"),
                           "status": row.get("end_status")}
    if row.get("sectors"):
        out["sectors"] = [s["time"] for s in row["sectors"]]
    elif row.get("splits"):
        out["splits"] = row["splits"]
    for k, n in (("abort_reason", 160), ("error", 200)):
        if row.get(k):
            out[k] = str(row[k])[:n]
    return out


def metric(row: dict, rank_by: str) -> float | None:
    """'sectors' (mean of the sector times), 'splits' (their sum), 'sim_time', or '<quantity>.<stat>'
    (e.g. 'Car.v.max'). None when the run has no such value."""
    if rank_by == "sectors":
        times = [s["time"] for s in row.get("sectors") or []]
        return sum(times) / len(times) if times and None not in times else None
    if rank_by == "splits":
        splits = row.get("splits") or []
        return sum(splits) if splits and None not in splits else None
    if rank_by == "sim_time":
        return row.get("sim_time_s")
    name, _, stat = rank_by.rpartition(".")
    q = (row.get("quantities") or {}).get(name) or {}
    v = q.get(stat)
    return float(v) if isinstance(v, (int, float)) else None


def _short(v: Any) -> Any:
    """Six significant digits: a result file's single-precision values carry no more."""
    return float(f"{v:.6g}") if isinstance(v, float) else v


def _compact(row: dict) -> dict:
    out = {k: row[k] for k in _ROW if row.get(k) not in (None, [], "")}
    if row.get("quantities"):
        out["quantities"] = {name: {k: _short(q[k]) for k in _STATS if k in q}
                             for name, q in row["quantities"].items()}
    return out


class StudyRunner:
    def __init__(self, session: Session, standalone: Callable[[], Any]):
        self.session = session
        self._standalone = standalone
        self._studies: dict[str, dict] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._progress: dict[str, threading.Condition] = {}
        self._lock = threading.Lock()
        self._n = 0

    # ---- public --------------------------------------------------------------------
    def start(self, testrun: str, variations: list[dict[str, Any]] | None = None,
              quantities: list[str] | None = None,
              mode: str = "auto", scope: str = "base", max_run_s: float = 900.0,
              save_logs: bool = False, movie: bool = False, speed: float | None = None,
              gates: list[float] | str | None = None, keep_open: bool = False,
              grid: dict | None = None, close_open: bool = False) -> dict:
        if mode == "auto":  # found in use: cm4sl as the default failed where only standalone was ready
            try:
                mode = "cm4sl" if self.session.backend.status().connected else "standalone"
            except BackendError:
                mode = "standalone"
        if mode not in ("cm4sl", "standalone"):
            raise BackendError("mode must be 'auto', 'cm4sl' or 'standalone'")
        if movie and mode != "standalone":
            raise BackendError("movie is for mode 'standalone'; in the MATLAB session open IPGMovie with "
                               "cm_movie_open before the study")
        if save_logs and mode != "cm4sl":
            raise BackendError("save_logs needs the MATLAB-connected session (mode 'cm4sl')")
        variations = list(variations or []) + grid_variations(grid or {})
        if not variations:
            raise BackendError("give variations, a grid, or both")
        if len(variations) > MAX_RUNS:
            raise BackendError(f"{len(variations)} runs: at most {MAX_RUNS} per study")
        runs = check_variations(variations, mode)
        markers = None
        if gates == "markers":  # the test run's trigger points, as the CarMaker instrument times them
            markers = timing.trigger_markers(self.session.project.read("testrun", testrun,
                                                                         max_items=100000)["values"])
            if not any(m["mode"] in (2, 3) for m in markers):
                raise BackendError(f"{testrun} has no trigger point markers that take a time (mode 2 or 3)")
            gates = None
        elif isinstance(gates, str):
            raise BackendError("gates is a list of road positions in m, or 'markers'")
        template = self._driver_template(testrun)
        for v in runs:
            if v["driver"] and v["keys"].get(_TEMPLATE, template) in (None, "", "TestRun"):
                v["keys"].update(v["driver"])  # the driver is the one saved in the test run itself
                v["driver"] = {}
        overruled = sorted({k for v in runs for k in v["keys"] if k.startswith("Driver.")
                            and v["keys"].get(_TEMPLATE, template) not in (None, "", "TestRun")})
        if overruled:  # checked live: such keys change nothing, so the runs would only repeat the baseline
            raise BackendError(
                f"the test run takes its driver from the template {template!r}, which overrides "
                f"{', '.join(overruled)} given as 'keys': those runs would repeat the baseline. Put driver "
                "values in each variation's 'driver' instead (a temporary template copy per run)")
        known_keys = self._known_keys(testrun, runs)
        names = sorted({n for v in runs for n in v["workspace"]})
        ws: dict[str, Any] = (self.session.workspace_check(names, scope) if names
                              else {"new": [], "overruled": []})
        open_note = self._open_instances(mode, close_open)
        with self._lock:
            active = [s["id"] for s in self._studies.values() if s["state"] == "running"]
            if active:
                raise BackendError(f"study {active[0]} is still running (cm_study_status, cm_study_cancel)")
            if mode == "cm4sl":
                self.session.require_idle("start a study")
            self._n += 1
            sid = f"{self.session.store.session}-s{self._n}"
            st = {
                "id": sid, "state": "running", "testrun": testrun, "mode": mode, "scope": scope,
                "quantities": list(quantities or DEFAULT_QUANTITIES), "max_run_s": max_run_s,
                "save_logs": bool(save_logs), "movie": bool(movie), "speed": speed,
                "gates": [float(g) for g in gates or []], "markers": markers, "driver_template": template,
                "keep_open": bool(keep_open and movie), "vehicle": self._vehicle(testrun),
                "started": time.strftime("%Y-%m-%d %H:%M:%S"), "total": len(runs), "current": 0,
                "current_label": None, "rows": [], "variations": runs,
            }
            self._studies[sid] = st
            self._cancel[sid] = threading.Event()
            self._progress[sid] = threading.Condition()
            self._save(st)
            t = threading.Thread(target=self._work, args=(st,), name=f"study-{sid}", daemon=True)
            self._threads[sid] = t
            t.start()
        out: dict[str, Any] = {"study": sid, "runs": len(runs), "state": "running", "mode": mode,
                               "note": "cm_study_wait blocks until the next run has finished; "
                                       "cm_study_status shows the table"}
        out.update(open_note)
        used = {k for v in runs for k in v["keys"]}
        unknown = sorted(used - set(known_keys)) if known_keys is not None else []
        if unknown:
            out["keys_not_found"] = unknown
            out["note"] += (". keys_not_found occur neither in the test run nor in its vehicle file: a key "
                            "the files leave to its default looks like that, and so does a misspelt one, "
                            "which changes nothing")
        if ws["overruled"]:
            out["workspace_overruled"] = ws["overruled"]
            out["note"] += (f". workspace_overruled: the model {ws['model']} has variables of these names in "
                            "its own workspace and uses those, so the values set in the base workspace have "
                            f"no effect on it. Cancel and start again with scope='{ws['model']}'")
        new = [n for n in ws["new"] if n not in ws["overruled"]]
        if new:
            out["workspace_not_found"] = new
            out["note"] += (". workspace_not_found did not exist in the workspace before: a misspelt name "
                            "changes nothing")
        return out

    def status(self, study: str | None = None, detail: str = "compact", rank_by: str | None = None) -> dict:
        """``brief``: one line per run (label, valid, status, sector times, short abort reason).
        ``compact``: also the statistics per quantity and the result file. ``full``: everything,
        including every run's keys and workspace values. ``rank_by`` adds a ranking (see ``metric``)."""
        if detail not in ("brief", "compact", "full"):
            raise BackendError("detail must be 'brief', 'compact' or 'full'")
        st = self._get(study)
        if detail == "full":
            out = {k: v for k, v in st.items() if k != "variations" and not k.startswith("_")}
            out["done"] = len(st["rows"])
        else:
            out = {k: st[k] for k in ("id", "state", "testrun", "total", "current_label", "started",
                                      "finished", "cancelled", "error", "kept_open") if st.get(k) is not None}
            out["done"] = len(st["rows"])
            out["rows"] = [_brief(r) if detail == "brief" else _compact(r) for r in st["rows"]]
        if rank_by:
            out.update(self._ranking(st["rows"], rank_by))
        return out

    @staticmethod
    def _ranking(rows: list[dict], rank_by: str) -> dict:
        desc = rank_by.startswith("-")
        key = rank_by.lstrip("-")
        ranked = sorted([(v, r["label"]) for r in rows
                         if r.get("valid") and (v := metric(r, key)) is not None], reverse=desc)
        return {"ranking": [{"label": label, key: round(v, 4)} for v, label in ranked],
                "ranking_by": f"{key} ({'largest' if desc else 'smallest'} first; valid runs only)",
                "not_ranked": [r["label"] for r in rows
                               if not r.get("valid") or metric(r, key) is None]}

    def wait_progress(self, study: str | None = None, timeout_s: float = 45.0,
                      until_done: bool = False, detail: str = "brief") -> dict:
        """Block until another run of the study has finished (or, ``until_done``, until the study has
        ended), at most ``timeout_s``. Returns the rows no earlier wait has returned: a cursor per
        study, so rows that finished between calls, or during a parallel call, are not lost."""
        st = self._get(study)
        cond = self._progress[st["id"]]
        t0 = time.time()
        with cond:
            # after the last run the end of the study follows at once: wait for that
            cond.wait_for(lambda: st["state"] != "running" or (
                not until_done and st.get("_delivered", 0) < len(st["rows"]) < st["total"]), timeout_s)
            first = st.get("_delivered", 0)
            st["_delivered"] = len(st["rows"])
        out = self.status(st["id"], detail)
        out["waited_s"] = round(time.time() - t0, 1)
        out["rows"] = out["rows"][first:st["_delivered"]]
        out["new_rows"] = len(out["rows"])
        return out

    def cancel(self, study: str | None = None, by: str = "cm_study_cancel") -> dict:
        st = self._get(study)
        if st["state"] != "running":
            return {"study": st["id"], "state": st["state"], "note": "not running"}
        st["cancelled"] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "by": by,
                           "during": st.get("current_label")}
        self._cancel[st["id"]].set()
        self._threads[st["id"]].join(90)
        return {"study": st["id"], "state": st["state"], "done": len(st["rows"]), "total": st["total"]}

    def wait(self, study: str | None = None, timeout: float = 60.0) -> dict:
        """Block until the study has ended (tests and scripts; tools poll instead)."""
        st = self._get(study)
        self._threads[st["id"]].join(timeout)
        return self.status(st["id"], "full")

    # ---- internals -------------------------------------------------------------------
    def _get(self, study: str | None) -> dict:
        if not self._studies:
            raise BackendError("no study has been started in this session")
        if study is None:
            return list(self._studies.values())[-1]
        if study not in self._studies:
            raise BackendError(f"unknown study {study!r}; known: {', '.join(self._studies)}")
        return self._studies[study]

    def _vehicle(self, testrun: str) -> str | None:
        try:
            return self.session.project.read("testrun", testrun, keys=["Vehicle"])["values"].get("Vehicle")
        except Exception:
            return None

    def _open_instances(self, mode: str, close: bool) -> dict:
        """Standalone programs this server left open (keep_open, start=false) each hold a licence: close
        them on request, else name them (found in use: a study then failed run after run)."""
        if mode != "standalone":
            return {}
        sa = self._standalone()
        own = sa.own_instances() if hasattr(sa, "own_instances") else []
        if not own:
            return {}
        if close:
            for inst in own:
                try:
                    sa.close(inst["instance"])
                except BackendError:
                    pass
            return {"closed_open": [i["instance"] for i in own]}
        return {"open_instances": own,
                "open_note": "each open instance holds a CarMaker licence; if runs fail for lack of one, "
                             "close them (cm_standalone_close) or start with close_open=true"}

    def _driver_template(self, testrun: str) -> str | None:
        try:
            return self.session.project.read("testrun", testrun, keys=[_TEMPLATE])["driver"].get("template")
        except Exception:
            return None

    def movie_instance(self, study: str | None = None) -> str | None:
        return self._get(study).get("_instance")

    def _run(self, st: dict, i: int, var: dict, cancel: threading.Event, one: Callable) -> dict:
        """One run; 'driver' values go into a temporary copy of the driver template for that run only."""
        if not var.get("driver"):
            return one(st, var, cancel)
        base = var["keys"].get(_TEMPLATE, st.get("driver_template"))
        name = f".mcp_{st['id']}_{i + 1}"
        try:
            path = self.session.project.temp_driver(str(base), var["driver"], name)
        except Exception as e:
            return {"label": var["label"], "keys": var["keys"], "driver": var["driver"],
                    "error": f"driver: {e}"}
        try:
            row = one(st, {**var, "keys": {**var["keys"], _TEMPLATE: name}}, cancel)
        finally:
            try:
                path.unlink()
            except OSError:
                pass
        row["driver"] = var["driver"]
        return row

    @staticmethod
    def _valid(row: dict, st: dict) -> bool:
        """The run completed and, with gates, passed every gate."""
        if row.get("end_status") != "completed" or row.get("error"):
            return False
        if st.get("markers"):
            return bool(row.get("sectors")) and all(s["time"] is not None for s in row["sectors"])
        return not st.get("gates") or (bool(row.get("splits")) and None not in row["splits"])

    def _gates(self, row: dict, st: dict) -> None:
        """Lap and sector times: between gate positions, or at the test run's trigger point markers.
        Timed on the road position Vhcl.sRoad when the file holds it (the odometer reads long)."""
        if not (st.get("gates") or st.get("markers")) or not row.get("result_file"):
            return
        try:
            erg = Erg(Path(row["result_file"]))
            if st.get("markers"):
                t = timing.sector_times(erg, st["markers"])
                row["sectors"], row["gates_on"] = t["sectors"], t["on"]
                return
            on = "Vhcl.sRoad" if "Vhcl.sRoad" in erg.names else "Car.Distance"
            c = erg.crossings(on, st["gates"], "rising")
            row["splits"] = [None if b is None else round(b, 4) for b in c["between_first"]]
            row["gates_on"] = on
        except (ErgError, OSError) as e:
            row["gates_error"] = str(e)

    def _known_keys(self, testrun: str, runs: list[dict]) -> list[str] | None:
        """The override keys that the test run or its vehicle file contain (None: could not look)."""
        keys = sorted({k for v in runs for k in v["keys"]})
        try:
            missing = self.session.keys_not_found(testrun, keys)
        except BackendError:
            return None
        return [k for k in keys if k not in missing]

    def _announce(self, st: dict) -> None:
        """Tell waiting callers, and other server processes, where the study stands."""
        if st["mode"] == "cm4sl":
            if st["state"] == "running":
                lock.write(self.session.cfg.state_dir, {
                    "study": st["id"], "testrun": st["testrun"], "total": st["total"],
                    "done": len(st["rows"]), "current_label": st.get("current_label"),
                    "started": st["started"]})
            else:
                lock.clear(self.session.cfg.state_dir)
        cond = self._progress.get(st["id"])
        if cond is not None:
            with cond:
                cond.notify_all()

    def _save(self, st: dict) -> None:
        self._announce(st)
        try:
            d = Path(self.session.store.dir) / "studies"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{st['id']}.json").write_text(json.dumps(st, indent=1, default=str), encoding="utf-8")
        except OSError:
            pass

    def _work(self, st: dict) -> None:
        cancel = self._cancel[st["id"]]
        one = self._one_cm4sl if st["mode"] == "cm4sl" else self._one_standalone
        if st["mode"] == "cm4sl":
            self.session.study_owner = threading.get_ident()
        try:
            for i, var in enumerate(st["variations"]):
                if cancel.is_set():
                    break
                st["current"], st["current_label"] = i + 1, var["label"]
                self._announce(st)  # other processes see which run is on
                row = self._run(st, i, var, cancel, one)
                row["valid"] = self._valid(row, st)
                # what the run used, so a reader can confirm it from the table (asked for in use)
                row["vehicle"] = var["keys"].get("Vehicle", st.get("vehicle"))
                row["driver_template"] = var["keys"].get(_TEMPLATE, st.get("driver_template"))
                if row.get("log_errors") and not row["valid"]:
                    row["abort_reason"] = abort_reason(row["log_errors"])
                    row["log_errors"] = row["log_errors"][:5]
                st["rows"].append(row)
                self._save(st)
                trouble = licence_trouble(row)
                if trouble:  # every further run would fail the same way
                    st["error"] = (f"stopped after run {i + 1}: no CarMaker licence ({trouble}). Close the "
                                   "programs that hold one (cm_standalone_servers, cm_standalone_close), or "
                                   "start the study again with close_open=true")
                    break
            st["state"] = "failed" if st.get("error") else "cancelled" if cancel.is_set() else "done"
        except Exception as e:  # a bug must not leave the study 'running' for ever
            st["state"], st["error"] = "failed", f"{type(e).__name__}: {e}"
        finally:
            if st.get("keep_open") and st.get("_instance"):
                st["kept_open"] = st["_instance"]  # the last run stays in IPGMovie
            else:
                self._close_standalone(st)
            self.session.study_owner = None
            st["current_label"] = None
            st["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._save(st)

    def _summarise(self, row: dict, st: dict) -> None:
        self._gates(row, st)
        if not row.get("result_file"):
            return
        try:
            erg = Erg(Path(row["result_file"]))
            names = [q for q in st["quantities"] if q in erg.names]
            row["quantities"] = erg.summary(names)["quantities"]
            missing = [q for q in st["quantities"] if q not in erg.names]
            if missing:
                row["missing_quantities"] = missing
        except (ErgError, OSError) as e:
            row["result_error"] = str(e)

    def _one_cm4sl(self, st: dict, var: dict, cancel: threading.Event) -> dict:
        s = self.session
        row: dict[str, Any] = {"label": var["label"], "keys": var["keys"], "workspace": var["workspace"]}
        changed: list[tuple[str, Any, bool]] = []
        try:
            for name, value in var["workspace"].items():
                r = s.workspace_set(name, value, st["scope"])
                changed.append((name, r["old"], r["existed"]))
            s.load_testrun(st["testrun"])
            s.key_values(var["keys"])
            # The logs are saved when the end of the run is reported, that is before the workspace
            # values are put back below: the file holds the values this run used.
            s.start_sim(start_timeout_s=min(st["max_run_s"], 300), save_logs=st.get("save_logs", False),
                        speed=st.get("speed"))
            t0 = time.time()
            while True:
                end = s.wait_end(timeout_s=2, poll_s=0.5)
                if end["finished"]:
                    break
                if cancel.is_set() or time.time() - t0 > st["max_run_s"]:
                    row["stopped"] = "cancelled" if cancel.is_set() else f"max_run_s ({st['max_run_s']:g} s)"
                    end = s.stop_sim(wait_s=60)
                    break
            for k in ("end_status", "sim_time_s", "distance_m", "result_file", "logs_file", "logs_error",
                      "log_errors", "log_warnings", "popups"):
                if end.get(k) is not None:
                    row[k] = end[k]
            row["wall_s"] = round(time.time() - t0, 1)
            self._summarise(row, st)
        except BackendError as e:
            row["error"] = str(e)
        finally:
            problems = []
            for name, old, existed in reversed(changed):
                try:
                    if existed:
                        s.workspace_set(name, old, st["scope"])
                    else:
                        s.workspace_clear(name, st["scope"])
                except BackendError as e:
                    problems.append(f"{name}: {e}")
            if var["keys"]:
                try:
                    s.key_values({})
                except BackendError as e:
                    problems.append(f"KeyValue reset: {e}")
            if problems:
                row["restore_errors"] = problems
        return row

    def _one_standalone(self, st: dict, var: dict, cancel: threading.Event) -> dict:
        """One run on the study's program. With movie the program, and its IPGMovie window, stay
        open from run to run (found in use: a window per run closed before anything could be seen);
        a program that ended is replaced by a new one."""
        sa = self._standalone()
        row: dict[str, Any] = {"label": var["label"], "keys": var["keys"], "workspace": {}}
        keep = bool(st.get("movie"))
        inst = st.get("_instance") if keep else None
        try:
            timed = ["Vhcl.sRoad", "DM.TriggerPoint.Time", "DM.TriggerPoint.Id"] \
                if st.get("gates") or st.get("markers") else []
            store = sorted({"Time", "Car.v", "Car.Distance", *timed, *st["quantities"]})
            args = {"overrides": var["keys"] or None, "quantities": store, "realtime_factor": st.get("speed")}
            if inst is not None:
                try:
                    sa.rerun(inst, st["testrun"], **args)
                except BackendError:
                    self._close_standalone(st)
                    inst = None
            if inst is None:
                inst = sa.launch(st["testrun"], movie=keep, **args)["instance"]
                if keep:
                    st["_instance"] = inst
            t0 = time.time()
            while True:
                end = sa.wait_end(inst, 2)
                if end["finished"]:
                    break
                if cancel.is_set() or time.time() - t0 > st["max_run_s"]:
                    row["stopped"] = "cancelled" if cancel.is_set() else f"max_run_s ({st['max_run_s']:g} s)"
                    sa.control("stop", inst)
                    end = sa.wait_end(inst, 60)
                    break
            row["end_status"] = "completed" if end.get("error_flag") in (0, None) and not row.get("stopped") \
                else "aborted"
            for src, dst in (("sim_time_s", "sim_time_s"), ("sim_dist_m", "distance_m"),
                             ("error_flag", "error_flag"), ("stop_reason", "stop_reason")):
                if end.get(src) is not None:
                    row[dst] = end[src]
            row["wall_s"] = round(time.time() - t0, 1)
            for k in ("log_errors", "log_warnings"):
                if end.get(k):
                    row[k] = end[k]
            files = sa.results(inst).get("result_files") or []
            row["result_file"] = files[-1] if files else None
            self._summarise(row, st)
        except BackendError as e:
            row["error"] = str(e)
        finally:
            if inst is not None and not keep:
                try:
                    sa.close(inst)
                except BackendError as e:
                    row["restore_errors"] = [f"close: {e}"]
        return row

    def _close_standalone(self, st: dict) -> None:
        """Close the program a study kept open for its runs (and IPGMovie with it)."""
        inst = st.pop("_instance", None)
        if inst is not None:
            try:
                self._standalone().close(inst)
            except BackendError:
                pass
