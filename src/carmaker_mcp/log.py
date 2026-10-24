"""Read-only access to CarMaker's session logs (``<project>/SimOutput/<host>/Log/*.log``).

The log is tab separated: a keyword, then the text, for example::

    SIM_START   My Runs/Braking   2026-01-01 12:00:00
    WARNING     IPGDriver: ...
    ERROR       PowerTrain.Motor Mapping: can't initialize torque map
    SIM_END     My Runs/Braking   5.055s   76.1026m

Libraries that CarMaker loads write their own messages indented and in another form, for example the
tyre library's ``<TAB><TAB>WARNING - Override value ... is ignored``: their level is the first word too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_LEVELS = {"error": ("ERROR", "FATAL"), "warning": ("ERROR", "FATAL", "WARNING")}
_LEVEL = re.compile(r"^\s*(FATAL|ERROR|WARNING)\b")
_SIM_END = re.compile(r"^SIM_END\s+(?P<name>.*?)\s+(?P<time>[0-9.eE+-]+)s\s+(?P<dist>[0-9.eE+-]+)m\s*$")


@dataclass(frozen=True)
class LogMark:
    """A position in the session log, taken before an action to read only what it appended."""

    path: Path | None
    size: int


def newest_log(project_root: Path) -> Path | None:
    logs = list((Path(project_root) / "SimOutput").glob("*/Log/*.log"))
    return max(logs, key=lambda p: p.stat().st_mtime) if logs else None


def _lines(text: str) -> list[str]:
    return [ln.rstrip() for ln in text.splitlines() if ln.strip()]


def _read(path: Path, start: int = 0) -> str:
    with path.open("rb") as f:
        f.seek(start)
        return f.read().decode("utf-8", errors="replace")


def filter_level(lines: list[str], level: str = "all") -> list[str]:
    """``level``: all, warning (warnings and errors) or error."""
    if level == "all":
        return lines
    if level not in _LEVELS:
        raise ValueError("level must be all, warning or error")
    keep = _LEVELS[level]
    return [ln for ln in lines if (m := _LEVEL.match(ln)) and m[1] in keep]


def warnings_only(lines: list[str]) -> list[str]:
    """The warning lines, without errors."""
    return [ln for ln in lines if (m := _LEVEL.match(ln)) and m[1] == "WARNING"]


def tail(project_root: Path, lines: int = 50, level: str = "all") -> dict:
    """Last ``lines`` lines of the newest session log, optionally only warnings / errors."""
    path = newest_log(project_root)
    if path is None:
        return {"file": None, "lines": []}
    sel = filter_level(_lines(_read(path)), level)
    return {"file": str(path), "total": len(sel), "lines": sel[-max(1, int(lines)):]}


def mark(project_root: Path) -> LogMark:
    path = newest_log(project_root)
    return LogMark(path, path.stat().st_size if path else 0)


def since(project_root: Path, m: LogMark) -> list[str]:
    """Lines written after ``m`` (the whole file if a newer log file appeared since)."""
    path = newest_log(project_root)
    if path is None:
        return []
    start = m.size if m.path is not None and path == m.path and path.stat().st_size >= m.size else 0
    return _lines(_read(path, start))


def sim_end(lines: list[str]) -> dict | None:
    """Simulation time and distance from the last ``SIM_END`` line, if there is one."""
    for ln in reversed(lines):
        mt = _SIM_END.match(ln)
        if mt:
            return {"testrun": mt["name"], "sim_time_s": float(mt["time"]), "distance_m": float(mt["dist"])}
    return None


_LAP = re.compile(r"^\s*Lap\s+(\d+):\s+t=\s*([0-9.]+)s")


def lap_times(lines: list[str]) -> list[float]:
    """CarMaker's own lap times of a lap-driven run ('Lap   2: t=  59.564s ...' in the session log).
    Found in use: DM.Lap.Time in the result file holds the last lap only after the next one starts, so a
    run that ends with its last lap never stores that lap's time."""
    laps: dict[int, float] = {}
    for ln in lines:
        mt = _LAP.match(ln)
        if mt:
            laps[int(mt[1])] = float(mt[2])
    return [laps[k] for k in sorted(laps)]


def dedupe(lines: list[str], limit: int = 10) -> list[str]:
    """Collapse repeated messages (a log can repeat one warning hundreds of times)."""
    counts: dict[str, int] = {}
    for ln in lines:
        key = " ".join(ln.split())
        counts[key] = counts.get(key, 0) + 1
    out = [k if n == 1 else f"{k} (x{n})" for k, n in counts.items()]
    return out[-limit:]
