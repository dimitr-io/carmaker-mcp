"""Read, edit and clone CarMaker project data files (test runs, vehicles, drivers, tyres...)."""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

from .guard import GuardError, PathGuard, is_within
from .infofile import InfoFile, InfoFileError, diff_values
from .state import StateStore

# kind -> folder below <project>/Data
KINDS = {
    "testrun": "TestRun",
    "vehicle": "Vehicle",
    "driver": "Driver",
    "tire": "Tire",
    "road": "Road",
    "trailer": "Trailer",
    "kinematics": "Kinematics",
    "config": "Config",
    "chassis": "Chassis",
    "misc": "Misc",
    "sensor": "Sensor",
    "traffic": "Traffic",
    "script": "Script",
}


MAX_CREATE_BYTES = 2_000_000  # of a file written by cm_create

# What a test run's IPGDriver is: chosen by the test run, not by the vehicle.
DRIVER_TEMPLATE = "Vehicle.DriverTemplate.FName"  # a file in Data/Driver/Template, or "TestRun"
DRIVER_KEYS = (
    "Driver.Mode", "Driver.Course.CornerCutCoef",
    "Driver.Acc.axMax", "Driver.Acc.axMin", "Driver.Acc.ayMax", "Driver.Acc.GGExp",
    "Driver.Acc.Factor.Lateral", "Driver.Acc.Factor.Accel", "Driver.Acc.Factor.Decel",
    "Driver.Acc.UseVelDepend", "Driver.Long.dtAccBrake",
    "Driver.Vel.dtMinAccelDecel", "Driver.Long.TractionControl", "Driver.Lat.StWhlAngleMax",
    "Driver.Lat.StWhlAngleVelMax", "Driver.Lat.StWhlAngleAccMax",
)


def timing_summary(testrun: dict[str, str]) -> dict:
    """How the test run ends and is timed: its manoeuvre end conditions, lap driving, and the trigger
    point markers that take times (asked for in use: they sit at the end of a long file)."""
    from .timing import trigger_markers

    ends = sorted({v for k, v in testrun.items()
                   if k.startswith("DrivMan.") and k.endswith(".EndCond") and v})
    out: dict[str, Any] = {"end_conditions": ends}
    if testrun.get("Driver.Course.LapDriving", "").strip() == "1":
        out["lap_driving"] = True
    markers = trigger_markers(testrun)
    if markers:
        out["markers"] = [{"id": m["id"], "s": round(m["s"], 3), "mode": m["mode"]} for m in markers]
    return out


class ProjectError(Exception):
    pass


class Project:
    def __init__(self, root: Path, guard: PathGuard, store: StateStore):
        self.root = Path(root)
        self.guard = guard
        self.store = store

    # ---- paths -------------------------------------------------------------
    def kind_dir(self, kind: str) -> Path:
        if kind not in KINDS:
            raise ProjectError(f"unknown kind {kind!r}; choose one of {sorted(KINDS)}")
        return self.root / "Data" / KINDS[kind]

    def path(self, kind: str, name: str) -> Path:
        name = name.replace("\\", "/").strip("/")
        if not name:
            raise ProjectError("empty name")
        p = self.guard.resolve(self.kind_dir(kind) / name)
        base = self.guard.resolve(self.kind_dir(kind))
        if not is_within(p, base):
            raise GuardError(f"{name!r} is outside Data/{KINDS[kind]}")
        return p

    # ---- listing -----------------------------------------------------------
    def list(
        self, kind: str, pattern: str | None = None, include_hidden: bool = False, limit: int = 500
    ) -> dict:
        base = self.kind_dir(kind)
        if not base.exists():
            return {"kind": kind, "names": [], "total": 0}
        names = []
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(base).as_posix()
            parts = rel.split("/")
            if any(x.startswith(".tmp") for x in parts):
                continue
            if not include_hidden and any(x.startswith(".") for x in parts):
                continue
            if pattern and not fnmatch.fnmatch(rel.lower(), pattern.lower()):
                continue
            names.append(rel)
        return {"kind": kind, "names": names[:limit], "total": len(names), "truncated": len(names) > limit}

    # ---- reading -----------------------------------------------------------
    def _load(self, kind: str, name: str) -> tuple[Path, InfoFile]:
        p = self.path(kind, name)
        if not p.is_file():
            raise ProjectError(f"{kind} {name!r} not found")
        info = InfoFile.load(p)
        return p, info

    def read(
        self, kind: str, name: str, keys: list[str] | None = None, prefix: str | None = None,
        max_items: int = 300, search: str | None = None, offset: int = 0,
    ) -> dict:
        p, info = self._load(kind, name)
        if not info.is_infofile:
            return {"kind": kind, "name": name, "infofile": False, "size_bytes": p.stat().st_size}
        d = info.to_dict()
        if keys:
            d = {k: d[k] for k in keys if k in d}
        if prefix:
            d = {k: v for k, v in d.items() if k.startswith(prefix)}
        if search:  # a part of the key name, any case (asked for in use: a prefix read flooded the context)
            d = {k: v for k, v in d.items() if search.lower() in k.lower()}
        left_out = 0
        if kind == "testrun" and not (keys or prefix or search):
            # found in use: the first page was road geometry and traffic, hundreds of keys
            bulk = [k for k in d if k.startswith(("Road.", "Traffic."))]
            left_out = len(bulk)
            d = {k: v for k, v in d.items() if not k.startswith(("Road.", "Traffic."))}
        total = len(d)
        items = dict(list(d.items())[offset:offset + max_items])
        out: dict = {"kind": kind, "name": name, "infofile": True}
        if kind == "testrun":  # first: the values below may be overruled by its driver template
            out["driver"] = self.driver(info.to_dict())
            out.update(self.standalone_check(info.to_dict()))
            out["timing"] = timing_summary(info.to_dict())
        out.update({"total_keys": total, "returned": len(items), "values": items})
        if offset + len(items) < total:
            out["next_offset"] = offset + len(items)
            out["note"] = (f"keys {offset + 1} to {offset + len(items)} of {total}: read on with "
                           f"offset={offset + len(items)}, or filter with keys, prefix or search")
        elif total == 0 and (keys or prefix or search):
            out["note"] = f"no key matches the filter; the file has {len(info.to_dict())} keys"
        if left_out:
            out["left_out"] = (f"{left_out} Road.* and Traffic.* keys (road geometry, traffic): read them "
                               "with prefix='Road.' or 'Traffic.'")
        return out

    def standalone_check(self, testrun: dict[str, str], overrides: dict[str, Any] | None = None) -> dict:
        """Whether the test run's vehicle can run without MATLAB: parts whose kind is CM4SL are Simulink
        models (e.g. PowerTrain.Control.Kind = CM4SL 1), which only CarMaker for Simulink has."""
        run = {**testrun, **{k: str(v) for k, v in (overrides or {}).items()}}
        vehicle = run.get("Vehicle")
        values = dict(run)
        if vehicle:
            try:
                p = self.path("vehicle", vehicle)
                if p.is_file():
                    values = {**InfoFile.load(p).to_dict(), **run}
            except (OSError, ProjectError, GuardError):
                pass
        parts = {k: v for k, v in values.items() if k.endswith(".Kind") and v.split()[:1] == ["CM4SL"]}
        out: dict[str, Any] = {"standalone": not parts}
        if parts:
            out["simulink_parts"] = parts
        # Checked live: a standalone override of a vehicle key (Body.mass) changed nothing, the result
        # was identical to the baseline; standalone overrides reach only the test run's own keys.
        template = run.get(DRIVER_TEMPLATE) or None
        if template and template != "TestRun" and self._driver_source(run)[1] is None:
            out["missing_driver_template"] = template
        vehicle_keys = sorted(k for k in (overrides or {})
                              if k.split(":", 1)[-1] in values and k.split(":", 1)[-1] not in testrun
                              and k != "Vehicle" and not k.startswith("Driver."))
        if vehicle_keys:
            out["vehicle_keys"] = vehicle_keys
        return out

    def diff(self, kind: str, a: str, b: str, prefix: str | None = None, max_items: int = 300) -> dict:
        """Keys only in a, only in b, and keys whose values differ (whitespace-insensitive)."""
        da, db = (self._load(kind, n)[1].to_dict() for n in (a, b))
        if prefix:
            da = {k: v for k, v in da.items() if k.startswith(prefix)}
            db = {k: v for k, v in db.items() if k.startswith(prefix)}

        def same(x: str, y: str) -> bool:
            return x.split() == y.split()

        differ = {k: [da[k], db[k]] for k in da if k in db and not same(da[k], db[k])}
        out: dict = {"kind": kind, "a": a, "b": b,
                     "only_in_a": {k: da[k] for k in da if k not in db},
                     "only_in_b": {k: db[k] for k in db if k not in da},
                     "differ": differ, "same": sum(1 for k in da if k in db) - len(differ)}
        for key in ("only_in_a", "only_in_b", "differ"):
            if len(out[key]) > max_items:
                out[key] = dict(list(out[key].items())[:max_items])
                out["note"] = f"lists cut to {max_items} keys each: filter with prefix"
        return out

    def driver(self, testrun: dict[str, str]) -> dict:
        """The driver a test run uses: its template (or the parametrization saved in the test run),
        the knowledge it carries and the main limits, read from where they are defined."""
        template = testrun.get(DRIVER_TEMPLATE) or None
        out: dict = {
            "template": template,
            "knowledge_template": testrun.get("Vehicle.KnowledgeTemplate.Name") or None,
            "knowledge_vehicle": testrun.get("Driver.Knowl.0.Vehicle"),
            "knowledge_testrun": testrun.get("Driver.Knowl.0.VehicleLimits.Testrun"),
        }
        source, out["defined_in"] = self._driver_source(testrun)
        if out["defined_in"] is None:
            out["note"] = f"no driver template {template!r} in Data/Driver/Template"
        out["values"] = {k: source[k] for k in DRIVER_KEYS if k in source}
        if source is not testrun:
            # Observed: with a template named, these keys of the test run itself changed nothing.
            own = {k: testrun[k] for k in DRIVER_KEYS if k in testrun and testrun[k] != source.get(k)}
            if own:
                out["unused_testrun_values"] = own
        return {k: v for k, v in out.items() if v is not None or k == "defined_in"}

    def _driver_source(self, testrun: dict[str, str]) -> tuple[dict[str, str], str | None]:
        """Every key of the driver the test run uses, and where they are: its template, or the test run
        itself. ({}, None) when the template it names does not exist."""
        template = testrun.get(DRIVER_TEMPLATE) or None
        if not template or template == "TestRun":
            return testrun, "this test run"
        for name in ("Template/" + template, template):
            try:
                p = self.path("driver", name)
            except (ProjectError, GuardError):
                continue
            if p.is_file():
                return InfoFile.load(p).to_dict(), f"driver {name}"
        return {}, None

    def driver_values(self, testrun: str) -> dict[str, str]:
        """The driver keys the test run's runs use (for scaling them in a study grid)."""
        return self._driver_source(self._load("testrun", testrun)[1].to_dict())[0]

    # ---- editing -----------------------------------------------------------
    def edit(self, kind: str, name: str, overrides: dict[str, str | None]) -> dict:
        """Change keys in place. ``None`` as a value removes the key. The file is backed up
        before its first edit in this session. A value with line breaks, or any value for a
        key that is a multi-line text key already, is written as a text key."""
        if not overrides:
            raise ProjectError("no overrides given")
        p, info = self._load(kind, name)
        if not info.is_infofile:
            raise ProjectError(f"{name!r} is not a text infofile; refusing to edit")
        before = InfoFile(info.dumps())
        for k, v in overrides.items():
            try:
                if v is None:
                    info.unset(k)
                elif isinstance(v, str) and ("\n" in v or info.is_text(k)):
                    info.set_text(k, v)
                else:
                    info.set(k, _fmt(v))
            except InfoFileError as e:
                raise ProjectError(str(e)) from e
        changes = diff_values(before, info)
        if not changes:
            return {"changed": False, "changes": []}
        self.store.backup_file(p)
        info.save(p)
        rel = self.guard.relative(p)
        for c in changes:
            self.store.log("file_key", rel, key=c["key"], old=c["old"], new=c["new"])
        out: dict[str, Any] = {"changed": True, "file": rel, "changes": changes}
        changed = {c["key"] for c in changes}
        if kind == "testrun" and changed & {"Vehicle", DRIVER_TEMPLATE}:
            out["driver"] = self.driver(info.to_dict())
            if "Vehicle" in changed:
                out["driver_note"] = (
                    "A new vehicle does not bring its own driver: the test run keeps the driver above "
                    f"and its knowledge. Check them, set {DRIVER_TEMPLATE} to a template from "
                    "Data/Driver/Template if they belong to another vehicle, and ask the user which "
                    "template if unclear")
        if kind == "driver":
            out["driver_note"] = (f"{rel} is used by every test run that names it: tell the user that this "
                                  "file changed")
        new = [c["key"] for c in changes if c["old"] is None]
        if new:
            out["new_keys"] = new
            out["note"] = ("new_keys were not in the file before. That is right for a key the file left "
                           "to its default, and wrong for a misspelt one: CarMaker ignores keys it does not "
                           "know")
        return out

    def temp_driver(self, base: str, values: dict[str, Any], name: str) -> Path:
        """A copy of driver template ``base`` with ``values``, for one run of a study. Not logged: the
        study deletes it after the run."""
        src = None
        for cand in ("Template/" + base, base):
            p = self.path("driver", cand)
            if p.is_file():
                src = p
                break
        if src is None:
            raise ProjectError(f"no driver template {base!r} in Data/Driver/Template")
        info = InfoFile.load(src)
        for k, v in values.items():
            try:
                if isinstance(v, str) and ("\n" in v or info.is_text(k)):
                    info.set_text(k, v)
                else:
                    info.set(k, _fmt(v))
            except InfoFileError as e:
                raise ProjectError(str(e)) from e
        dst = self.path("driver", "Template/" + name)
        info.save(dst)
        return dst

    def create(self, kind: str, name: str, content: str) -> dict:
        """Write a new file of this kind. Never overwrites; a revert moves it to the trash folder."""
        if not isinstance(content, str) or not content.strip():
            raise ProjectError("content is empty")
        data = content.encode("utf-8")
        if len(data) > MAX_CREATE_BYTES:
            raise ProjectError(f"content is larger than {MAX_CREATE_BYTES // 1_000_000} MB")
        dst = self.path(kind, name)
        if dst.exists():
            raise ProjectError(f"{name!r} already exists; refusing to overwrite (change it with cm_edit)")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        self.store.record_created(dst)
        rel = self.guard.relative(dst)
        self.store.log("file_create", rel, bytes=len(data))
        return {"created": rel, "bytes": len(data), "infofile": InfoFile(content).is_infofile}

    def clone(self, kind: str, base: str, new_name: str) -> dict:
        src = self.path(kind, base)
        if not src.is_file():
            raise ProjectError(f"{kind} {base!r} not found")
        dst = self.path(kind, new_name)
        if dst.exists():
            raise ProjectError(f"{new_name!r} already exists; refusing to overwrite")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        self.store.record_created(dst)
        rel = self.guard.relative(dst)
        self.store.log("file_create", rel, source=self.guard.relative(src))
        out: dict[str, Any] = {"created": rel, "name": new_name.replace("\\", "/").strip("/"),
                               "from": self.guard.relative(src)}
        if kind == "testrun":
            info = InfoFile.load(dst)
            if info.is_infofile:
                out["driver"] = self.driver(info.to_dict())
                out["driver_note"] = (
                    "The copy keeps the source's driver (template, or the parametrization saved in the "
                    "test run) and its knowledge. Before using it with another vehicle, check them and set "
                    f"{DRIVER_TEMPLATE}; ask the user which template if unclear")
        return out


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (list, tuple)):
        return " ".join(_fmt(x) for x in v)
    if isinstance(v, float):
        return repr(v)
    return str(v)


__all__ = ["KINDS", "GuardError", "Project", "ProjectError"]
