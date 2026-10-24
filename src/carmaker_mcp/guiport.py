"""A CarMaker GUI started by this server, driven over its command port (``HIL.exe -cmdport``).

Used where no MATLAB session provides a GUI: the GUI runs the script commands (ScriptControl) that
``cmguicmd`` sends in the MATLAB session. A request is one line of Tcl; the answer is the result, each
line prefixed with ``O`` (or ``E`` for an error), ended by an empty line.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from .backend import BackendError


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def parse(raw: bytes) -> tuple[int, str]:
    """(status, result): 0 and the text for an ``O`` answer, -1 and the message for ``E``."""
    text = raw.decode("utf-8", "replace").rstrip("\r\n")
    lines = text.split("\r\n") if text else []
    status = -1 if lines and lines[0].startswith("E") else 0
    return status, "\n".join(ln[1:] if ln[:1] in ("O", "E") else ln for ln in lines)


class GuiPort:
    """``tcl(command, timeout_ms) -> (status, result)``, like the backend's ``gui_tcl``."""

    def __init__(self, port: int, host: str = "127.0.0.1"):
        self.host, self.port = host, port

    def tcl(self, command: str, timeout_ms: int = 10000) -> tuple[int, str]:
        if "\n" in command:
            raise BackendError("the command port takes one line; source a file for longer scripts")
        try:
            with socket.create_connection((self.host, self.port), timeout=10) as s:
                s.sendall((command + "\n").encode())
                s.settimeout(max(1.0, timeout_ms / 1000))
                data = b""
                # An answer ends with an empty line; an empty result is a bare line end (found live).
                while data != b"\r\n" and not data.endswith(b"\r\n\r\n"):
                    chunk = s.recv(1 << 20)
                    if not chunk:
                        break
                    data += chunk
        except TimeoutError:
            return -3, f"no answer within {timeout_ms / 1000:g} s"
        except OSError as e:
            return -2, f"CarMaker GUI not reachable: {e}"
        return parse(data)


def _processes() -> list[tuple[int, int, str]]:
    """(pid, parent pid, exe name) of every process (Windows; empty elsewhere)."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    out, e = [], Entry()
    e.dwSize = ctypes.sizeof(Entry)
    try:
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out.append((e.th32ProcessID, e.th32ParentProcessID, e.szExeFile))
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return out


def descendants(pid: int) -> list[tuple[int, str]]:
    """Processes started by ``pid``, and by those, and so on."""
    procs = _processes()
    found, todo = [], [pid]
    while todo:
        parent = todo.pop()
        for child, ppid, exe in procs:
            if ppid == parent and child != parent and all(child != f for f, _ in found):
                found.append((child, exe))
                todo.append(child)
    return found


class OwnGui:
    """A CarMaker GUI (HIL.exe) this server started for the project, with its simulation program."""

    def __init__(self, cm_home: Path, project: Path):
        self.exe = Path(cm_home) / "GUI" / ("HIL.exe" if sys.platform == "win32" else "HIL")
        if not self.exe.exists():
            raise BackendError(f"CarMaker GUI not found: {self.exe}")
        self.project = Path(project)
        self.port = free_port()
        self.proc: subprocess.Popen | None = None
        self.gui = GuiPort(self.port)

    def start(self, timeout_s: float = 90.0) -> None:
        self.proc = subprocess.Popen([str(self.exe), "-cmdport", str(self.port)], cwd=str(self.project),
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            if self.proc.poll() is not None:
                raise BackendError(f"the CarMaker GUI ended at once (exit code {self.proc.returncode})")
            if self.gui.tcl("expr 1", 2000)[0] == 0:
                return
            time.sleep(1.0)
        raise BackendError(f"the CarMaker GUI did not answer within {timeout_s:g} s")

    def alive(self) -> bool:
        """The GUI still runs, answers and shows no dialog that blocks it (CarMaker's internal error
        dialog .bgerror leaves a modal error box behind, and the next start hangs: found in use)."""
        if self.proc is None or self.proc.poll() is not None or self.gui.tcl("expr 1", 2000)[0] != 0:
            return False
        # a grab of the main window "." is normal after an adaption; one of a dialog is not
        return self.gui.tcl("expr {[winfo exists .bgerror] || [grab current] ni {{} .}}", 3000) == (0, "0")

    def wait_quiet(self, quiet_s: float = 1.0, max_s: float = 30.0) -> None:
        """Wait until the GUI shows no message box. Found in use: a race adaption started while the info
        box that follows a program start was still open raised CarMaker's internal error dialog at its
        end (can't set "HIL(SimState)": bad window path name ".msgbox"), and the next start hung."""
        self.settle(0.0, quiet_s, max_s)

    def settle_and_stop(self) -> None:
        """Stop the simulation program once the GUI has finished an adaption (frees the licence)."""
        self.settle(2.0, 1.0, 30.0)
        self.gui.tcl("Application stop", 60000)

    def settle(self, min_s: float, quiet_s: float, max_s: float) -> None:
        """At least ``min_s``, and no message box for ``quiet_s`` (at most ``max_s``)."""
        t0, quiet_since = time.time(), None
        while time.time() - t0 < max_s:
            busy = self.gui.tcl("winfo exists .msgbox", 3000) != (0, "0")
            now = time.time()
            quiet_since = None if busy else (quiet_since or now)
            if quiet_since and now - quiet_since >= quiet_s and now - t0 >= min_s:
                break
            time.sleep(0.25)

    def close(self) -> None:
        """Stop its simulation program and end the GUI (nothing of the user's is in it)."""
        if self.proc is None:
            return
        # What the GUI started, IPGMovie included: a race adaption opened IPGMovie by itself, and it
        # stayed open after the GUI ended (found in use).
        started = descendants(self.proc.pid)
        self.gui.tcl("Application stop", 60000)
        for pid in [self.proc.pid, *(p for p, _ in started)]:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        self.proc = None
