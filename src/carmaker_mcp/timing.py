"""Lap and sector times from a test run's trigger point markers, as CarMaker times them.

A road marker of type ``DrivManTrigger`` ("Trigger point" in the Scenario Editor) has the parameters
``offset ? ? mode id``. Mode 1 sets a new reference point, mode 2 takes the measurements, mode 3 does
both. CarMaker reports the time since the reference point as ``DM.TriggerPoint.Time`` when the car
passes a measuring marker at its road position (``sRoad``); the skid pad of a Formula Student project,
for example, times the second right and the second left circle this way.

From a result file the same times follow from the road position ``Vhcl.sRoad``. The odometer
``Car.Distance`` is not the same: a driver who cuts the circle drives less than the road length
(found on a skid pad: about 15 ms per lap too long). Marker offsets are taken as road positions, which
holds when the marker's link starts where the route starts (one-link courses such as a skid pad).
"""

from __future__ import annotations

import re

import numpy as np

from .results import Erg, ErgError

_MARKER = re.compile(r"^Road\.RL\.\d+\.Marker\.\d+\.Type$")


def trigger_markers(testrun: dict[str, str]) -> list[dict]:
    """The trigger point markers of a test run (its infofile keys), along the road."""
    out = []
    for key, value in testrun.items():
        if not _MARKER.match(key) or value.strip() != "DrivManTrigger":
            continue
        param = testrun.get(key[: -len("Type")] + "Param", "").split()
        try:
            out.append({"id": int(float(param[4])), "mode": int(float(param[3])), "s": float(param[0])})
        except (IndexError, ValueError):
            continue
    return sorted(out, key=lambda m: m["s"])


def _position(erg: Erg) -> str:
    for name in ("Vhcl.sRoad", "Car.Distance"):
        if name in erg.names:
            return name
    raise ErgError("the result file holds neither Vhcl.sRoad nor Car.Distance")


def sector_times(erg: Erg, markers: list[dict]) -> dict:
    """Time from the last reference marker (mode 1 or 3) to each measuring marker (mode 2 or 3).
    CarMaker's own values when the file stores DM.TriggerPoint.* (they are what its lap timing shows);
    otherwise from the road position (checked on a skid pad: within 2 to 6 ms of CarMaker's values)."""
    own = carmaker_times(erg)
    if own is not None:
        # Accept CarMaker's value only if the reference marker was passed too and the value matches the
        # time between the two passes. Found in use: in runs that left the road the first marker passed
        # reported id 1 instead of 0, no reference was set, and every "time" read 0.001 s.
        time_at = {c["id"]: c["time"] for c in own}
        passed_at = {c["id"]: c["at_s"] for c in own}
        sectors, ref = [], None
        for m in markers:
            if m["mode"] in (2, 3):
                t = time_at.get(m["id"])
                ok = (t is not None and ref is not None and ref in passed_at and m["id"] in passed_at
                      and abs((passed_at[m["id"]] - passed_at[ref]) - t) < 0.1)
                sectors.append({"id": m["id"], "s": m["s"], "time": t if ok else None})
            if m["mode"] in (1, 3):
                ref = m["id"]
        return {"on": "DM.TriggerPoint.Time", "sectors": sectors}
    pos = _position(erg)
    found = erg.crossings(pos, [m["s"] for m in markers], "rising")["crossings"]
    passed = {c["value"]: c["first"] for c in found}
    sectors, ref = [], None
    for m in markers:
        t = passed.get(m["s"])
        if m["mode"] in (2, 3):
            sectors.append({"id": m["id"], "s": m["s"],
                            "time": None if t is None or ref is None else round(t - ref, 4)})
        if m["mode"] in (1, 3):
            ref = t
    out: dict = {"on": pos, "sectors": sectors}
    if pos != "Vhcl.sRoad":
        out["note"] = "no Vhcl.sRoad in the result file: timed on the odometer Car.Distance, which reads long"
    return out


def carmaker_times(erg: Erg) -> list[dict] | None:
    """CarMaker's own values when the file stores them: DM.TriggerPoint.Time just after the car passed
    each marker (DM.TriggerPoint.Id changed)."""
    if "DM.TriggerPoint.Id" not in erg.names or "DM.TriggerPoint.Time" not in erg.names:
        return None
    ids = erg.column("DM.TriggerPoint.Id").astype(float)
    tp = erg.column("DM.TriggerPoint.Time").astype(float)
    t = erg.column("Time").astype(float)
    out = []
    for i in np.flatnonzero(np.diff(ids) != 0) + 1:
        out.append({"id": int(ids[i]), "at_s": round(float(t[i]), 4), "time": round(float(tp[i]), 4)})
    return out
