"""Fourth round from use: how a run ended, a missing driver template, keys for every run, a rerun that
names its own test run, a revert that says what it undid."""

import pytest
from test_study import FakeStandalone

from carmaker_mcp import log as sessionlog
from carmaker_mcp.backend import BackendError
from carmaker_mcp.study import StudyRunner

TAB = "\t"


def test_an_aborted_run_says_why():
    """Found in use: an empty battery showed only as error_flag 1 and a SIM_ABORT line in the full log."""
    lines = ["TIME 570.058", TAB + "ERROR Zero battery voltage",
             "SIM_ABORT" + TAB + TAB + "Sub/Run" + TAB + "570.059s" + TAB + "15761.8m"]
    end = sessionlog.sim_end(lines)
    assert end["ended"] == "aborted" and "Zero battery voltage" in end["end_reason"]
    assert end["sim_time_s"] == 570.059


def test_a_missing_driver_template_is_refused_before_the_launch(session, project):
    """Found in use: the launch started and the run stopped at once, a step later."""
    (project / "Data" / "TestRun" / "Sub" / "Gone").write_text(
        "#INFOFILE1.1 (UTF-8) - Do not remove this line!\nVehicle = Test_Vehicle\n"
        "Vehicle.DriverTemplate.FName = NotThere\n")
    with pytest.raises(BackendError, match="names the driver template 'NotThere'"):
        session.require_standalone("Sub/Gone")
    session.require_standalone("Sub/Gone", {"Vehicle.DriverTemplate.FName": "TestRun"})  # overridden: fine


def test_keys_for_every_run_and_a_rerun_without_its_test_run(session):
    sa = FakeStandalone()
    runner = StudyRunner(session, lambda: sa)
    first = runner.start("A", [{"label": "a"}, {"label": "b", "keys": {"Road.FName": "X"}}],
                         mode="standalone", keys={"Road.FName": "B.rd5"})["study"]
    runner.wait()
    assert [o for _, o, _ in sa.launched] == [{"Road.FName": "B.rd5"}, {"Road.FName": "X"}]  # own keys win
    r = runner.start(None, rerun={"study": first, "labels": ["b"]}, mode="standalone")
    runner.wait()
    assert runner._get(r["study"])["testrun"] == "A"
    with pytest.raises(BackendError, match="name the test run"):
        runner.start(None, mode="standalone")


def test_a_revert_names_what_it_undid(session, mock):
    session.workspace_set("Kp", 1.5)
    r = session.revert_all()
    assert r["reverted"] == ["workspace Kp"]
