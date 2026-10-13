"""The "Internal Debugger" dialog of the CarMaker GUI and IPGMovie: seen, reported, closed."""

import pytest

from carmaker_mcp import internalerror
from carmaker_mcp.backend import BackendError

FBO = "FBO Creation error (unknown error)\nplease check if FrameBufferObjects are supported"
GUI_ERROR = ("Internal Error in CarMaker for Simulink Version 14.1.1:\ncan't read \"x\": no such variable"
             "\n\nPlease report this bug to IPG Automotive GmbH.",
             "ERROR: can't read \"x\": no such variable\n\n\nprocedure \"Foo\" line 3:\n   \"set y $x\"\n\n"
             "Application\nCarMaker 14.1.1\nrunning on host\n")


def test_parse_keeps_the_error_and_its_stack_and_drops_the_rest():
    e = internalerror.parse("CarMaker", GUI_ERROR[0] + chr(31) + GUI_ERROR[1])
    assert e == {"type": "internal error", "program": "CarMaker",
                 "text": "Internal Error in CarMaker for Simulink Version 14.1.1: can't read \"x\": no such variable",
                 "details": "ERROR: can't read \"x\": no such variable\nprocedure \"Foo\" line 3:\n   \"set y $x\""}
    assert internalerror.parse("CarMaker", "") is None  # no dialog
    assert "raised an internal error" in internalerror.sentence(e) and "Foo" in internalerror.sentence(e)
    assert "Foo" not in internalerror.sentence(e, 0)


def test_popups_show_a_dialog_of_the_gui_and_close_it(session, mock):
    """Reported from use: the dialog was on the screen and the agent knew nothing of it."""
    mock.internal_errors["CarMaker"] = GUI_ERROR
    mock.popup_msgs = [("warn", "Vehicle not saved", 0)]
    got = session.popup_status()["messages"]
    assert [m["type"] for m in got] == ["warn", "internal error"]
    assert got[1]["program"] == "CarMaker" and got[1]["closed"] and "no such variable" in got[1]["text"]
    assert "CarMaker" not in mock.internal_errors and session.popups() == []


def test_a_dialog_is_reported_with_the_action_that_follows(session, mock):
    mock.internal_errors["CarMaker"] = GUI_ERROR
    r = session.load_testrun("Sub/Run1")  # dropping old pop-ups before the load leaves the dialog alone
    assert r["popups"][0]["type"] == "internal error" and mock.internal_errors == {}


def test_a_failed_picture_says_what_ipgmovie_said(session, mock):
    session.movie_open()
    mock.movie_export_error = FBO
    with pytest.raises(BackendError) as e:
        session.movie_snapshot()
    msg = str(e.value)
    assert msg.startswith("IPGMovie raised an internal error: Internal Error in IPGMovie Version 14.1.1 FBO Creation")
    assert "OSD::FBOSetup" in msg and "cm_movie_open(restart=true)" in msg
    assert "IPGMovie" not in mock.internal_errors  # its dialog was closed
    assert any("Export::Stop" in c[1] for c in mock.calls if c[0] == "tcl")  # and IPGMovie tidied up

    r = session.movie_open(restart=True)  # the way out
    assert r["restarted"] and r["started"] and "holds no run" in r["note"]
    with pytest.raises(BackendError, match="IPGMovie holds no run.*empty default scene"):
        session.movie_snapshot()  # found live: it returned the default scene as "the last run"
    mock.movie_recorded_s = 28.8  # a run with IPGMovie open
    assert session.movie_snapshot(time_s=12)["file"].endswith(".jpg")
    with pytest.raises(BackendError, match="holds the run from 0 s to 28.8 s: there is no picture for t = 40 s"):
        session.movie_snapshot(time_s=40)
    assert "restarted" not in session.movie_open()


def test_a_dialog_from_before_is_not_blamed_on_the_picture(session, mock):
    session.movie_open()
    mock.internal_errors["IPGMovie"] = ("Internal Error in IPGMovie\nsomething else", "ERROR: something else\n")
    assert session.movie_snapshot()["file"].endswith(".jpg") and mock.internal_errors == {}


def test_a_gui_without_movie_eval_changes_nothing(session, mock):
    session.movie_open()
    mock.movie_eval, mock.movie_export_error = False, FBO
    with pytest.raises(BackendError, match="IPGMovie wrote no picture"):
        session._movie_ctl().export(None, 960, 540, timeout_s=1.0)
    assert session.popups() == []
