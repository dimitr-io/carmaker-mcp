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

from . import lock
from .backend import BackendError
from .results import Erg, ErgError
from .session import Session

_KEY = re.compile(r"^[A-Za-z0-9_]+(:[A-Za-z0-9_.]+)?(\.[A-Za-z0-9_]+)*$")
_ALLOWED = {"label", "keys", "workspace"}
DEFAULT_QUANTITIES = ["Time", "Car.v"]


def check_variations(variations: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    out = []
    for i, v in enumerate(variations):
        if not isinstance(v, dict) or set(v) - _ALLOWED:
            raise BackendError(f"variation {i + 1}: use only the fields {sorted(_ALLOWED)}")
        keys, ws = v.get("keys") or {}, v.get("workspace") or {}
        if not isinstance(keys, dict) or not isinstance(ws, dict):
            raise BackendError(f"variation {i + 1}: 'keys' and 'workspace' must be objects")
        for k in keys:
            if not _KEY.match(str(k)):
                raise BackendError(f"variation {i + 1}: invalid infofile key {k!r}")
        if ws and mode == "standalone":
            raise BackendError("standalone runs have no MATLAB workspace: use 'keys' only, or mode 'cm4sl'")
        out.append({"label": str(v.get("label") or f"run {i + 1}"), "keys": dict(keys),
                    "workspace": dict(ws)})
    return out


_ROW = ("label", "end_status", "sim_time_s", "distance_m", "result_file", "logs_file", "stopped", "error",
        "logs_error", "log_errors", "log_warnings", "restore_errors", "missing_quantities", "result_error")
_STATS = ("min", "max", "mean", "last")


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
    def start(self, testrun: str, variations: list[dict[str, Any]], quantities: list[str] | None = None,
              mode: str = "cm4sl", scope: str = "base", max_run_s: float = 900.0,
              save_logs: bool = False, movie: bool = False, speed: float | None = None) -> dict:
        if mode not in ("cm4sl", "standalone"):
            raise BackendError("mode must be 'cm4sl' or 'standalone'")
        if movie and mode != "standalone":
            raise BackendError("movie is for mode 'standalone'; in the MATLAB session open IPGMovie with "
                               "cm_movie_open before the study")
        if save_logs and mode != "cm4sl":
            raise BackendError("save_logs needs the MATLAB-connected session (mode 'cm4sl')")
        runs = check_variations(variations, mode)
        known_keys = self._known_keys(testrun, runs)
        names = sorted({n for v in runs for n in v["workspace"]})
        ws: dict[str, Any] = (self.session.workspace_check(names, scope) if names
                              else {"new": [], "overruled": []})
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
        out: dict[str, Any] = {"study": sid, "runs": len(runs), "state": "running",
                               "note": "cm_study_wait blocks until the next run has finished; "
                                       "cm_study_status shows the table"}
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

    def status(self, study: str | None = None, detail: str = "compact") -> dict:
        """``compact``: what a caller needs while it waits (no parameter values, four statistics per
        quantity). ``full``: everything, including every run's keys and workspace values."""
        if detail not in ("compact", "full"):
            raise BackendError("detail must be 'compact' or 'full'")
        st = self._get(study)
        if detail == "full":
            out = {k: v for k, v in st.items() if k != "variations"}
            out["done"] = len(st["rows"])
            return out
        out = {k: st[k] for k in ("id", "state", "testrun", "total", "current_label", "started", "finished",
                                  "cancelled", "error") if st.get(k) is not None}
        out["done"] = len(st["rows"])
        out["rows"] = [_compact(r) for r in st["rows"]]
        return out

    def wait_progress(self, study: str | None = None, timeout_s: float = 45.0) -> dict:
        """Block until another run of the study has finished or the study has ended, at most
        ``timeout_s``. Returns the compact status."""
        st = self._get(study)
        cond = self._progress[st["id"]]
        done, t0 = len(st["rows"]), time.time()
        with cond:
            # after the last run the end of the study follows at once: wait for that
            cond.wait_for(lambda: st["state"] != "running" or done < len(st["rows"]) < st["total"],
                          timeout_s)
        out = self.status(st["id"])
        out["waited_s"] = round(time.time() - t0, 1)
        out["new_rows"] = len(st["rows"]) - done
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
                st["rows"].append(one(st, var, cancel))
                self._save(st)
            st["state"] = "cancelled" if cancel.is_set() else "done"
        except Exception as e:  # a bug must not leave the study 'running' for ever
            st["state"], st["error"] = "failed", f"{type(e).__name__}: {e}"
        finally:
            self.session.study_owner = None
            st["current_label"] = None
            st["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._save(st)

    def _summarise(self, row: dict, st: dict) -> None:
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
        sa = self._standalone()
        row: dict[str, Any] = {"label": var["label"], "keys": var["keys"], "workspace": {}}
        inst = None
        try:
            store = sorted({"Time", "Car.v", "Car.Distance", *st["quantities"]})
            inst = sa.launch(st["testrun"], overrides=var["keys"] or None, quantities=store,
                             movie=st.get("movie", False), realtime_factor=st.get("speed"))["instance"]
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
            if end.get("log_errors"):
                row["log_errors"] = end["log_errors"]
            files = sa.results(inst).get("result_files") or []
            row["result_file"] = files[-1] if files else None
            self._summarise(row, st)
        except BackendError as e:
            row["error"] = str(e)
        finally:
            if inst is not None:
                try:
                    sa.close(inst)
                except BackendError as e:
                    row["restore_errors"] = [f"close: {e}"]
        return row
