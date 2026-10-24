"""Text an agent can read: server instructions, a short guide (resource) and prompt templates."""

from __future__ import annotations

INSTRUCTIONS = (
    "Drives IPG CarMaker. Two ways to simulate: (1) the MATLAB-connected CarMaker for Simulink session "
    "(cm_* tools without 'standalone'), needed when the vehicle's controller is a Simulink model; "
    "(2) independent CarMaker processes without MATLAB (cm_standalone_* tools). "
    "Typical run: cm_status, cm_load_testrun, cm_start_sim, then cm_wait_end repeatedly until "
    "finished=true (it returns result_file), then cm_results_summary / cm_results_read. "
    "If nothing is running yet call cm_session_start; if a run fails read cm_log and cm_popups. "
    "Typical study: cm_doctor (ready per mode), cm_read of the test run (its driver), cm_study_start "
    "(variations, gates='markers' for lap times as CarMaker's own timing), cm_study_wait(until_done=true), "
    "then cm_results_crossings / cm_results_plot / cm_results_export. This server has no MATLAB evaluation: plot with cm_results_plot (IPGControl), or "
    "use a MATLAB server for MATLAB figures. "
    "Edits (cm_edit, cm_set_workspace_var, cm_model_set) change real project files and the live model: "
    "each is backed up and logged, and cm_revert_all undoes this session's changes. "
    "The simulation must be idle for loads, edits and reverts. "
    "Every run goes at CarMaker's maximum speed by default (the GUI's 'max'): leave 'speed' out. Pass a "
    "slower speed only when the user asks for one; to watch a run, use IPGMovie. "
    "The test run, not the vehicle, chooses the driver: Vehicle.DriverTemplate.FName names a template in "
    "Data/Driver/Template (or 'TestRun' for the one saved in the test run), and the driver's knowledge is "
    "learnt for one vehicle. Changing Vehicle or cloning another vehicle's test run keeps the old driver: "
    "check `driver` in the answer of cm_read, cm_edit or cm_clone, and ask the user which template if "
    "unclear. Driver parameters (Driver.Acc.*, dtAccBrake, StWhlAngle*) are changed in the template file "
    "(cm_edit kind 'driver'), which other test runs share: tell the user which file changed. As test-run "
    "or study keys they change nothing while a template is named; in a study use a variation's 'driver' "
    "(a temporary template copy per run). Lap times "
    "depend on the driver's limit Driver.Acc.ayMax: compare vehicle variants each at its own limit. "
    "Driver.Acc.GGExp (rows 'vel_kmh exp_acc exp_dec') shapes how much lateral and longitudinal "
    "acceleration the driver combines; for a car with aero downforce, exponents rising with speed (e.g. "
    "10 1.5 1.5 / 30 2 2 / 60 3 3 / 90 5 5) are often right, a flat table holds it back at speed. "
    "Driver choice: the race driver only on closed circuits (Autocross, Endurance), adapted to both car "
    "and course; the standard driver for Acceleration and Skid Pad, with the limit in focus (axMax, or "
    "ayMax) set very high so the car, not the driver, is the limit. cm_driver_adaption runs a driver "
    "adaption and saves the knowledge; it takes minutes (about 2 standalone, 5 to 20 with MATLAB): run it only "
    "when the car changed noticeably, the race driver lacks knowledge, or the user asks. To follow a speed "
    "exactly (input from file, validation) set dtAccBrake and dtMinAccelDecel to about 0.01 s. "
    "cm_guide('ipgdriver') has the lap-time procedure, corner cutting, adaption and every Driver.* key "
    "with its default; cm_guide lists the other topics. "
    "A run that ends 'completed' does not prove every setting was applied: CarMaker reports ignored or "
    "unsupported parameters only as WARNING lines in the session log (log_warnings of cm_wait_end and of "
    "study rows, cm_log(level='warning')), for example a tyre override not supported at the tyre file's "
    "FITTYP. A result identical to the baseline after a parameter change is a reason to read them."
)

GUIDE = """\
# carmaker-mcp guide

## Run a test run (CarMaker for Simulink session)
1. `cm_status`: must be connected and idle. Not connected: `cm_session_start` (repeat until ready), or `cm_doctor`.
2. `cm_load_testrun(name)`: name relative to Data/TestRun; find names with `cm_list("testrun")`.
3. `cm_start_sim()`: returns when the run has left idle (a Simulink model may compile first, up to a minute or more).
4. `cm_wait_end()`: returns after at most 45 s. `finished=false` means still running: call again.
   `finished=true` carries `end_status`, `sim_time_s`, `distance_m`, `result_file`, `log_errors`, `popups`.
5. `cm_results_summary(result_file, quantities)` for first/last/min/max/mean, `cm_results_read` for time series.
   `cm_results_summary(file, search="Car.v*")` finds quantity names (`search="*"` lists all).

## Choose what a run stores
`cm_output_quantities` lists the quantities the next run writes to its result file.
`cm_output_quantities_edit(add=[...], remove=[...])` changes the list from the next start on; wildcards work
(`PT.Motor*.Trq`). A name CarMaker does not know is left out silently: check with `cm_results_summary(search=...)`.

## See the car (IPGMovie)
1. `cm_movie_open` BEFORE the run: IPGMovie records a run only while it is open.
2. Run as usual, wait for the end.
3. `cm_movie_snapshot(time_s=12.5, camera="Bird's Eye View")` returns a picture of that moment of the last run.
During a run, `cm_movie_snapshot()` without `time_s` shows the IPGMovie window as it is at that moment and
can be repeated; do not pass `time_s` during a run (that makes IPGMovie stop following it). A saved result file can be
replayed with `erg=...` if it holds the vehicle's motion: `cm_output_quantities_edit(preset="movie")` before
that run.
If a picture fails with an internal error of IPGMovie, try once more, then `cm_movie_open(restart=true)`.
CarMaker's programs show errors of their own in a dialog "Internal Debugger": `cm_popups` reads and closes it.

## Run without MATLAB (standalone)
`cm_standalone_launch(testrun, overrides?, stop_after_s)` then `cm_standalone_wait_end` (repeat) and
`cm_standalone_results`. Only for vehicles whose controller is built into CarMaker. `overrides` changes
test-run keys in memory, no file is edited. Close with `cm_standalone_close`.

## Change parameters
* Project files (test run, vehicle, driver, tyre): `cm_read`, then `cm_edit(kind, name, {key: value})`.
  Load the test run again afterwards. `cm_diff(kind, a, b)` compares two files (two vehicles, a clone).
* Controller parameters usually live in the Simulink **model workspace**:
  `cm_list_workspace_vars(scope=<model>)`, `cm_get_workspace_var`, `cm_set_workspace_var(name, value, scope=<model>)`.
  They change in memory only; `cm_model_save` persists them. A variable the model has in its own workspace
  is not changed by setting one of the same name in the base workspace: the answer then says `overruled_by`.
* The result file (.erg) holds CarMaker's quantities. What Simulink logged (signals marked for logging,
  To Workspace blocks) is saved after the run with `cm_model_logs_save`: one MAT file with the signals and
  the base and model workspaces. `cm_start_sim(save_logs=true)` and `cm_study_start(..., save_logs=true)`
  do that for every run (`logs_file` in the result).
* Several settings of one test run: `cm_study_start` runs them one after another. Wait with `cm_study_wait`
  (not `cm_wait_end`, at most 50 s per call); it answers one brief line per run. `cm_study_status` gives
  the table; `rank_by='sectors'` (or `'Car.v.max'`, ...) ranks the valid runs with their result files,
  `top` keeps the best, `with_studies` ranks several studies together, `labels` picks rows.
  `grid` runs every combination of value lists (a g-g table is one value); `driver_scale` multiplies the
  driver's own value instead (`{'Driver.Acc.GGExp': [1, 2, 4]}`: the exponents, not the speeds).
  `rerun={'study': id, 'labels': ['best']}` with `movie=true, keep_open=true` shows a run again in
  IPGMovie; a window an earlier study kept open is reused. A study stops at the first run that finds no
  CarMaker licence; programs the server left open hold one (`close_open=true`). A vehicle with Simulink
  parts (`PowerTrain.Control.Kind = CM4SL ...`) runs only in the MATLAB session: `cm_read` of the test
  run says `standalone: false`, and standalone launches and studies refuse it.
  Only one study runs on a CarMaker session at a time, also across conversations: `cm_status` shows
  `study_running`, and loads, starts and stops are refused meanwhile. Cancel only a study you started.
* A new file (a tyre property file with other values, for example): `cm_clone` to copy and `cm_edit` to change
  an infofile, or `cm_create(kind, name, content)` to write any text file. Do not write project files with a
  shell: the server then knows nothing of them and cannot take them back.

## The driver (IPGDriver)
The test run chooses its driver, not the vehicle: `Vehicle.DriverTemplate.FName` names a template in
Data/Driver/Template, or is `TestRun` for the parametrization saved in the test run itself;
`Vehicle.KnowledgeTemplate.Name` and `Driver.Knowl.0.*` hold what the driver learnt, and for which vehicle.
`cm_read` of a test run returns this as `driver`, with the main limits read from where they are defined.
* Changing `Vehicle`, or `cm_clone` of another vehicle's test run, keeps the old driver and its knowledge.
  Check `driver` and set `Vehicle.DriverTemplate.FName` (`cm_edit`); ask the user which template if unclear.
* Driver parameters (`Driver.Acc.axMax/axMin/ayMax`, `Driver.Long.dtAccBrake`, `Driver.Vel.dtMinAccelDecel`,
  `Driver.Long.TractionControl`, `Driver.Lat.StWhlAngle*`) belong in the template:
  `cm_edit("driver", "Template/<name>", ...)`. A template is shared by every test run that names it:
  tell the user which file changed. While a template is named, the same keys set on the test run or as
  study `keys` change nothing (checked: a standalone skid pad run with `Driver.Acc.ayMax` as a key was
  identical to the stock run). For a study, put driver values in a variation's `driver`: each run gets a
  copy of the template with those values, deleted afterwards, and no project file changes.
* IPGDriver corners only as fast as `Driver.Acc.ayMax` allows, not as fast as the car could: a run whose
  largest `Car.ay` is close to it was limited by the driver. To compare vehicle variants on time, give each
  its own limit (a template per variant, or a value the user agrees to), judge only runs that ended
  `completed` by the time for the course, and report the limits used. `DM.Lap.Time` holds lap times only
  when the course is driven as laps.
* Lap and sector times: a test run's trigger point markers (type DrivManTrigger: mode 1 starts the
  timing, 2 takes a time, 3 does both) are how CarMaker times a course such as a skid pad; it reports
  them as `DM.TriggerPoint.Time` and `.Id`. `cm_study_start(gates="markers")` gives each row these
  `sectors`: each is the time from the last reference marker to that marker, a lap time on a skid pad
  (the second right and the second left circle), not a split within a lap. A run that left the road gets
  `null`, not a time. `cm_results_crossings` on `Vhcl.sRoad` differs by a few ms, because it interpolates
  the road position while CarMaker times at the step the trigger fires. Gates by hand belong on the road
  position `Vhcl.sRoad`: the odometer `Car.Distance` reads long when the driver cuts a circle (about 15 ms
  per skid pad lap).
* `Driver.Acc.GGExp` is a table, one row per speed: `vel_kmh exp_acc exp_dec`, the exponents of the
  driver's g-g diagram when accelerating and braking. 1 is an ellipse (lateral and longitudinal
  acceleration traded against each other); larger values let the driver combine more of both, which is
  faster up to the point where the car leaves the course or spins. A car with aerodynamic downforce has
  more grip at speed, so exponents that rise with speed often suit it, for example
  `10 1.5 1.5` / `30 2 2` / `60 3 3` / `90 5 5`. A flat table holds such a car back at high speed. The
  speed-dependent limits `Driver.Acc.VelDepend` (used with `Driver.Acc.UseVelDepend = 1`) serve the same
  purpose for `ayMax` and `axMax`. If a run leaves the course, lower the exponents a little.
* Choosing the driver, the lap-time procedure, corner cutting, following a speed exactly, driver
  adaption and all driver keys: section "IPGDriver reference" (`cm_guide("ipgdriver")`).
* Replays from input from file: the steering angle reaches `DM.Steer.Ang` about 0.14 s late (a pure delay,
  not changed by the driver's steering limits), the `Velocity` channel without delay. Advance the steering
  in the file by that time when comparing yaw response with measurements. In such a replay
  `dtAccBrake` and `dtMinAccelDecel` did not change the result.

## IPGDriver reference
Sources: IPG's IPGDriver User Manual 14.1.1 (chapters in brackets), IPG's Formula CarMaker Tutorial (FCM)
and the CarMaker User's Guide. Keys are infofile keys of the driver template (or of the test run when its
driver is `TestRun`); defaults in brackets.

### Choosing the driver: standard or race
* Race driver (`Driver.Mode = race`): only on closed race circuits. It is optimised for the fastest lap on
  a closed track, so it is the choice for Autocross and Endurance. It must be adapted to both the car and
  the course (Basic adaption, then Race Driver Adaption on that track), and adapted again after any
  change to the car or the test run; with out-of-date knowledge the results differ. Its accelerations
  come from the knowledge (speed dependent table `Driver.Knowl.<i>.Vhcl.Acc`) and a slip controller
  drives each tyre close to the learnt maximum slip; most standard fields are unused.
  Manual example (5.4, Hockenheim): race driver 93.2 s, standard driver with everyday limits 144.2 s.
* Standard, user parameterised driver (`Driver.Mode = std`): for Acceleration, Skid Pad and other
  manoeuvres; FCM recommends it for FS cars (reproducible, tunable per discipline). Focus it on the task
  by setting the limit of the dynamics in focus very high, `axMax` for Acceleration and `ayMax` for Skid
  Pad, even unrealistic values such as 50 m/s^2, so that the car and not the driver sets the limit and
  the run finds the car's limits. FCM starting point:
  the aggressive preset, a lower `dtAccBrake`, `dtMinAccelDecel` = 0, accelerations and g-g exponents
  doubled; if the car leaves the road or rolls over, lower the accelerations step by step.
* Presets (GUI: right-click in the driver dialog; 3.3), normal / defensive / aggressive: cruising speed
  150/100/250 km/h, CornerCutCoef 0.5/0.25/0.8, dtAccBrake 0.5/0.75/0.25 s, dtMinAccelDecel 4/8/0.5 s,
  axMax 3/2/4, axMin -4/-2/-6, ayMax 4/3/5 m/s^2, g-g exponents 1/0.5/1.5.

### Lap-time optimisation procedure (FCM 6.4.4)
1. The vehicle parameterisation is complete and simulates without errors.
2. Benchmark run (optional): `cm_results_plot`, lap times with `cm_study_start(gates="markers")`.
3. Driver Adaption - Basic Knowledge.
4. Driver Adaption - Race Driver Adaption.
5. Refine the g-g exponents iteratively.
6. Adjust the race driver's learning rate if required.
Repeat after significant changes to the car.

### How the driver plans and drives (2)
* Before the run it plans once. The course (Static Desired Course) from the route, shaped by the course
  coefficients below. Then the speed (Static Desired Velocity): the lowest of cruising speed, speed limits
  and the cornering speed v = sqrt(ayMax / curvature), ramped with axMax and axMin and combined through
  the g-g exponents, then smoothed: accel/decel sequences shorter than `dtMinAccelDecel` are removed.
* During the run a longitudinal and a lateral controller follow course and speed, using preview times
  from the knowledge. Gas and brake are never pressed together; switching waits `dtAccBrake`.
* `Driver.OutSdcv = 1` writes the planned course and speed to SimOutput: what the driver intended.

### Corner cutting (2.2, 3.1.5)
`Driver.Course.CornerCutCoef` (0) shapes the planned course: 0 = the route itself (lane centre), 1 = the
whole lane width (the car's side is led to the inner lane edge and back to the lane centre before the
curve ends), above 1 = outside the lane. The course optimiser (smallest curvature, swinging out before and
after curves) needs at least 0.01: between 0 and 0.01 nothing is optimised, and 0.01 follows the course
more accurately than 0. Cutting widens the curve radius, so the planned cornering speed rises and the
driven distance shrinks (why the odometer `Car.Distance` reads short of the road position on a skid pad).
Presets use 0.25 to 0.8 (the manual's race driver 0.8); its steady-circle example uses 0 to hold the radius.
Use 0 or 0.01 to follow a defined line (steady circle, a measured path), more to let the driver use the
lane for lap time, and compare variants at the same value. Race Driver Adaption may need a slightly lower
value to complete its laps (FCM 6.4). Related: `CornerRoundCoef` (0; > 0 rounder, lower peak curvature),
`ApexShiftCoef` (0; moves the apex; the manual gives both directions for positive values, so check),
`ShapeCoef` (1), `PylonShiftFdCoef`/`PylonShiftBkCoef` (0.1; pylon lane changes, 0 to 0.3), `LapDriving` (1).

### Following a speed exactly (Input from File, model validation)
Set `Driver.Long.dtAccBrake` (the forced wait between gas and brake, 0.1 s) and `Driver.Vel.dtMinAccelDecel`
(removes accel/decel sequences shorter than this from the planned speed, 0 s; presets 4 s and more) very
low, about 0.01 s, so the driver can follow quick speed changes; keep `Driver.Long.DevMax` 0,
`Driver.Long.tReact` 0, `Driver.Long.AccuracyCoef` 1, and run a Basic adaption so the preview times fit
the car. Too small preview times overshoot, too large ones lag (5.6). A speed that reaches the car directly
(for example `VelExtInput` in a replay) bypasses this planning: there these keys change nothing.

### Driver adaption and knowledge (3.2, 4)
* What the driver knows about a car (the knowledge, keys `Driver.Knowl.<i>.*`, several cars per template)
  comes from a driver adaption. Basic: Vehicle Limits (idle, top speed per gear, open-loop steering:
  `nEngine.MaxSpeed`, the speed dependent acceleration table `Vhcl.Acc`, maximum tyre slip `Long.SlipMax`,
  pedal free play) and Controller Dynamics (step responses and closed-loop runs: `Long.tPreviewAcc/Bra`,
  `Long.tPreEngDyn/Dead`, `Long.tPreBraDyn/Dead`, `Lat.tPreview`, `Lat.tYawPro`, `Lat.tPreDyn`). Road
  friction for the adaption 1.0. Progress: quantity `Driver.Adapt.Phase`. Not for trailers or motorcycles.
* The learnt limits are open-loop (longitudinal without lateral and the other way round), so
  `Driver.Acc.Factor.Accel/Decel/Lateral` (1/1/0.95) keep a reserve. A race driver leaving the road after
  an adaption: lower the decel and lateral factors step by step (FCM 5.5.3).
* Run it with `cm_driver_adaption(action="start", kind="basic" or "race", testrun=...)`, then
  `action="wait"` until `state` is done or failed. It saves the knowledge into the driver template file, or
  into the test run when its driver is kept there, after a backup: `cm_revert_all` undoes it. In the
  MATLAB session the session's GUI runs it; without MATLAB the server starts a CarMaker GUI of its own
  (cars without a Simulink controller only). Measured: an FS car's Basic adaption took 94 s standalone at
  maximum speed. Behind it is the GUI's script command `Driver adaptbasicknowledge` / `adaptracedriver`.
* Needed for the race driver, optional but helpful for the standard driver. Run it again after changes
  with a real effect on the car (tyres, suspension, powertrain), not after small ones.
* **It takes long:** Basic about 2 minutes standalone and 5 to 20 in the MATLAB session (measured: 17 min
  for an FS car with a Simulink controller, with no phase shown, only `wall_s`); the Race
  Driver Adaption needs a run of at least 1000 s. Run it only when the car changed noticeably, when the
  race driver has no knowledge for this car and course, or when the user asks, and tell the user the
  expected duration first.
* Race Driver Adaption: closed, flat circuit with simple corners, after a Basic adaption. It lowers the lap
  time lap by lap by raising the acceleration table towards the maximum tyre slip, and saves the knowledge
  after each lap. Exponents first: start from defaults, look at Car.v, Car.ay, Car.ax at a few speeds,
  raise the exponents until the lap time converges, lower them when the car leaves the track (spinning
  while braking: lower `exp_dec`, while accelerating: lower `exp_acc`; manual example 2.0/1.75 to
  1.5/1.25). Then the learning rate: sensitive for an oversteering car, aggressive for understeer;
  inconsistent lap times are the sign.
* A powertrain built in Simulink can leave the adapted driver crawling: then `Driver.Learn.vIdle` in the
  test run must be above 0 (FCM 5.5.3).
* Options in the driver's parameter field: `Driver.Adapt.NoLaDy` (only longitudinal), `WeakSide` (1 left,
  -1 right), `LimitSpeed` (500 km/h), `MinimizeYFlag` (1), `JerkYRed` (0.05).

### Other driver keys (3.1)
* Speed: `Driver.Vel.CruisingSpeed` (km/h), `Driver.Vel.LatInclFromRoad` (1, use banking),
  `Driver.Long.Road3DRedCoef` (0, 1 ignores bumps and crests), `Driver.Vel.MinimumSpeed` (1 km/h).
* Accelerations: `Driver.Acc.axMax/axMin/ayMax` (2/-4/4 m/s^2), `Driver.Acc.GGExp` (rows `vel_kmh exp_acc
  exp_dec`, n in (ax/axmax)^n + (ay/aymax)^n = 1, linear between rows; default `50 1 1`),
  `Driver.Acc.UseVelDepend` (0; 1 = the knowledge table), `Driver.Acc.VelDepend.UserDefined` with the
  table `Driver.Acc.VelDepend` (`vel_kmh acc dec lat`).
* Pedals: `Driver.Long.dtAccBrakeKind` (0 = the pedal wait may be overruled when unstable),
  `Driver.Long.TractionControl` (1; the driver eases the throttle at wheel spin using the learnt slip: set
  0 to test the car's own traction control), `Driver.Long.SmoothCoef` (0), `Driver.Long.ThrottleAmp`,
  `Driver.Long.BrakeAmp` (1), `Driver.Long.SmoothThrottleLimit` (1), pedal speeds `ThrottleVelPush/Release`,
  `BrakeVelPush/Release` (10 1/s).
* Steering: `Driver.Lat.StWhlAngleMax/VelMax/AccMax` (630 deg, 500 deg/s, 3000 deg/s^2),
  `Driver.Lat.SteeringAmp` (1), `Driver.Lat.DevProReact` and `Driver.Lat.tDwell` (steering style in lane
  changes).
* Imperfection: `Driver.Long.DevMax`/`Driver.Lat.DevMax` (0 = follow exactly), `Driver.Long.tReact`/
  `Driver.Lat.tReact` (0 s), `Driver.Long.AccuracyCoef`/`Driver.Lat.AccuracyCoef` (1), random speed
  offset `Driver.Vel.Random.Amp/Freq`.
* Quantities: `Driver.ReCon.Speed` (target speed, writable during a run), `DM.SpeedLimit`,
  `Driver.Adapt.Phase`; `Driver.ReCon.DriveChar.CF_axy`/`CF_GGExp` with `iChange = 1` re-plan the speed
  with scaled limits during a run (5.7).
* Manoeuvre end conditions: CarMaker steps at 1 kHz, so compare with `>=`/`<=` (for example
  `Vhcl.sRoad >= 75`, `DM.Lap.No >= 1`), never `==` (FCM 3.1.4).
* Not covered here: traffic, motorcycle, rally driving, gear shifting, consumption-optimised driving.

## When something goes wrong
* `cm_log(level="error")`: CarMaker's session log. `cm_popups`: what the GUI asked or reported.
* A GUI question (for example about unsaved data) waits for a click and the tool call waits with it.
  `cm_popup_timeout(seconds)` lets such questions answer themselves with their default choice.
* `cm_changelog` lists what this session changed; `cm_revert_all` undoes it.

## Safety
All edits are in place, on real files and on the live model. Backups are taken before the first write of each file.
Result and log files written by runs are not removed by a revert.
"""


# cm_guide topics: name -> the heading its section starts with
TOPICS = {
    "run": "## Run a test run", "outputs": "## Choose what a run stores", "movie": "## See the car",
    "standalone": "## Run without MATLAB", "parameters": "## Change parameters", "driver": "## The driver",
    "ipgdriver": "## IPGDriver reference", "errors": "## When something goes wrong", "safety": "## Safety",
}


def section(topic: str | None) -> str:
    """One section of the guide, or the list of topics."""
    if not topic:
        return "Topics: " + ", ".join(TOPICS) + ". Ask for one with cm_guide(topic)."
    if topic not in TOPICS:
        raise ValueError(f"unknown topic {topic!r}; choose one of {', '.join(TOPICS)}")
    start = GUIDE.index(TOPICS[topic])
    end = GUIDE.find("\n## ", start + 1)
    return GUIDE[start:] if end < 0 else GUIDE[start:end + 1]


def prompt_run_and_summarise(testrun: str, quantities: str = "Car.v, Car.ax, Car.ay") -> str:
    return (
        f"Run the CarMaker test run '{testrun}' and summarise it.\n"
        "1. cm_status (if not connected: cm_session_start until ready).\n"
        f"2. cm_load_testrun('{testrun}'), cm_start_sim, then cm_wait_end until finished=true.\n"
        "3. If end_status is not 'completed' or log_errors is not empty, read cm_log(level='error') and "
        "report the cause instead of results.\n"
        f"4. cm_results_summary(result_file, quantities=[{quantities}]) and report simulation time, "
        "distance and the min / max / mean of each quantity with units. State which numbers come from "
        "the result file."
    )


def prompt_compare_settings(testrun: str, variable: str, value_a: str, value_b: str, scope: str = "base") -> str:
    return (
        f"Compare the test run '{testrun}' with {variable} = {value_a} and {variable} = {value_b} "
        f"(workspace scope '{scope}').\n"
        "Use cm_study_start with two variations that set this workspace variable, then cm_study_status "
        "until done. Report the two rows side by side and the differences. Finally confirm with "
        f"cm_get_workspace_var that {variable} is back at its original value."
    )


def prompt_undo_session() -> str:
    return (
        "Show what this server session changed and undo it.\n"
        "1. cm_changelog: list the changes grouped by kind (files, workspace variables, model parameters).\n"
        "2. cm_status must be idle; if a simulation is running, ask before stopping it.\n"
        "3. cm_revert_all, then report what was reverted and anything that failed."
    )
