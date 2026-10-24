# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version is 0.x, tool names and
parameters may still change between minor versions.

## [Unreleased]

## [0.3.0] - 2026-10-22

### Added
- `cm_study_start(grid={...})` runs every combination of value lists for `keys`, `driver` and `workspace`
  (a g-g table counts as one value), alone or after `variations`; at most 100 runs per study.
- `cm_study_status(rank_by=...)` ranks the valid runs by their mean sector time, the sum of their splits,
  the simulation time or a quantity statistic such as `Car.v.max` (`-` for largest first).
- `cm_diff(kind, a, b)` compares two project files: keys only in a, only in b, and differing values.
- `cm_study_status`: `top`, `with_studies` (one ranking over several studies, for coarse-to-fine sweeps)
  and `labels`; ranking entries name the run's result file.
- `grid={"driver_scale": {...}}` multiplies the driver's own value by each factor; for a table such as
  `Driver.Acc.GGExp` every column but the first (the speeds), labelled `GGExp×2`.
- `cm_study_start(rerun={"study": id, "labels": [...]})` runs rows of an earlier study again, for example
  the best one with `movie=true, keep_open=true`. A movie study reuses the program and IPGMovie window an
  earlier study kept open instead of closing it.
- Five agents (Haiku, xhigh) each did a task with the server and reported what was hard. From that:
  - Every run's answer and study row on a lap-driven course has `lap_times`, CarMaker's own from its log
    (`rank_by='laps'`): the result file never holds the last lap of a run that ends with it.
  - `cm_read` of a test run leaves the road geometry and traffic keys out unless asked for (`left_out`
    says how many) and gives `timing`: end conditions, lap driving, the timing markers.
  - `cm_results_crossings(at=[...])` gives other quantities at each first crossing (the speed at 75 m).
  - `cm_model_logs_save` (and `save_logs`) answers with the logged `signal_names`.
  - Sector times are named by their markers in brief rows (`0->1`); sectors carry `from`.
  - `cm_standalone_launch` names the `vehicle` it uses; `cm_get_workspace_var` names the variable and
    scope it read; an IPGControl plot window closes with the server.
  - The server instructions describe the standalone route, and `cm_status` without MATLAB says that
    standalone work needs none; the guide's standalone and IPGMovie sections cover studies, driver
    values, quantities and `movie=true`.
  - Standalone launches and studies refuse keys of the vehicle file (`Body.mass`): checked live, a
    standalone run ignores them and gives the baseline result. The answer says how to make a vehicle
    variant (clone the vehicle, name it with `Vehicle`); in the MATLAB session such keys do apply.
- Standalone driver adaptions share one CarMaker GUI of the server's own, instead of one opened and closed
  per adaption; between adaptions only its simulation program is stopped, so the CarMaker licence is free
  for standalone runs. `cm_driver_adaption(action="close")` ends it (it also ends with the server). An
  adaption now waits until the GUI's info box after a program start has closed: a race adaption started
  under it raised CarMaker's internal error dialog at its end ("bad window path name .msgbox") and left
  the GUI blocked. A GUI showing that dialog is replaced by a new one.
- A driver adaption ends what the server's own CarMaker GUI started: a race adaption opened IPGMovie by
  itself, which stayed open after the GUI closed. A race adaption's answer names the `learning_rate` used
  (the knowledge's own LearningRate field is not changed by it).
- `cm_read` of a test run says whether its vehicle can run standalone (`standalone`, `simulink_parts`:
  parts of kind `CM4SL`); `cm_standalone_launch` and standalone studies refuse such a vehicle with that
  reason. `cm_read` also takes `search` (part of the key name) and `offset` for paging (`next_offset`).
- Study answers with `gates="markers"` say which markers the sectors are and what they measure.
- A standalone study stops at the first run that finds no CarMaker licence, instead of failing run after
  run. `cm_study_start` names the CarMaker programs this server left open (each holds a licence), and
  `close_open=true` closes them first.
- `cm_driver_adaption` runs a driver adaption (Basic: learn the car; Race: laps of a closed circuit) and
  saves the knowledge into the driver template file or the test run, after a backup (`cm_revert_all`
  undoes it). It runs in the background (`action` start / wait / status / cancel). In the MATLAB session
  the session's GUI runs it; without MATLAB the server starts a CarMaker GUI of its own (cars without a
  Simulink controller). It uses the GUI's undocumented script command `Driver adaptbasicknowledge` /
  `adaptracedriver` (CarMaker 14.1.1). Checked live standalone: an FS car's Basic adaption took 94 s.
- The guide has an "IPGDriver reference" from IPG's IPGDriver manual and Formula CarMaker tutorial:
  choosing the standard or race driver, the lap-time optimisation procedure, how the driver plans course
  and speed, corner cutting, following a speed exactly (dtAccBrake and dtMinAccelDecel about 0.01 s),
  driver adaption and its cost, and the driver keys with their defaults. The server instructions give
  the essentials and point to it.
- `cm_guide(topic)` returns a section of the guide: clients such as Claude Desktop do not let an agent
  open MCP resources by itself.
- `cm_read`'s `driver` summary includes `Driver.Mode` and `Driver.Course.CornerCutCoef`.
- `cm_study_start(gates="markers")` times every run at the test run's trigger point markers, as CarMaker's
  own lap timing does (the instrument's sector times): rows get `sectors`, taken from
  `DM.TriggerPoint.Time` when the result file holds it (standalone studies store it) and otherwise from
  the road position. Gate positions given by hand are timed on `Vhcl.sRoad` instead of the odometer
  `Car.Distance`, which read about 15 ms long per skid pad lap.
- `cm_results_plot` shows quantities of one or more result files in IPGControl, IPG's plotting program,
  without MATLAB: several files are overlaid, the x axis can be any quantity (for example `Car.Distance`),
  the window stays open for the user and a picture of it comes back to the agent. It drives IPGControl's
  own, undocumented procedures (IPGControl 3.0.17). `CM_IPGCONTROL` names the program if it is not found.
- `cm_standalone_launch(driver={...})`: driver template values for that program, in a copy that is removed
  when it closes (or when the launch fails).
- `cm_study_start(movie=true, keep_open=true)` leaves the last run in IPGMovie (`kept_open` names the
  instance). Study rows name the `vehicle` and `driver_template` they used, and an invalid row gives
  `abort_reason` (its first log error) with at most five log errors.
- `cm_read`'s `driver` summary includes `Driver.Acc.GGExp`, the acceleration factors and `UseVelDepend`.
- The server instructions give a typical study workflow and say that this server has no MATLAB evaluation.
- A study variation can carry `driver` values: the run uses a temporary copy of the test run's driver
  template with those values, deleted after the run, so a driver sweep needs no new project files.
  Checked live: the same values as plain keys change nothing while the test run names a template.
- `cm_study_start(gates=[...])` adds `splits` to every row: the times between `Car.Distance` gates.
- `cm_study_wait(until_done=true)` returns only when the study has ended (or at the time-out).
- Study rows have `valid`: the run completed and, with gates, passed every gate.
- `cm_standalone_status` reports `movie_open`, and `cm_standalone_control(action="movie")` reopens IPGMovie
  for a program this server launched.
- `cm_study_start` mode `auto` (the default): the MATLAB session if it is connected, otherwise standalone.
- `cm_results_export` writes quantities of a result file at full resolution, optionally in a time window,
  to a MAT file (one double variable per quantity, plus `quantity_names` and `units`) or a CSV file.
- `cm_results_crossings` gives the interpolated times at which a quantity reaches given values and the
  time between them, for example lap or sector times from `Car.Distance` gates.
- Study rows report `wall_s`. Standalone runs and study rows report the errors and warnings of that run
  from the session log, so an aborted run says why.
- `cm_doctor` returns `ready` (`cm4sl`, `standalone`): a missing MATLAB session no longer makes standalone
  work look broken.
- `cm_read` says when it shows only part of a file, and `driver` lists `unused_testrun_values`: the test
  run's own driver values that differ from the template it names.
- `cm_standalone_launch(movie=true)` and `cm_study_start(mode="standalone", movie=true)` show a standalone
  run in IPGMovie, connected to that CarMaker program while it runs. A standalone program has no window
  of its own, so these runs could not be watched before. IPGMovie closes with the program.

### Changed
- `cm_study_wait` answers one brief line per run (label, valid, end status, sector or split times, abort
  reason); `detail` gives more. `cm_study_status` takes `detail="brief"` too.
- Waits (`timeout_s`, `max_wait_s`) are cut to 50 s: a client that ends tool calls after 60 s cut a
  long study wait off.
- `cm_doctor`: `ok` is true when at least one mode is ready; `all_checks_passed` says whether every check,
  the MATLAB session included, passed.
- `cm_read` of a test run gives its `driver` summary first.
- An invalid study row's `abort_reason` is CarMaker's own reason (the car left the road, for example)
  rather than the first log line.
- The `quantities` of a study are, standalone, everything its result files store besides what timing
  needs; the guide says what marker sector times are and why `cm_results_crossings` differs by a few ms.
- `cm_study_wait` returns each row once: a cursor per study, so rows that finished between two calls, or
  during parallel calls, are not lost. `cm_study_status` has the whole table.
- `cm_study_start` refuses `Driver.*` given as plain keys while the test run names a driver template
  (they would change nothing), and points to the variation's `driver`.
- `cm_read` with a filter that matches nothing says how many keys the file has.
- A licence error of a standalone launch names this server's own open standalone programs, which hold
  licences too, instead of pointing only at MATLAB.
- `cm_doctor` puts `ready` first. Tool descriptions say that `cm_movie_open` needs the MATLAB session,
  that `cm_standalone_launch(start=false)` only opens CarMaker, where `cm_results_export` may write, and
  what `wall_s` is.
- `cm_clone` also returns the new file's `name` in the form `cm_list` uses. A `cm_results_summary` search
  without matches lists the quantities the file holds.
- The server instructions and the guide explain the driver's g-g exponents (`Driver.Acc.GGExp`, rows
  `vel_kmh exp_acc exp_dec`) and that exponents rising with speed often suit a car with aerodynamic
  downforce.
- Every run goes at CarMaker's maximum speed. Before each start in the MATLAB session the server selects
  the GUI's speed "max" (`SetSimTimeAcc 999999`). Standalone runs and studies use the largest speed IPG's
  Python API accepts (327 x real time; 1000 overflows it, 0 pauses the run); before, they ran in real
  time. `cm_start_sim`, `cm_study_start`, `cm_standalone_launch` and `cm_standalone_attach` take `speed`
  (x real time) for a slower run when the user asks; left out, it is the maximum. `realtime_factor` of
  the standalone tools is gone.

### Fixed
- Sector times of a run that left the road read 0.001 s: CarMaker's trigger values are now used only when
  the reference marker was passed, the value matches the time between the passes and the car covered at
  least half the road between the markers (found in use: two markers fired 10 ms apart as the car left
  the road); otherwise `null`. Rechecked on 152 recorded rows: the 15 aborted ones with 0.001 s are now
  `null`, no completed run changed.
- `cm_changelog` without `session` returned every session's changes; it now returns this session's
  (`session="all"` for every one). A JSON string sent with its quotes (`"\"markers\""`) is read too.
- List and object parameters sent as JSON text are read (found in use: `gates=[...]` arrived as a string
  from a client and was refused).
- A standalone study with `movie=true` started a new program and IPGMovie for every run, so the window
  closed before anything could be seen. The study now keeps one program and one IPGMovie window for all
  its runs (a program that ended is replaced) and closes them after the last run. Without a program
  start per run a study is also faster.
- `cm_edit` and `cm_restore` failed with "No shared MATLAB session" when there was no MATLAB session,
  so standalone work could not change project files. They now only refuse while a run of the MATLAB
  session is going on.
- A standalone program whose run stopped with an error at its start stayed running after
  `cm_standalone_close` (and after a study row), holding a CarMaker licence. A program the server
  started is now ended with its instance.
- `MATLAB error in cmguicmd: Unknown exception` now says that MATLAB has no CarMaker GUI to talk to and
  what to start (`cm_session_start`, or `movie=true` for standalone runs).

## [0.2.2] - 2026-10-19

### Added
- `cm_read` of a test run returns `driver`: its driver template (`Vehicle.DriverTemplate.FName`, or
  `TestRun` for the one saved in the test run), the vehicle and test run its knowledge was learnt on, and
  the main limits read from where they are defined. `cm_clone` of a test run and a `cm_edit` that changes
  `Vehicle` or the template return it too, with a note that a new vehicle does not bring its own driver.
  Editing a driver template notes that other test runs share the file.
- The server instructions and the guide say that the test run chooses the driver, that driver parameters
  are changed in the template, that IPGDriver corners only as fast as `Driver.Acc.ayMax` allows (compare
  vehicle variants each at its own limit), and that steering from input from file arrives about 0.14 s late.
- `cm_wait_end` and each study row return `log_warnings`: the run's new WARNING lines of the session log,
  repeated ones collapsed (at most five). The server instructions say that a completed run does not prove
  every setting was applied.

### Fixed
- `cm_log(level="warning"/"error")`, `log_errors` and the error check after a start missed messages that
  libraries write indented, such as the tyre library's `WARNING - Override value ... is ignored, because it
  is not supported at fittype 62`. A tyre setting that CarMaker ignored therefore left no trace in the
  answers.

### Changed
- The registry name is now `io.github.dimitr-io/carmaker-mcp`, after the GitHub account was renamed.
  Versions up to 0.2.1 stay listed under `io.github.De-Ioannidis/carmaker-mcp`.

## [0.2.1] - 2026-10-15

### Added
- The "Internal Debugger" dialog that the CarMaker GUI or IPGMovie shows after an error of its own is now
  seen: `cm_popups`, and the `popups` of a load, start or finished run, report it as type `internal error`
  with the program and the call stack, and close it. Before, it stayed on the screen and the agent knew
  nothing of it.
- `cm_movie_open(restart=true)` closes IPGMovie and starts it anew, for when its pictures keep failing.

### Fixed
- A picture that IPGMovie failed to make (an internal error of its graphics, for example "FBO Creation
  error") was reported after 15 s as "wrote no picture", with IPGMovie's dialog left open. The call now
  fails at once with IPGMovie's own message, closes the dialog and puts IPGMovie's controls back.
- `cm_movie_snapshot` on an IPGMovie that was started after the run returned a picture of IPGMovie's
  empty default scene as the last run. It now says that IPGMovie holds no run, and a time outside the
  recorded run is refused at once with the recorded range.

## [0.2.0] - 2026-10-12

### Added
- `cm_study_wait` blocks until another run of a study has finished or the study has ended.
- `cm_create` writes a new project file (logged, removed again by `cm_revert_all`).
- A parameter study now holds the CarMaker session for itself: other server processes (other clients or
  conversations) refuse to load, start or stop meanwhile, and `cm_status` reports `study_running`.
- `cm_study_start` and `cm_edit` name keys that occur in no file (`keys_not_found`, `new_keys`).
- `cm_study_start` and `cm_set_workspace_var` say when a value will not reach the model: a variable set in
  the base workspace while the model has one of that name in its own workspace (`workspace_overruled`,
  `overruled_by`), and a variable that did not exist before (`workspace_not_found`).
- The setup check tells whether MATLAB sees the server's state folder.

### Changed
- `cm_study_status` is compact by default (label, end status, result file, four statistics per quantity);
  `detail="full"` gives the previous table with every run's parameter values.
- `cm_study_cancel` needs the study's id, and the study records when and during which run it was cancelled.
- `cm_wait_end` during a study says so instead of reporting the pause between two runs as an end.
- On Windows the state folder (backups, change log, `server.log`) is now `%USERPROFILE%\.carmaker-mcp`
  instead of `%LOCALAPPDATA%\carmaker-mcp`. The old folder is copied there at the first start and left as
  it is. `CM_STATE_DIR` still overrides the place.

### Fixed
- Under a client installed as a Windows app package (Claude Desktop), with a MATLAB started outside it,
  MATLAB did not see the server's state folder: Windows gives such a client a private copy of `AppData`.
  Simulink's diagnostics were not captured, so a failed start showed a stale or unrelated error, and
  `cm_model_logs_save` and pictures from IPGMovie failed. The state folder has moved (see Changed).
- A failed start or run that CarMaker's session log explains was announced with an unrelated Simulink
  error, one that a model raises and handles at every start. The log errors now come first, and
  Simulink's last-error memory is only used when nothing else says anything.
- A start that CarMaker ended at once (a missing file, for example) could wait for the whole start time
  before it reported the failure.
- A MATLAB working folder that had left the CarMaker project made the next start hang at a question of
  CarMaker for Simulink. `cm_load_testrun` and `cm_start_sim` now put the folder back first, and switch the
  GUI back to the project if it had been changed.

## [0.1.1] - 2026-10-07

### Fixed
- The setup check (`doctor`, `cm_doctor`, `config`) chose the wrong engine package and Python version for
  MATLAB releases other than R2024b: releases before R2023b have engine versions `9.x`, and each engine
  package installs only up to a certain Python version. A release whose engine needs a Python older than
  3.10 is now reported as such.

### Added
- One-click bundles for MATLAB R2022b, R2023a, R2023b and R2024a next to R2024b (untested).

## [0.1.0] - 2026-10-07

First version. Developed and tested with CarMaker 14.1.1 and MATLAB R2024b on Windows; what has been verified
against real software is listed in `docs/verification.md`.

### Added
- **MATLAB-connected session (CarMaker for Simulink):** `cm_status`, `cm_load_testrun`, `cm_start_sim`,
  `cm_wait_end`, `cm_stop_sim`, `cm_live`, `cm_dva_write`, `cm_dva_release`, through the MATLAB Engine for
  Python and the GUI's Tcl interface.
- **Results by default:** `cm_start_sim` switches the GUI's storage mode to "Save all" (restored by
  `cm_revert_all`); `cm_wait_end` returns the result file, simulation time, distance, new log errors and
  pop-ups, waits at most 45 s per call and reports MCP progress.
- **Diagnostics:** `cm_log` reads CarMaker's session log; `cm_popups` / `cm_popup_timeout` read the GUI's
  pop-ups and let them answer themselves; failed loads and starts quote pop-ups and log errors. A Simulink model
  that does not compile fails `cm_start_sim` at once with Simulink's own error message.
- **Cold start and setup:** `cm_session_start` brings up MATLAB, the model and the CarMaker GUI as far as they
  are missing; `carmaker-mcp doctor` and `carmaker-mcp config` (and `cm_doctor`) check the machine and print
  the client registration.
- **Standalone instances:** `cm_standalone_*` run test runs on independent CarMaker processes through IPG's
  `cmapi`, without MATLAB.
- **Project data:** `cm_list`, `cm_read`, `cm_edit`, `cm_clone` with a byte-preserving infofile editor.
- **MATLAB workspace and Simulink:** `cm_list_workspace_vars`, `cm_get_workspace_var`, `cm_set_workspace_var`,
  `cm_model_get`, `cm_model_set`, `cm_model_save`; `cm_model_logs_save` writes what Simulink logged in a
  run, with the base and the model workspace, to a MAT file; `save_logs` on `cm_start_sim` and
  `cm_study_start` does that for every run.
- **Parameter studies:** `cm_study_start`, `cm_study_status`, `cm_study_cancel` run one test run with several
  sets of in-memory infofile keys and workspace values and tabulate the results.
- **Results:** `cm_results_list`, `cm_results_summary`, `cm_results_read` with a pure-numpy `.erg` reader.
- **Output quantities:** `cm_output_quantities` and `cm_output_quantities_edit` show and change what runs
  write to result files.
- **IPGMovie:** `cm_movie_open` and `cm_movie_snapshot` return a picture of the 3D view at any moment of
  the last run, of a result file, or of the window while a run is going on.
- **History:** backup before the first write of every file, change log, `cm_changelog`, `cm_revert_all`,
  `cm_restore`.
- **MCP surface:** described and typed parameters, a title and read-only / destructive hints per tool, output
  schemas for status / start / wait, resources (`carmaker://guide`, `status`, `changelog`, `log`), three
  prompts, a log file. Raw Tcl and Simulink structure edits are opt-in (`CM_ENABLE`); tool groups can be
  switched off (`CM_DISABLE`).
- **Packaging:** PyPI package for `uvx`; MCP registry entry (`server.json`); one-click bundles for Claude
  Desktop (`packaging/build_mcpb.py`); release workflow with trusted publishing; optional single-file
  executable build (`packaging/build_exe.ps1`).
