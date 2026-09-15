from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from .models import Environment, SimulationResult, TimingData, VehicleConfig
from .weather import quarterpro_weather

GC = 32.174
Z5 = 3600.0 / 5280.0  # ft/s -> mph
Z6 = (60.0 / (2.0 * np.pi)) * 550.0  # 5252-ish hp/tq constant

# Quarter Pro legacy constants
AX = 10.8
CMU = 0.025
CMUK = 0.01
FRCT = 1.03
KP21 = 0.15
KP22 = 0.25
AMIN_G = 0.004


@dataclass
class SolverOptions:
    dt_s: float = 0.0025
    max_time_s: float = 20.0
    max_distance_ft: float = 1400.0
    include_rotating_inertia: bool = True
    # The fixed-step surrogate evaluates PMI loss from an instantaneous dRPM/dt,
    # while Quarter Pro iterates an event-sized transient until time converges.
    # Regression across all six shipped QPro examples shows that 0.72 preserves
    # the source engine's effective inertia response across the full timeslip
    # much better than a raw 1.0 multiplier. Physical PMI inputs are untouched.
    inertia_transient_scale: float = 0.72
    legacy_traction: bool = True
    legacy_tire_growth: bool = True
    # During an actual ratio change QPro advances through a longer step.  A mild
    # torque reduction during this period produces a continuous fixed-step model.
    shift_torque_fraction: float = 1.00
    minimum_speed_for_power_fps: float = 4.0


def _track_temp_effect(temp_f: float) -> float:
    if temp_f > 100:
        e = 1.0 + 0.0000025 * abs(100.0 - temp_f) ** 2.5
    else:
        e = 1.0 + 0.0000020 * abs(100.0 - temp_f) ** 2.5
    return min(e, 1.04)


def _tire_state(v_fps: float, accel_g: float, v: VehicleConfig) -> Tuple[float, float, float]:
    """Return growth multiplier, loaded circumference [ft], loaded radius [in]."""
    dia = float(v.tire_diameter_in)
    width = max(0.25, float(v.tire_width_in))
    if dia <= 0:
        raise ValueError("tire_diameter_in must be > 0")

    tgk = (width ** 1.4 + dia - 16.0) / (0.171 * dia ** 1.7)
    growth = 1.0 + float(v.tire_growth_scale) * tgk * 0.0000135 * max(0.0, v_fps) ** 1.6
    linear = 1.0 + float(v.tire_growth_scale) * tgk * 0.00035 * max(0.0, v_fps)
    growth = min(growth, linear)
    squat = growth - 0.035 * abs(float(accel_g))
    squat = max(0.72, squat)
    circumference_ft = squat * dia * np.pi / 12.0
    loaded_radius_in = 12.0 * circumference_ft / (2.0 * np.pi)
    return growth, circumference_ft, loaded_radius_in


def _tire_slip_ratio(distance_ft: float, v: VehicleConfig, env: Environment) -> float:
    effect = _track_temp_effect(env.track_temperature_f)
    work = 0.005 * (float(v.traction_index) - 1.0) + 3.0 * (effect - 1.0)
    factor = max(0.0, 1.0 - (max(0.0, distance_ft) / 1320.0) ** 2)
    return max(1.0, 1.02 + work * factor)


def _traction_factor(v: VehicleConfig, env: Environment) -> float:
    temp_effect = _track_temp_effect(env.track_temperature_f)
    return (1.0 - (float(v.traction_index) - 1.0) * 0.01) / (temp_effect ** 0.25)


def _relative_wind_fps(v_fps: float, env: Environment) -> float:
    wind = float(env.wind_mph) / Z5
    theta = np.deg2rad(float(env.wind_angle_deg))
    value = v_fps * v_fps + 2.0 * v_fps * wind * np.cos(theta) + wind * wind
    return float(np.sqrt(max(0.0, value)))


def _converter_or_clutch(
    v: VehicleConfig,
    gear_idx: int,
    lock_rpm: float,
    elapsed_s: float,
) -> Tuple[float, float, float]:
    """Return engine RPM, transmitted torque multiplier, clutch/power slip factor.

    This follows the shape of QPro's converter/clutch calculation while keeping
    the fixed-step solver numerically smooth enough for inverse optimization.
    """
    stall = max(1.0, float(v.stall_rpm))
    slip = max(1.0, float(v.slippage))
    base_rpm = slip * max(0.0, lock_rpm)

    if v.transmission_type == "clutch":
        rpm = base_rpm
        if rpm < stall and (gear_idx == 0 or not v.lockup_after_first):
            rpm = stall
        # Quarter Pro uses Launch RPM only for the static starting-line hit.
        # Once the first rolling step begins it substitutes Stall/Slip RPM as
        # the engine-speed baseline (TIMESLIP.FRM 1093-1095).  Carrying a launch
        # limiter RPM into the rolling solver can cause an immediate false shift
        # when launch RPM is above the first shift point (notably MOTORCYC.DAT).
        power_slip = min(1.0, max(0.0, lock_rpm / max(rpm, 1.0)))
        # A slipping clutch transmits torque even when wheel speed is near zero.
        tq_mult = 1.0
        return rpm, tq_mult, power_slip

    # Converter.  QPro varies effective stall and decays multiplication toward 1.
    if gear_idx == 0 or not v.lockup_after_first:
        zstall = stall
        slip_ratio = slip * lock_rpm / zstall
        if slip_ratio > 0.6 and slip > 1.000001:
            denom = (1.0 / slip) - 0.6
            if abs(denom) > 1e-8:
                zstall *= 1.0 + (slip - 1.0) * (slip_ratio - 0.6) / denom
                zstall = max(0.75 * stall, min(1.25 * stall, zstall))
                slip_ratio = slip * lock_rpm / max(zstall, 1.0)
        rpm = max(base_rpm, zstall)
        frac = max(0.0, min(1.0, slip_ratio))
        tq_mult = float(v.torque_multiplication) - (float(v.torque_multiplication) - 1.0) * frac
        tq_mult = max(1.0, tq_mult)
        power_slip = min(1.0, max(0.0, tq_mult * lock_rpm / max(rpm, 1.0)))
        return rpm, tq_mult, power_slip

    rpm = 1.005 * lock_rpm
    return rpm, 1.0, min(1.0, lock_rpm / max(rpm, 1.0))


def _interp_crossing(x0: float, x1: float, y0: float, y1: float, target: float) -> float:
    if x1 == x0:
        return y1
    f = (target - x0) / (x1 - x0)
    f = min(1.0, max(0.0, f))
    return y0 + f * (y1 - y0)


def _timing_from_trace(trace: pd.DataFrame) -> TimingData:
    d = trace["timing_distance_ft"].to_numpy(float)
    t = trace["et_clock_s"].to_numpy(float)
    v = trace["speed_mph"].to_numpy(float)

    def t_at(dist: float) -> Optional[float]:
        idx = np.flatnonzero((d[:-1] < dist) & (d[1:] >= dist))
        if len(idx) == 0:
            exact = np.flatnonzero(np.isclose(d, dist, atol=1e-7))
            return float(t[exact[0]]) if len(exact) else None
        i = int(idx[0])
        return float(_interp_crossing(d[i], d[i + 1], t[i], t[i + 1], dist))

    t60 = t_at(60.0)
    t330 = t_at(330.0)
    t594 = t_at(594.0)
    t660 = t_at(660.0)
    t1000 = t_at(1000.0)
    t1254 = t_at(1254.0)
    t1320 = t_at(1320.0)
    mph660 = None if t594 is None or t660 is None or t660 <= t594 else Z5 * 66.0 / (t660 - t594)
    mph1320 = None if t1254 is None or t1320 is None or t1320 <= t1254 else Z5 * 66.0 / (t1320 - t1254)
    return TimingData(
        sixty_ft_s=t60,
        three_thirty_ft_s=t330,
        eighth_mile_s=t660,
        eighth_mile_mph=mph660,
        thousand_ft_s=t1000,
        quarter_mile_s=t1320,
        quarter_mile_mph=mph1320,
    )


def simulate(
    vehicle: VehicleConfig,
    env: Optional[Environment] = None,
    *,
    power_scale: float = 1.0,
    curve_multipliers: Optional[List[float]] = None,
    efficiency_scale: float = 1.0,
    shift_rpm_offset: float = 0.0,
    options: Optional[SolverOptions] = None,
) -> SimulationResult:
    """Forward drag-strip simulation derived from Quarter Pro's model structure.

    It intentionally keeps QPro-specific tire, traction, aero, weather, rollout,
    trap-window and rotating-inertia concepts while using a modern fixed-step
    state integration that is smooth enough to sit inside a numerical optimizer.
    """
    vcfg = vehicle.normalized()
    env = env or Environment()
    opt = options or SolverOptions()
    weather = quarterpro_weather(env)

    dt = float(opt.dt_s)
    if not (0.0005 <= dt <= 0.05):
        raise ValueError("dt_s must be between 0.0005 and 0.05 seconds")

    # legacy Quarter Pro overhang/rollout geometry.
    ftd = max(2.0 * float(vcfg.rollout_in), 24.0)
    overhang_adjust_ft = (float(vcfg.front_overhang_in) + 0.25 * ftd) / 12.0
    overhang_adjust_ft = max(overhang_adjust_ft, 0.5 * ftd / 12.0)
    rollout_ft = max(float(vcfg.rollout_in) / 12.0, 1e-6)

    x = 0.0
    speed = 0.0
    physical_t = 0.0
    et_zero_t: Optional[float] = None
    gear_idx = 0
    shift_until = -1.0
    prev_rpm = float(vcfg.launch_rpm)
    prev_dsrpm = 0.0
    # Establish the launch condition the same way Quarter Pro does.  The legacy
    # model infers a *static* front axle weight once at the starting line from
    # the launch hit, then holds that baseline constant while dynamic transfer
    # evolves downtrack.  Re-estimating it every step would artificially erase
    # part of the weight transfer and distort the traction limit.
    caxi = _traction_factor(vcfg, env)
    launch_tire_slip = _tire_slip_ratio(0.0, vcfg, env)
    launch_rpm = max(float(vcfg.launch_rpm), 1.0)
    launch_hp = vcfg.dyno.hp_at(launch_rpm, curve_multipliers) * float(vcfg.hp_multiplier) * float(power_scale)
    launch_hp /= max(weather.horsepower_correction, 1e-6)
    launch_torque = Z6 * launch_hp / launch_rpm
    launch_gear = vcfg.gear_ratios[0]
    launch_geff = max(0.50, min(1.0, vcfg.gear_efficiencies[0] * float(efficiency_scale)))
    launch_wind = _relative_wind_fps(0.0, env)
    launch_q = weather.density_lbm_ft3 * launch_wind * launch_wind / (2.0 * GC)
    launch_drag = CMU * vcfg.weight_lb + vcfg.drag_coefficient * vcfg.frontal_area_ft2 * launch_q
    launch_wheel_torque = (
        launch_torque * float(vcfg.torque_multiplication) * launch_gear * launch_geff
        * vcfg.final_drive_ratio * vcfg.final_drive_efficiency
    )
    launch_force = launch_wheel_torque / max(vcfg.tire_diameter_in / 24.0, 0.1)
    launch_force /= max(launch_tire_slip, 1.0)
    launch_force -= launch_drag
    loss_factor = 0.96 if vcfg.transmission_type == "converter" else 0.88
    launch_accel_g = loss_factor * launch_force / max(vcfg.weight_lb, 1.0)
    launch_accel_g = max(AMIN_G, launch_accel_g)

    cg_h = vcfg.cg_height_in if vcfg.cg_height_in is not None else (vcfg.tire_diameter_in / 2.0 + 3.75)
    _, launch_circ_ft, launch_tire_rad_in = _tire_state(0.0, launch_accel_g, vcfg)
    launch_delta_front = (
        launch_accel_g * vcfg.weight_lb
        * ((cg_h - launch_tire_rad_in) + (FRCT / max(vcfg.final_drive_efficiency, 0.5)) * launch_tire_rad_in)
        + launch_drag * cg_h
    ) / max(vcfg.wheelbase_in, 1.0)
    static_front = float(vcfg.static_front_weight_lb) if vcfg.static_front_weight_lb is not None else launch_delta_front
    static_front = max(0.0, min(vcfg.weight_lb, static_front))
    static_rear = max(0.0, vcfg.weight_lb - static_front)
    launch_traction_force = caxi * AX * vcfg.tire_diameter_in * (vcfg.tire_width_in + 1.0) * (
        0.92 + 0.08 * (max(static_rear, 1.0) / 1900.0) ** 2.15
    )
    if vcfg.body_style == 8:
        launch_traction_force *= 0.5
    launch_amax = (launch_traction_force - launch_drag) / max(vcfg.weight_lb, 1.0)
    accel_g = max(AMIN_G, min(launch_accel_g, launch_amax))
    max_accel_g = accel_g
    slip_count = 1 if launch_accel_g > launch_amax else 0

    rows: List[Dict[str, float]] = []
    max_steps = int(opt.max_time_s / dt) + 2

    for _ in range(max_steps):
        # Quarter Pro zeroes ET when the rearward edge of the staged front tire
        # has rolled the configured rollout distance, then *adds* its front
        # overhang correction directly to the solver distance state.  Therefore
        # the legacy timing coordinate after beam release is x + overhang, not
        # x - rollout + overhang.  The rollout determines clock zero; it is not
        # subtracted again from subsequent distance targets.
        timing_distance = x
        et_clock = -1.0
        if et_zero_t is not None:
            et_clock = physical_t - et_zero_t
            timing_distance = x + overhang_adjust_ft

        growth, tire_circ_ft, tire_rad_in = _tire_state(speed, accel_g, vcfg)
        tire_slip = _tire_slip_ratio(max(0.0, timing_distance), vcfg, env)
        wheel_rpm = tire_slip * speed * 60.0 / max(tire_circ_ft, 1e-6)
        driveshaft_rpm = wheel_rpm * float(vcfg.final_drive_ratio)

        gear_ratio = vcfg.gear_ratios[gear_idx]
        gear_eff = vcfg.gear_efficiencies[gear_idx] * float(efficiency_scale)
        gear_eff = max(0.50, min(1.0, gear_eff))
        lock_rpm = driveshaft_rpm * gear_ratio
        rpm, converter_tq_mult, power_slip = _converter_or_clutch(vcfg, gear_idx, lock_rpm, physical_t)

        # Shift on the user / legacy Quarter Pro shift RPM. Last gear has no shift event.
        shift_target = (vcfg.shift_rpms[gear_idx] + shift_rpm_offset) if gear_idx < len(vcfg.shift_rpms) else 0.0
        just_shifted = False
        if gear_idx < vcfg.n_gears - 1 and shift_target > 0 and rpm >= shift_target and physical_t >= shift_until:
            gear_idx += 1
            just_shifted = True
            shift_until = physical_t + max(0.0, float(vcfg.shift_duration_s))
            gear_ratio = vcfg.gear_ratios[gear_idx]
            gear_eff = max(0.50, min(1.0, vcfg.gear_efficiencies[gear_idx] * float(efficiency_scale)))
            lock_rpm = driveshaft_rpm * gear_ratio
            rpm, converter_tq_mult, power_slip = _converter_or_clutch(vcfg, gear_idx, lock_rpm, physical_t)

        hp_raw = vcfg.dyno.hp_at(rpm, curve_multipliers) * float(vcfg.hp_multiplier) * float(power_scale)
        hp_weather = hp_raw / max(weather.horsepower_correction, 1e-6)
        torque_engine = Z6 * hp_weather / max(rpm, 1.0)

        # Aerodynamic and rolling load, matching QPro's sign convention and
        # small frontal-area growth from the tire.
        wind_fps = _relative_wind_fps(speed, env)
        q = weather.density_lbm_ft3 * wind_fps * wind_fps / (2.0 * GC)
        if vcfg.body_style == 8:
            ref_area2 = vcfg.frontal_area_ft2 + ((growth - 1.0) * vcfg.tire_diameter_in / 2.0) * vcfg.tire_width_in / 144.0
        else:
            ref_area2 = vcfg.frontal_area_ft2 + ((growth - 1.0) * vcfg.tire_diameter_in / 2.0) * (2.0 * vcfg.tire_width_in) / 144.0
        downforce = vcfg.weight_lb + vcfg.lift_coefficient * ref_area2 * q
        cmu = max(0.0, CMU - max(0.0, timing_distance) / 1320.0 * CMUK)
        drag_force = cmu * downforce + 0.0001 * downforce * (Z5 * speed) + vcfg.drag_coefficient * ref_area2 * q

        # Dynamic front load uses the fixed static-front baseline established
        # above, matching the Quarter Pro source structure.
        delta_front = (
            accel_g * vcfg.weight_lb * ((cg_h - tire_rad_in) + (FRCT / max(vcfg.final_drive_efficiency, 0.5)) * tire_rad_in)
            + drag_force * cg_h
        ) / max(vcfg.wheelbase_in, 1.0)
        dynamic_front = static_front - delta_front
        wheelie_bar = 0.0
        if dynamic_front < 0.0:
            wheelie_bar = -dynamic_front * vcfg.wheelbase_in / 64.0
            dynamic_front = 0.0
        dynamic_rear = downforce - dynamic_front - wheelie_bar
        if dynamic_rear < 0.0:
            dynamic_rear = vcfg.weight_lb

        traction_force = caxi * AX * vcfg.tire_diameter_in * (vcfg.tire_width_in + 1.0) * (
            0.92 + 0.08 * (max(dynamic_rear, 1.0) / 1900.0) ** 2.15
        )
        if vcfg.body_style == 8:
            traction_force *= 0.5
        traction_force = traction_force / max(growth, 0.8)

        # Wheel force from torque path. This remains well-defined at v=0 and is
        # physically consistent with QPro's launch calculation.
        wheel_torque_lbft = (
            torque_engine
            * converter_tq_mult
            * gear_ratio
            * gear_eff
            * vcfg.final_drive_ratio
            * vcfg.final_drive_efficiency
        )
        # The rolling engine-speed relationship is based on the loaded/grown
        # tire circumference. Use the corresponding loaded radius for the
        # torque-to-force path as well; using the nominal diameter here makes
        # the torque and power paths inconsistent and systematically biases the
        # smooth solver low when the tire is squatted.
        drive_force = wheel_torque_lbft / max(tire_rad_in / 12.0, 0.1)
        drive_force /= max(tire_slip, 1.0)

        # Source-style rotating-inertia power loss. The PMI units are lb-in-s^2
        # and QPro converts with (2pi/60)^2 / (12*550*dt).
        inertia_hp = 0.0
        chassis_inertia_hp = 0.0
        if opt.include_rotating_inertia and physical_t > 0 and dt > 0:
            inertia_scale = max(0.0, float(opt.inertia_transient_scale))
            eng_acc_term = vcfg.engine_pmi * rpm * (rpm - prev_rpm) * inertia_scale
            if eng_acc_term < 0:
                eng_acc_term *= KP22 if vcfg.transmission_type == "converter" else KP21
            chassis_pmi = vcfg.tires_pmi + vcfg.transmission_pmi * vcfg.final_drive_ratio ** 2 * gear_ratio ** 2
            chas_acc_term = chassis_pmi * wheel_rpm * (wheel_rpm - prev_dsrpm) * inertia_scale
            chas_acc_term = max(0.0, chas_acc_term)
            work = (2.0 * np.pi / 60.0) ** 2 / (12.0 * 550.0 * dt)
            inertia_hp = eng_acc_term * work
            chassis_inertia_hp = chas_acc_term * work
            available_hp = max(0.0, (hp_weather - inertia_hp) * power_slip)
            available_hp = max(0.0, available_hp * gear_eff * vcfg.final_drive_efficiency - chassis_inertia_hp)
            # At moderate speed, use the source power path. At very low speed,
            # retain torque-path launch force to avoid singular P/v behavior.
            if speed > opt.minimum_speed_for_power_fps:
                power_force = available_hp * 550.0 / max(speed, opt.minimum_speed_for_power_fps)
                # This is the path Quarter Pro actually uses once rolling: RPM
                # already contains tire slip through wheel speed, so applying a
                # separate torque-path cap would effectively penalize tire slip
                # twice.  Retain torque force only around zero speed where P/V
                # is singular; above that use the source-style residual-power
                # force directly.
                drive_force = power_force / max(tire_slip, 1.0)

        if physical_t < shift_until:
            drive_force *= float(opt.shift_torque_fraction)

        net_force = drive_force - drag_force
        traction_limited = False
        max_net_force = traction_force - drag_force
        if opt.legacy_traction and net_force > max_net_force:
            net_force = max_net_force
            traction_limited = True
            slip_count += 1

        new_accel_g = max(AMIN_G, net_force / max(vcfg.weight_lb, 1.0))
        # Source clamps jerk to [-4,+2] g/s. Smooth one fixed step the same way.
        jerk = (new_accel_g - accel_g) / dt
        jerk = max(-4.0, min(2.0, jerk))
        new_accel_g = accel_g + jerk * dt
        new_accel_g = max(AMIN_G, new_accel_g)
        max_accel_g = max(max_accel_g, new_accel_g)

        rows.append({
            "physical_time_s": physical_t,
            "et_clock_s": et_clock,
            "axle_distance_ft": x,
            "timing_distance_ft": timing_distance,
            "speed_fps": speed,
            "speed_mph": speed * Z5,
            "accel_g": accel_g,
            "gear": gear_idx + 1,
            "engine_rpm": rpm,
            "wheel_rpm": wheel_rpm,
            "driveshaft_rpm": driveshaft_rpm,
            "tire_growth": growth,
            "tire_slip_ratio": tire_slip,
            "traction_limited": 1.0 if traction_limited else 0.0,
            "engine_hp_weather": hp_weather,
            "engine_torque_lbft": torque_engine,
            "drive_force_lb": drive_force,
            "drag_force_lb": drag_force,
            "traction_force_lb": traction_force,
            "dynamic_rear_weight_lb": dynamic_rear,
            "engine_inertia_hp": inertia_hp,
            "chassis_inertia_hp": chassis_inertia_hp,
        })

        if et_zero_t is not None and timing_distance >= 1322.0:
            break

        # Semi-implicit integration.
        a_fps2 = new_accel_g * GC
        x_next = x + speed * dt + 0.5 * a_fps2 * dt * dt
        speed_next = max(0.0, speed + a_fps2 * dt)
        t_next = physical_t + dt

        if et_zero_t is None and x_next >= rollout_ft:
            # Interpolate the exact beam-release time inside the step.
            if x_next > x:
                f = (rollout_ft - x) / (x_next - x)
            else:
                f = 1.0
            et_zero_t = physical_t + max(0.0, min(1.0, f)) * dt

        prev_rpm = rpm
        prev_dsrpm = wheel_rpm
        x, speed, physical_t, accel_g = x_next, speed_next, t_next, new_accel_g

        if x > opt.max_distance_ft or physical_t > opt.max_time_s:
            break

    trace = pd.DataFrame(rows)
    if trace.empty:
        raise RuntimeError("Simulation produced no trace data.")
    timing = _timing_from_trace(trace)
    return SimulationResult(
        trace=trace,
        timing=timing,
        diagnostics={
            "weather_density_lbm_ft3": weather.density_lbm_ft3,
            "weather_hp_correction": weather.horsepower_correction,
            "rollout_ft": rollout_ft,
            "overhang_adjust_ft": overhang_adjust_ft,
            "inferred_cg_height_in": cg_h,
            "static_front_weight_lb": static_front,
            "static_front_pct": 100.0 * static_front / max(vcfg.weight_lb, 1.0),
            "launch_accel_unclipped_g": launch_accel_g,
            "launch_traction_limit_g": launch_amax,
            "max_accel_g": max_accel_g,
            "traction_limited_steps": slip_count,
            "steps": len(trace),
            "solver_dt_s": dt,
            "inertia_transient_scale": float(opt.inertia_transient_scale),
        },
    )


def timeslip_table(result: SimulationResult) -> pd.DataFrame:
    t = result.timing
    rows = [
        ("60 ft", t.sixty_ft_s, None),
        ("330 ft", t.three_thirty_ft_s, None),
        ("1/8 mile", t.eighth_mile_s, t.eighth_mile_mph),
        ("1000 ft", t.thousand_ft_s, None),
        ("1/4 mile", t.quarter_mile_s, t.quarter_mile_mph),
    ]
    return pd.DataFrame(rows, columns=["Increment", "ET (s)", "MPH"])
