# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version is 0.x, tool names and
parameters may still change between minor versions.

## [Unreleased]

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
