"""Lap and sector times at trigger point markers (how CarMaker times a skid pad)."""

import numpy as np
import pytest

from carmaker_mcp import timing
from carmaker_mcp.results import Erg

SKIDPAD = {  # as in a skid pad test run: start, 2nd right lap, start, 2nd left lap
    "Road.RL.1.Marker.0.Type": "DrivManTrigger", "Road.RL.1.Marker.0.Param": "72.334 0 1 1 0",
    "Road.RL.1.Marker.1.Type": "DrivManTrigger", "Road.RL.1.Marker.1.Param": "129.668 0 1 3 1",
    "Road.RL.1.Marker.2.Type": "DrivManTrigger", "Road.RL.1.Marker.2.Param": "187.002 0 1 1 2",
    "Road.RL.1.Marker.3.Type": "DrivManTrigger", "Road.RL.1.Marker.3.Param": "244.336 0 1 3 3",
    "Road.RL.1.Marker.4.Type": "DriverStop", "Road.RL.1.Marker.4.Param": "260 0 1",
}


def write_erg(tmp_path, cols: dict[str, np.ndarray], name="run.erg"):
    dt = np.dtype([(k, "<f8") for k in cols])
    data = np.zeros(len(next(iter(cols.values()))), dtype=dt)
    for k, v in cols.items():
        data[k] = v
    p = tmp_path / name
    p.write_bytes(b"CM-ERG\0\0" + (1).to_bytes(2, "little") + dt.itemsize.to_bytes(2, "little") + bytes(4)
                  + data.tobytes())
    info = "#INFOFILE1.1\nFile.Format = erg\nFile.ByteOrder = LittleEndian\n"
    for i, k in enumerate(cols, 1):
        info += f"File.At.{i}.Name = {k}\nFile.At.{i}.Type = Double\n"
    (tmp_path / (name + ".info")).write_text(info)
    return p


def test_markers_are_read_from_the_test_run():
    m = timing.trigger_markers(SKIDPAD)
    assert [(x["id"], x["mode"]) for x in m] == [(0, 1), (1, 3), (2, 1), (3, 3)]


def test_sectors_on_the_road_position_not_the_odometer(tmp_path):
    t = np.arange(0, 30, 0.01)
    s_road = 10.0 * t  # 10 m/s along the road
    odo = 9.9 * t  # the odometer reads differently (a driver cutting the circle)
    e = Erg(write_erg(tmp_path, {"Time": t, "Vhcl.sRoad": s_road, "Car.Distance": odo}))
    r = timing.sector_times(e, timing.trigger_markers(SKIDPAD))
    assert r["on"] == "Vhcl.sRoad" and "carmaker" not in r
    assert [x["time"] for x in r["sectors"]] == [pytest.approx(5.7334, abs=1e-3), pytest.approx(5.7334, abs=1e-3)]

    e = Erg(write_erg(tmp_path, {"Time": t, "Car.Distance": odo}, "odo.erg"))
    r = timing.sector_times(e, timing.trigger_markers(SKIDPAD))
    assert r["on"] == "Car.Distance" and "reads long" in r["note"]


def test_a_run_that_stops_early_has_no_time_for_the_later_sectors(tmp_path):
    t = np.arange(0, 15, 0.01)
    e = Erg(write_erg(tmp_path, {"Time": t, "Vhcl.sRoad": 10.0 * t}))
    r = timing.sector_times(e, timing.trigger_markers(SKIDPAD))
    assert r["sectors"][0]["time"] == pytest.approx(5.7334, abs=1e-3) and r["sectors"][1]["time"] is None


def _triggers(t, passes):
    """DM.TriggerPoint.Id / .Time as CarMaker writes them: each pass sets the id and its measured time."""
    ids, tp = np.full(len(t), -1.0), np.zeros(len(t))
    for at, mid, val in passes:
        ids[t >= at], tp[t >= at] = mid, val
    return ids, tp


def test_carmakers_own_values_are_used_when_they_are_consistent(tmp_path):
    t = np.arange(0, 30, 0.01)
    ids, tp = _triggers(t, [(11.0, 0, 0.0), (16.5, 1, 5.5), (22.0, 2, 0.0), (27.25, 3, 5.25)])
    e = Erg(write_erg(tmp_path, {"Time": t, "Vhcl.sRoad": t, "DM.TriggerPoint.Id": ids, "DM.TriggerPoint.Time": tp}))
    r = timing.sector_times(e, timing.trigger_markers(SKIDPAD))
    assert r["on"] == "DM.TriggerPoint.Time" and [x["time"] for x in r["sectors"]] == [5.5, 5.25]


def test_a_run_that_left_the_road_gets_no_sector_times(tmp_path):
    """Found in use: the first marker reported id 1, no reference was set, and the times read 0.001 s."""
    t = np.arange(0, 18.5, 0.01)
    ids, tp = _triggers(t, [(11.34, 1, 0.001), (16.33, 2, 0.001)])
    e = Erg(write_erg(tmp_path, {"Time": t, "Vhcl.sRoad": t, "DM.TriggerPoint.Id": ids, "DM.TriggerPoint.Time": tp}))
    assert [x["time"] for x in timing.sector_times(e, timing.trigger_markers(SKIDPAD))["sectors"]] == [None, None]
