"""Study behaviour asked for in use: licence stop, open instances, grid, brief rows, ranking; cm_diff."""

import pytest
from test_driver import _setup
from test_study import FakeStandalone

from carmaker_mcp.backend import BackendError
from carmaker_mcp.study import StudyRunner, grid_variations, metric


def test_a_study_stops_at_the_first_run_without_a_licence(session):
    """Found in use: every further run failed the same way, one after another."""
    sa = FakeStandalone()

    def no_licence(testrun, overrides=None, quantities=None, **kw):
        sa.launched.append(testrun)
        raise BackendError("CarMaker did not start: too many licenses in use")

    sa.launch = no_licence
    runner = StudyRunner(session, lambda: sa)
    st = runner.wait(runner.start("A", [{}, {}, {}], mode="standalone")["study"])
    assert st["state"] == "failed" and len(sa.launched) == 1 and len(st["rows"]) == 1
    assert "no CarMaker licence" in st["error"] and "close_open=true" in st["error"]


def test_open_instances_are_named_and_closed_on_request(session):
    sa = FakeStandalone()
    sa.own_instances = lambda: [{"instance": "sa9", "testrun": "B", "finished": True, "movie": True}]
    runner = StudyRunner(session, lambda: sa)
    r = runner.start("A", [{}], mode="standalone")
    assert r["open_instances"][0]["instance"] == "sa9" and "licence" in r["open_note"]
    runner.wait()
    r = runner.start("A", [{}], mode="standalone", close_open=True)
    assert r["closed_open"] == ["sa9"] and "sa9" in sa.closed
    runner.wait()


def test_grid_runs_every_combination():
    gg = "10 1.5 1.5\n90 5 5"
    runs = grid_variations({"driver": {"Driver.Acc.ayMax": [12, 14], "Driver.Acc.GGExp": ["10 1 1", gg]},
                            "keys": {"Body.mass": [300]}})
    assert len(runs) == 4
    assert runs[0] == {"label": "ayMax=12 GGExp=10 1 1 mass=300", "keys": {"Body.mass": 300},
                       "driver": {"Driver.Acc.ayMax": 12, "Driver.Acc.GGExp": "10 1 1"}}
    assert runs[3]["label"] == "ayMax=14 GGExp#2 mass=300" and runs[3]["driver"]["Driver.Acc.GGExp"] == gg
    for bad, msg in (({"keys": {"a": []}}, "non-empty list"), ({"nope": {}}, "grid takes")):
        with pytest.raises(BackendError, match=msg):
            grid_variations(bad)


def test_a_grid_alone_makes_a_study(session):
    runner = StudyRunner(session, lambda: FakeStandalone())
    r = runner.start("A", grid={"keys": {"Body.mass": [300, 320, 340]}}, mode="standalone")
    assert r["runs"] == 3
    runner.wait()
    with pytest.raises(BackendError, match="variations, a grid"):
        runner.start("A", mode="standalone")
    with pytest.raises(BackendError, match="at most 100"):
        runner.start("A", grid={"keys": {"a": list(range(11)), "b": list(range(10))}}, mode="standalone")


def test_waits_answer_briefly_and_status_ranks(session):
    runner = StudyRunner(session, lambda: FakeStandalone())
    sid = runner.start("A", [{"label": "a"}, {"label": "b"}], mode="standalone")["study"]
    w = runner.wait_progress(sid, 20, until_done=True)
    assert set(w["rows"][0]) == {"label", "valid", "status"}  # no statistics, no file paths
    st = runner._get(sid)
    st["rows"][0]["sectors"] = [{"id": 1, "s": 1, "time": 5.5}, {"id": 3, "s": 2, "time": 5.3}]
    st["rows"][1]["sectors"] = [{"id": 1, "s": 1, "time": 5.2}, {"id": 3, "s": 2, "time": 5.2}]
    r = runner.status(sid, "brief", rank_by="sectors")
    assert r["rows"][0]["sectors"] == [5.5, 5.3]
    assert [x["label"] for x in r["ranking"]] == ["b", "a"] and r["ranking"][0]["sectors"] == 5.2
    st["rows"][1]["sectors"][0]["time"] = None  # left the road: not ranked
    r = runner.status(sid, rank_by="sectors")
    assert [x["label"] for x in r["ranking"]] == ["a"] and r["not_ranked"] == ["b"]
    assert metric({"quantities": {"Car.v": {"max": 20.0}}}, "Car.v.max") == 20.0


def test_diff_lists_what_differs(session, project):
    _setup(project)
    d = session.project.diff("testrun", "Sub/Run1", "Sub/Own")
    assert d["differ"] and all(len(v) == 2 for v in d["differ"].values())
    assert "Driver.Knowl.0.Vehicle" in d["only_in_b"]
    assert session.project.diff("testrun", "Sub/Own", "Sub/Own") == {
        "kind": "testrun", "a": "Sub/Own", "b": "Sub/Own", "only_in_a": {}, "only_in_b": {}, "differ": {},
        "same": 5}


def test_read_puts_the_driver_first(session, project):
    _setup(project)
    assert list(session.project.read("testrun", "Sub/Own"))[:4] == ["kind", "name", "infofile", "driver"]


def test_waits_are_cut_to_50_s():
    from pydantic import TypeAdapter

    from carmaker_mcp.server import MaxWait

    assert TypeAdapter(MaxWait).validate_python(600) == 50.0
    assert TypeAdapter(MaxWait).validate_python(20) == 20.0
