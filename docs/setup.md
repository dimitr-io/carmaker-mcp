# Setup

## Requirements

| | |
|---|---|
| Operating system | Windows 10 or 11 |
| CarMaker | a release with CarMaker for Simulink and the Python API (`cmapi`); developed on 14.1.1 |
| MATLAB / Simulink | a release your CarMaker version supports (CarMaker 14.1.1: up to R2024b); only needed for the MATLAB-connected session |
| Python | one of the versions your CarMaker ships `cmapi` for, 3.10 or newer (CarMaker 14.1: 3.10, 3.11, 3.12) |
| Tooling | [uv](https://docs.astral.sh/uv/) (recommended) or pip |

Only the listed development setup is tested, see [verification.md](verification.md).

## 1. Check the machine

```bash
uvx carmaker-mcp doctor
```

It looks for the CarMaker install, the Python versions it supports, the installed MATLAB releases and the one
your CarMaker supports, the matching `matlabengine` version, a shared MATLAB session, the CarMaker GUI and the
project folder. Every failed check comes with its fix, and the last lines give the `uvx` arguments for this
machine. Run it again with those arguments to check the environment the server will really run in:

```bash
uvx --python 3.12 --with "matlabengine==24.2.*" carmaker-mcp doctor
```

`matlabengine` can only be installed where the matching MATLAB release is installed.

The two extra arguments matter, which is why the tool works them out for you:

* `--python 3.12` selects a Python version that both your CarMaker and your MATLAB release work with. Without
  it `uvx` may pick a newer Python that neither can use.
* `--with "matlabengine==24.2.*"` adds the MATLAB engine package for **your** MATLAB release. Leave it out if
  you only use standalone runs.

Both depend on the MATLAB release, because MathWorks publishes one engine package per release and each
installs only on some Python versions:

| MATLAB | Python | `uvx` arguments | Bundle on the release page |
|---|---|---|---|
| R2024b | 3.12 | `--python 3.12 --with "matlabengine==24.2.*"` | `...-R2024b-py312.mcpb` |
| R2024a | 3.11 | `--python 3.11 --with "matlabengine==24.1.*"` | `...-R2024a-py311.mcpb` |
| R2023b | 3.11 | `--python 3.11 --with "matlabengine==23.2.*"` | `...-R2023b-py311.mcpb` |
| R2023a | 3.10 | `--python 3.10 --with "matlabengine==9.14.*"` | `...-R2023a-py310.mcpb` |
| R2022b | 3.10 | `--python 3.10 --with "matlabengine==9.13.*"` | `...-R2022b-py310.mcpb` |
| none (standalone runs only) | 3.12 | `--python 3.12` | `...-standalone-py312.mcpb` |

Only the R2024b row has been run against real software. The others follow from the engine packages'
published requirements and are untested; reports are welcome. MATLAB R2022a and older cannot be used for the
MATLAB-connected session, because their engine packages need a Python older than this server supports
(standalone runs still work).

To look at the tools without CarMaker installed: `uvx carmaker-mcp --mock`.

## 2. Register the server

Every client needs the same three things: the command `uvx`, the arguments from step 1, and your settings as
environment variables. The settings you will normally set:

* `CM_PROJECT`: your CarMaker project folder.
* `CM_MATLAB_INIT`: if you normally start work by running a MATLAB script of your project (one that adds
  folders to the path and opens the model), name it here so that the agent runs it too.
* `CM_MODEL`: the Simulink model the agent opens when it starts a session. A name on the MATLAB path, or a
  path relative to the project's `src_cm4sl` folder. If you leave it out, the agent is shown the models it
  finds and picks one or asks you.

```bash
uvx carmaker-mcp config --client claude-code     # or claude-desktop, vscode, codex, antigravity, cursor
```

prints the registration with the detected values and every `CM_` variable set in your shell. Set `CM_PROJECT`
to your CarMaker project folder before running it, or edit the printed entry. Where the entry goes:

| Client | Where |
|---|---|
| Claude Code | run the printed `claude mcp add ...` command, or put the JSON into a project `.mcp.json` |
| Claude Desktop | Settings, Developer, Edit Config (`claude_desktop_config.json`), under `mcpServers` |
| VS Code | `.vscode/mcp.json`, under `servers` |
| Codex | `codex mcp add ...`, or `~/.codex/config.toml` under `[mcp_servers.carmaker]` |
| Antigravity | agent panel, MCP Servers, Manage MCP Servers, View raw config (`mcp_config.json`), under `mcpServers` |
| Cursor | `.cursor/mcp.json`, under `mcpServers` |

The examples below assume MATLAB R2024b and Python 3.12; replace the arguments with the ones `doctor` printed.
In JSON and TOML, write Windows paths with double backslashes or with forward slashes. So far only Claude Code
and Claude Desktop have been used with this server; the other entries follow each client's documented format.

### Claude Code

Run in a terminal:

```bash
claude mcp add carmaker --env CM_PROJECT="C:\CM_Projects\my-project" --env CM_MODEL="MyModel" -- uvx --python 3.12 --with "matlabengine==24.2.*" carmaker-mcp
```

Add further settings with more `--env NAME="value"` before the `--`. With `--scope project` the entry goes
into a `.mcp.json` in the current folder, where you can edit its `env` block later; otherwise remove and add
it again (`claude mcp remove carmaker`). `claude mcp list` shows whether the server connects.

### Claude Desktop

**One-click bundle.** Download the `.mcpb` file for your MATLAB release from the
[latest release](https://github.com/dimitr-io/carmaker-mcp/releases/latest) (the table in step 1 names them) and drag
it into **Settings > Extensions**. Fill in the project folder, the model and, if your project has one, its
MATLAB setup script in the dialog; **Configure** changes them later. The bundle holds the server but not its
Python environment: Claude Desktop builds that with `uv` on first use, so `uv` must be installed.

**By hand.** **Settings > Developer > Edit Config** opens `claude_desktop_config.json`. Add the entry and
restart Claude Desktop:

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

### GitHub Copilot in Visual Studio Code

Create `.vscode/mcp.json` in your workspace (for all workspaces: **MCP: Open User Configuration** in the
Command Palette):

```json
{
  "servers": {
    "carmaker": {
      "type": "stdio",
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

Click **Start** above the entry, then use Copilot Chat in agent mode.

### Codex

Run in a terminal:

```bash
codex mcp add carmaker --env CM_PROJECT="C:\CM_Projects\my-project" --env CM_MODEL="MyModel" -- uvx --python 3.12 --with "matlabengine==24.2.*" carmaker-mcp
```

or edit `C:\Users\<username>\.codex\config.toml`:

```toml
[mcp_servers.carmaker]
command = "uvx"
args = ["--python", "3.12", "--with", "matlabengine==24.2.*", "carmaker-mcp"]
env_vars = ["WINDIR"]

[mcp_servers.carmaker.env]
CM_PROJECT = "C:\\CM_Projects\\my-project"
CM_MODEL = "MyModel"
```

Codex starts servers with a reduced environment; `env_vars = ["WINDIR"]` passes on a Windows variable that
MATLAB's libraries need.

### Antigravity

In the agent panel open the **...** menu, then **MCP Servers > Manage MCP Servers > View raw config**. Add the
entry to the `mcp_config.json` that opens, with the same content as shown for Claude Desktop, save, and press
**Refresh** in the server list.

### Cursor and other clients

Cursor: create `.cursor/mcp.json` in your project (or `~/.cursor/mcp.json` for all projects) with the same
content as shown for Claude Desktop. Most other clients use that `mcpServers` format too.

## 3. Start a session

Either let the agent do it, or do it yourself.

**By the agent.** `cm_session_start` brings up what is missing: a MATLAB desktop started in
`<project>/src_cm4sl` (it runs `cmenv` and shares its engine), the Simulink model named in `CM_MODEL` or in
the call, and the CarMaker GUI. It never closes or restarts anything. MATLAB can take a minute to start; the
tool returns `ready=false` with what it is waiting for and is simply called again.

Which model? CarMaker does not record which Simulink model belongs to a test run or vehicle, so the server
cannot look it up. If neither the call nor `CM_MODEL` names one, `cm_session_start` opens none and returns
the models that are already loaded and the model files it finds under the start folder (most recently
changed first), so that the agent can pick the obvious one or ask you. Set `CM_MODEL` to skip that step.

**By hand.** Open MATLAB, change to your project's `src_cm4sl`, open the model and the CarMaker GUI as you
always do, then once per MATLAB session:

```matlab
matlab.engine.shareEngine('cm_mcp')
```

Put that line into `startup.m` to make it permanent.

Standalone runs (`cm_standalone_*`) need neither MATLAB nor an open GUI.

## Settings

All settings are environment variables in the client entry, set like `CM_PROJECT` and `CM_MODEL` above.

**Common**

| Variable | Default | Meaning |
|---|---|---|
| `CM_PROJECT` | read from the running CarMaker GUI | CarMaker project folder. The server writes nowhere else. Needed to start a session from scratch |
| `CM_MODEL` | none | Simulink model to open when a session is started |
| `CM_MATLAB_INIT` | none | Your project's own MATLAB setup script (in `src_cm4sl`, or a full path), run once when a session is started. Use it if you normally run a script that adds folders to the path and opens the model: without it the model may not compile |
| `CM_POPUP_TIMEOUT` | not set | Seconds after which CarMaker pop-ups answer themselves with their default choice, so that a question cannot block a run. Not set: they wait for your click. See [safety.md](safety.md) |
| `CM_DISABLE` | none | Tool groups to switch off, to give the model a shorter tool list: `standalone`, `study`, `matlab`, `movie` |
| `CM_ENABLE` | none | Optional tools to switch on: `tcl` (raw Tcl in the CarMaker GUI), `experimental` (add and delete Simulink blocks) |

**Advanced**

| Variable | Default | Meaning |
|---|---|---|
| `CM_HOME` | newest `C:\IPG\carmaker\win64-*` | CarMaker install folder |
| `CM_MATLAB_EXE` | newest installed MATLAB that your CarMaker supports | MATLAB executable used to start a session |
| `CM_MATLAB_DIR` | `<project>/src_cm4sl` | Folder MATLAB starts in (where `cmenv.m` is) |
| `CM_MATLAB_SESSION` | `cm_mcp` | Name under which MATLAB shares its engine |
| `CM_IPGCONTROL` | found next to CarMaker | `ipg-control.exe` that `cm_results_plot` opens |
| `CM_RESULT_DIRS` | none | Extra folders to search for result files |
| `CM_STATE_DIR` | `%USERPROFILE%\.carmaker-mcp` | Where backups, the change log and `server.log` are kept (never inside the project). MATLAB and CarMaker must see the folder too, so not one below `AppData` |
| `CM_ENGINE_TIMEOUT` | `30` | Seconds before a call into MATLAB is given up |
| `CM_LOG_LEVEL` | `INFO` | Detail of `server.log` |

## Using it with the MATLAB MCP server

For CarMaker for Simulink work it is worth connecting MathWorks'
[MATLAB MCP Core Server](https://github.com/matlab/matlab-mcp-core-server) as well. It is optional, and
standalone runs do not need it. The two servers do different jobs:

| Server | Use it for |
|---|---|
| carmaker-mcp | The CarMaker side: session, test runs, run control, results and project data, and controller parameters with a change log and undo |
| MATLAB MCP server | The MATLAB side: writing, checking and running MATLAB code (post-processing scripts, plots) and looking into the Simulink model |

Things to know when you use both:

* Let both work on the same MATLAB session (set the MATLAB server up to use your open MATLAB, see its README),
  so that they see the same model and workspace. This is how the pair was used during development.
* MATLAB does one thing at a time. While a model compiles or a simulation runs, calls through the MATLAB server
  wait. This server's run tools are built around that (time-limited waits that are simply repeated).
* Start and stop runs with this server's tools, so that it can follow the run (result file, errors, storage
  mode).
* Running a script through the MATLAB server can move MATLAB's working folder out of the CarMaker project.
  CarMaker for Simulink then stops the next start with a question about the project directory. This server
  puts the folder back before it loads a test run or starts one, and says so in the result.
* What is changed through the MATLAB server is not in this server's change log, and `cm_revert_all` does not
  undo it.
* If several MATLAB releases are installed, make sure the MATLAB server works in the release CarMaker uses
  (`carmaker-mcp doctor` names it). A MATLAB server that starts a newer release of its own sees neither your
  model nor the CarMaker session.

## Several conversations on one CarMaker

Every client and conversation starts a server of its own, and all of them drive the same MATLAB and CarMaker.
While one of them runs a parameter study, the others refuse to load, start or stop anything and say who is
running what; `cm_status` shows it as `study_running`. Outside studies there is no such guard: two
conversations that both start single runs will get in each other's way.

## Updating and pinning

`uvx` caches the environment. To move to the newest release run `uvx carmaker-mcp@latest --version` once; to
stay on one release write `carmaker-mcp==0.1.0` in the `args`.

## Fewer tools

Each tool description costs the model some context. If you never use a group, switch it off:
`CM_DISABLE=standalone,study` (also `matlab`, `movie`). Raw Tcl and the experimental Simulink structure tools are off
unless you set `CM_ENABLE=tcl,experimental`.

## Without uv

```bash
py -3.12 -m venv .venv
.venv\Scripts\pip install carmaker-mcp "matlabengine==24.2.*"
.venv\Scripts\carmaker-mcp doctor
```

and register `"command": "C:\\path\\to\\.venv\\Scripts\\carmaker-mcp.exe"` without `args`.

## One-click bundle (Claude Desktop)

Releases carry one `.mcpb` bundle per MATLAB release from R2022b to R2024b (for example
`carmaker-mcp-<version>-R2024b-py312.mcpb`; the Python version in the name is the newest one that release's
engine package installs on). Download the one for your MATLAB release, open it with Claude Desktop (Settings,
Extensions) and fill in the project folder. The host creates the Python environment itself with `uv`, which
must be installed; MATLAB of that release must be installed too, because the MATLAB engine package is built
against it. The bundle without MATLAB (`...-standalone-...`) only offers standalone runs. Only the R2024b
bundle has been installed and used; the others are built the same way but untested.

## Single-file executable

For a machine without Python, `packaging\build_exe.ps1` builds one `carmaker-mcp.exe` (about 40 MB) with
PyInstaller. It is tied to the Python version it was built with (your CarMaker must ship `cmapi` for it) and
to the MATLAB release and install folder of the build machine, so build it per setup.
