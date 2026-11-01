"""The GUI's command port over a real local socket, and the server's own GUI: when it counts as usable,
when it counts as quiet, and what closing it ends."""

import socket
import threading

import pytest

from carmaker_mcp import guiport
from carmaker_mcp.backend import BackendError
from carmaker_mcp.guiport import GuiPort, OwnGui, descendants


@pytest.fixture
def port_answering():
    """A local listener that answers each connection with the next of ``answers``."""
    listener = socket.create_server(("127.0.0.1", 0))
    answers: list = []
    seen: list = []

    def serve():
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            with conn:
                seen.append(conn.recv(4096))
                answer = answers.pop(0)
                if answer is not None:  # None: stay silent until the client gives up
                    conn.sendall(answer)
                else:
                    conn.settimeout(3)
                    try:
                        conn.recv(1)
                    except OSError:
                        pass

    threading.Thread(target=serve, daemon=True).start()
    yield GuiPort(listener.getsockname()[1]), answers, seen
    listener.close()


def test_a_command_goes_out_as_one_line_and_its_answer_comes_back(port_answering):
    gui, answers, seen = port_answering
    answers.extend([b"O2\r\n\r\n", b"\r\n", b"Oa\r\nOb\r\n\r\n", b"Ebad cmd\r\n\r\n"])
    assert gui.tcl("expr 1+1") == (0, "2")
    assert seen == [b"expr 1+1\n"]
    assert gui.tcl("set x {}") == (0, "")  # a bare line end ends the answer too
    assert gui.tcl("two lines") == (0, "a\nb")
    assert gui.tcl("nonsense") == (-1, "bad cmd")


def test_an_answer_cut_off_by_the_gui_is_returned_as_far_as_it_came(port_answering):
    gui, answers, _ = port_answering
    answers.append(b"Opartial\r\n")
    assert gui.tcl("Application stop") == (0, "partial")


def test_a_silent_gui_is_a_time_out(port_answering):
    gui, answers, _ = port_answering
    answers.append(None)
    status, text = gui.tcl("Application start", 1000)
    assert status == -3 and "no answer within 1 s" in text


def test_a_closed_port_says_the_gui_is_not_reachable():
    status, text = GuiPort(guiport.free_port()).tcl("expr 1")
    assert status == -2 and "not reachable" in text


def test_the_port_takes_one_line():
    with pytest.raises(BackendError, match="one line"):
        GuiPort(1).tcl("a\nb")


def test_descendants_follow_the_whole_tree(monkeypatch):
    monkeypatch.setattr(guiport, "_processes", lambda: [
        (10, 1, "HIL.exe"), (20, 10, "CarMaker.exe"), (30, 20, "Movie.exe"), (40, 2, "other.exe"),
        (10, 10, "HIL.exe"), (20, 30, "CarMaker.exe"),  # a pid reused by a child: no endless loop
    ])
    assert sorted(descendants(10)) == [(20, "CarMaker.exe"), (30, "Movie.exe")]
    assert descendants(40) == []


class FakeProc:
    pid = 4711
    returncode = None

    def __init__(self):
        self.code = None

    def poll(self):
        self.returncode = self.code
        return self.code


class ScriptedPort:
    """Answers by command; a list gives one answer per call and then keeps its last one."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def tcl(self, command, timeout_ms=10000):
        self.calls.append(command)
        for key, answer in self.answers.items():
            if key in command:
                if isinstance(answer, list):
                    return answer.pop(0) if len(answer) > 1 else answer[0]
                return answer
        return 0, ""


@pytest.fixture
def own(tmp_path, monkeypatch):
    home = tmp_path / "cm"
    (home / "GUI").mkdir(parents=True)
    (home / "GUI" / "HIL").write_text("")
    (home / "GUI" / "HIL.exe").write_text("")
    monkeypatch.setattr(guiport.time, "sleep", lambda s: None)
    gui = OwnGui(home, tmp_path)
    gui.proc = FakeProc()
    return gui


def test_a_gui_needs_its_program(tmp_path):
    with pytest.raises(BackendError, match="CarMaker GUI not found"):
        OwnGui(tmp_path, tmp_path)


def test_start_waits_for_the_first_answer(own, monkeypatch):
    proc = FakeProc()
    started = []
    monkeypatch.setattr(guiport.subprocess, "Popen", lambda args, **kw: started.append(args) or proc)
    own.gui = ScriptedPort({"expr 1": [(-2, "not yet"), (-2, "not yet"), (0, "1")]})
    own.start()
    assert own.proc is proc and "-cmdport" in started[0] and own.gui.calls.count("expr 1") == 3


def test_start_says_when_the_gui_ended_or_never_answered(own, monkeypatch):
    proc = FakeProc()
    monkeypatch.setattr(guiport.subprocess, "Popen", lambda args, **kw: proc)
    own.gui = ScriptedPort({"expr 1": (-2, "not reachable")})
    proc.code = 3
    with pytest.raises(BackendError, match="ended at once .exit code 3"):
        own.start()
    proc.code = None
    with pytest.raises(BackendError, match="did not answer within 0.01 s"):
        own.start(timeout_s=0.01)


@pytest.mark.parametrize(("blocked", "usable"), [
    ((0, "0"), True),  # no error dialog; a grab of "." alone counts as this too
    ((0, "1"), False),  # found in use: .bgerror left a modal box and the next start hung
    ((-3, "no answer"), False),
])
def test_a_gui_is_reused_only_if_nothing_blocks_it(own, blocked, usable):
    own.gui = ScriptedPort({"expr 1": (0, "1"), "bgerror": blocked})
    assert own.alive() is usable


def test_a_gui_that_ended_or_stopped_answering_is_not_reused(own):
    own.gui = ScriptedPort({"expr 1": (-2, "gone")})
    assert own.alive() is False
    own.gui = ScriptedPort({"expr 1": (0, "1")})
    own.proc.code = 1
    assert own.alive() is False
    own.proc = None
    assert own.alive() is False


def test_waiting_goes_on_until_the_message_box_has_closed(own):
    """Found in use: a race adaption started under the info box ended in CarMaker's error dialog."""
    own.gui = ScriptedPort({"msgbox": [(0, "1"), (0, "1"), (0, "0")]})
    own.wait_quiet(quiet_s=0.0)
    assert own.gui.calls.count("winfo exists .msgbox") == 3


def test_a_gui_that_does_not_answer_is_not_taken_for_quiet(own):
    own.gui = ScriptedPort({"msgbox": (-3, "no answer")})
    own.settle(0.0, 0.0, 0.01)
    assert len(own.gui.calls) > 1


def test_stopping_after_an_adaption_frees_the_licence_and_keeps_the_gui(own, monkeypatch):
    waited = []
    monkeypatch.setattr(own, "settle", lambda *a: waited.append(a))
    own.gui = ScriptedPort({})
    own.settle_and_stop()
    assert waited == [(2.0, 1.0, 30.0)] and own.gui.calls == ["Application stop"] and own.proc is not None


def test_close_ends_the_gui_and_what_it_started(own, monkeypatch):
    """Found in use: a race adaption opened IPGMovie by itself, and it stayed after the GUI ended."""
    killed = []

    def kill(pid, sig):
        killed.append(pid)
        if pid == 30:
            raise OSError("already gone")

    monkeypatch.setattr(guiport.os, "kill", kill)
    monkeypatch.setattr(guiport, "descendants", lambda pid: [(20, "CarMaker.exe"), (30, "Movie.exe")])
    own.gui = ScriptedPort({})
    own.close()
    assert killed == [4711, 20, 30] and own.gui.calls == ["Application stop"] and own.proc is None
    own.close()  # nothing left to do
    assert own.gui.calls == ["Application stop"]
