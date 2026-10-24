"""Driver adaption: let IPGDriver learn a car (Basic) or a car on a circuit (Race), and save what it learnt.

IPG documents this only as a GUI dialog (Simulation > Driver Adaption). The GUI also has the script
command ``Driver adaptbasicknowledge <limits> <dynamics>`` / ``Driver adaptracedriver <rate>`` (read
from CarMaker 14.1.1), which starts the same procedure: a special run on a straight road (Basic) or
laps of the test run's course (Race). It returns at once; the GUI reads the result into the driver's
knowledge when the run ends, in memory. Saving writes the knowledge into the driver template file, or
into the test run when its driver is kept there ("Test Run").

In the MATLAB session the session's own GUI does this. Without MATLAB the server starts a CarMaker GUI
of its own (guiport.OwnGui), which works for cars without a Simulink controller.

A Basic adaption takes minutes: measured 94 s standalone and 17 min in the MATLAB session for an FS car
(the second with a Simulink controller), 30 s for a simple example car; a Race adaption runs as long as the
test run allows. In the MATLAB session the GUI reported no phase (Driver.Adapt.Phase read 0 throughout):
then only wall_s shows progress.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .backend import BackendError

Tcl = Callable[[str, int], tuple[int, str]]

# Helpers sourced into the GUI (one-line commands only reach it over its command port).
HELPERS = r"""
proc ::mcp_adapt_state {} {
    set active [[::Scene::Dynamic_GetController DriverAdaption] IsActive]
    set phase ""
    catch {set phase [lindex [::ScriptControl::DVARead Driver.Adapt.Phase] 0]}
    return [list active $active simstate $::HIL(SimState) connected $::HIL(Connected) phase $phase]
}
proc ::mcp_adapt_knowledge_obj {} {
    set k [[::Scene::Dynamic_GetModel EgoVehicle] GetDriverKnowledge]
    if {$k eq ""} {
        set kc [::Scene::Dynamic_GetController DriverTemplate.Knowledge]
        set k [$kc GetKnowledgeByName DefaultDriverKnowledge]
    }
    return $k
}
proc ::mcp_adapt_knowledge {} {
    set ego [::Scene::Dynamic_GetModel EgoVehicle]
    set out [list template [$ego GetDriverTemplateFName] testrun $::TestRun(FName)]
    set k [::mcp_adapt_knowledge_obj]
    if {$k eq ""} { return $out }
    foreach p {Name Mode VehicleLimitsDate ControllerDynDate RaceAdaptionDate Vehicle TestRun Friction
               LearningRate} {
        set v ""
        catch {set v [$k PropertyGetValue $p]}
        lappend out "k_$p" $v
    }
    return $out
}
proc ::mcp_adapt_save {} {
    set ego [::Scene::Dynamic_GetModel EgoVehicle]
    set k [::mcp_adapt_knowledge_obj]
    if {$k eq ""} { error "no knowledge to save" }
    $ego SetDriverKnowledge $k
    [::Scene::Dynamic_GetController DriverTemplate.Knowledge] SaveModel
    set template [$ego GetDriverTemplateFName]
    if {$template ne "Test Run"} {
        set tc [::Scene::Dynamic_GetController DriverTemplate]
        $tc WriteFileNode [$tc GetDataNodeWithFileName $template]
    }
    SaveTestRun $::TestRun(FName)
    return [list template $template testrun $::TestRun(FName) knowledge [$k PropertyGetValue Name]]
}
"""

# Driver.Adapt.Phase: the manoeuvre ids of the IPGDriver manual, chapter 4
PHASES = [(1, 45, "idle"), (100, 130, "top speed per gear"), (200, 240, "pedal step responses"),
          (300, 310, "preview times"), (400, 420, "open-loop steering"), (500, 560, "steering response"),
          (600, 600, "closed-loop steering"), (999, 999, "finished")]


def phase_name(phase: float | None) -> str | None:
    if phase is None:
        return None
    for lo, hi, name in PHASES:
        if lo <= phase <= hi:
            return name
    return None


def tcl_dict(text: str) -> dict[str, str]:
    """A flat Tcl list ``k v k {v w} ...`` as a dict (values without inner braces)."""
    out: dict[str, str] = {}
    tokens, cur, depth = [], "", 0
    for ch in text.strip():
        if ch == "{":
            if depth:
                cur += ch
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth:
                cur += ch
        elif ch.isspace() and depth == 0:
            if cur or (tokens and len(tokens) % 2 == 1):
                tokens.append(cur)
            cur = ""
            continue
        else:
            cur += ch
    if cur or len(tokens) % 2 == 1:
        tokens.append(cur)
    for i in range(0, len(tokens) - 1, 2):
        out[tokens[i]] = tokens[i + 1]
    return out


class Adaption:
    """One adaption on one GUI, run on a background thread."""

    def __init__(self, tcl: Tcl, helpers_file: Path, kind: str, vehicle_limits: bool = True,
                 controller_dynamics: bool = True, learning_rate: float = 0.5, knowledge: str | None = None,
                 save: bool = True, max_run_s: float = 3600.0,
                 before_save: Callable[[dict], None] | None = None,
                 after: Callable[[], None] | None = None, poll_s: float = 2.0):
        if kind not in ("basic", "race"):
            raise BackendError("kind is 'basic' or 'race'")
        if kind == "basic" and not (vehicle_limits or controller_dynamics):
            raise BackendError("a basic adaption needs vehicle_limits or controller_dynamics")
        self.tcl, self.helpers_file, self.kind = tcl, helpers_file, kind
        self.vehicle_limits, self.controller_dynamics = vehicle_limits, controller_dynamics
        self.learning_rate, self.knowledge, self.save = learning_rate, knowledge, save
        self.max_run_s, self.before_save, self.after, self.poll_s = max_run_s, before_save, after, poll_s
        self.state: dict[str, Any] = {"state": "starting", "kind": kind}
        self._cancel = threading.Event()
        self._done = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- GUI calls -------------------------------------------------------------------------
    def _ok(self, command: str, timeout_ms: int = 30000) -> str:
        status, result = self.tcl(command, timeout_ms)
        if status != 0:
            raise BackendError(f"`{command}` failed: {result}")
        return result

    def prepare(self) -> None:
        """Load the helpers and start the adaption; raises if the GUI refuses."""
        self.helpers_file.parent.mkdir(parents=True, exist_ok=True)
        self.helpers_file.write_text(HELPERS, encoding="utf-8")
        self._ok("source {" + self.helpers_file.as_posix() + "}")
        if self.knowledge:
            self._ok("Driver setactiveknowledge {" + self.knowledge + "}")
        before = tcl_dict(self._ok("::mcp_adapt_knowledge"))
        self.state["template"] = before.get("template")
        self.state["testrun"] = before.get("testrun")
        cmd = (f"Driver adaptbasicknowledge {int(self.vehicle_limits)} {int(self.controller_dynamics)}"
               if self.kind == "basic" else f"Driver adaptracedriver {float(self.learning_rate):g}")
        res = self._ok(cmd, 60000).strip()
        if res != "0":
            raise BackendError(f"the GUI did not start the adaption (answer {res!r}); see cm_popups")
        self.state.update(state="running", started=time.strftime("%Y-%m-%d %H:%M:%S"))
        self._t0 = time.time()

    def run(self) -> None:
        self._thread = threading.Thread(target=self._work, name="driver-adaption", daemon=True)
        self._thread.start()

    def _work(self) -> None:
        try:
            seen_active = False
            while True:
                st = tcl_dict(self._ok("::mcp_adapt_state", 10000))
                try:
                    phase = float(st.get("phase", ""))
                except ValueError:
                    phase = None
                if phase:  # 0: not readable (found in the MATLAB session), not a phase
                    self.state["phase"], self.state["phase_name"] = phase, phase_name(phase)
                self.state["wall_s"] = round(time.time() - self._t0, 1)
                active = st.get("active") == "1"
                seen_active = seen_active or active
                if not active and (seen_active or time.time() - self._t0 > 10):
                    break
                if self._cancel.is_set() or time.time() - self._t0 > self.max_run_s:
                    self.state["stopped"] = ("cancelled" if self._cancel.is_set()
                                             else f"max_run_s ({self.max_run_s:g} s)")
                    self.tcl("StopSim", 30000)
                    self._cancel.set()
                time.sleep(self.poll_s)
            k = tcl_dict(self._ok("::mcp_adapt_knowledge"))
            self.state["knowledge"] = {key[2:]: v for key, v in k.items() if key.startswith("k_") and v != ""}
            failed = k.get("k_Mode") == "failed" or self.state.get("stopped")
            if failed:
                self.state["state"] = "failed"
                self.state["note"] = ("stopped: nothing was saved" if self.state.get("stopped") else
                                      "the adaption did not finish: nothing was saved. See cm_log, cm_popups")
            elif self.save:
                if self.before_save:
                    self.before_save(self.state)
                self.state["saved"] = tcl_dict(self._ok("::mcp_adapt_save", 60000))
                self.state["state"] = "done"
            else:
                self.state["state"] = "done"
                self.state["note"] = "not saved (save=false): the knowledge is only in the GUI's memory"
        except Exception as e:  # a bug or a lost GUI must not leave the adaption 'running'
            self.state.update(state="failed", error=f"{type(e).__name__}: {e}")
        finally:
            self.state["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
            if self.after:
                try:
                    self.after()
                except Exception as e:
                    self.state["close_error"] = str(e)
            self._done.set()

    def wait(self, timeout_s: float) -> dict:
        self._done.wait(timeout_s)
        return dict(self.state)

    def cancel(self) -> dict:
        self._cancel.set()
        self._done.wait(90)
        return dict(self.state)

    @property
    def running(self) -> bool:
        return not self._done.is_set()
