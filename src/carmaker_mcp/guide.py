"""Text an agent can read: server instructions, a short guide (resource) and prompt templates."""

from __future__ import annotations

INSTRUCTIONS = (
    "Drives IPG CarMaker. Two ways to simulate: (1) the MATLAB-connected CarMaker for Simulink session "
    "(cm_* tools without 'standalone'), needed when the vehicle's controller is a Simulink model; "
    "(2) independent CarMaker processes without MATLAB (cm_standalone_* tools). "
    "Typical run: cm_status, cm_load_testrun, cm_start_sim, then cm_wait_end repeatedly until "
    "finished=true (it returns result_file), then cm_results_summary / cm_results_read. "
    "If nothing is running yet call cm_session_start; if a run fails read cm_log and cm_popups. "
    "Edits (cm_edit, cm_set_workspace_var, cm_model_set) change real project files and the live model: "
    "each is backed up and logged, and cm_revert_all undoes this session's changes. "
    "The simulation must be idle for loads, edits and reverts. "
    "The test run, not the vehicle, chooses the driver: Vehicle.DriverTemplate.FName names a template in "
    "Data/Driver/Template (or 'TestRun' for the one saved in the test run), and the driver's knowledge is "
    "learnt for one vehicle. Changing Vehicle or cloning another vehicle's test run keeps the old driver: "
    "check `driver` in the answer of cm_read, cm_edit or cm_clone, and ask the user which template if "
    "unclear. Driver parameters (Driver.Acc.*, dtAccBrake, StWhlAngle*) are changed in the template file "
    "(cm_edit kind 'driver'), which other test runs share: tell the user which file changed. Lap times "
    "depend on the driver's limit Driver.Acc.ayMax: compare vehicle variants each at its own limit. "
    "More in the resource carmaker://guide."
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
  Load the test run again afterwards.
* Controller parameters usually live in the Simulink **model workspace**:
  `cm_list_workspace_vars(scope=<model>)`, `cm_get_workspace_var`, `cm_set_workspace_var(name, value, scope=<model>)`.
  They change in memory only; `cm_model_save` persists them. A variable the model has in its own workspace
  is not changed by setting one of the same name in the base workspace: the answer then says `overruled_by`.
* The result file (.erg) holds CarMaker's quantities. What Simulink logged (signals marked for logging,
  To Workspace blocks) is saved after the run with `cm_model_logs_save`: one MAT file with the signals and
  the base and model workspaces. `cm_start_sim(save_logs=true)` and `cm_study_start(..., save_logs=true)`
  do that for every run (`logs_file` in the result).
* Several settings of one test run: `cm_study_start` runs them one after another. Wait with `cm_study_wait`
  (not `cm_wait_end`); `cm_study_status` gives one short row per run, with its label and result file.
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
  tell the user which file changed. Whether the same keys set on a test run or as study `keys` take effect
  when a template is named is not established; do not rely on it, and do not claim they cannot work.
* IPGDriver corners only as fast as `Driver.Acc.ayMax` allows, not as fast as the car could: a run whose
  largest `Car.ay` is close to it was limited by the driver. To compare vehicle variants on time, give each
  its own limit (a template per variant, or a value the user agrees to), judge only runs that ended
  `completed` by the time for the course, and report the limits used. `DM.Lap.Time` holds lap times only
  when the course is driven as laps.
* Replays from input from file: the steering angle reaches `DM.Steer.Ang` about 0.14 s late (a pure delay,
  not changed by the driver's steering limits), the `Velocity` channel without delay. Advance the steering
  in the file by that time when comparing yaw response with measurements. In such a replay
  `dtAccBrake` and `dtMinAccelDecel` did not change the result.

## When something goes wrong
* `cm_log(level="error")`: CarMaker's session log. `cm_popups`: what the GUI asked or reported.
* A GUI question (for example about unsaved data) waits for a click and the tool call waits with it.
  `cm_popup_timeout(seconds)` lets such questions answer themselves with their default choice.
* `cm_changelog` lists what this session changed; `cm_revert_all` undoes it.

## Safety
All edits are in place, on real files and on the live model. Backups are taken before the first write of each file.
Result and log files written by runs are not removed by a revert.
"""


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
