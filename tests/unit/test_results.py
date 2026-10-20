import numpy as np
import pytest

from carmaker_mcp.results import Erg, ErgError, list_results


def make_erg(tmp_path, n=100, name="run.erg"):
    dt = np.dtype([("Time", "<f8"), ("Car.v", "<f4"), ("Cnt", "<i4")])
    data = np.zeros(n, dtype=dt)
    data["Time"] = np.arange(n) * 0.01
    data["Car.v"] = np.linspace(0, 10, n)
    data["Cnt"] = np.arange(n)
    p = tmp_path / name
    header = b"CM-ERG\0\0" + (1).to_bytes(2, "little") + dt.itemsize.to_bytes(2, "little") + bytes(4)
    p.write_bytes(header + data.tobytes())
    (tmp_path / (name + ".info")).write_text(
        "#INFOFILE1.1\nFile.Format = erg\nFile.ByteOrder = LittleEndian\n"
        "File.At.1.Name = Time\nFile.At.1.Type = Double\nQuantity.Time.Unit = s\n"
        "File.At.2.Name = Car.v\nFile.At.2.Type = Float\nQuantity.Car.v.Unit = m/s\n"
        "File.At.3.Name = Cnt\nFile.At.3.Type = Int\n"
    )
    return p


def test_summary_and_read(tmp_path):
    e = Erg(make_erg(tmp_path))
    assert e.n_rows == 100 and e.names == ["Time", "Car.v", "Cnt"]
    s = e.summary(["Time", "Car.v"])
    assert s["duration_s"] == pytest.approx(0.99)
    assert s["quantities"]["Car.v"]["max"] == pytest.approx(10.0)
    assert s["quantities"]["Car.v"]["unit"] == "m/s"
    r = e.read(["Time", "Cnt"], t_min=0.5, max_points=10)
    assert r["rows_returned"] <= 10 and r["data"]["Time"][0] >= 0.5
    assert e.search("car") == ["Car.v"]


def test_errors(tmp_path):
    p = make_erg(tmp_path)
    with pytest.raises(ErgError):
        Erg(p).column("Nope")
    data = bytearray(p.read_bytes())
    data[10:12] = (99).to_bytes(2, "little")  # header record size no longer matches the info file
    p.write_bytes(bytes(data))
    with pytest.raises(ErgError, match="record size"):
        Erg(p)
    with pytest.raises(ErgError):
        Erg(tmp_path / "missing.erg")


def test_truncated_file_reads_complete_rows(tmp_path):
    p = make_erg(tmp_path, n=10)
    p.write_bytes(p.read_bytes()[:-5])
    e = Erg(p)
    assert e.truncated and e.n_rows == 9


def test_list_results_skips_modelcheck(tmp_path):
    make_erg(tmp_path, name="a.erg")
    mc = tmp_path / "ModelCheck"
    mc.mkdir()
    make_erg(mc, name="check.erg")
    names = [r["name"] for r in list_results([tmp_path])]
    assert names == ["a.erg"]


def test_export_full_resolution_to_csv_and_mat(tmp_path):
    """Asked for in use: cm_results_read thins to 5000 points and there was no way to a .mat file."""
    e = Erg(make_erg(tmp_path, n=8000))
    r = e.export(tmp_path / "out.csv", ["Time", "Car.v"], t_min=10.0)
    assert r["rows"] == 7000 and r["units"] == {"Time": "s", "Car.v": "m/s"}
    lines = (tmp_path / "out.csv").read_text().splitlines()
    assert lines[0] == "Time [s],Car.v [m/s]" and len(lines) == 7001 and lines[1].startswith("10,")
    with pytest.raises(ErgError, match="refusing to overwrite"):
        e.export(tmp_path / "out.csv", ["Time"])
    with pytest.raises(ErgError, match="no quantity"):
        e.export(tmp_path / "x.mat", ["Nope"])
    assert not (tmp_path / "x.mat").exists()

    r = e.export(tmp_path / "out.mat", ["Time", "Car.v"])
    assert r["variables"] == {"Time": "Time", "Car.v": "Car_v"} and r["rows"] == 8000
    sio = pytest.importorskip("scipy.io")
    m = sio.loadmat(tmp_path / "out.mat")
    assert m["Car_v"].shape == (8000, 1) and m["Car_v"][-1, 0] == pytest.approx(10.0)
    assert [s.strip() for s in m["quantity_names"]] == ["Time", "Car.v"]
    assert [s.strip() for s in m["units"]] == ["s", "m/s"]


def test_crossings_give_gate_times(tmp_path):
    """Asked for in use: lap times from distance gates needed hand-made interpolation."""
    e = Erg(make_erg(tmp_path))  # Car.v rises linearly from 0 to 10 over 0.99 s
    r = e.crossings("Car.v", [2.5, 5.0, 20.0])
    assert r["crossings"][0]["first"] == pytest.approx(0.2475) and r["crossings"][2]["times"] == []
    assert r["between_first"][0] == pytest.approx(0.2475) and r["between_first"][1] is None
    assert e.crossings("Car.v", [5.0], direction="falling")["crossings"][0]["times"] == []
