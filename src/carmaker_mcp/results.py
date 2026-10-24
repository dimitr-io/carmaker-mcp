"""Reader for CarMaker ``.erg`` result files (binary data + ``.erg.info`` description)."""

from __future__ import annotations

import fnmatch
import math
import re
import struct
import time
from pathlib import Path

import numpy as np

_TYPES = {
    "Double": "f8", "Float": "f4", "LongLong": "i8", "ULongLong": "u8", "Long": "i4",
    "ULong": "u4", "Int": "i4", "UInt": "u4", "Short": "i2", "UShort": "u2", "Char": "i1",
    "UChar": "u1",
}
_HEADER = 16
_MAGIC = b"CM-ERG"


class ErgError(Exception):
    pass


def _parse_info(path: Path) -> tuple[dict[str, str], str]:
    kv: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            kv[k.strip()] = v.strip()
    return kv, kv.get("File.ByteOrder", "LittleEndian")


class Erg:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        info_path = Path(str(self.path) + ".info")
        if not self.path.is_file() or not info_path.is_file():
            raise ErgError(f"need both {self.path.name} and {info_path.name}")
        kv, order = _parse_info(info_path)
        prefix = "<" if order.lower().startswith("little") else ">"
        self.names: list[str] = []
        self.units: dict[str, str] = {}
        fields = []
        i = 1
        while f"File.At.{i}.Name" in kv:
            name, typ = kv[f"File.At.{i}.Name"], kv.get(f"File.At.{i}.Type", "Double")
            if typ in _TYPES:
                dt = prefix + _TYPES[typ]
            elif typ.endswith("Bytes"):
                dt = f"S{int(typ.split()[0])}"
            else:
                raise ErgError(f"unsupported column type {typ!r} for {name}")
            fields.append((name, dt))
            self.names.append(name)
            self.units[name] = kv.get(f"Quantity.{name}.Unit", "")
            i += 1
        if not fields:
            raise ErgError("no columns found in info file")
        self.dtype = np.dtype(fields)
        with self.path.open("rb") as f:
            head = f.read(_HEADER)
        if len(head) < _HEADER or not head.startswith(_MAGIC):
            raise ErgError("not a CM-ERG file")
        rec = int.from_bytes(head[10:12], "little")
        if rec != self.dtype.itemsize:
            raise ErgError(
                f"record size mismatch: header says {rec} bytes, info file describes "
                f"{self.dtype.itemsize}"
            )
        payload = self.path.stat().st_size - _HEADER
        self.n_rows = payload // self.dtype.itemsize
        self.truncated = payload % self.dtype.itemsize != 0
        self._data = (
            np.memmap(self.path, dtype=self.dtype, mode="r", offset=_HEADER, shape=(self.n_rows,))
            if self.n_rows
            else np.empty(0, dtype=self.dtype)
        )

    def column(self, name: str) -> np.ndarray:
        if name not in self.names:
            raise ErgError(f"no quantity {name!r} (use search to find names)")
        return np.asarray(self._data[name])

    def search(self, text: str, limit: int | None = 100) -> list[str]:
        """Quantity names containing ``text``, or matching it if it has wildcards (``*``, ``?``)."""
        t = text.lower()
        if any(c in t for c in "*?["):
            hits = [n for n in self.names if fnmatch.fnmatchcase(n.lower(), t)]
        else:
            hits = [n for n in self.names if t in n.lower()]
        return hits if limit is None else hits[:limit]

    def read(
        self, names: list[str], t_min: float | None = None, t_max: float | None = None,
        max_points: int = 500,
    ) -> dict:
        idx = self._window(t_min, t_max)
        stride = max(1, math.ceil(len(idx) / max(1, max_points)))
        idx = idx[::stride]
        cols = {n: _clean(self.column(n)[idx]) for n in names}
        return {
            "file": self.path.name, "rows_total": self.n_rows, "rows_returned": len(idx),
            "stride": stride, "units": {n: self.units.get(n, "") for n in names}, "data": cols,
        }

    def summary(self, names: list[str]) -> dict:
        out = {}
        for n in names:
            c = self.column(n)
            if c.dtype.kind == "S" or len(c) == 0:
                out[n] = {"unit": self.units.get(n, "")}
                continue
            c = c.astype(float)
            f = c[np.isfinite(c)]
            out[n] = {
                "unit": self.units.get(n, ""),
                "first": _num(c[0]), "last": _num(c[-1]),
                "min": _num(f.min()) if len(f) else None, "max": _num(f.max()) if len(f) else None,
                "mean": _num(f.mean()) if len(f) else None,
            }
        t_end = float(self.column("Time")[-1]) if "Time" in self.names and self.n_rows else None
        return {"file": self.path.name, "rows": self.n_rows, "duration_s": t_end, "quantities": out}


    def _window(self, t_min: float | None, t_max: float | None) -> np.ndarray:
        idx = np.arange(self.n_rows)
        if (t_min is not None or t_max is not None) and "Time" in self.names:
            t = self.column("Time")
            m = np.ones(self.n_rows, dtype=bool)
            if t_min is not None:
                m &= t >= t_min
            if t_max is not None:
                m &= t <= t_max
            idx = idx[m]
        return idx

    def export(self, target: Path, names: list[str], t_min: float | None = None,
               t_max: float | None = None) -> dict:
        """Write quantities at full resolution to a .mat (MATLAB 5 format, one variable per quantity,
        dots in names become underscores, plus ``quantity_names`` and ``units``) or a .csv file."""
        fmt = target.suffix.lower()
        if fmt not in (".mat", ".csv"):
            raise ErgError("the file must end in .mat or .csv")
        if target.exists():
            raise ErgError(f"{target} exists; refusing to overwrite")
        if not target.parent.is_dir():
            raise ErgError(f"folder {target.parent} does not exist")
        for n in names:
            self.column(n)  # unknown names fail here, before anything is written
        # Result files hold padding columns of bytes ('$none$'): they are no quantities.
        skipped = [n for n in names if self.dtype[n].kind in "SUV"]
        names = [n for n in names if n not in skipped]
        idx = self._window(t_min, t_max)
        cols = {n: np.asarray(self.column(n)[idx], dtype=float) for n in names}
        units = [self.units.get(n, "") for n in names]
        if fmt == ".csv":
            head = ",".join(f"{n} [{u}]" if u else n for n, u in zip(names, units, strict=True))
            table = np.column_stack([cols[n] for n in names]) if names else np.empty((len(idx), 0))
            np.savetxt(target, table, delimiter=",", header=head, comments="", fmt="%.10g")
        else:
            target.write_bytes(_mat5({**{_mat_name(n): cols[n] for n in names}},
                                     {"quantity_names": names, "units": units}))
        return {"file": str(target), "format": fmt[1:], "rows": len(idx), "quantities": names,
                "units": dict(zip(names, units, strict=True)),
                "variables": {n: _mat_name(n) for n in names} if fmt == ".mat" else None,
                "skipped": skipped or None}

    def crossings(self, name: str, values: list[float], direction: str = "any", limit: int = 20,
                  at: list[str] | None = None) -> dict:
        """Times (linearly interpolated) at which a quantity reaches each value; for a distance
        quantity these are gate times. ``direction``: any, rising or falling. ``at``: other quantities,
        interpolated at the first crossing (e.g. the speed at 75 m)."""
        if direction not in ("any", "rising", "falling"):
            raise ErgError("direction must be any, rising or falling")
        x = self.column(name).astype(float)
        t = self.column("Time").astype(float)
        out = []
        for v in values:
            a, b = x[:-1] - v, x[1:] - v
            hit = (a <= 0) & (b > 0) if direction == "rising" else (a >= 0) & (b < 0) \
                if direction == "falling" else ((a <= 0) & (b > 0)) | ((a >= 0) & (b < 0))
            times = []
            for i in np.flatnonzero(hit)[:limit]:
                f = 0.0 if x[i + 1] == x[i] else (v - x[i]) / (x[i + 1] - x[i])
                times.append(float(t[i] + f * (t[i + 1] - t[i])))
            hit_at: dict = {"value": v, "times": times, "first": times[0] if times else None}
            if at and times:
                hit_at["at_first"] = {q: _num(np.interp(times[0], t, self.column(q).astype(float)))
                                      for q in at}
            out.append(hit_at)
        firsts = [c["first"] for c in out]
        pairs = zip(firsts[:-1], firsts[1:], strict=True)
        between = [None if a is None or b is None else b - a for a, b in pairs]
        return {"file": self.path.name, "quantity": name, "unit": self.units.get(name, ""),
                "range": [_num(np.nanmin(x)), _num(np.nanmax(x))] if len(x) else None,
                "crossings": out, "between_first": between}


def _mat_name(name: str) -> str:
    s = re.sub(r"\W", "_", name)
    return ("q_" + s if not s[:1].isalpha() else s)[:63]


def _mat5(arrays: dict[str, np.ndarray], texts: dict[str, list[str]]) -> bytes:
    """A MATLAB 5 MAT file: double column vectors and char matrices (one row per string)."""
    def element(kind: int, data: bytes) -> bytes:
        return struct.pack("<II", kind, len(data)) + data + b"\0" * (-len(data) % 8)

    def matrix(name: str, cls: int, dims: tuple[int, int], body: bytes) -> bytes:
        inner = (element(6, struct.pack("<II", cls, 0)) + element(5, struct.pack("<ii", *dims))
                 + element(1, name.encode("ascii")) + body)
        return element(14, inner)

    out = b"MATLAB 5.0 MAT-file, written by carmaker-mcp".ljust(116) + b"\0" * 8
    out += struct.pack("<H", 0x0100) + b"IM"  # version, little endian
    for name, a in arrays.items():
        a = np.ascontiguousarray(a, dtype="<f8")
        out += matrix(name, 6, (len(a), 1), element(9, a.tobytes()))
    for name, rows in texts.items():
        width = max((len(r) for r in rows), default=0)
        grid = np.array([[ord(c) for c in r.ljust(width)] for r in rows] or [[]], dtype="<u2")
        grid = grid.reshape(len(rows), width)
        out += matrix(name, 4, (len(rows), width), element(4, grid.flatten(order="F").tobytes()))
    return out


def _num(x) -> float | None:
    x = float(x)
    return x if math.isfinite(x) else None


def _clean(a: np.ndarray) -> list:
    if a.dtype.kind == "S":
        return [v.decode("latin-1") for v in a]
    return [_num(v) for v in a.astype(float)]


def list_results(dirs: list[Path], limit: int = 30, include_modelcheck: bool = False) -> list[dict]:
    seen: dict[str, dict] = {}
    for d in dirs:
        if not d.exists():
            continue
        for p in d.rglob("*.erg"):
            if not include_modelcheck and "modelcheck" in (x.lower() for x in p.parts):
                continue
            if not Path(str(p) + ".info").exists():
                continue
            st = p.stat()
            seen[str(p)] = {"path": str(p), "name": p.name, "size_bytes": st.st_size, "mtime": st.st_mtime}
    items = sorted(seen.values(), key=lambda r: r["mtime"], reverse=True)[:limit]
    for r in items:
        r["modified"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.pop("mtime")))
    return items


__all__ = ["Erg", "ErgError", "list_results"]
