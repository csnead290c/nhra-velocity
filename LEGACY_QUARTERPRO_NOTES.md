# Quarter Pro source analysis

This project was built after tracing the legacy legacy **QUARTER Pro / QUARTER jr** Visual Basic source contained in the March 2023 `SourceFiles` archive. The goal isn't to copy the old UI; it's to preserve the drag-racing physics that still matter and make the model bidirectional.

## Source tree that matters

The Quarter Pro family is split into a thin product-specific UI and a shared physics library:

- `QPro Family 1_18_2023/QPro3w/QUARTER.FRM` — Pro input/UI behavior.
- `QPro Family 1_18_2023/QCommon/TIMESLIP.FRM` — the important part: pass solver, clutch/converter, tire, traction, aero, inertia, shift and timing-slip calculations.
- `QCommon/QTRPERF.BAS` — input definitions and the weather / horsepower-correction model.
- `QCommon/DECLARES.BAS` — global physical/input variables and core constants such as `gc = 32.174` and the HP/TQ conversion constant.
- `QCommon/DynoData.frm`, `HPTQCALC.FRM` — RPM / HP / torque relationship and dyno-curve handling.
- `QCommon/GEARRAT.FRM`, `TIREWID.FRM`, `REFAREA.FRM`, `POLAREC.FRM`, `POLARTC.FRM`, `POLARTW.FRM` — worksheets used to estimate final drive, tire width, frontal area and rotating polar inertias.
- `QUARTER Pro 12_19_2022/*.DAT` — examples of the persisted v3.21 input format.

The included `Qjr.vbp` project shows the intended architecture: most code is shared from `QCommon`, with conditional compilation selecting Quarter jr vs Quarter Pro vs Bonneville behavior.

## What Quarter Pro actually solves

Quarter Pro is a time/distance marching vehicle model, not a simple ET correlation.

### Engine and driveline

- Up to 11 dyno points are supplied as RPM + HP. Torque is linked by the standard HP/TQ/RPM relationship.
- Up to six transmission ratios, per-gear efficiencies and per-gear shift RPMs are supported.
- Final-drive ratio and efficiency are separate inputs.
- Both clutch and torque-converter behavior are modeled.
- The converter model contains stall speed, slippage and torque multiplication that decays as turbine/pump speed ratio closes.
- A lock-up path can be used after first gear.
- Engine, transmission/driveshaft and tire/final-drive polar inertias are included as transient horsepower demands.

### Tire and traction

- Tire diameter grows with speed using an empirical width/diameter relationship.
- Loaded circumference is reduced by tire squat as acceleration rises.
- A downtrack tire-slip term begins above 1.0 and fades toward the finish line.
- Track temperature alters the traction model.
- A Quarter Pro “Traction Index” alters the available tire force.
- Dynamic rear axle load is calculated from longitudinal acceleration, CG height, tire radius, wheelbase, driveline reaction and aerodynamic drag.
- If calculated front load goes negative, the solver adds a wheelie-bar reaction.
- Motorcycle body style receives a separate traction-force treatment.

### Aero and resistance

- Relative wind combines vehicle speed, wind speed and wind approach angle.
- Dynamic pressure is calculated from the weather-derived air density.
- Aero force uses frontal/reference area and drag coefficient.
- Lift coefficient is used as an added vertical load in the original sign convention (effectively downforce when positive).
- Reference area is increased slightly with tire growth.
- Rolling/friction resistance is empirical and decreases somewhat with distance; a speed-dependent viscous term is also present.

### Timing-system behavior

The timing model is unusually important and is worth preserving:

- Vehicle motion begins before the ET clock because staging rollout is modeled.
- When rollout is consumed, ET is reset to zero and the model applies a front-overhang/front-tire geometry adjustment.
- Timing points are 30, 60, 330, 594, 660, 1000, 1254 and 1320 ft.
- 1/8- and 1/4-mile “trap speeds” are **not instantaneous speed**. Quarter Pro calculates them from elapsed time across the final 66-ft trap (594→660 and 1254→1320).

That detail is crucial when fitting to official timing data: matching instantaneous 660- or 1320-ft speed to a printed timeslip MPH value is subtly wrong.

### Numerical behavior

The legacy solver:

- advances vehicle speed with an adaptive step,
- limits jerk to roughly -4 to +2 g/s,
- shortens steps at shifts/timing points,
- iterates rotating-inertia horsepower until the step converges,
- caps calculated acceleration at the traction limit,
- interpolates the converged state back to exact timing/print points.

There are now **two separate engines** rather than trying to make one numerical method serve incompatible jobs:

- `runlab/physics.py` is the smooth fixed-step optimizer engine. It keeps the important Quarter Pro physical terms while remaining stable enough for thousands of nonlinear-optimizer evaluations.
- `runlab/legacy_reference.py` is the source-faithful reference engine. It mirrors the VB6 adaptive speed stepping, event matching, shift dwell, rotating-inertia iteration, jerk limits, traction reflection, rollout/overhang behavior and trap windows. It exists to judge the smoother engine rather than to make optimization easy.

Both implementations explicitly distinguish **wheel/tire RPM** (what the legacy variable named `DSRPM` actually computes) from **driveshaft RPM** as a modern logger user normally means it. The smooth engine is not claimed bit-for-bit identical to the VB solver; the source-faithful engine is the closer translation and still awaits final independent comparison against the compiled Windows executable.

## Weather / horsepower correction

`QTRPERF.BAS::Weather()` calculates:

- dry-air partial pressure from temperature, humidity, barometer and elevation,
- water/air ratio,
- ambient air density,
- a fuel/induction-specific horsepower correction factor.

Legacy fuel-system codes are:

1. gasoline carburetor
2. gasoline injection
3. methanol carburetor
4. methanol injection
5. nitromethane injection
6. supercharged gasoline
7. supercharged methanol
8. supercharged nitromethane
9. flat/uncorrected engine power

`runlab/weather.py` is a direct mathematical port of that routine.

## Legacy input set

The source exposes these primary user variables:

**Weather / surface** — elevation, ambient temperature, barometer, humidity, wind speed, wind angle, track temperature, traction index.

**Vehicle** — race weight, wheelbase, staging rollout, front overhang, body style.

**Aero** — reference/frontal area, drag coefficient, lift coefficient.

**Engine** — 11-point RPM/HP curve, HP/TQ multiplier, fuel system.

**Launch / converter / clutch** — transmission type, launch RPM, stall/slip RPM or legacy stall index, slippage, lock-up, converter torque multiplication.

**Transmission** — up to six gear ratios, efficiencies and shift RPMs.

**Final drive / tire** — final ratio, final-drive efficiency, tire diameter/rollout and tire width.

**Rotating inertia** — engine PMI, transmission/driveshaft/pinion PMI, tire/wheel/ring-gear/axle PMI.

**Geometry / calculated fields** — static front weight, longitudinal CG and vertical CG exist in the shared declarations, although Quarter Pro often calculates the CG/front-load quantities heuristically during a run.

## Why inverse fitting must be constrained

The forward model has more inputs than a single timeslip can uniquely determine. A few examples:

- **Cd vs frontal area** — track data primarily sees the product CdA. Estimating both independently from one pass is false precision.
- **Engine power vs driveline efficiency** — both can increase wheel power. Engine RPM, driveshaft RPM, coast-down information, known transmission efficiencies or multiple gearing conditions help separate them.
- **Tire diameter vs final-drive ratio vs slip** — engine RPM and driveshaft/wheel speed are what make this identifiable.
- **Torque-curve shape** — official incrementals constrain integrated performance, but RPM-resolved telemetry is far better for locating which portion of the curve is wrong.
- **Power vs traction** — a traction-limited first half of a run can hide additional power; later speed and repeat runs on different surfaces help separate the two.

For that reason the new inverse solver reports covariance/correlation and an identifiability rating instead of just returning a suspiciously precise number.

## New bidirectional model

The new workflow is deliberately symmetrical:

### Direct reconstruction — observed pass → apparent delivered power

Before optimization, the NHRA Tech Data prototype can derive a pass-based apparent torque/HP curve from speed/time/RPM data by differentiating smoothed vehicle speed, adding back modeled road/aero loads and reducing the required wheel torque through the known driveline. The observed engine-RPM / driveshaft-RPM ratio is also summarized by gear, making clutch/converter slip or an incorrect ratio immediately visible.

### Inverse mode — observed pass → most likely vehicle

Known data can include:

- telemetry channels (RPM, driveshaft RPM, speed, longitudinal G, gear, throttle, boost, etc.),
- official 60/330/660/1000/1320 timing and trap speeds,
- weather and track temperature,
- race weight, CG height and static front-axle weight,
- known ratios, tire, fuel system, converter/clutch information,
- repeated runs of the same vehicle.

The optimizer can estimate shared unknowns including:

- global power multiplier,
- five local torque/dyno curve shape multipliers,
- CdA and combined ClA/downforce area,
- traction index,
- stall/slip RPM,
- slippage,
- converter torque multiplication,
- final-drive ratio and final-drive efficiency,
- tire diameter and tire-growth scale,
- race weight, CG height and static front-axle weight,
- driveline efficiency scale,
- common shift-RPM offset or individual shift RPMs,
- individual transmission gear ratios,
- rollout and front overhang.

### Forward mode — fitted vehicle → what-if result

Once the vehicle is identified, the same model predicts changes from:

- gear ratios,
- final drive,
- shift RPM,
- power level / torque-curve shape,
- weight,
- tire size,
- traction assumptions,
- environment and wind,
- aero.

That “same physics in both directions” is the foundation of the NHRA Tech Data application.


## Source fidelity corrections found during prototype validation

Two details from the legacy source materially changed the first prototype and are now explicit regression targets:

- **Static front-load baseline:** Quarter Pro infers the static front-axle load once from the launch condition when no measured value is supplied. It then holds that baseline fixed while dynamic longitudinal load transfer changes downtrack. Re-estimating the baseline every time step artificially cancels part of the load transfer and contaminates the traction model. The modern solver now follows the source structure.
- **Rotating inertia during reconstruction:** pass-derived apparent flywheel power now includes engine and chassis rotating-inertia terms before reversing the driveline power path. Without those terms, an accelerating engine/driveline can be mistaken for missing horsepower.

The supplied sample cars are also run through an automated time-step convergence suite. That is a regression and numerical-stability test; it is **not** an independent proof of exact legacy-executable parity.

## Fit observability preflight

The inverse workflow now checks the measurement set before optimization. For each selected unknown it reports what evidence is present, major confounds and the best next measurement. The intent is to prefer direct measurements where they are cheap and strong—for example race weight, static axle weights and tire rollout—and reserve inverse estimation for quantities that are genuinely difficult to measure.

## Native RacePak/DataLink findings

Two real DataLink `.rpk` demo files used during development were used to validate a native parser. The legacy file family is self-describing enough for interoperability: recorded channels carry a length-prefixed `ScaledBuffer` definition, linear raw-to-engineering calibration, timer name/sample rate, and serialized float buffers. The prototype aligns mixed-rate buffers to their configured timers, applies the stored calibration, resamples onto a common analysis grid, and materializes simple direct calculated channels such as driveshaft-RPM-to-MPH.

The Pro Stock demo contains 20 Hz engine RPM, driveshaft RPM, clutch RPM, G-meter, pressure/voltage channels and eight EGTs. The Top Fuel demo exercises 50/100 Hz mixed channels and includes embedded 4.85 s / 253.4 mph run metadata plus ambient temperature/elevation. Automatic pass detection correctly rejects pre-run/staging motion and finds the dominant high-speed pass before reconstruction or inverse fitting.

This parser intentionally fails closed on a structurally different `.rpk` variant rather than assigning channel names to unknown binary buffers.

## Additional source details confirmed during parity work

The v0.5 parity pass resolved several behaviors that are easy to misread from the variable names or UI:

- **Body style is not stored as a rich vehicle category in the v3.21 DAT loader.** `CalcBodyStyle` classifies weight above 800 lb as the car family and 800 lb or below as motorcycle. The parser now follows that exact rule for legacy inputs.
- **Transmission type is inferred from converter multiplication.** The loader treats torque multiplication exactly equal to `1.0` as clutch; anything else is converter.
- **Rollout is an event, not a permanent distance subtraction.** The model first travels the rollout distance with the ET clock running internally. At beam release the *current* legacy time is reset to zero and an overhang/front-tire adjustment is added to the distance variable. Later timing targets are then compared to that adjusted modeled coordinate. Subtracting rollout from every later distance biases the modern timeslip.
- **The first rolling RPM state is stall/slip based, not launch-limiter based.** Launch RPM is used for the static starting-line hit. Carrying launch RPM into the rolling shift logic can create an immediate false shift, especially in the motorcycle example.
- **Traction exceedance uses reflection rather than a simple clamp.** When calculated acceleration exceeds `AMAX`, the source reflects the excess below the limit: `AMAX - (AGS - AMAX)`. That behavior is unusual but is preserved by the strict reference solver.
- **Rotating inertia is converged iteratively.** The source recalculates step time and PMI horsepower up to 12 times, using a 0.01% time-convergence criterion and relaxation bounded by approximately 0.92–1.08. A fixed-step derivative approximation is not guaranteed to produce the same effective transient loss.
- **Shifts are events.** QPro adjusts a candidate state to the shift RPM, then advances through a fixed shift dwell (0.20 s clutch, 0.25 s converter) before continuing. That is different from continuously integrating through a ratio change.

These differences explain why a fixed-step model can be perfectly numerically converged and still miss Quarter Pro by a measurable amount.

### Fixed-step inertia surrogate calibration

A controlled sweep of the smooth engine's rotating-inertia transient strength showed a highly consistent source-reference bias across all six sample vehicles: full instantaneous fixed-step PMI loss made the modern engine slow, while disabling inertia made it fast. Fitting the surrogate scale against **60/330/660/1000/1320 ET plus both trap speeds for every supplied example** produced an optimum near 0.72.

`SolverOptions.inertia_transient_scale` therefore defaults to **0.72**. This is explicitly a numerical-surrogate calibration, not a change to engine/transmission/tire PMI inputs. The source-faithful reference engine retains the original equations and iterative transient with no such scale. At the 2.5 ms final step the calibrated smooth engine now stays within 0.024 s and 0.98 mph at 1320 ft across the six shipped examples.

## Validation architecture

The sample-vehicle test suite now produces three distinct artifacts under `examples/qpro_reference/`:

- `convergence_summary.csv` / `convergence_detail.csv` — smooth-engine time-step stability;
- `legacy_source_reference_snapshot.csv` — regression-locked source-faithful outputs;
- `modern_vs_legacy_parity_summary.csv` / `..._detail.csv` — physics difference between the two engines.

The inverse workflow also performs **post-fit high-fidelity verification**. Optimization occurs with the smooth engine, then the optimized vehicle is rerun through `legacy_reference.py` against the same observations. The UI exposes those residuals separately. This is intentional model-discrepancy accounting: a smooth-fit residual and a reference-fit residual answer different questions.

## Recommended next engineering steps

1. **Capture authoritative outputs from the original `QPro.exe`.** The source-faithful Python engine is a strong reference but the compiled executable remains the final authority for parity. Record all six shipped sample vehicles and, ideally, intermediate trace output if the old program can export it.
2. **Refine the remaining close/parity differences.** Compare launch state, every shift event, incrementals, RPM, speed, inertia HP and traction events rather than tuning only the final ET.
3. **Blind recovery with real repeat runs.** Use a vehicle with 3–5 high-quality passes and deliberately withhold known changes (gear, ballast, power/tune, shift point) to measure whether the inverse tool recovers them.
4. **Expand native logger validation.** RacePak has real native coverage. Add representative current MoTeC, FuelTech and MaxxECU files with known channels/units before claiming broad native-format support.
5. **Add track elevation/grade.** High-quality longitudinal acceleration and GPS speed can otherwise force gravity into apparent power/aero errors.
6. **Improve clutch/converter models.** Move from scalar stall/slippage/multiplication toward measured or parameterized maps when sufficient channels exist.
7. **Posterior uncertainty.** Add profile likelihood / Monte Carlo or Bayesian posterior analysis after the deterministic inverse model is validated on real data.
8. **Persistent project database.** Vehicle → configuration → event → run → raw telemetry → normalized data → fit → scenario, with provenance and revision history.
