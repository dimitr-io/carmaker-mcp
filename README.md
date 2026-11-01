# carmaker-mcp

<!-- mcp-name: io.github.dimitr-io/carmaker-mcp -->

https://github.com/user-attachments/assets/6093b1a3-8ef5-43ef-8134-b214d534720f

*Claude Desktop with this server (CarMaker without MATLAB, IPGMovie open) and MathWorks'
[MATLAB MCP server](https://github.com/matlab/matlab-mcp-core-server) for the figure. A 68-run sweep of
the driver's limits on a Formula Student skid pad; the agent's work is shown 30 times faster.*

<details>
<summary>The prompt in the video</summary>

> Open Carmaker (standalone) and run Skidpad tests with the Rhea vehicle (torque vectoring disabled). Run a
> parameter sweep for the IPGDriver's lateral acceleration limits and gg exponents to get the best lap time.
> Open IPGMovie first so I can see the runs. Evaluate lap time based on the average time between the second
> lap on the right and the second lap on the left. Plot out the yaw rate and lateral acceleration of the
> best run using MATLAB (MCP).

</details>

An [MCP](https://modelcontextprotocol.io) server that lets an AI agent drive **IPG CarMaker** on your
computer: start a session, run test runs and parameter studies, read and plot the results, change vehicle,
driver and Simulink controller parameters, and undo what it changed.

> Unofficial community project, not affiliated with or endorsed by IPG Automotive or MathWorks. You need your
> own CarMaker and MATLAB/Simulink licences. This repository contains no IPG or MathWorks code or data.

**Status: alpha.** Developed and tested on one setup (CarMaker 14.1.1, MATLAB R2024b, Windows 11).
[docs/verification.md](https://github.com/dimitr-io/carmaker-mcp/blob/main/docs/verification.md) lists
what has been checked against real software and what has not.

## What it does

Things you can ask an agent once the server is connected:

* "Run the braking test run and tell me the stopping distance."
* "Set `Kp_yaw` to 1.5 in the controller model, run the slalom again and compare the yaw rate."
* "Try the lane change with a vehicle mass of 280, 300 and 320 kg and tabulate the lateral acceleration."
* "Sweep the driver's lateral acceleration limit and g-g exponents on the skid pad and give me the best lap
  time." (lap times come from the test run's own timing markers, as CarMaker's instrument shows them)
* "Plot the yaw rate of the last two runs over distance."
* "The car got heavier. Run a driver adaption, then the autocross again."
* "The last run aborted. Why?"
* "Undo everything you changed."

Runs go at CarMaker's maximum speed unless you ask for a slower one. Parameter studies run in the
background, one run after another, with IPGMovie open if you want to watch. The server also teaches the agent
how IPGDriver works (`cm_guide`): which driver to choose, how its limits and g-g exponents set the lap time,
and when a driver adaption is worth its minutes.

It works in two ways, and the agent picks the one that fits the vehicle:

| | MATLAB-connected session | Standalone run |
|---|---|---|
| Use it for | vehicles whose controller is a Simulink model (CarMaker for Simulink) | vehicles with CarMaker's built-in controllers |
| Needs | MATLAB with your model, and the CarMaker GUI (the server can start both) | only CarMaker; no MATLAB, no window (IPGMovie on request) |

**Not covered:** Linux, TruckMaker and MotorcycleMaker, CarMaker HIL, Test Manager and test series, building
roads, traffic or scenarios, Movie NX, result formats other than `.erg`, and remote machines. The full list
is in [docs/scope.md](https://github.com/dimitr-io/carmaker-mcp/blob/main/docs/scope.md), and more worked
examples are in [docs/examples.md](https://github.com/dimitr-io/carmaker-mcp/blob/main/docs/examples.md).

## Requirements

* Windows 10 or 11
* IPG CarMaker with its Python API (developed on 14.1.1)
* For the MATLAB-connected session: CarMaker for Simulink and MATLAB R2022b or newer, as far as your CarMaker
  supports it (only R2024b has been tested)
* [uv](https://docs.astral.sh/uv/) (it fetches the server and its Python environment; pip also works)
* An MCP client: Claude Code, Claude Desktop, VS Code with GitHub Copilot, Codex, Antigravity, Cursor, ...

## Setup

**1. Check your machine.** This finds your CarMaker and MATLAB installs, tells you what does not fit and how
to fix it, and prints the `uvx` arguments for your machine:

```bash
uvx carmaker-mcp doctor
```

**2. Register the server.** This prints the entry for your client, with those arguments filled in:

```bash
uvx carmaker-mcp config --client claude-code     # or claude-desktop, vscode, codex, antigravity, cursor
```

For most clients the entry looks like this:

```json
{
  "mcpServers": {
    "carmaker": {
      "command": "uvx",
      "args": ["--python", "3.12", "--with", "matlabengine==24.2.*", "carmaker-mcp"],
      "env": {
        "CM_PROJECT": "C:\\CM_Projects\\my-project",
        "CM_MODEL": "MyModel"
      }
    }
  }
}
```

In Claude Desktop you can instead drag the `.mcpb` bundle for your MATLAB release from the
[latest release](https://github.com/dimitr-io/carmaker-mcp/releases/latest) into **Settings > Extensions**;
`uv` must be installed. [docs/setup.md](https://github.com/dimitr-io/carmaker-mcp/blob/main/docs/setup.md)
has the steps for each client and the versions that belong to each MATLAB release.

**3. Start a session.** Ask the agent, for example "start CarMaker and run the braking test run". It opens
MATLAB, your model and the CarMaker GUI as far as they are not open yet, and never closes anything. Standalone
runs need neither. If you would rather open MATLAB and CarMaker yourself, run this once per MATLAB session so
that the server can attach:

```matlab
matlab.engine.shareEngine('cm_mcp')
```

## Settings

Settings are environment variables in the client entry. These are the ones you are likely to need;
[docs/setup.md](https://github.com/dimitr-io/carmaker-mcp/blob/main/docs/setup.md#settings) has the rest.

| Variable | Default | Meaning |
|---|---|---|
| `CM_PROJECT` | read from the running CarMaker GUI | CarMaker project folder. The server writes nowhere else. Needed to start a session from scratch |
| `CM_MODEL` | none | Simulink model to open when a session is started |
| `CM_MATLAB_INIT` | none | Your project's own MATLAB setup script, run once when a session is started. Without it the model may not compile |
| `CM_POPUP_TIMEOUT` | not set | Seconds after which CarMaker pop-ups answer themselves with their default choice. Not set: they wait for your click. See [Safety](#safety-and-privacy) |
| `CM_DISABLE` | none | Tool groups to switch off, for a shorter tool list: `standalone`, `study`, `matlab`, `movie` |
| `CM_ENABLE` | none | Optional tools to switch on: `tcl` (raw Tcl in the CarMaker GUI), `experimental` (add and delete Simulink blocks) |

## Tools

* **Session and runs:** start MATLAB and CarMaker, check the setup, load, start, stop and follow runs, read the
  session log and GUI pop-ups.
* **Results:** summaries, time series, lap and sector times, IPGControl plots, MAT and CSV export, IPGMovie
  pictures.
* **Project data and parameters:** list, read, compare, edit and copy project files, workspace and Simulink
  parameters, parameter studies, driver adaption.
* **Standalone runs:** launch, follow and close independent CarMaker programs, without MATLAB.
* **History:** what a session changed, undo it, restore an earlier session.

Each tool tells the client whether it is read-only, changes state or is destructive, so that clients can ask
for confirmation where it matters. Every tool and parameter is described in
[docs/tools.md](https://github.com/dimitr-io/carmaker-mcp/blob/main/docs/tools.md).

## Using it with the MATLAB MCP server

For CarMaker for Simulink work it is worth connecting MathWorks'
[MATLAB MCP Core Server](https://github.com/matlab/matlab-mcp-core-server) as well: this server handles
CarMaker, and that one writes and runs MATLAB code. Let both work on the same MATLAB session, in the release
CarMaker uses. What is changed through the MATLAB server is not in this server's change log, and `cm_revert_all`
does not undo it.
[More in docs/setup.md](https://github.com/dimitr-io/carmaker-mcp/blob/main/docs/setup.md#using-it-with-the-matlab-mcp-server).

## Safety and privacy

This server can start simulations and **edit your project files and the live Simulink model in place**. Connect
it only to agents you trust.

What protects your work:

* Every file is backed up before its first change, every change is logged with its old value, and
  `cm_revert_all` undoes a session.
* Files are only written inside the project folder, and only while the simulation is idle. No tool deletes
  project files.
* Raw Tcl and Simulink structure edits are off unless you switch them on with `CM_ENABLE`.
* CarMaker pop-ups wait for your click by default. If you set `CM_POPUP_TIMEOUT`, a question such as "Vehicle
  not saved. All changes will be lost. OK to continue?" is answered with its default, which discards unsaved
  changes in the CarMaker GUI.

Runs write result and log files into the project's `SimOutput` folder; a revert does not remove those.

The server collects no telemetry and makes no network connections of its own. It only talks to MATLAB and
CarMaker on your machine. Details:
[docs/safety.md](https://github.com/dimitr-io/carmaker-mcp/blob/main/docs/safety.md).

## Troubleshooting

Run `uvx carmaker-mcp doctor` first: it names most setup problems together with their fix.

| Symptom | Cause and fix |
|---|---|
| "No shared MATLAB session" | MATLAB is closed or has not shared its engine. Let the agent start the session, or run `matlab.engine.shareEngine('cm_mcp')` in MATLAB |
| `uvx` fails while installing `matlabengine` | The pin must match your MATLAB release, and that MATLAB must be installed. Use the arguments `doctor` prints |
| "CarMaker ships no cmapi for Python 3.x" | Add `--python 3.12` (or another version the message lists) |
| A tool call hangs at load or start | The CarMaker GUI is showing a question. Answer it, or see `CM_POPUP_TIMEOUT` |
| "too many licenses in use" on a standalone run | Another CarMaker program holds the licence: an open MATLAB with CarMaker for Simulink, or a standalone program the server left open |
| "license has expired" | The licence must be renewed; `doctor` shows its end date |
| The wait tool returns `finished: false` | Not an error: waits are limited to 50 s per call and are simply repeated |

More: [docs/troubleshooting.md](https://github.com/dimitr-io/carmaker-mcp/blob/main/docs/troubleshooting.md).
The server's own log is `server.log` in the state folder.

## How it works

* **MATLAB-connected session:** the server attaches to your MATLAB through the MATLAB Engine for Python and
  sends commands to the CarMaker GUI through CarMaker for Simulink's own `cmguicmd`.
* **Standalone runs:** it uses IPG's Python API `cmapi`, loaded from your CarMaker install, to start and
  control a separate CarMaker process.
* **Project files** are edited by a byte-preserving editor for CarMaker's infofile format, and **results** are
  read by a NumPy reader for `.erg` files (checked against MATLAB's `cmread`).

Nothing of IPG's or MathWorks' is bundled or redistributed.

## Documentation and contributing

* [Setup in detail](https://github.com/dimitr-io/carmaker-mcp/blob/main/docs/setup.md)
* [Example sessions](https://github.com/dimitr-io/carmaker-mcp/blob/main/docs/examples.md)
* [Tools reference](https://github.com/dimitr-io/carmaker-mcp/blob/main/docs/tools.md)
* [What is verified](https://github.com/dimitr-io/carmaker-mcp/blob/main/docs/verification.md)
* [What it does not cover](https://github.com/dimitr-io/carmaker-mcp/blob/main/docs/scope.md)
* [Contributing](https://github.com/dimitr-io/carmaker-mcp/blob/main/CONTRIBUTING.md): test reports from
  other CarMaker and MATLAB versions are especially welcome
* [Security policy](https://github.com/dimitr-io/carmaker-mcp/blob/main/SECURITY.md)

Related work: [pycarmaker](https://github.com/gmnvh/pycarmaker) talks to the command port of a standalone
CarMaker program. This project also covers CarMaker for Simulink, uses IPG's own interfaces, and shares no
code with it.

## Licence

MIT, see [LICENSE](https://github.com/dimitr-io/carmaker-mcp/blob/main/LICENSE).
