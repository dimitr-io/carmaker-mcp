"""The "Internal Debugger" dialog of the CarMaker GUI and of IPGMovie: read it and close it.

Both programs are Tcl/Tk applications. An error in one of their own scripts ends in a dialog titled
"Internal Debugger" (the window ``.bgerror``) with the message and the call stack. It is not a
pop-up of ``PopupCtrl``, stays on top of the other windows and keeps the program's input until
somebody presses Ok, so a caller that only reads pop-ups never learns of it.

The GUI's dialog is read with a Tcl command in the GUI. IPGMovie is another process: the GUI's
``Movie eval`` passes a script on to it. That subcommand is not in ``Movie help``; where it does not
exist the answer is an error and IPGMovie's dialog is simply not seen.
"""

from __future__ import annotations

from collections.abc import Callable

Tcl = Callable[[str, int], tuple[int, str]]

_US = chr(31)
# No global variables are left behind in the program: the script runs in a lambda.
_READ = ("apply {{} {if {![winfo exists .bgerror]} {return {}}; set m {}; set t {}; "
         "catch {set m [.bgerror.msg cget -text]}; catch {set t [.bgerror.text get 1.0 end]}; "
         "return \"$m[format %c 31]$t\"}}")
_CLOSE = "catch {destroy .bgerror}"
# After a failed export IPGMovie is left as it was in the middle of it: controls disabled, the
# thread that draws the window stopped. Its own clean-up puts that right.
_MOVIE_TIDY = "if {[llength [info procs ::Export::Stop]]} {catch {::Export::Stop}}"
PROGRAMS = ("CarMaker", "IPGMovie")
MAX_DETAILS = 2500


def _wrap(program: str, script: str) -> str:
    return script if program == "CarMaker" else "Movie eval eval {" + script + "}"


def parse(program: str, raw: str) -> dict | None:
    """The dialog's content as a pop-up record, or None if the answer holds none."""
    if _US not in raw:
        return None
    message, details = raw.split(_US, 1)
    lines = [ln.strip() for ln in message.splitlines()]
    text = " ".join(ln for ln in lines if ln and not ln.startswith("Please report this bug"))
    for end in ("\nGlobal Variables", "\nApplication\n"):  # what follows describes the program, not the error
        details = details.split(end, 1)[0]
    details = "\n".join(ln.rstrip() for ln in details.strip().splitlines() if ln.strip())
    out = {"type": "internal error", "program": program, "text": text or "Internal Error"}
    if details:
        out["details"] = details[:MAX_DETAILS]
    return out


def read(tcl: Tcl, program: str, close: bool = True) -> dict | None:
    """The dialog one program is showing, or None. ``close`` presses its Ok."""
    status, raw = tcl(_wrap(program, _READ), 5000)
    found = parse(program, raw) if status == 0 else None
    if found is not None:
        found["closed"] = False
        if close:
            status, _ = tcl(_wrap(program, _CLOSE), 5000)
            found["closed"] = status == 0
    return found


def read_all(tcl: Tcl, close: bool = True) -> list[dict]:
    return [e for e in (read(tcl, p, close) for p in PROGRAMS) if e is not None]


def tidy_movie(tcl: Tcl) -> None:
    tcl(_wrap("IPGMovie", _MOVIE_TIDY), 10000)


def sentence(e: dict, details: int = 400) -> str:
    """One line for an error message."""
    out = f"{e['program']} raised an internal error: {e['text']}"
    if e.get("details") and details:
        out += " (" + " / ".join(e["details"].splitlines())[:details] + ")"
    return out
