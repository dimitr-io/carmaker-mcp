"""The driver of a test run: chosen by the test run, not by the vehicle."""

HEAD = "#INFOFILE1.1 (UTF-8) - Do not remove this line!\n"
TEMPLATE = HEAD + "FileIdent = CarMaker-DriverTemplate 14\nDriver.Acc.ayMax = 15.8\nDriver.Long.dtAccBrake = 0.01\n"
OWN = (HEAD + "Vehicle = Car_A\nVehicle.DriverTemplate.FName = TestRun\nDriver.Knowl.0.Vehicle = CAR_A\n"
       "Driver.Knowl.0.VehicleLimits.Testrun = Accel_A\nDriver.Acc.ayMax = 12\n")


def _setup(project):
    (project / "Data" / "Driver" / "Template").mkdir(parents=True)
    (project / "Data" / "Driver" / "Template" / "Fast").write_text(TEMPLATE)
    (project / "Data" / "TestRun" / "Sub" / "Own").write_text(OWN)


def test_read_names_the_driver_and_where_its_limits_are(session, project):
    _setup(project)
    d = session.project.read("testrun", "Sub/Own", prefix="Road")["driver"]
    assert d == {"template": "TestRun", "knowledge_vehicle": "CAR_A", "knowledge_testrun": "Accel_A",
                 "defined_in": "this test run", "values": {"Driver.Acc.ayMax": "12"}}
    session.edit_file("testrun", "Sub/Own", {"Vehicle.DriverTemplate.FName": "Fast"})
    d = session.project.read("testrun", "Sub/Own")["driver"]
    assert d["defined_in"] == "driver Template/Fast"
    assert d["values"] == {"Driver.Acc.ayMax": "15.8", "Driver.Long.dtAccBrake": "0.01"}
    assert d["unused_testrun_values"] == {"Driver.Acc.ayMax": "12"}  # the test run's own value, not used
    session.edit_file("testrun", "Sub/Own", {"Vehicle.DriverTemplate.FName": "Gone"})
    d = session.project.read("testrun", "Sub/Own")["driver"]
    assert d["defined_in"] is None and "no driver template 'Gone'" in d["note"] and d["values"] == {}


def test_a_new_vehicle_keeps_the_old_driver_and_says_so(session, project):
    """Observed: a test run cloned from another car's kept that car's driver and knowledge."""
    _setup(project)
    r = session.clone_file("testrun", "Sub/Own", "Sub/Copy")
    assert r["driver"]["template"] == "TestRun" and "keeps the source's driver" in r["driver_note"]
    r = session.edit_file("testrun", "Sub/Copy", {"Vehicle": "Car_B"})
    assert r["driver"]["knowledge_vehicle"] == "CAR_A" and "does not bring its own driver" in r["driver_note"]
    assert "driver" not in session.edit_file("testrun", "Sub/Copy", {"Road.FName": "x.rd5"})


def test_editing_a_template_says_it_is_shared(session, project):
    _setup(project)
    r = session.edit_file("driver", "Template/Fast", {"Driver.Acc.ayMax": 16})
    assert "Data/Driver/Template/Fast is used by every test run" in r["driver_note"]
