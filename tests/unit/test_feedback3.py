"""Third round from use (five agents): lap times of lap-driven runs, the change log's default, quoted
strings, values at a crossing, a shorter test-run read with its timing, the standalone hint."""

import pytest
from test_results import make_erg

from carmaker_mcp import log as sessionlog
from carmaker_mcp.results import Erg
from carmaker_mcp.server import _from_json_text
from carmaker_mcp.study import metric

LOG = """SIM_START\tEV25/Autocross\t2026-10-24 15:36:25
\t\tDriver results: event 1 (t=  60.753s, s=  730.30m)
\t\tLap   1: t=  61.443s\tDist=741.3290m\tsRoad=0.5856m
\t\tLap   2: t=  59.564s\tDist=743.5579m\tsRoad=0.5855m
\t\tLap Time = 59.564 secomds
SIM_END\t\tEV25/Autocross\t121.008s\t1484.9m
"""


def test_lap_times_come_from_carmakers_log():
    """Found in use: the result file never holds the last lap of a run that ends with it."""
    assert sessionlog.lap_times(LOG.splitlines()) == [61.443, 59.564]
    assert metric({"lap_times": [61.443, 59.564]}, "laps") == 59.564
    assert metric({}, "laps") is None


def test_the_change_log_shows_this_session_by_default(session, project):
    session.store.log("file_key", "x", key="a", old="1", new="2")
    other = session.store.session
    session.store.session = "older-session"
    session.store.log("file_key", "y", key="b", old="1", new="2")
    session.store.session = other
    assert [e["target"] for e in session.changelog()] == ["x"]
    assert {e["target"] for e in session.changelog("all")} == {"x", "y"}


def test_a_quoted_string_is_read_as_its_text():
    assert _from_json_text('"markers"') == "markers" and _from_json_text("markers") == "markers"
    assert _from_json_text("[1, 2]") == [1, 2]


def test_crossings_give_other_quantities_at_the_first_crossing(tmp_path):
    erg = Erg(make_erg(tmp_path))
    names = [n for n in erg.names if n != "Time"]
    r = erg.crossings("Time", [0.5], "rising", at=names[:1])
    hit = r["crossings"][0]
    assert hit["first"] is not None and set(hit["at_first"]) == set(names[:1])


def test_a_test_run_read_leaves_road_and_traffic_out_and_names_its_timing(session, project):
    p = project / "Data" / "TestRun" / "Sub" / "Laps"
    p.write_text("#INFOFILE1.1 (UTF-8) - Do not remove this line!\nVehicle = Test_Vehicle\n"
                 "Road.FName = A.rd5\nRoad.RL.1.Marker.0.Type = DrivManTrigger\n"
                 "Road.RL.1.Marker.0.Param = 72.3 0 0 1 0\nRoad.RL.1.Marker.1.Type = DrivManTrigger\n"
                 "Road.RL.1.Marker.1.Param = 129.7 0 0 3 1\nTraffic.N = 0\nDriver.Course.LapDriving = 1\n"
                 "DrivMan.Man.0.LongStep.0.EndCond = DM.Lap.No >= 2\n")
    r = session.project.read("testrun", "Sub/Laps")
    assert not any(k.startswith(("Road.", "Traffic.")) for k in r["values"]) and "6 Road.*" in r["left_out"]
    assert r["timing"] == {"end_conditions": ["DM.Lap.No >= 2"], "lap_driving": True,
                           "markers": [{"id": 0, "s": 72.3, "mode": 1}, {"id": 1, "s": 129.7, "mode": 3}]}
    assert "Road.FName" in session.project.read("testrun", "Sub/Laps", prefix="Road.")["values"]


def test_status_without_matlab_points_to_standalone(session, mock):
    mock.connected = False
    assert "need no MATLAB" in session.status()["standalone_note"]


@pytest.mark.parametrize("key", ["Body.mass", "Vehicle"])
def test_launch_overrides_may_name_vehicle_keys(key):
    from carmaker_mcp.server import Overrides  # the description says so (found in use: an agent cloned files)

    assert key in str(Overrides.__metadata__[0].description)
