"""Levels of session log lines that libraries write indented (found with the tyre library)."""

from test_run_control import write_log

from carmaker_mcp import log as sessionlog

TAB = chr(9)
IGNORED = "WARNING - Override value 1.000000 for TV_MODEL is ignored, because it is not supported at fittype 62."
TYRE = [TAB + "0.001", TAB + TAB + "INFO - MF-Tyre/MF-Swift 2406  (1784f5ec5d08)"] + [TAB + TAB + IGNORED] * 4


def test_indented_library_lines_have_a_level():
    """Reported from use: cm_log(level='warning') returned nothing while the log held these four lines."""
    lines = ["TIME" + TYRE[0], *TYRE[1:], "WARNING" + TAB + "IPGDriver: x", "ERRORS_SEEN" + TAB + "1"]
    assert sessionlog.filter_level(lines, "warning") == [TAB + TAB + IGNORED] * 4 + ["WARNING" + TAB + "IPGDriver: x"]
    assert sessionlog.filter_level(lines, "error") == []
    assert sessionlog.filter_level([TAB + "  FATAL - gone", "ERROR" + TAB + "boom"], "error") == [
        TAB + "  FATAL - gone", "ERROR" + TAB + "boom"]
    assert sessionlog.dedupe(sessionlog.warnings_only(lines)) == [IGNORED + " (x4)", "WARNING IPGDriver: x"]


def test_a_completed_run_reports_its_warnings(session, mock, project):
    mock.polls_until_idle = 2
    session.start_sim()
    write_log(project, ("SIM_START", "Sub/Run1", "2026-01-01 12:00:00"), ("TIME", "0.001"),
              *[("", "", IGNORED)] * 4, ("SIM_END", "", "Sub/Run1", "5.055s", "76.1026m"))
    r = session.wait_end(timeout_s=5, poll_s=0.01)
    assert r["end_status"] == "completed" and "log_errors" not in r
    assert r["log_warnings"] == [IGNORED + " (x4)"]
    assert session.log_tail(level="warning")["total"] == 4
