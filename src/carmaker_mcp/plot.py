"""Plot quantities of result files in IPGControl, IPG's plotting program, without MATLAB.

IPGControl opens the files given on its command line and runs a Tcl script given with ``-cmd``. The
script below uses IPGControl's own procedures, the ones its quantity list calls, to put the quantities
into the diagram (one data source per file: F1, F2...), optionally sets the x axis, fits the diagram
and writes what it did to a file. The window then stays open for the user; a picture of it can go back
to the agent. These procedures are not documented by IPG: they were read from IPGControl 3.0.17.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

from .backend import BackendError

EXE = "ipg-control.exe"
_NAME = re.compile(r"^[A-Za-z0-9_.:\[\]#+-]+$")  # safe inside a Tcl list without quoting

_SCRIPT = r"""
proc mcp_plot {keys names xname out tries} {
    global DatasetOfKey Windows
    foreach k $keys {
        if {![info exists DatasetOfKey($k)] || ![llength $Windows]} {
            if {$tries > 0} { after 300 [list mcp_plot $keys $names $xname $out [expr {$tries - 1}]]; return }
        }
    }
    set f [open $out w]
    if {![llength $Windows]} { puts $f "error no window"; close $f; return }
    set win [lindex $Windows 0]
    set diag [$win getActiveDiagram]
    foreach k $keys {
        if {![info exists DatasetOfKey($k)]} { puts $f "notloaded $k"; continue }
        set ds $DatasetOfKey($k)
        foreach name $names {
            set q [dataset quantities $ds $name]
            if {$q eq ""} { puts $f "missing $k $name"; continue }
            if {[catch {::Quantities::ToggleQuantInDiag $diag $q} err]} {
                puts $f "error $k $name $err"
            } else { puts $f "added $k $name" }
        }
    }
    if {$xname ne ""} {
        set k [lindex $keys 0]
        set qi [dict create dataset $DatasetOfKey($k) name $xname diagram $diag]
        if {[catch {::Connection::AddAsRefQuantity $qi} err] || $err eq ""} {
            puts $f "xerror $xname $err"
        } else { puts $f "x $xname" }
    }
    catch {$win Fit total}
    puts $f "done"
    close $f
}
after 500 [list mcp_plot %KEYS% %NAMES% %X% %OUT% 60]
"""


def find_ipgcontrol(cm_home: Path | None) -> Path:
    """IPGControl is installed next to CarMaker: <IPG>/control/win64-<version>/bin/ipg-control.exe."""
    if os.environ.get("CM_IPGCONTROL"):
        return Path(os.environ["CM_IPGCONTROL"])
    roots = [cm_home.parent.parent] if cm_home else []
    roots += [Path("C:/IPG"), Path("/opt/ipg")]
    found = []
    for root in roots:
        found += [p for p in (root / "control").glob("*/bin/" + EXE) if p.is_file()]
    if not found:
        raise BackendError("IPGControl not found (looked in <IPG>/control/*/bin): install it with CarMaker, "
                           "or set CM_IPGCONTROL to ipg-control.exe")

    def ver(p: Path):
        return [int(x) for x in re.findall(r"\d+", p.parent.parent.name)]

    return max(found, key=ver)


def _tcl_word(s: str) -> str:
    return "{" + s + "}"


def script(n_files: int, names: list[str], x: str | None, out: Path) -> str:
    for n in [*names, *([x] if x else [])]:
        if not _NAME.match(n):
            raise BackendError(f"not a quantity name: {n!r}")
    keys = " ".join(f"F{i + 1}" for i in range(n_files))
    return (_SCRIPT.replace("%KEYS%", _tcl_word(keys)).replace("%NAMES%", _tcl_word(" ".join(names)))
            .replace("%X%", _tcl_word(x or "")).replace("%OUT%", _tcl_word(out.as_posix())))


def parse(text: str, files: list[Path]) -> dict:
    """What the script reported, by file."""
    key = {f"F{i + 1}": str(p) for i, p in enumerate(files)}
    out: dict = {"plotted": [], "missing": [], "errors": []}
    for line in text.splitlines():
        parts = line.split(" ", 3)
        if parts[0] == "added":
            out["plotted"].append({"file": key.get(parts[1], parts[1]), "quantity": parts[2]})
        elif parts[0] == "missing":
            out["missing"].append({"file": key.get(parts[1], parts[1]), "quantity": parts[2]})
        elif parts[0] in ("error", "xerror", "notloaded"):
            out["errors"].append(line)
        elif parts[0] == "x":
            out["x"] = parts[1]
    return out


def open_plot(exe: Path, files: list[Path], names: list[str], x: str | None, workdir: Path,
              timeout_s: float = 30.0) -> dict:
    """Start IPGControl with the files and the quantities; returns its pid and what was plotted."""
    workdir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = workdir / f"plot-{stamp}.txt"
    tcl = workdir / f"plot-{stamp}.tcl"
    tcl.write_text(script(len(files), names, x, out), encoding="utf-8")
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen([str(exe), "-norestore", "-cmd", f"source {_tcl_word(tcl.as_posix())}",
                             *[str(f) for f in files]], cwd=str(workdir), creationflags=flags,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            close_fds=True)
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if out.is_file() and out.read_text(encoding="utf-8", errors="replace").rstrip().endswith("done"):
            res = parse(out.read_text(encoding="utf-8", errors="replace"), files)
            res["pid"] = proc.pid
            return res
        if proc.poll() is not None:
            raise BackendError(f"IPGControl ended at once (exit code {proc.returncode})")
        time.sleep(0.3)
    return {"pid": proc.pid, "plotted": [], "missing": [], "errors": [
        f"IPGControl did not report within {timeout_s:g} s; its window may still show the files"]}
