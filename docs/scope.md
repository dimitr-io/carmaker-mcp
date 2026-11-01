# What it does not cover

The server was written for vehicle-dynamics and controller work in a Formula Student team, where every run was
either a standalone run or a CarMaker for Simulink run. CarMaker can do much more than that, and the rest is
outside what this server does or has been tried with.

**Not supported** (there are no tools for it):

* **Other platforms and products:** Linux; TruckMaker and MotorcycleMaker; CarMaker HIL and CarMaker Office
  Extended (real-time hardware, Fail Safe Tester, bus interfaces such as CAN, FlexRay, SOME/IP, XCP).
* **CarMaker's own test automation:** Test Manager and test series, test reports, parallel (HPC) execution,
  batch mode with start-up files. The server runs its own parameter studies instead, one run after another.
* **Building scenarios:** the Scenario Editor and roads, traffic, sensors, the environment, OpenSCENARIO import.
  `cm_edit` changes keys in files that exist; it does not author these things.
* **Most visualisation:** Movie NX, Instruments, video export, Model Check. Of IPGMovie: watching runs and single
  pictures; of IPGControl: plots of result files.
* **Other result formats:** only `.erg` files are read, not MDF or ASCII.
* **Rebuilding the simulation program:** models in C code or generated with Simulink Coder.
* **Remote machines:** CarMaker and MATLAB must run on the computer the server runs on.

**May work, never tested:**

* FMUs, CarMaker exported as an FMU, third-party tyre models and other co-simulation tools.
* Encrypted or protected data files.
* CarMaker and MATLAB versions other than CarMaker 14.1.1 and R2024b; more than one MATLAB session or CarMaker
  GUI at a time.
* Several standalone runs in parallel (each needs a CarMaker licence), pausing and resuming a standalone run.
* Driver adaption on other CarMaker versions: `cm_driver_adaption` uses an undocumented command of the
  CarMaker 14.1.1 GUI. The race adaption has been tried standalone only.
* Test runs with traffic, sensors or driver-assistance functions. Nothing stands in their way, but every check
  so far used vehicle-dynamics runs without them.

The state of each tool is in [verification.md](verification.md). Reports from other setups are welcome.
