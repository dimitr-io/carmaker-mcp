"""FastMCP server: tool, resource and prompt registration. Logic lives in session.py and friends.

No ``from __future__ import annotations`` here: FastMCP reads the tool signatures, and older versions
cannot resolve annotations that are only strings.
"""

import argparse
import asyncio
import base64
import functools
import inspect
import json
import logging
import os
import time
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from typing import Annotated, Any, Literal

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ImageContent, TextContent, ToolAnnotations
from pydantic import AfterValidator, BeforeValidator, Field

from . import __version__, guide
from .backend import BackendError
from .config import Config, adopt_old_state
from .guard import GuardError
from .infofile import InfoFileError
from .project import ProjectError
from .results import ErgError
from .schemas import StartResult, StatusResult, WaitResult
from .session import Session

log = logging.getLogger("carmaker_mcp")

# ---- shared state ------------------------------------------------------------------
_session: Session | None = None
_standalone = None
_studies = None


def set_session(s: Session | None) -> None:
    global _session, _studies
    _session, _studies = s, None


def S() -> Session:
    global _session
    if _session is None:
        import atexit

        from .backend_cm4sl import Cm4slBackend

        cfg = Config.from_env()
        _session = Session(Cm4slBackend(cfg.matlab_session, cfg.engine_timeout), cfg)
        atexit.register(_session.at_exit)
    return _session


def set_standalone(m) -> None:
    global _standalone
    _standalone = m


def SA():
    """Manager for independent CarMaker instances (created on first use)."""
    global _standalone
    if _standalone is None:
        import atexit

        from .standalone import StandaloneManager

        cfg = S().cfg
        project = cfg.project
        if project is None:
            try:
                project = S().project.root
            except BackendError:
                project = None
        _standalone = StandaloneManager(cfg.cm_home, project)
        atexit.register(_standalone.close_all)
    return _standalone


def ST():
    """Parameter-study runner (created on first use)."""
    global _studies
    if _studies is None:
        from .study import StudyRunner

        _studies = StudyRunner(S(), SA)
    return _studies


# ---- registration ------------------------------------------------------------------
# Hints for MCP clients (permission prompts, auto-approval of read-only calls). Everything here acts
# on the local CarMaker / MATLAB session, hence openWorldHint is false throughout.
# (model_validate with the protocol's own names works with every version of the MCP SDK)
READ = ToolAnnotations.model_validate({"readOnlyHint": True, "openWorldHint": False})
WRITE = ToolAnnotations.model_validate(
    {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
DESTRUCTIVE = ToolAnnotations.model_validate(
    {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})

# Tool groups that are off unless named in CM_ENABLE (comma separated).
FEATURES = {
    "tcl": "raw Tcl in the CarMaker GUI (cm_gui_tcl)",
    "experimental": "Simulink structure edits (cm_model_add_block, cm_model_add_line, cm_model_delete_block)",
}
# Tool groups that are on unless named in CM_DISABLE: a shorter tool list costs the model less context.
GROUPS = {
    "standalone": "independent CarMaker processes without MATLAB (cm_standalone_*)",
    "study": "parameter studies (cm_study_*)",
    "matlab": "MATLAB workspace and Simulink parameters (cm_*_workspace_*, cm_model_*)",
    "movie": "IPGMovie pictures (cm_movie_*)",
}


def _group(tool: str) -> str | None:
    if tool.startswith("cm_standalone_"):
        return "standalone"
    if tool.startswith("cm_study_"):
        return "study"
    if tool.startswith("cm_movie_"):
        return "movie"
    if tool.startswith("cm_model_") or "_workspace_" in tool:
        return "matlab"
    return None


_DOMAIN_ERRORS = (BackendError, GuardError, ProjectError, InfoFileError, ErgError)


@dataclass
class _Spec:
    fn: Any
    annotations: ToolAnnotations
    title: str
    feature: str | None


_TOOLS: list[_Spec] = []


def _guarded(fn):
    """Turn our domain errors into clean tool errors and log every call."""
    name = fn.__name__

    def done(t0: float, err: Exception | None) -> None:
        ms = (time.perf_counter() - t0) * 1000
        if err is None:
            log.info("%s ok %.0f ms", name, ms)
        else:
            log.warning("%s failed after %.0f ms: %s", name, ms, err)

    @functools.wraps(fn)
    async def async_wrapper(*a, **kw):
        t0 = time.perf_counter()
        try:
            out = await fn(*a, **kw)
        except _DOMAIN_ERRORS as e:
            done(t0, e)
            raise ToolError(str(e)) from e
        done(t0, None)
        return out

    @functools.wraps(fn)
    def sync_wrapper(*a, **kw):
        t0 = time.perf_counter()
        try:
            out = fn(*a, **kw)
        except _DOMAIN_ERRORS as e:
            done(t0, e)
            raise ToolError(str(e)) from e
        done(t0, None)
        return out

    return async_wrapper if inspect.iscoroutinefunction(fn) else sync_wrapper


def _tool(annotations: ToolAnnotations, title: str, feature: str | None = None):
    """Declare a tool. It is registered by create_server (optional groups only when enabled)."""

    def deco(fn):
        _TOOLS.append(_Spec(_guarded(fn), annotations, title, feature))
        return fn

    return deco


def _progress(ctx: Context, total: float):
    """Callback for long waits (called from a worker thread): forwards MCP progress to the client."""
    loop = asyncio.get_running_loop()

    def report(elapsed: float, live: dict) -> None:
        t = live.get("Time")
        msg = f"simulation time {t:.1f} s" if isinstance(t, (int, float)) else "waiting"
        asyncio.run_coroutine_threadsafe(ctx.report_progress(elapsed, total, msg), loop)

    return report


# ---- parameter types ---------------------------------------------------------------
Kind = Annotated[
    Literal["testrun", "vehicle", "driver", "tire", "road", "trailer", "kinematics", "config", "chassis",
            "misc", "sensor", "traffic", "script"],
    Field(description="Kind of project data; selects the folder below <project>/Data"),
]
Scope = Annotated[str, Field(description="'base' for the MATLAB base workspace, or the name of a loaded "
                                         "Simulink model for that model's workspace")]
Instance = Annotated[str | None, Field(description="Standalone instance id such as 'sa1' (may be "
                                                   "omitted while there is only one)")]
ErgPath = Annotated[str, Field(description="Result file (.erg): absolute path, or relative to the project")]
def _from_json_text(v: Any) -> Any:
    """A list or object some clients send as JSON text (found in use: gates=[...] arrived as a string),
    or a JSON string such as '"markers"' with its quotes."""
    if isinstance(v, str) and v.strip()[:1] in ("[", "{", '"'):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


JsonText = BeforeValidator(_from_json_text)


Quantities = Annotated[list[str], JsonText,
                       Field(description="CarMaker quantity names, e.g. ['Time', 'Car.v']")]
MAX_WAIT_S = 50.0  # some clients end a tool call after 60 s (found in use: a remote device bridge)
MaxWait = Annotated[float, Field(description="Longest time to wait in s, at most 50 (larger values are cut "
                                             "to 50); call again if not finished", gt=0),
                    AfterValidator(lambda v: min(v, MAX_WAIT_S))]
Speed = Annotated[float | None, Field(description="x real time; omit for CarMaker's maximum. Slower only "
                                                   "if the user asks", gt=0)]
Detail = Annotated[Literal["brief", "compact", "full"],
                   Field(description="brief: per run label, valid, end status, sector or split times, "
                                     "abort reason. compact: also time, distance, result file and min / "
                                     "max / mean / last of the quantities. full: also every run's keys, "
                                     "workspace values and all statistics")]
RankBy = Annotated[str | None, Field(description="Rank the valid runs: 'sectors' (mean sector time), "
                                                 "'splits' (their sum), 'sim_time', or a quantity statistic "
                                                 "such as 'Car.v.max'; '-' first for largest first")]
Overrides = Annotated[dict[str, Any] | None, Field(description="Test-run keys to change in memory only, "
                                                               "e.g. {'Vehicle': 'Car_B'} for another car. "
                                                               "Vehicle keys (Body.mass) do not reach a "
                                                               "standalone run: clone the vehicle"), JsonText]


# ---- setup ---------------------------------------------------------------------------
@_tool(WRITE, "Start the CarMaker for Simulink session")
async def cm_session_start(
    model: Annotated[str | None, Field(description="Simulink model to open: a name on the MATLAB path, "
                                                   "a path as listed in models_found, or a full path "
                                                   "(default: CM_MODEL)")] = None,
    max_wait_s: MaxWait = 45.0,
    init: Annotated[str | None, Field(description="The project's own MATLAB setup script, run once per "
                                                  "MATLAB session before the model is opened (default: "
                                                  "CM_MATLAB_INIT). A name from init_scripts_found, or "
                                                  "a full path")] = None,
) -> dict:
    """Bring up a CarMaker for Simulink session as far as it is missing: start MATLAB (visible, in the
    project's src_cm4sl folder, engine shared), run cmenv, open the Simulink model and open the CarMaker
    GUI. Nothing is restarted or closed. Returns ready=true, or ready=false with what it is waiting
    for: call again until ready. Without a model it opens none and lists models_loaded and
    models_found to choose from. Many projects need their own setup script before the model compiles:
    if init_scripts_found lists one, pass it as init."""
    return await asyncio.to_thread(S().session_start, model, max_wait_s, init)


@_tool(READ, "Check the setup")
def cm_doctor() -> dict:
    """Check the setup: CarMaker install, Python version, MATLAB release and engine, shared MATLAB
    session, GUI, project folder. Each failed check comes with its fix. ok: at least one mode is ready
    (see ready); all_checks_passed: everything, the MATLAB session included."""
    return S().doctor()


# ---- status and run control -----------------------------------------------------------
@_tool(READ, "Simulation status")
def cm_status() -> StatusResult:
    """The MATLAB session (CarMaker for Simulink) only; standalone work needs none of it (cm_doctor).
    Simulation state (sim_status; sim_status_code is CarMaker's raw value, -2 idle, 0 or more running),
    matlab_simstate (Simulink's model state: 'terminated' is normal when idle), active model, project
    directory, last end status, the GUI's storage mode (save_mode) and gui_all_saved (false: the GUI
    holds unsaved data and will ask before a load; true is no guarantee)."""
    return S().status()  # type: ignore[return-value]


@_tool(WRITE, "Load a test run")
def cm_load_testrun(
    name: Annotated[str, Field(description="Test run relative to Data/TestRun, e.g. "
                                           "'Examples/BasicFunctions/Driver/BackAndForth'")],
    force: Annotated[bool, Field(description="Do not let the GUI ask about unsaved data; that data is "
                                             "discarded")] = False,
) -> dict:
    """Load a test run into the CarMaker GUI. Requires an idle simulation. Find names with
    cm_list('testrun')."""
    return S().load_testrun(name, force)


@_tool(WRITE, "Start the simulation")
def cm_start_sim(
    start_timeout_s: Annotated[float, Field(description="How long the start may take (a Simulink model "
                                                        "may compile first)", gt=0)] = 90.0,
    save: Annotated[Literal["save", "collect", "keep"],
                    Field(description="save: write a result file (GUI storage mode becomes 'Save all', "
                                      "cm_revert_all puts it back). collect: buffer only. keep: leave "
                                      "the GUI setting alone")] = "save",
    save_logs: Annotated[bool, Field(description="Also save what Simulink logged in this run to a MAT "
                                                 "file next to the result file (a Simulink Dataset, for "
                                                 "MATLAB; for Python call cm_model_logs_save(format="
                                                 "'struct', file=...)); cm_wait_end returns logs_file and "
                                                 "logs_signal_names")] = False,
    speed: Speed = None,
) -> StartResult:
    """Start the loaded test run. Returns once it is running; fails at once, with Simulink's error,
    if the model does not compile. Then call cm_wait_end until it reports finished."""
    return S().start_sim(start_timeout_s, save, save_logs, speed)  # type: ignore[return-value]


@_tool(DESTRUCTIVE, "Stop the simulation")
def cm_stop_sim(
    wait_s: Annotated[float, Field(description="Wait this long for the simulation to become idle "
                                               "(0: do not wait)", ge=0)] = 30.0,
) -> WaitResult:
    """Stop the running simulation. With wait_s > 0 it returns what cm_wait_end returns."""
    return S().stop_sim(wait_s)  # type: ignore[return-value]


@_tool(READ, "Wait for the simulation to end")
async def cm_wait_end(
    ctx: Context,
    timeout_s: MaxWait = 45.0,
    poll_s: Annotated[float, Field(description="Seconds between status polls", gt=0)] = 1.0,
) -> WaitResult:
    """Wait until the simulation is idle again. finished=true: end status, simulation time and
    distance, result_file, new log errors and warnings (settings CarMaker ignored show up there) and
    pop-ups. finished=false: current state and live values;
    call again to keep waiting."""
    return await asyncio.to_thread(S().wait_end, timeout_s, poll_s, _progress(ctx, timeout_s))  # type: ignore[return-value]


@_tool(READ, "Read the CarMaker session log")
def cm_log(
    lines: Annotated[int, Field(description="Number of lines from the end", ge=1, le=500)] = 50,
    level: Annotated[Literal["all", "warning", "error"],
                     Field(description="warning: warnings and errors only; error: errors only")] = "all",
) -> dict:
    """Last lines of the newest CarMaker session log of the project. Use it when a run aborts or does
    not start."""
    return S().log_tail(lines, level)


@_tool(READ, "Read live quantities")
def cm_live(quantities: Quantities) -> dict:
    """Current values of CarMaker quantities during a run (or the last values after it)."""
    return S().backend.quantity_read(quantities)


@_tool(WRITE, "Overwrite a quantity (DVA)")
def cm_dva_write(
    name: Annotated[str, Field(description="Quantity to overwrite, e.g. 'DM.Gas'")],
    value: Annotated[float, Field(description="Value, offset or factor, depending on mode")],
    duration_ms: Annotated[int, Field(description="How long the override lasts in ms (-1: until "
                                                  "released or the run ends)")] = -1,
    mode: Annotated[Literal["Abs", "Off", "Fac", "AbsRamp", "OffRamp", "FacRamp"],
                    Field(description="Absolute value, offset or factor; Ramp variants blend in")] = "Abs",
) -> dict:
    """Overwrite a quantity during a run via Direct Variable Access."""
    S().backend.dva_write(name, value, duration_ms, mode)
    return {"dva_written": name, "value": value}


@_tool(WRITE, "Release DVA overrides")
def cm_dva_release() -> dict:
    """Release all quantities from DVA control."""
    S().backend.dva_release()
    return {"released": True}


@_tool(WRITE, "Read GUI pop-ups")
def cm_popups() -> dict:
    """Pop-up messages the CarMaker GUI raised for this server's commands (type info/warn/err/question,
    text, index of the answer given) and the current pop-up timeout. Also the "Internal Debugger" dialog
    that the GUI or IPGMovie shows after an error of its own (type 'internal error', with the program
    and the call stack): it is read and then closed. Reading empties the GUI's buffer (it keeps five).
    cm_load_testrun, cm_start_sim and cm_wait_end already return new ones as 'popups'."""
    return S().popup_status()


@_tool(DESTRUCTIVE, "Let GUI pop-ups answer themselves")
def cm_popup_timeout(
    seconds: Annotated[float, Field(description="Seconds until a pop-up answers itself; 0 = never shown; "
                                                "-1 = wait for a click in the GUI (the normal setting)")],
) -> dict:
    """Let GUI pop-ups raised by this server's commands answer themselves with their DEFAULT choice, so
    that a question such as 'Vehicle not saved. All changes will be lost. OK to continue?' cannot block
    a run. The default answer there discards the unsaved changes. Read what was answered with
    cm_popups. Stays until set back, cm_revert_all or a GUI restart."""
    return S().set_popup_timeout(seconds)


@_tool(DESTRUCTIVE, "Run Tcl in the CarMaker GUI", feature="tcl")
def cm_gui_tcl(
    command: Annotated[str, Field(description="Tcl / ScriptControl command")],
    timeout_ms: Annotated[int, Field(description="Time-out in ms (0: do not wait for the result)",
                                     ge=0)] = 10000,
) -> dict:
    """Run a Tcl / ScriptControl command in the CarMaker GUI. Escape hatch with a small deny-list
    (exit, exec, cd, file delete...). Logged. Prefer the dedicated tools."""
    return S().gui_tcl(command, timeout_ms)


# ---- results --------------------------------------------------------------------------
@_tool(READ, "List result files")
def cm_results_list(
    limit: Annotated[int, Field(description="Maximum number of files", ge=1, le=200)] = 30,
) -> list[dict]:
    """Newest .erg result files under the project's SimOutput folder, CM_RESULT_DIRS and the folders
    this session's runs wrote to."""
    return S().results_list(limit)


@_tool(READ, "Summarise a result file")
def cm_results_summary(
    erg: ErgPath,
    quantities: Annotated[list[str] | None, Field(description="Quantities to summarise (default: Time, "
                                                              "Car.v)"), JsonText] = None,
    search: Annotated[str | None, Field(description="Instead of a summary, list the quantity names that "
                                                    "contain this text ('PT.') or match this wildcard "
                                                    "pattern ('Car.v*'; '*' lists all)")] = None,
) -> dict:
    """First / last / min / max / mean and unit of quantities in a result file, plus rows and duration."""
    e = S().erg(erg)
    if search:
        hits = e.search(search, None)
        out = {"matches": hits[:300], "n_matches": len(hits), "n_quantities": len(e.names)}
        if not hits:
            out["quantities_in_file"] = e.names[:200]  # a run stores only its output quantities
        return out
    return e.summary(quantities or [n for n in ("Time", "Car.v") if n in e.names])


@_tool(READ, "Read time series from a result file")
def cm_results_read(
    erg: ErgPath,
    quantities: Quantities,
    t_min: Annotated[float | None, Field(description="Start of the time window in s")] = None,
    t_max: Annotated[float | None, Field(description="End of the time window in s")] = None,
    max_points: Annotated[int, Field(description="Samples are thinned to at most this many per quantity",
                                     ge=2, le=5000)] = 500,
) -> dict:
    """Time series from a result file, decimated to at most max_points samples."""
    return S().erg(erg).read(quantities, t_min, t_max, max_points)


@_tool(WRITE, "Export a result file")
def cm_results_export(
    erg: ErgPath,
    quantities: Annotated[list[str] | None, Field(description="Default: all"), JsonText] = None,
    t_min: Annotated[float | None, Field(description="Start of the time window in s")] = None,
    t_max: Annotated[float | None, Field(description="End of the time window in s")] = None,
    file: Annotated[str | None, Field(description="Target .mat or .csv (absolute, or relative to the "
                                                   "result file's folder); default next to it")] = None,
    format: Annotated[Literal["mat", "csv"], Field(description="When file is not given")] = "mat",
) -> dict:
    """Write quantities of a result file at full resolution (no thinning) to a MAT file (one double
    variable per quantity, dots as underscores, plus quantity_names and units) or a CSV file (header
    'Time [s],Car.v [m/s],...': name and unit), in any folder of this computer. Never overwrites."""
    return S().results_export(erg, quantities, t_min, t_max, file, format)


@_tool(WRITE, "Plot result files in IPGControl")
def cm_results_plot(
    ergs: Annotated[list[str], Field(description="Result files (.erg), absolute or relative to the project; "
                                                 "several are overlaid", min_length=1, max_length=8),
                    JsonText],
    quantities: Annotated[list[str], Field(description="Quantities to plot, e.g. ['Car.ay', 'Car.YawRate']",
                                           min_length=1, max_length=12), JsonText],
    x: Annotated[str | None, Field(description="Quantity for the x axis (default: Time), e.g. "
                                               "'Car.Distance'")] = None,
    picture: Annotated[bool, Field(description="Also return a picture of the plot")] = True,
) -> list:
    """Plot quantities of result files in IPGControl, IPG's plotting program; needs no MATLAB. The window
    stays open for the user (the next plot replaces it) and a picture comes back as an image. This
    server has no MATLAB evaluation: for MATLAB figures use a MATLAB server, or cm_results_export."""
    out = S().results_plot(ergs, quantities, x, picture)
    content: list = [TextContent.model_validate({"type": "text", "text": json.dumps(out)})]
    if out.get("picture"):
        with open(out["picture"], "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        content.append(ImageContent.model_validate({"type": "image", "data": data, "mimeType": "image/png"}))
    return content


@_tool(DESTRUCTIVE, "Driver adaption")
async def cm_driver_adaption(
    action: Annotated[Literal["start", "wait", "status", "cancel", "close"],
                      Field(description="wait: until it ends or timeout_s. close: end the CarMaker GUI "
                                        "the server opened for standalone adaptions (it stays open for "
                                        "the next one; it ends with the server)")],
    kind: Annotated[Literal["basic", "race"], Field(description="basic: learn the car (needed first); "
                                                                "race: laps of a closed circuit")] = "basic",
    testrun: Annotated[str | None, Field(description="Load this test run first (needed standalone)")] = None,
    learning_rate: Annotated[float, Field(description="race: 0 sensitive .. 1 aggressive", ge=0, le=1)] = 0.5,
    knowledge: Annotated[str | None, Field(description="Knowledge set to learn into (default: the active "
                                                       "one, else DefaultDriverKnowledge)")] = None,
    save: Annotated[bool, Field(description="Save the knowledge (template file or test run; backed "
                                            "up)")] = True,
    mode: Annotated[Literal["auto", "cm4sl", "standalone"], Field(description="auto: the MATLAB session if "
                                                                              "connected")] = "auto",
    timeout_s: MaxWait = 45.0,
) -> dict:
    """Let IPGDriver learn the car (basic) or the car on this circuit (race), and save the knowledge.
    It takes minutes (basic about 2 standalone, 5 to 20 with MATLAB; race as long as the test run allows):
    run it only when the car changed noticeably, the race driver lacks knowledge, or the user asks, and
    tell the user the duration first. Start returns at once; then 'wait' until state is done/failed."""
    return await asyncio.to_thread(S().driver_adaption, action, kind, testrun, True, True, learning_rate,
                                   knowledge, save, mode, timeout_s)


@_tool(READ, "Read a section of the guide")
def cm_guide(
    topic: Annotated[str | None, Field(description="e.g. 'ipgdriver', 'driver', 'parameters'; none lists "
                                                   "the topics")] = None,
) -> str:
    """A section of this server's guide (the same text as the resource carmaker://guide)."""
    try:
        return guide.section(topic)
    except ValueError as e:
        raise BackendError(str(e)) from e


@_tool(READ, "Times at which a quantity reaches values")
def cm_results_crossings(
    erg: ErgPath,
    quantity: Annotated[str, Field(description="e.g. 'Car.Distance' for gates along the course")],
    values: Annotated[list[float], Field(description="Values to find, e.g. gate distances in m",
                                         min_length=1, max_length=100), JsonText],
    direction: Annotated[Literal["any", "rising", "falling"], Field(description="Which crossings")] = "any",
    at: Annotated[list[str] | None, Field(description="Other quantities to read at each first "
                                                      "crossing, e.g. ['Car.v', 'Car.ax']"), JsonText] = None,
) -> dict:
    """Interpolated times at which a quantity crosses each value, and the time between the first
    crossings of consecutive values (lap or sector times from distance gates); with `at`, the values of
    other quantities there (the speed at 75 m)."""
    try:
        return S().erg(erg).crossings(quantity, values, direction, at=at)
    except ErgError as e:
        raise BackendError(str(e)) from e


@_tool(READ, "Read the output quantities")
def cm_output_quantities() -> dict:
    """The quantities the next run writes to its result file, per storage rate (names may hold
    wildcards), with the sample times. movie_replay says whether such a result file can be replayed in
    IPGMovie. What a finished result file holds: cm_results_summary(erg, search='*')."""
    return S().output_quantities()


@_tool(DESTRUCTIVE, "Change the output quantities")
def cm_output_quantities_edit(
    add: Annotated[list[str] | None, Field(description="Quantities to store as well, e.g. ['Car.az', "
                                                       "'PT.Motor*.Trq']; wildcards * and ? "
                                                       "allowed"), JsonText] = None,
    remove: Annotated[list[str] | None, Field(description="Entries to take out, spelled as they are "
                                                          "listed"), JsonText] = None,
    rate: Annotated[Literal["fast", "normal", "slow"],
                    Field(description="Storage rate for added quantities (sample times: "
                                      "cm_output_quantities)")] = "normal",
    preset: Annotated[Literal["movie"] | None,
                      Field(description="movie: add what IPGMovie needs to replay the vehicle from a result "
                                        "file")] = None,
) -> dict:
    """Add quantities to, or remove them from, the project's output-quantities file (backed up first,
    logged, restored by cm_revert_all). Applies from the next start. Requires an idle simulation. Find
    names with cm_live (it reads any quantity) or in another result file."""
    return S().output_quantities_edit(add, remove, rate, preset)


# ---- IPGMovie ---------------------------------------------------------------------------
@_tool(WRITE, "Open IPGMovie")
def cm_movie_open(
    restart: Annotated[bool, Field(description="Close a running IPGMovie and start it anew: the way out "
                                               "when its pictures fail with an internal error. It then "
                                               "holds no run")] = False,
) -> dict:
    """Open IPGMovie, CarMaker's 3D animation window (or take over one that is open). Open it BEFORE a
    run: it records a run only while it is open, and cm_movie_snapshot can then show any moment of it.
    Needs the MATLAB session; without it use cm_standalone_launch(movie=true)."""
    return S().movie_open(restart)


@_tool(WRITE, "Take a picture in IPGMovie")
def cm_movie_snapshot(
    time_s: Annotated[float | None, Field(description="Simulation time of the picture in s (default: the "
                                                      "latest moment IPGMovie holds)", ge=0)] = None,
    camera: Annotated[str | None, Field(description="Camera view: 'DEFAULT', \"Bird's Eye View\", 'Left "
                                                    "Side', 'Right Side', 'Sitting In Vehicle (A)', or one "
                                                    "from the project (default: keep the view)")] = None,
    erg: Annotated[str | None, Field(description="Replay this result file instead of the last run "
                                                 "(absolute path, or relative to the project)")] = None,
    width: Annotated[int, Field(description="Picture width in pixels (not during a run)", ge=160,
                                le=1920)] = 960,
    height: Annotated[int, Field(description="Picture height in pixels (not during a run)", ge=120,
                                 le=1080)] = 540,
) -> list:
    """A picture of IPGMovie's 3D view, returned as an image. After a run it shows any moment of the last
    run (time_s), provided IPGMovie was open during that run. During a run, without time_s, it shows the
    IPGMovie window as it is at that moment (in the window's own size). With erg it replays a saved
    result file, which must hold the vehicle's motion (cm_output_quantities_edit(preset='movie') before
    that run). Do not pass time_s during a run: that makes IPGMovie stop following the run. Needs the
    MATLAB session's IPGMovie (cm_movie_open); a standalone IPGMovie (movie=true) has no pictures."""
    out = S().movie_snapshot(time_s, camera, erg, width, height)
    with open(out["file"], "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    mime = "image/png" if out["file"].lower().endswith(".png") else "image/jpeg"
    # (model_validate with the protocol's own names works with every version of the MCP SDK)
    return [TextContent.model_validate({"type": "text", "text": json.dumps(out)}),
            ImageContent.model_validate({"type": "image", "data": data, "mimeType": mime})]


# ---- project data -----------------------------------------------------------------------
@_tool(READ, "List project data files")
def cm_list(
    kind: Kind,
    pattern: Annotated[str | None, Field(description="Wildcard filter on the name, e.g. '*Brak*'")] = None,
    include_hidden: Annotated[bool, Field(description="Also list names starting with a dot")] = False,
) -> dict:
    """Names of project data files of one kind (test runs, vehicles, drivers, tyres...)."""
    return S().project.list(kind, pattern, include_hidden)


@_tool(READ, "Read a project data file")
def cm_read(
    kind: Kind,
    name: Annotated[str, Field(description="File name relative to the kind's folder, as cm_list returns it")],
    keys: Annotated[list[str] | None, Field(description="Only these keys"), JsonText] = None,
    prefix: Annotated[str | None, Field(description="Only keys starting with this, e.g. 'Vehicle' or "
                                                    "'DrivMan.'")] = None,
    search: Annotated[str | None, Field(description="Only keys containing this, any case, e.g. "
                                                    "'Control.Kind'")] = None,
    offset: Annotated[int, Field(description="Skip this many keys (paging: next_offset)", ge=0)] = 0,
) -> dict:
    """Key / value pairs of a CarMaker infofile, 300 at a time: filter by keys, prefix or search, or page
    with offset. For a test run first `driver` (its template or 'TestRun', knowledge, main limits) and,
    also for a vehicle, `standalone`: false names the vehicle's Simulink parts (runs need the MATLAB
    session)."""
    return S().project.read(kind, name, keys, prefix, search=search, offset=offset)


@_tool(READ, "Compare two project data files")
def cm_diff(
    kind: Kind,
    a: Annotated[str, Field(description="First file, relative to the kind's folder")],
    b: Annotated[str, Field(description="Second file")],
    prefix: Annotated[str | None, Field(description="Only keys starting with this")] = None,
) -> dict:
    """Keys only in a, only in b, and those whose values differ ([a, b]), e.g. two vehicles or a test
    run and its clone."""
    return S().project.diff(kind, a, b, prefix)


@_tool(DESTRUCTIVE, "Edit a project data file")
def cm_edit(
    kind: Kind,
    name: Annotated[str, Field(description="File name relative to the kind's folder")],
    overrides: Annotated[dict[str, Any], Field(description="Keys to set, e.g. {'Road.FName': "
                                                           "'SKIDPAD.rd5'}; a null value removes the "
                                                           "key"), JsonText],
) -> dict:
    """Change keys in a project file in place (backed up first, logged; only the edited lines change).
    Requires an idle simulation; load the test run again afterwards. Driver parameters belong in the
    driver template (kind 'driver', 'Template/<name>'), which other test runs share: say which changed."""
    return S().edit_file(kind, name, overrides)


@_tool(WRITE, "Copy a project data file")
def cm_clone(
    kind: Kind,
    base: Annotated[str, Field(description="Existing file to copy")],
    new_name: Annotated[str, Field(description="Name of the copy (must not exist)")],
) -> dict:
    """Copy a project file to a new name in the same kind's folder. Never overwrites. A copied test run
    keeps the source's driver and knowledge (`driver`): check them for another vehicle."""
    return S().clone_file(kind, base, new_name)


@_tool(WRITE, "Create a project data file")
def cm_create(
    kind: Kind,
    name: Annotated[str, Field(description="Name of the new file relative to the kind's folder (must not "
                                           "exist)")],
    content: Annotated[str, Field(description="The whole text of the file, at most 2 MB")],
) -> dict:
    """Write a new project file, for example a tyre property file that differs from an existing one.
    Never overwrites; the file is logged and cm_revert_all moves it to the trash folder. To change a
    file that exists use cm_edit, to copy one cm_clone."""
    return S().create_file(kind, name, content)


# ---- MATLAB workspace and Simulink -------------------------------------------------------
@_tool(READ, "List workspace variables")
def cm_list_workspace_vars(
    scope: Scope = "base",
    pattern: Annotated[str | None, Field(description="Wildcard filter on the name, e.g. 'Kp_*'")] = None,
) -> dict:
    """Variables (name, class, size) of the MATLAB base workspace or of a Simulink model's workspace.
    Controller parameters usually live in the model workspace."""
    return S().workspace_list(scope, pattern)


@_tool(READ, "Read a workspace variable")
def cm_get_workspace_var(
    name: Annotated[str, Field(description="Variable or field, e.g. 'Kp_12' or 'Table.Value'")],
    scope: Scope = "base",
) -> Any:
    """Value of a variable or field. MATLAB objects are described, not converted: read their fields."""
    return {"name": name, "scope": scope, "value": S().workspace_get(name, scope)}


@_tool(DESTRUCTIVE, "Set a workspace variable")
def cm_set_workspace_var(
    name: Annotated[str, Field(description="Variable or field, e.g. 'Kp_12' or 'Table.Value'")],
    value: Annotated[Any, Field(description="Number, string, list or nested list (matrix)")],
    scope: Scope = "base",
) -> dict:
    """Set a variable or field. The old value is logged and cm_revert_all restores it. Model-workspace
    changes live in memory until cm_model_save. Requires an idle simulation. overruled_by in the answer:
    the model has a variable of that name in its own workspace and uses that one, so set it there."""
    return S().workspace_set(name, value, scope)


@_tool(READ, "Read a Simulink parameter")
def cm_model_get(
    path: Annotated[str, Field(description="Model or block path, e.g. 'MyModel/Controller/Gain'")],
    param: Annotated[str, Field(description="Parameter name, e.g. 'Gain'")],
) -> Any:
    """get_param on a loaded Simulink model or block."""
    return S().model_get(path, param)


@_tool(DESTRUCTIVE, "Set a Simulink parameter")
def cm_model_set(
    path: Annotated[str, Field(description="Model or block path")],
    param: Annotated[str, Field(description="Parameter name")],
    value: Annotated[Any, Field(description="New value (numbers are converted to text as Simulink expects)")],
    save: Annotated[bool, Field(description="Also back up and save the model file")] = False,
) -> dict:
    """set_param on a loaded Simulink model or block. Logged; cm_revert_all restores the old value."""
    return S().model_set(path, param, value, save)


@_tool(DESTRUCTIVE, "Save a Simulink model")
def cm_model_save(model: Annotated[str, Field(description="Name of the loaded model")]) -> dict:
    """Save a loaded Simulink model. The file must be inside the project; it is backed up first."""
    return S().model_save(model)


@_tool(WRITE, "Save Simulink's logged data to a MAT file")
def cm_model_logs_save(
    file: Annotated[str | None, Field(description="MAT file to write, inside the project (default: next to "
                                                  "the last result file, with the same name)")] = None,
    model: Annotated[str | None, Field(description="Loaded Simulink model (default: the active one)")] = None,
    logs: Annotated[Literal["inspector", "workspace", "both"],
                    Field(description="inspector: every signal the Simulation Data Inspector holds for "
                                      "the last run (logged signals and To Workspace blocks, complete). "
                                      "workspace: the logging variables in the base workspace as they "
                                      "are")] = "inspector",
    format: Annotated[Literal["dataset", "struct"],
                      Field(description="dataset: a Simulink.SimulationData.Dataset. struct: plain arrays "
                                        "(name, time, values, units, block) that load without "
                                        "Simulink")] = "dataset",
    base_workspace: Annotated[bool, Field(description="Include the base workspace's variables")] = True,
    model_workspace: Annotated[bool, Field(description="Include the model workspace's variables")] = True,
    overwrite: Annotated[bool, Field(description="Replace the file if it exists")] = False,
    timeout_s: Annotated[float, Field(description="Longest time MATLAB may take to write the file",
                                      gt=0)] = 120.0,
) -> dict:
    """After a CarMaker for Simulink run: write what Simulink logged (signals marked for logging and
    To Workspace blocks) to a MAT file, with the base workspace and the model workspace as one struct
    each (variables: signals, base_workspace, model_workspace, info); the answer lists signal_names.
    Requires an idle simulation. The result file (.erg) holds CarMaker's quantities, this the Simulink
    side. To see whether a signal is logged, run with save_logs=true and read signal_names."""
    return S().model_logs_save(file, model, logs, format, base_workspace, model_workspace, overwrite,
                               timeout_s=timeout_s)


@_tool(WRITE, "Add a Simulink block (experimental)", feature="experimental")
def cm_model_add_block(
    src: Annotated[str, Field(description="Library block, e.g. 'simulink/Math Operations/Gain'")],
    dest: Annotated[str, Field(description="New block path, e.g. 'MyModel/Sub/Gain1'")],
    params: Annotated[dict[str, Any] | None, Field(description="Block parameters to set"), JsonText] = None,
) -> dict:
    """EXPERIMENTAL. add_block. Unsaved until cm_model_save; a revert reloads the model from disk."""
    return S().model_struct("add_block", src=src, dest=dest, params=params or {})


@_tool(WRITE, "Add a Simulink line (experimental)", feature="experimental")
def cm_model_add_line(
    system: Annotated[str, Field(description="System that contains both blocks, e.g. 'MyModel/Sub'")],
    out: Annotated[str, Field(description="Source port as 'Block/1'")],
    inp: Annotated[str, Field(description="Destination port as 'Block2/1'")],
) -> dict:
    """EXPERIMENTAL. add_line. Unsaved until cm_model_save."""
    return S().model_struct("add_line", system=system, out=out, inp=inp)


@_tool(DESTRUCTIVE, "Delete a Simulink block (experimental)", feature="experimental")
def cm_model_delete_block(path: Annotated[str, Field(description="Block path")]) -> dict:
    """EXPERIMENTAL. delete_block. Unsaved until cm_model_save; a revert reloads the model from disk."""
    return S().model_struct("delete_block", path=path)


# ---- standalone instances (independent of MATLAB) ------------------------------------------
@_tool(READ, "List running CarMaker programs")
def cm_standalone_servers() -> list[dict]:
    """CarMaker simulation programs running on this machine (pid, description, whether this server
    manages it). A CarMaker Office window you opened shows up once its application is started."""
    return SA().servers()


@_tool(WRITE, "Launch a standalone CarMaker run")
def cm_standalone_launch(
    testrun: Annotated[str, Field(description="Test run relative to Data/TestRun")],
    overrides: Overrides = None,
    quantities: Annotated[list[str] | None, Field(description="Quantities to store (default: Time, Car.v, "
                                                              "Car.YawRate, Car.ax, Car.ay, "
                                                              "Car.Distance)"), JsonText] = None,
    stop_after_s: Annotated[float | None, Field(description="Safety stop at this simulation time in s "
                                                            "(null: none)")] = 600.0,
    executable: Annotated[str | None, Field(description="CarMaker executable (default: the stock one of "
                                                        "the install)")] = None,
    start: Annotated[bool, Field(description="Start the run at once")] = True,
    movie: Annotated[bool, Field(description="Show the run in IPGMovie (the program has no window; "
                                             "IPGMovie closes with it)")] = False,
    speed: Speed = None,
    driver: Annotated[dict[str, Any] | None,
                      Field(description="Driver template values for this program only, in a copy removed "
                                        "when it closes"), JsonText] = None,
) -> dict:
    """Start a NEW independent CarMaker simulation program (not connected to MATLAB) and run a test run
    on it. Only for test runs whose vehicle does not need a Simulink controller. Results go to the
    project's SimOutput; see cm_standalone_results. start=false only opens CarMaker (and IPGMovie)."""
    S().require_standalone(testrun, overrides)
    overrides, temp = S().standalone_driver(testrun, dict(overrides or {}), driver)
    try:
        out = SA().launch(testrun, overrides=overrides or None, quantities=quantities,
                          stop_after_s=stop_after_s, executable=executable, start=start, movie=movie,
                          realtime_factor=speed, temp_files=temp)
        out["vehicle"] = S().last_standalone_vehicle  # asked for in use: did the override apply?
        return out
    except Exception:
        for p in temp:  # found live: a failed launch left its template copy in the project
            p.unlink(missing_ok=True)
        raise


@_tool(WRITE, "Attach to a running CarMaker program")
def cm_standalone_attach(
    pid: Annotated[int, Field(description="Process id from cm_standalone_servers")],
    testrun: Annotated[str | None, Field(description="Test run to configure (needed to start a run)")] = None,
    overrides: Overrides = None,
    quantities: Annotated[list[str] | None, Field(description="Quantities to store"), JsonText] = None,
    stop_after_s: Annotated[float | None, Field(description="Safety stop at this simulation time "
                                                            "in s")] = 600.0,
    start: Annotated[bool, Field(description="Start the run at once (needs testrun)")] = False,
    speed: Speed = None,
) -> dict:
    """Attach to a CarMaker simulation program that is already running, for example one started from a
    CarMaker Office window."""
    return SA().attach(pid, testrun, overrides=overrides, quantities=quantities, stop_after_s=stop_after_s,
                       start=start, realtime_factor=speed)


@_tool(READ, "Standalone instance status")
def cm_standalone_status(
    instance: Instance = None,
    quantities: Annotated[list[str] | None, Field(description="Live quantities to read (default: Time, "
                                                              "Car.v)"), JsonText] = None,
) -> dict:
    """State of a standalone instance plus live values."""
    return SA().status(instance, quantities)


@_tool(DESTRUCTIVE, "Control a standalone run")
def cm_standalone_control(
    action: Annotated[Literal["start", "pause", "resume", "stop", "movie"],
                      Field(description="movie: (re)open IPGMovie for the program")],
    instance: Instance = None,
) -> dict:
    """Start, pause, resume or stop the simulation of a standalone instance, or open its IPGMovie. A
    study with movie=true runs on one instance: cm_standalone_status shows it."""
    return SA().control(action, instance)


@_tool(READ, "Wait for a standalone run to end")
async def cm_standalone_wait_end(instance: Instance = None, timeout_s: MaxWait = 45.0) -> dict:
    """Wait until the instance's simulation has finished. finished=true: simulation time and distance,
    error flag and log errors. finished=false: call again to keep waiting."""
    return await asyncio.to_thread(SA().wait_end, instance, timeout_s)


@_tool(WRITE, "Overwrite a quantity in a standalone run (DVA)")
def cm_standalone_dva_write(
    name: Annotated[str, Field(description="Quantity to overwrite")],
    value: Annotated[float, Field(description="Absolute value")],
    duration_ms: Annotated[int, Field(description="How long the override lasts in ms (-1: until the run "
                                                  "ends)")] = -1,
    instance: Instance = None,
) -> dict:
    """Overwrite a quantity in a running standalone simulation (Direct Variable Access)."""
    return SA().dva_write(name, value, duration_ms, instance)


@_tool(READ, "Result files of a standalone run")
def cm_standalone_results(instance: Instance = None) -> dict:
    """Result .erg files of the instance's run (read them with cm_results_summary / cm_results_read)."""
    return SA().results(instance)


@_tool(DESTRUCTIVE, "Close a standalone instance")
def cm_standalone_close(instance: Instance = None) -> dict:
    """Disconnect; for instances this server launched, also stop the CarMaker process."""
    return SA().close(instance)


# ---- parameter studies ---------------------------------------------------------------------
@_tool(WRITE, "Start a parameter study")
def cm_study_start(
    testrun: Annotated[str | None, Field(description="Test run relative to Data/TestRun (with rerun: "
                                                     "default its study's)")] = None,
    variations: Annotated[list[dict[str, Any]] | None, Field(
        description="One entry per run: {'label': 'heavy', 'keys': {'Body.mass': 320}, 'workspace': "
                    "{'Kp_yaw': 1.5}, 'driver': {'Driver.Acc.ayMax': 14, 'Driver.Acc.GGExp': "
                    "'10 1.5 1.5\\n90 5 5'}}. 'keys': infofile keys in memory "
                    "for that run; 'workspace': MATLAB variables in 'scope', restored after the run; "
                    "'driver': driver template values, in a copy deleted after the run. All optional",
        max_length=100), JsonText] = None,
    quantities: Annotated[list[str] | None, Field(description="Quantities to summarise per run (default: "
                                                              "Time, Car.v). Standalone they are also all "
                                                              "its result file stores, besides what timing "
                                                              "needs: list every quantity to plot "
                                                              "later"), JsonText] = None,
    mode: Annotated[Literal["auto", "cm4sl", "standalone"],
                    Field(description="cm4sl: the MATLAB-connected session. standalone: CarMaker without "
                                      "MATLAB (no 'workspace' values). auto: cm4sl if MATLAB is "
                                      "connected")] = "auto",
    scope: Scope = "base",
    max_run_s: Annotated[float, Field(description="A run is stopped after this wall time in s",
                                      gt=0)] = 900.0,
    save_logs: Annotated[bool, Field(description="After every run, save what Simulink logged and the "
                                                 "workspaces as that run used them to a MAT file next "
                                                 "to its result file (mode cm4sl; logs_file per "
                                                 "row)")] = False,
    movie: Annotated[bool, Field(description="mode standalone: show the runs in IPGMovie")] = False,
    speed: Speed = None,
    gates: Annotated[list[float] | Literal["markers"] | None,
                     Field(description="'markers': each row gets 'sectors', the times CarMaker's lap "
                                       "timing takes at the test run's trigger point markers, each from the "
                                       "last reference marker (a lap on a skid pad). Or road positions in "
                                       "m: 'splits', the times between them"), JsonText] = None,
    keep_open: Annotated[bool, Field(description="With movie: leave the last run in IPGMovie (close "
                                                 "it with cm_standalone_close)")] = False,
    grid: Annotated[dict[str, dict[str, list]] | None, Field(
        description="Every combination of value lists, added to variations: {'driver': "
                    "{'Driver.Acc.ayMax': [12, 14]}, 'driver_scale': {'Driver.Acc.GGExp': [1, 2, 4]}, "
                    "'keys': {...}, 'workspace': {...}}. driver_scale multiplies the driver's own value (a "
                    "table: all but its first column). At most 100 runs"), JsonText] = None,
    close_open: Annotated[bool, Field(description="standalone: first close the CarMaker programs this "
                                                  "server left open (each holds a licence)")] = False,
    keys: Annotated[dict[str, Any] | None, Field(description="Keys for every run, e.g. {'Vehicle': "
                                                         "'Car_B'}; a variation's own keys win"),
                    JsonText] = None,
    rerun: Annotated[dict[str, Any] | None, Field(
        description="Runs of an earlier study again: {'study': id, 'labels': ['best']}, e.g. with movie and "
                    "keep_open to show the best run; an IPGMovie window kept open is "
                    "reused"), JsonText] = None,
) -> dict:
    """Run one test run several times with different parameter values, one after another, in the
    background. Returns a study id at once; wait with cm_study_wait. Nothing is written to project files.
    The answer names values that will change nothing: keys_not_found, workspace_not_found and
    workspace_overruled (use scope=<model>); Driver.* keys that a driver template overrides are refused
    (use 'driver'). Rows give valid and wall_s, the clock time of the run. A study stops at the first
    run that finds no CarMaker licence."""
    return ST().start(testrun, variations, quantities, mode, scope, max_run_s, save_logs, movie, speed,
                      gates, keep_open, grid, close_open, rerun, keys)


@_tool(READ, "Parameter study progress and results")
def cm_study_status(
    study: Annotated[str | None, Field(description="Study id (default: the latest)")] = None,
    detail: Detail = "compact",
    rank_by: RankBy = None,
    top: Annotated[int | None, Field(description="Only the best N of the ranking", ge=1)] = None,
    with_studies: Annotated[list[str] | None, JsonText,
                            Field(description="Rank these studies' runs together with this one's")] = None,
    labels: Annotated[list[str] | None, Field(description="Only these rows"), JsonText] = None,
) -> dict:
    """State of a study (running, done, cancelled, failed) and one row per finished run, which also maps
    every label to its result file. The ranking names each run's result file. To wait use
    cm_study_wait."""
    return ST().status(study, detail, rank_by, labels, top, with_studies)


@_tool(READ, "Wait for a parameter study")
async def cm_study_wait(
    study: Annotated[str | None, Field(description="Study id (default: the latest)")] = None,
    timeout_s: MaxWait = 45.0,
    until_done: Annotated[bool, Field(description="Return only when the study has ended (or at "
                                                  "timeout_s)")] = False,
    detail: Detail = "brief",
) -> dict:
    """Wait until another run of the study has finished or the study has ended, at most timeout_s, and
    return the rows no earlier call returned (cm_study_status has the whole table and rank_by). Call it
    again while state is 'running'. Use this for studies instead of cm_wait_end."""
    return await asyncio.to_thread(ST().wait_progress, study, timeout_s, until_done, detail)


@_tool(DESTRUCTIVE, "Cancel a parameter study")
def cm_study_cancel(
    study: Annotated[str, Field(description="Id of the study to cancel, as cm_study_start returned it. It "
                                            "must be named: a study is not cancelled by default")],
) -> dict:
    """Stop the run in progress, skip the remaining ones and restore the changed workspace values. Only
    cancel a study this conversation started."""
    return ST().cancel(study)


# ---- history -------------------------------------------------------------------------------
@_tool(READ, "Change log")
def cm_changelog(
    session: Annotated[str | None, Field(description="Session id (default: this session; 'all' for "
                                                     "every session)")] = None,
    limit: Annotated[int, Field(description="Newest entries to return", ge=1, le=1000)] = 100,
) -> list[dict]:
    """Recorded changes (file keys, workspace variables, model parameters, GUI settings) with old and
    new values."""
    return S().changelog(session, limit)


@_tool(DESTRUCTIVE, "Undo this session's changes")
def cm_revert_all() -> dict:
    """Undo every change made in this server session: workspace values and model parameters in reverse
    order, backed-up files put back (created files go to a trash folder), GUI settings restored."""
    return S().revert_all()


@_tool(DESTRUCTIVE, "Restore files of an earlier session")
def cm_restore(session: Annotated[str, Field(description="Session id as shown by cm_changelog")]) -> dict:
    """Restore project files from the backups of an earlier session. Files only."""
    return S().restore(session)


# ---- server ----------------------------------------------------------------------------------
def _names_from_env(var: str, known: dict[str, str]) -> frozenset[str]:
    names = {n.strip().lower() for n in os.environ.get(var, "").split(",") if n.strip()}
    if names - set(known):
        log.warning("%s: unknown name(s) %s (known: %s)", var, sorted(names - set(known)), sorted(known))
    return frozenset(names & set(known))


def features_from_env() -> frozenset[str]:
    return _names_from_env("CM_ENABLE", FEATURES)


def disabled_from_env() -> frozenset[str]:
    return _names_from_env("CM_DISABLE", GROUPS)


def create_server(features: frozenset[str] | set[str] = frozenset(),
                  disabled: frozenset[str] | set[str] = frozenset()) -> FastMCP:
    """Build the MCP server. ``features`` switches on optional tools (FEATURES), ``disabled`` switches
    off tool groups (GROUPS)."""
    m = FastMCP("carmaker", version=__version__, instructions=guide.INSTRUCTIONS)
    for spec in _TOOLS:
        if spec.feature is not None and spec.feature not in features:
            continue
        if _group(spec.fn.__name__) in disabled:
            continue
        m.tool(spec.fn, annotations=spec.annotations, title=spec.title)

    @m.resource("carmaker://guide", name="guide", mime_type="text/markdown",
                description="How to use this server: workflows, parameters, troubleshooting")
    def guide_resource() -> str:
        return guide.GUIDE

    @m.resource("carmaker://status", name="status", mime_type="application/json",
                description="Current simulation status (same as cm_status)")
    def status_resource() -> str:
        return json.dumps(S().status(), default=str)

    @m.resource("carmaker://changelog", name="changelog", mime_type="application/json",
                description="Changes made by this server session (same as cm_changelog)")
    def changelog_resource() -> str:
        return json.dumps(S().changelog(None, 200), default=str)

    @m.resource("carmaker://log", name="log", mime_type="text/plain",
                description="Last 200 lines of the newest CarMaker session log")
    def log_resource() -> str:
        return "\n".join(S().log_tail(200)["lines"])

    @m.prompt(name="run_and_summarise", description="Run a test run and summarise the result")
    def run_and_summarise(testrun: str, quantities: str = "Car.v, Car.ax, Car.ay") -> str:
        return guide.prompt_run_and_summarise(testrun, quantities)

    @m.prompt(name="compare_settings", description="Run a test run with two values of one parameter and "
                                                   "compare the results")
    def compare_settings(testrun: str, variable: str, value_a: str, value_b: str, scope: str = "base") -> str:
        return guide.prompt_compare_settings(testrun, variable, value_a, value_b, scope)

    @m.prompt(name="undo_session", description="Show what this session changed and undo it")
    def undo_session() -> str:
        return guide.prompt_undo_session()

    return m


mcp = create_server(features_from_env(), disabled_from_env())


def _setup_logging(cfg: Config) -> None:
    """Log to stderr (MCP clients show it) and to <state_dir>/server.log. Level: CM_LOG_LEVEL."""
    level = getattr(logging, os.environ.get("CM_LOG_LEVEL", "INFO").upper(), logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(cfg.state_dir / "server.log", maxBytes=1_000_000,
                                            backupCount=2, encoding="utf-8"))
    except OSError:
        pass
    log.setLevel(level)
    for h in handlers:
        h.setFormatter(fmt)
        log.addHandler(h)


def _setup_cli(args) -> int:
    """`carmaker-mcp doctor` and `carmaker-mcp config`: print and exit (nothing is changed)."""
    from . import doctor
    from .backend_cm4sl import Cm4slBackend

    cfg = Config.from_env()
    backend = Cm4slBackend(cfg.matlab_session, min(cfg.engine_timeout, 10))
    live = args.command == "doctor"
    rep = doctor.diagnose(cfg, gui_status=backend.status if live else None,
                          matlab_sees=backend.sees_folder if live else None)
    if args.command == "config":
        try:
            print(doctor.client_config(args.client, rep, cfg))
        except ValueError as e:
            print(e)
            return 2
        return 0
    print(json.dumps(rep.as_dict(), indent=2) if args.json else doctor.format_report(rep))
    return 0 if rep.ok else 1


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        prog="carmaker-mcp",
        description="MCP server (stdio) for IPG CarMaker for Simulink. Configure via CM_* env vars.",
    )
    p.add_argument("command", nargs="?", default="serve", choices=("serve", "doctor", "config"),
                   help="serve: run the MCP server (default). doctor: check this machine's setup. "
                        "config: print the registration for an MCP client")
    p.add_argument("--mock", action="store_true", help="use an in-memory backend (no CarMaker needed)")
    p.add_argument("--client", default="claude-code", help="for config: claude-code, claude-desktop, "
                                                           "vscode, codex, antigravity or cursor")
    p.add_argument("--json", action="store_true", help="for doctor: print the report as JSON")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = p.parse_args(argv)
    if args.command != "serve":
        raise SystemExit(_setup_cli(args))
    cfg = Config.from_env()
    adopted = adopt_old_state(cfg)
    _setup_logging(cfg)
    if adopted:
        log.info("state of an earlier version copied from %s to %s", adopted, cfg.state_dir)
    if args.mock:
        from .backend_mock import MockBackend

        set_session(Session(MockBackend(), cfg))
    log.info("carmaker-mcp %s starting (features: %s)", __version__, sorted(features_from_env()) or "none")
    mcp.run(show_banner=False)  # stdio transport; keep stderr quiet for MCP clients


if __name__ == "__main__":
    main()
