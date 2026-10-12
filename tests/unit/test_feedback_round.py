"""Behaviour added after the first report from use: what a failure says, studies that can be waited
for and are not disturbed by other server processes, new files, keys that are not there."""

import json
import os
import threading
import time

import pytest
from test_init_and_simulink import INIT, Errors, scripted

from carmaker_mcp import lock
from carmaker_mcp.backend import IDLE, BackendError
from carmaker_mcp.project import ProjectError
from carmaker_mcp.study import StudyRunner

TAB = chr(9)


def write_log(project, *lines):
    f = project / "SimOutput" / "host" / "Log" / "host_20260101_120000.log"
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a", newline="") as fh:
        for kind, text in lines:
            fh.write(kind + TAB + text + "\r\n")


# ---- 1. what a failed start says ---------------------------------------------------------------
def test_carmakers_own_error_comes_first_and_a_handled_simulink_error_is_left_out(session, mock, project):
    """Reported from use: a missing driver file was announced as an error of a Simulink block that
    the model raises and handles at every start."""
    errors = Errors(mock)
    real = errors.__call__

    def simulink(clear=False, certain=False):  # nothing reported for this run, only the old memory
        return None if certain and not clear else real(clear)

    mock.simulink_error = simulink
    session.require_idle = lambda action: None
    scripted(mock, [(IDLE, "completed"), (INIT, ""), (IDLE, "failed")])

    def start():
        errors.message = "Invalid Simulink object name: 'Integrator/State'."
        write_log(project, ("ERROR", "Can't read driver template 'Nope_Driver'"))

    mock.start_sim = start
    with pytest.raises(BackendError) as e:
        session.start_sim(start_timeout_s=30)
    msg = str(e.value)
    assert msg.startswith("the simulation did not start. Session log: ") and "Nope_Driver" in msg
    assert "Integrator/State" not in msg

    # without anything in the log the last-error memory is better than nothing
    scripted(mock, [(IDLE, "completed"), (INIT, ""), (IDLE, "failed")])
    mock.start_sim = lambda: setattr(errors, "message", "Algebraic loop")
    with pytest.raises(BackendError, match="did not start. Simulink: Algebraic loop"):
        session.start_sim(start_timeout_s=30)


# ---- 2, 3, 4. studies: short table, a wait that blocks, label -> file ------------------------------
@pytest.fixture
def runner(session, mock):
    mock.polls_until_idle = 2
    return StudyRunner(session, lambda: pytest.fail("standalone manager not expected"))


def test_compact_status_leaves_the_parameter_values_out(runner, project):
    big = {f"Key.{i}": i for i in range(40)}
    r = runner.start("Sub/Run1", [{"label": "a", "keys": big}, {"label": "b", "keys": big}], quantities=["Time"])
    runner.wait(r["study"])
    compact, full = runner.status(), runner.status(detail="full")
    assert [row["label"] for row in compact["rows"]] == ["a", "b"] and compact["state"] == "done"
    assert all("keys" not in row and "workspace" not in row for row in compact["rows"])
    assert set(compact["rows"][0]) <= {"label", "end_status", "sim_time_s", "distance_m", "result_file",
                                       "quantities", "missing_quantities"}
    assert full["rows"][0]["keys"] == big and len(json.dumps(compact)) < len(json.dumps(full)) / 3
    with pytest.raises(BackendError, match="detail must be"):
        runner.status(detail="short")


def test_wait_returns_when_a_run_has_finished_and_when_the_study_has(runner, mock):
    mock.polls_until_idle = 10_000  # the first run goes on until it is stopped
    r = runner.start("Sub/Run1", [{"label": "a"}, {"label": "b"}])
    t0 = time.time()
    w = runner.wait_progress(r["study"], timeout_s=0.3)
    assert w["state"] == "running" and w["new_rows"] == 0 and 0.2 < time.time() - t0 < 5

    threading.Timer(0.3, lambda: setattr(mock, "polls_until_idle", 3)).start()  # now the runs end
    w = runner.wait_progress(r["study"], timeout_s=20)
    assert w["new_rows"] >= 1 and w["rows"][0]["label"] == "a"
    while w["state"] == "running":
        w = runner.wait_progress(r["study"], timeout_s=20)
    assert w["state"] == "done" and [row["label"] for row in w["rows"]] == ["a", "b"]
    assert runner.wait_progress(r["study"], timeout_s=5)["new_rows"] == 0  # over: returns at once


def test_wait_end_during_a_study_points_to_the_study(runner, session, mock):
    mock.polls_until_idle = 10_000
    r = runner.start("Sub/Run1", [{"label": "a"}])
    time.sleep(0.2)
    w = session.wait_end(timeout_s=5)  # from another thread than the study's
    assert w["finished"] is False and "cm_study_wait" in w["note"] and r["study"] in w["note"]
    assert session.status()["study_running"]["owner"] == "this server"
    runner.cancel(r["study"])
    assert "study_running" not in session.status()


# ---- 5, 12. who cancelled, and other server processes ------------------------------------------
def test_cancel_is_recorded(runner, mock):
    mock.polls_until_idle = 10_000
    r = runner.start("Sub/Run1", [{"label": "a"}, {"label": "b"}])
    time.sleep(0.2)
    runner.cancel(r["study"])
    st = runner.status(r["study"])
    assert st["state"] == "cancelled" and st["cancelled"]["by"] == "cm_study_cancel"
    assert st["cancelled"]["during"] == "a" and st["cancelled"]["at"]


def test_another_server_process_cannot_disturb_a_running_study(session, mock, runner):
    """Reported from use: a second conversation drove the same CarMaker session and ended a study."""
    other = os.getppid()  # a process that exists and is not this one
    lock.write(session.cfg.state_dir, {"study": "s-9", "testrun": "Sub/Run1", "total": 4, "done": 1,
                                       "started": "2026-01-01 12:00:00"})
    f = session.cfg.state_dir / lock.NAME
    f.write_text(json.dumps({**json.loads(f.read_text()), "pid": other}))

    for action in (lambda: session.load_testrun("Sub/Run1"), session.start_sim, session.stop_sim,
                   lambda: session.edit_file("vehicle", "Test_Vehicle", {"Body.mass": 1}),
                   lambda: runner.start("Sub/Run1", [{"label": "x"}])):
        with pytest.raises(BackendError, match=f"process {other}.*study s-9.*1 of 4 runs done"):
            action()
    assert mock.calls == [] or all(c[0] == "tcl" for c in mock.calls)  # nothing was loaded or started
    st = session.status()["study_running"]
    assert st["study"] == "s-9" and st["owner"] == f"another carmaker-mcp server (process {other})"
    assert "process" in session.wait_end(timeout_s=5)["note"]

    f.write_text(json.dumps({**json.loads(f.read_text()), "pid": 4_000_000}))  # that process is gone
    assert lock.read(session.cfg.state_dir) is None and "study_running" not in session.status()
    assert session.load_testrun("Sub/Run1") == {"loaded": "Sub/Run1"}


def test_lock_is_written_for_the_study_and_removed_at_its_end(runner, session, mock):
    mock.polls_until_idle = 10_000
    r = runner.start("Sub/Run1", [{"label": "a"}])
    time.sleep(0.2)
    cur = lock.read(session.cfg.state_dir)
    assert cur["mine"] and cur["study"] == r["study"] and cur["total"] == 1
    runner.cancel(r["study"])
    assert not (session.cfg.state_dir / lock.NAME).exists()
    assert lock.pid_alive(os.getpid()) and not lock.pid_alive(4_000_000) and not lock.pid_alive(0)


# ---- 9. new files ------------------------------------------------------------------------------
def test_create_a_file_that_revert_takes_away_again(session, project):
    text = "[MODEL]\r\nFITTYP = 61\r\nQSY1 = 0.012\r\n"
    r = session.create_file("tire", "Mine/MF_soft.tir", text)
    f = project / "Data" / "Tire" / "Mine" / "MF_soft.tir"
    assert r == {"created": "Data/Tire/Mine/MF_soft.tir", "bytes": len(text), "infofile": False}
    assert f.read_bytes() == text.encode()
    assert session.changelog()[-1]["kind"] == "file_create"
    with pytest.raises(ProjectError, match="already exists; refusing to overwrite"):
        session.create_file("tire", "Mine/MF_soft.tir", "x")
    for bad in (("tire", "../../outside.tir", "x"), ("tire", "empty.tir", "  "),
                ("tire", "big.tir", "x" * 2_000_001)):
        with pytest.raises(Exception, match="outside|empty|larger"):
            session.create_file(*bad)
    session.revert_all()
    assert not f.exists() and (session.store.dir / "trash" / "t1" / "Data/Tire/Mine/MF_soft.tir").exists()


# ---- 10. keys that are not there -----------------------------------------------------------------
def test_edit_names_keys_that_were_not_in_the_file(session):
    r = session.edit_file("vehicle", "Test_Vehicle", {"Body.mass": 300, "Body.mas": 310})
    assert r["new_keys"] == ["Body.mas"] and "misspelt" in r["note"]
    assert "new_keys" not in session.edit_file("vehicle", "Test_Vehicle", {"Body.mass": 301})


def test_study_names_override_keys_found_in_no_file(runner, session):
    assert session.keys_not_found("Sub/Run1", ["Road.FName", "Body.mass", "Vehicle:Body.mass", "Body.mas"]) == [
        "Body.mas"]
    assert session.keys_not_found("No/Such", ["x"]) == []  # could not look: no claim
    r = runner.start("Sub/Run1", [{"label": "a", "keys": {"Body.mass": 300, "Body.mas": 1}},
                                  {"label": "b", "keys": {"Vehicle:Body.mass": 310}}])
    assert r["keys_not_found"] == ["Body.mas"] and "misspelt" in r["note"]
    runner.wait(r["study"])
    assert "keys_not_found" not in runner.start("Sub/Run1", [{"label": "c", "keys": {"Body.mass": 1}}])
