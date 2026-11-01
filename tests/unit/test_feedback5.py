"""Found when the licence ran out: the setup check, the launch error and the study error each pointed
elsewhere. Also a vehicle's standalone answer, and two tools that took standalone work for an error."""

from datetime import date
from pathlib import Path

import pytest
from test_study import FakeStandalone

from carmaker_mcp import doctor
from carmaker_mcp.backend import BackendError
from carmaker_mcp.config import Config
from carmaker_mcp.standalone import StandaloneManager, _launch_failure
from carmaker_mcp.study import StudyRunner

EXPIRED = "ERROR\t\tUnable to obtain CarMaker license: license has expired (-4)"
IN_USE = "ERROR\t\tUnable to obtain CarMaker license: too many licenses in use (-17)"
LICENCES = """### License No.: 1

Product CarMaker/GUI
\tExpiration\t2027-05-01

Product CarMaker
\tVersion\t\t14.0
\tExpiration\t2026-10-31
\tPassword\tsecret

Product CarMaker
\tExpiration\t2026-12-31

Product IPGMovie
\tExpiration\t2030-01-01
"""


def test_licence_ends_reads_the_carmaker_entries_only():
    assert doctor.licence_ends(LICENCES) == [date(2026, 10, 31), date(2026, 12, 31)]
    assert doctor.licence_ends("Product CarMaker\n\tVersion\t14.0\n") == [None]
    assert doctor.licence_ends("nothing here") == []


@pytest.mark.parametrize(("today", "ok"), [(date(2026, 12, 31), True), (date(2027, 1, 1), False)])
def test_an_expired_licence_is_not_ready(tmp_path, today, ok):
    """Found in use: cm_doctor said standalone studies work, and every launch failed."""
    home = tmp_path / "carmaker" / "win64-14.1.1"
    (home / "Python").mkdir(parents=True)
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "Licenses.dat").write_text(LICENCES)
    (tmp_path / "Data" / "TestRun").mkdir(parents=True)
    cfg = Config(cm_home=home, project=tmp_path, state_dir=tmp_path / "state")
    rep = doctor.diagnose(cfg, installs={}, sessions=None, engine=None, today=today)
    check = next(c for c in rep.checks if c.name == "CarMaker licence")
    assert check.ok is ok and "2026-12-31" in check.detail and "secret" not in check.detail
    assert (check.fix is None) is ok and rep.ready()["standalone"] is ok


def test_no_licence_file_is_not_a_failure(tmp_path):
    home = tmp_path / "carmaker" / "win64-14.1.1"
    (home / "Python").mkdir(parents=True)
    cfg = Config(cm_home=home, state_dir=tmp_path / "state")
    rep = doctor.diagnose(cfg, installs={}, sessions=None, engine=None)
    assert next(c for c in rep.checks if c.name == "CarMaker licence").ok is None


def test_an_expired_licence_blames_no_program():
    """Found in use: the hint about a program holding the licence, with nothing holding it."""
    msg = _launch_failure(RuntimeError("x"), [EXPIRED], [], Path("C:/p/run.log"))
    assert "license has expired" in msg and "must be renewed" in msg and "holding" not in msg
    assert msg.endswith("Log: " + str(Path("C:/p/run.log")))
    assert "holding the licence" in _launch_failure(RuntimeError("x"), [IN_USE])
    assert "sa1" in _launch_failure(RuntimeError("x"), [IN_USE], ["sa1 (finished, A)"])


def test_a_study_offers_close_open_only_when_a_program_holds_the_licence(session):
    sa = FakeStandalone()

    def expired(testrun, overrides=None, quantities=None, **kw):
        raise BackendError(_launch_failure(RuntimeError("x"), [EXPIRED]))

    sa.launch = expired
    runner = StudyRunner(session, lambda: sa)
    st = runner.wait(runner.start("A", [{}, {}], mode="standalone")["study"])
    assert "license has expired" in st["error"] and "close_open" not in st["error"]


def test_a_vehicle_read_says_whether_it_runs_standalone(session, project):
    v = project / "Data" / "Vehicle" / "Sim"
    v.write_text("#INFOFILE1.1 (UTF-8) - Do not remove this line!\nPowerTrain.Control.Kind = CM4SL 1\n")
    r = session.project.read("vehicle", "Sim")
    assert r["standalone"] is False and r["simulink_parts"] == {"PowerTrain.Control.Kind": "CM4SL 1"}
    assert session.project.read("vehicle", "Test_Vehicle")["standalone"] is True


def test_no_open_instance_is_an_answer_not_an_error(tmp_path):
    mgr = StandaloneManager.__new__(StandaloneManager)
    mgr.instances = {}
    assert mgr.status()["instances"] == []
    with pytest.raises(BackendError, match="unknown instance"):
        mgr.status("sa1")


def test_popups_without_matlab_are_an_answer_not_an_error(session, mock):
    mock.connected = False
    r = session.popup_status()
    assert r["messages"] == [] and "cm_log" in r["note"]
