"""Driver adaption through the GUI's script commands (fake GUI answering as CarMaker 14.1.1 did)."""

import pytest

from carmaker_mcp import adaption
from carmaker_mcp.backend import BackendError


class FakeGui:
    """Starts an adaption on `Driver adapt...`, runs through phases on each state poll, then ends."""

    def __init__(self, phases=(0, 100, 410, 600), fail=False, refuse=False):
        self.phases, self.fail, self.refuse = list(phases), fail, refuse
        self.calls, self.active, self.saved = [], False, False

    def tcl(self, command, timeout_ms=10000):
        self.calls.append(command)
        if command.startswith("source ") or command.startswith("Driver setactiveknowledge"):
            return 0, ""
        if command.startswith("Driver adapt"):
            if self.refuse:
                return 0, "-1"
            self.active = True
            return 0, "0"
        if command == "::mcp_adapt_state":
            phase = self.phases.pop(0) if self.phases else 0
            if not self.phases and self.active and phase == 0:
                self.active = False
            return 0, f"active {int(self.active)} simstate -5 connected 1 phase {phase}"
        if command == "::mcp_adapt_knowledge":
            mode = "failed" if self.fail and not self.active else "std"
            return 0, (f"template McpT testrun Sub/Run1 k_Name Knowledge k_Mode {mode} "
                       "k_VehicleLimitsDate {2026-10-22 10:33:10} k_RaceAdaptionDate {}")
        if command == "::mcp_adapt_save":
            self.saved = True
            return 0, "template McpT testrun Sub/Run1 knowledge Knowledge"
        if command == "StopSim":
            self.active = False
            return 0, ""
        return -1, f"unknown {command}"


def run(gui, tmp_path, **kw):
    seen = {}
    a = adaption.Adaption(gui.tcl, tmp_path / "h.tcl", kw.pop("kind", "basic"), poll_s=0.01,
                          before_save=lambda st: seen.setdefault("backup", st.get("template")),
                          after=lambda: seen.setdefault("closed", True), **kw)
    a.prepare()
    a.run()
    return a.wait(10), seen


def test_basic_adaption_runs_through_its_phases_and_saves(tmp_path):
    gui = FakeGui()
    st, seen = run(gui, tmp_path)
    assert st["state"] == "done" and gui.saved and seen == {"backup": "McpT", "closed": True}
    assert "Driver adaptbasicknowledge 1 1" in gui.calls
    assert st["knowledge"]["Name"] == "Knowledge" and st["knowledge"]["VehicleLimitsDate"].startswith("2026")
    assert "RaceAdaptionDate" not in st["knowledge"]  # empty values are left out
    assert (tmp_path / "h.tcl").read_text().count("proc ::mcp_adapt_") == 4


def test_a_failed_adaption_saves_nothing(tmp_path):
    gui = FakeGui(fail=True)
    st, seen = run(gui, tmp_path)
    assert st["state"] == "failed" and not gui.saved and "backup" not in seen and seen["closed"]


def test_race_adaption_and_a_chosen_knowledge(tmp_path):
    gui = FakeGui()
    st, _ = run(gui, tmp_path, kind="race", learning_rate=0.3, knowledge="Track A")
    assert "Driver setactiveknowledge {Track A}" in gui.calls and "Driver adaptracedriver 0.3" in gui.calls


def test_the_gui_refusing_raises_before_anything_runs(tmp_path):
    a = adaption.Adaption(FakeGui(refuse=True).tcl, tmp_path / "h.tcl", "basic")
    with pytest.raises(BackendError, match="did not start the adaption"):
        a.prepare()
    with pytest.raises(BackendError, match="needs vehicle_limits or controller_dynamics"):
        adaption.Adaption(FakeGui().tcl, tmp_path / "h.tcl", "basic", vehicle_limits=False,
                          controller_dynamics=False)


def test_phase_names_and_tcl_lists():
    assert adaption.phase_name(410) == "open-loop steering" and adaption.phase_name(999) == "finished"
    assert adaption.tcl_dict("a {b c} d {} e f") == {"a": "b c", "d": "", "e": "f"}


def test_command_port_answers():
    from carmaker_mcp import guiport

    assert guiport.parse(b"O2\r\n\r\n") == (0, "2")
    assert guiport.parse(b"\r\n") == (0, "")  # an empty result: a bare line end
    assert guiport.parse(b"Oa\r\nOb\r\n\r\n") == (0, "a\nb")
    assert guiport.parse(b"Ebad cmd\r\n\r\n") == (-1, "bad cmd")


def test_in_the_matlab_session_it_holds_the_session_and_saves_with_a_backup(session, mock, project):
    import time


    r = session.driver_adaption("start", testrun="Sub/Run1", mode="cm4sl")
    assert r["state"] == "running" and r["mode"] == "cm4sl" and mock.time_acc == 999999
    with pytest.raises(BackendError, match="while a driver adaption is running"):
        session.load_testrun("Sub/Run1")
    t0 = time.time()
    while session.driver_adaption("status")["state"] == "running" and time.time() - t0 < 30:
        time.sleep(0.2)
    st = session.driver_adaption("wait", timeout_s=1)
    assert st["state"] == "done" and mock.adaption_saved and st["knowledge"]["Name"] == "Knowledge"
    assert [e["kind"] for e in session.changelog()][-1] == "driver_adaption"  # the test run, backed up
    session.load_testrun("Sub/Run1")  # the session is free again


def test_standalone_adaptions_share_one_gui_and_free_the_licence_between(session, project, monkeypatch):
    """Found in use: a GUI per adaption flickered, and closing it at the end raised CarMaker's error dialog."""
    import time

    from carmaker_mcp import guiport, standalone

    started, guis = [], []

    class Gui:
        def __init__(self, cm_home, root):
            self.fake, self.open = FakeGui(phases=(100, 600, 0)), True
            self.gui = self
            guis.append(self)

        def tcl(self, command, timeout_ms=10000):
            if command.startswith(("LoadTestRun", "Application", "SetSimTimeAcc", "expr")):
                self.fake.calls.append(command)
                return 0, ""
            return self.fake.tcl(command, timeout_ms)

        def start(self):
            started.append(self)

        def alive(self):
            return self.open

        def settle_and_stop(self):
            self.tcl("Application stop")

        def wait_quiet(self):
            self.fake.calls.append("wait_quiet")

        def close(self):
            self.open = False

    monkeypatch.setattr(guiport, "OwnGui", Gui)
    monkeypatch.setattr(standalone, "find_cm_home", lambda explicit=None: project)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    for _ in range(2):
        session.driver_adaption("start", testrun="Sub/Run1", mode="standalone")
        st = session.driver_adaption("wait", timeout_s=10)
        assert st["state"] == "done"
        guis[0].fake.phases = [100, 600, 0]
        guis[0].fake.active = False
    assert len(started) == 1 and guis[0].open  # one GUI for both
    assert guis[0].fake.calls.count("Application stop") == 2  # the licence is free after each
    assert guis[0].fake.calls.count("wait_quiet") == 2  # no adaption starts under the GUI's info box
    assert session.driver_adaption("close") == {"closed": True} and not guis[0].open
