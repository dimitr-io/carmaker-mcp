"""Plots in IPGControl: the script IPGControl runs, and what the server makes of its report."""

from pathlib import Path

import pytest

from carmaker_mcp import plot
from carmaker_mcp.backend import BackendError


def test_script_names_the_files_quantities_and_axis(tmp_path):
    s = plot.script(2, ["Car.ay", "Car.YawRate"], "Car.Distance", tmp_path / "out.txt")
    assert "{F1 F2} {Car.ay Car.YawRate} {Car.Distance}" in s and (tmp_path / "out.txt").as_posix() in s
    with pytest.raises(BackendError, match="not a quantity name"):
        plot.script(1, ["Car.ay} ; exit {"], None, tmp_path / "x")  # nothing that could run in IPGControl


def test_report_is_mapped_back_to_the_files():
    files = [Path("a.erg"), Path("b.erg")]
    r = plot.parse("added F1 Car.ay\nmissing F2 Car.ay\nx Car.Distance\nerror F1 Car.v boom\ndone\n", files)
    assert r["plotted"] == [{"file": "a.erg", "quantity": "Car.ay"}]
    assert r["missing"] == [{"file": "b.erg", "quantity": "Car.ay"}]
    assert r["x"] == "Car.Distance" and r["errors"] == ["error F1 Car.v boom"]


def test_ipgcontrol_is_found_next_to_carmaker(tmp_path, monkeypatch):
    monkeypatch.delenv("CM_IPGCONTROL", raising=False)
    for v in ("3.0.9", "3.0.17"):
        exe = tmp_path / "IPG" / "control" / f"win64-{v}" / "bin" / plot.EXE
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"")
    found = plot.find_ipgcontrol(tmp_path / "IPG" / "carmaker" / "win64-14.1.1")
    assert found.parent.parent.name == "win64-3.0.17"  # the newest
