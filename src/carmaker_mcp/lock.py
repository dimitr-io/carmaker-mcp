"""Who is using the CarMaker session: a small file in the state folder, shared by all server processes.

Every MCP client starts a server process of its own, and all of them attach to the same MATLAB and
CarMaker. A parameter study runs for minutes; while it does, another process must not load, start or
stop anything. The process that runs a study writes this file and removes it at the end; the others
read it before they change the session's state.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

NAME = "study.lock"


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ok = kernel32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
            return bool(ok) and code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # exists, but belongs to someone else
    return True


def write(state_dir: Path, data: dict) -> None:
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / NAME).write_text(json.dumps({**data, "pid": os.getpid()}), encoding="utf-8")
    except OSError:
        pass  # the study runs all the same; other processes are then not warned


def clear(state_dir: Path) -> None:
    """Remove the file if it is ours."""
    cur = _load(state_dir)
    if cur is not None and cur.get("pid") == os.getpid():
        try:
            (state_dir / NAME).unlink()
        except OSError:
            pass


def read(state_dir: Path) -> dict | None:
    """The study that is running on this CarMaker session, if any; ``mine`` says whether this
    process runs it. A file left behind by a process that no longer exists counts as none."""
    cur = _load(state_dir)
    if cur is None:
        return None
    pid = cur.get("pid")
    if not isinstance(pid, int) or not pid_alive(pid):
        return None
    return {**cur, "mine": pid == os.getpid()}


def _load(state_dir: Path) -> dict | None:
    try:
        data = json.loads((state_dir / NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
