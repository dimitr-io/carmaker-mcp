"""Second round from use: JSON text for lists, Simulink cars refused standalone, cm_read paging,
ranking across studies with result files, scaled driver values, re-running a row in IPGMovie."""

import asyncio

import pytest
from fastmcp import Client
from test_driver import _setup
from test_study import FakeStandalone

from carmaker_mcp import server
from carmaker_mcp.backend import BackendError
from carmaker_mcp.study import StudyRunner, scale_value

SIMULINK_CAR = ("#INFOFILE1.1 (UTF-8) - Do not remove this line!\nFileIdent = CarMaker-Car 14\n"
                "PowerTrain.Kind = BEV 1\nPowerTrain.Control.Kind = CM4SL 1\n")


class Kept(FakeStandalone):
    """Knows which programs are still open, as the real manager does."""

    def own_instances(self):
        return [{"instance": f"sa{i + 1}", "testrun": t, "finished": True, "movie": True}
                for i, (t, _, _) in enumerate(self.launched) if f"sa{i + 1}" not in self.closed]


def call(name, args):
    async def go():
        async with Client(server.mcp) as c:
            return await c.call_tool(name, args, raise_on_error=False)

    return asyncio.run(go())


@pytest.fixture
def tools(session):
    server.set_session(session)
    server.set_standalone(FakeStandalone())
    server._studies = None
    yield
    server._studies = None
    server.set_standalone(None)
    server.set_session(None)


def test_lists_sent_as_json_text_are_read(tools, project):
    """Found in use: gates=[...] arrived as the string '[...]' and was refused."""
    r = call("cm_read", {"kind": "testrun", "name": "Sub/Run1", "keys": '["Vehicle"]'})
    assert r.structured_content["values"] == {"Vehicle": "Test_Vehicle"}
    r = call("cm_study_start", {"testrun": "Sub/Run1", "mode": "standalone", "gates": "[10, 20]",
                                "variations": '[{"label": "a"}]'})
    assert not r.is_error, r.content
    assert server.ST()._get(None)["gates"] == [10.0, 20.0]
    server.ST().wait()


def test_a_car_with_simulink_parts_is_refused_standalone(session, project):
    (project / "Data" / "Vehicle" / "SL_Car").write_text(SIMULINK_CAR)
    (project / "Data" / "TestRun" / "Sub" / "SL").write_text(
        "#INFOFILE1.1 (UTF-8) - Do not remove this line!\nVehicle = SL_Car\n")
    r = session.project.read("testrun", "Sub/SL")
    assert r["standalone"] is False and r["simulink_parts"] == {"PowerTrain.Control.Kind": "CM4SL 1"}
    assert session.project.read("testrun", "Sub/Run1")["standalone"] is True
    with pytest.raises(BackendError, match="runs only in the MATLAB session"):
        session.require_standalone("Sub/SL")
    session.require_standalone("Sub/SL", {"Vehicle": "Test_Vehicle"})  # another car: fine
    runner = StudyRunner(session, lambda: FakeStandalone())
    with pytest.raises(BackendError, match="PowerTrain.Control.Kind = CM4SL 1"):
        runner.start("Sub/SL", [{}], mode="standalone")


def test_read_pages_and_searches(session, project):
    r = session.project.read("vehicle", "Test_Vehicle", max_items=2)
    assert r["returned"] == 2 and r["next_offset"] == 2 and "offset=2" in r["note"]
    r2 = session.project.read("vehicle", "Test_Vehicle", max_items=2, offset=2)
    assert not set(r2["values"]) & set(r["values"])
    assert list(session.project.read("vehicle", "Test_Vehicle", search="MASS")["values"]) == ["Body.mass"]


def test_ranking_names_result_files_and_spans_studies(session):
    runner = StudyRunner(session, lambda: FakeStandalone())
    a = runner.start("A", [{"label": "a1"}, {"label": "a2"}], mode="standalone")["study"]
    runner.wait()
    b = runner.start("A", [{"label": "b1"}], mode="standalone")["study"]
    runner.wait()
    for sid, times in ((a, [5.4, 5.2]), (b, [5.3])):
        for row, t in zip(runner._get(sid)["rows"], times, strict=True):
            row["sectors"] = [{"id": 1, "s": 1, "time": t}]
            row["result_file"] = f"{row['label']}.erg"
    r = runner.status(b, "brief", "sectors", top=2, with_studies=[a])
    assert [(e["label"], e["study"]) for e in r["ranking"]] == [("a2", a), ("b1", b)]
    assert r["ranking"][0]["result_file"] == "a2.erg" and r["ranked"] == 3
    r = runner.status(a, "brief", labels=["a2", "zz"])
    assert [x["label"] for x in r["rows"]] == ["a2"] and r["labels_not_found"] == ["zz"]


def test_driver_values_can_be_scaled_in_a_grid(session, project):
    assert scale_value("10 1.5 1.5\n90 5 5", 2) == "10 3 3\n90 10 10"  # the speeds stay
    assert scale_value("13.5", 0.5) == "6.75"
    _setup(project)
    session.edit_file("testrun", "Sub/Own", {"Vehicle.DriverTemplate.FName": "Fast"})
    sa = FakeStandalone()
    runner = StudyRunner(session, lambda: sa)
    runner.start("Sub/Own", grid={"driver_scale": {"Driver.Acc.ayMax": [1, 0.5]}}, mode="standalone")
    runner.wait()
    st = runner._get(None)
    assert [v["label"] for v in st["variations"]] == ["ayMax×1", "ayMax×0.5"]
    assert [v["driver"] for v in st["variations"]] == [{"Driver.Acc.ayMax": "15.8"}, {"Driver.Acc.ayMax": "7.9"}]
    with pytest.raises(BackendError, match="has no such value"):
        runner.start("Sub/Own", grid={"driver_scale": {"Driver.Nope": [2]}}, mode="standalone")


def test_the_best_run_is_shown_again_in_the_window_left_open(session):
    sa = Kept()
    runner = StudyRunner(session, lambda: sa)
    first = runner.start("A", [{"label": "slow"}, {"label": "best", "keys": {"Body.mass": 280}}],
                         mode="standalone", movie=True, keep_open=True)["study"]
    runner.wait()
    assert runner._get(first)["kept_open"] == "sa1"
    r = runner.start("A", rerun={"study": first, "labels": ["best"]}, mode="standalone", movie=True,
                     keep_open=True)
    st = runner.wait(r["study"])
    assert "open_instances" not in r and len(sa.launched) == 1  # no new program, no window closing
    assert sa.reruns[-1] == ("sa1", {"Body.mass": 280}) and st["kept_open"] == "sa1"
    assert "kept_open" not in runner._get(first)
    with pytest.raises(BackendError, match="no runs labelled"):
        runner.start("A", rerun={"study": first, "labels": ["nope"]}, mode="standalone")
