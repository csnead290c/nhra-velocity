from __future__ import annotations

"""Source-faithful Quarter Pro v3.21 reference solver.

This module intentionally mirrors the event-driven numerical structure in
QCommon/TIMESLIP.FRM.  It is *not* the optimizer engine.  Its job is to provide
an independent reference implementation that stays close to Patrick Hale's
legacy VB6 equations so the smoother modern solver has something concrete to
be compared against.

The original program used VB6 Single precision and several event-matching
revisions (distance, time, speed, shift).  Python uses double precision here,
but the equations, adaptive step limits, shift dwell, inertia iteration,
traction reflection, rollout/overhang handling and trap-speed windows follow
the source structure.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .models import Environment, SimulationResult, TimingData, VehicleConfig
from .weather import quarterpro_weather

PI = 3.141593
GC = 32.174
Z5 = 3600.0 / 5280.0
Z6 = (60.0 / (2.0 * PI)) * 550.0

JMIN = -4.0
JMAX = 2.0
K6 = 0.92
K61 = 1.08
AMIN = 0.004
AX = 10.8
CMU = 0.025
CMUK = 0.01
TIME_TOL = 0.002
KV = 0.02 / Z5
K7 = 9.5
KP21 = 0.15
KP22 = 0.25
FRCT = 1.03


@dataclass
class LegacyReferenceOptions:
    max_time_s: float = 30.0
    max_iterations: int = 250000
    preserve_vb_single_rounding: bool = False


def _f32(x: float, enabled: bool) -> float:
    return float(np.float32(x)) if enabled else float(x)


def _interp_hp(v: VehicleConfig, rpm: float, curve_multipliers: Optional[List[float]] = None) -> float:
    return v.dyno.hp_at(rpm, curve_multipliers)


def _track_temp_effect(temp_f: float) -> float:
    if temp_f > 100.0:
        out = 1.0 + 0.0000025 * abs(100.0 - temp_f) ** 2.5
    else:
        out = 1.0 + 0.0000020 * abs(100.0 - temp_f) ** 2.5
    return min(out, 1.04)


def _tire(v: VehicleConfig, speed_fps: float, accel_g: float) -> Tuple[float, float, float]:
    dia = float(v.tire_diameter_in)
    tgk = (float(v.tire_width_in) ** 1.4 + dia - 16.0) / (0.171 * dia ** 1.7)
    growth = 1.0 + tgk * 0.0000135 * max(speed_fps, 0.0) ** 1.6
    linear = 1.0 + tgk * 0.00035 * max(speed_fps, 0.0)
    if linear < growth:
        growth = linear
    squat = growth - 0.035 * abs(accel_g)
    circ_ft = squat * dia * PI / 12.0
    rad_in = 12.0 * circ_ft / (2.0 * PI)
    return growth, circ_ft, rad_in


def _wind_q(rho: float, speed_fps: float, env: Environment) -> float:
    wind = float(env.wind_mph) / Z5
    theta = PI * float(env.wind_angle_deg) / 180.0
    wf = np.sqrt(max(0.0, speed_fps * speed_fps + 2.0 * speed_fps * wind * np.cos(theta) + wind * wind))
    return float(rho * wf * wf / (2.0 * GC))


def _time_print_increment(v: VehicleConfig, env: Environment, rho: float, hpc: float, tire_slip: float, track_effect: float) -> float:
    hpmax = (
        max(v.dyno.hp) * float(v.hp_multiplier) / max(hpc, 1e-9)
        * v.gear_efficiencies[0] * v.final_drive_efficiency
        / (max(v.slippage, 1e-9) * max(tire_slip, 1e-9))
    )
    et = (track_effect ** 0.25) * (1.8 + 4.2 * (hpmax / v.weight_lb) ** (-1.0 / 3.0))
    kd = 33 - (1 if v.body_style == 8 else 0)
    for inc in (0.25, 0.5, 1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 35, 40, 50):
        z = et / inc + 2 * (v.n_gears - 1)
        if z < kd:
            return float(inc)
    return 100.0


def _apply_traction_reflection(pqwt: float, ag: float, amax: float) -> Tuple[float, float, int]:
    slip = 0
    if ag > amax:
        slip = 1
        reflected = amax - (ag - amax)
        if abs(ag) > 1e-12:
            pqwt = pqwt * reflected / ag
        ag = reflected
    if ag < AMIN:
        if abs(ag) > 1e-12:
            pqwt = pqwt * AMIN / ag
        else:
            pqwt = AMIN * GC * 1e-6
        ag = AMIN
    return pqwt, ag, slip


def simulate_legacy_reference(
    vehicle: VehicleConfig,
    env: Optional[Environment] = None,
    *,
    power_scale: float = 1.0,
    curve_multipliers: Optional[List[float]] = None,
    efficiency_scale: float = 1.0,
    shift_rpm_offset: float = 0.0,
    options: Optional[LegacyReferenceOptions] = None,
) -> SimulationResult:
    v = vehicle.normalized()
    env = env or Environment()
    opt = options or LegacyReferenceOptions()
    wx = quarterpro_weather(env)
    rho = wx.density_lbm_ft3
    hpc = wx.horsepower_correction
    sp = bool(opt.preserve_vb_single_rounding)

    # QPro v3.21 constants / event locations.
    ftd = max(2.0 * v.rollout_in, 24.0)
    ovradj = max((v.front_overhang_in + 0.25 * ftd) / 12.0, 0.5 * ftd / 12.0)
    dist_targets = [max(v.rollout_in / 12.0, 1.0 if v.rollout_in == 0 else 0.0), 30.0, 60.0, 330.0, 594.0, 660.0, 1000.0, 1254.0, 1320.0]
    speed_targets = [60.0 / Z5, 100.0 / Z5]

    track_effect = _track_temp_effect(env.track_temperature_f)
    tire_slip = 1.02 + (v.traction_index - 1.0) * 0.005 + (track_effect - 1.0) * 3.0
    caxi = (1.0 - (v.traction_index - 1.0) * 0.01) / (track_effect ** 0.25)
    shift_tol = 20.0 if v.shift_rpms[0] > 8000 else 10.0
    dt_shift = 0.25 if v.transmission_type == "converter" else 0.20
    time_print_inc = _time_print_increment(v, env, rho, hpc, tire_slip, track_effect)
    next_print_time = time_print_inc

    # Legacy DAT examples all store explicit stall/slip RPM (>220).  Keep the
    # source's explicit value. Lambda/index solving can be added when old files
    # using <=220 are encountered.
    stall = float(v.stall_rpm)
    if stall <= 220.0:
        raise ValueError("Legacy reference solver currently requires explicit stall/slip RPM (>220), matching the shipped QPro v3.21 examples.")

    gear = 0
    t = 0.0
    dist = 0.0
    vel = 0.0
    rpm = float(v.launch_rpm)
    wheel_rpm = 0.0
    shift_active = False
    shift_end_time = 0.0
    et_zeroed = False

    # Launch static calculation.
    hp = _interp_hp(v, rpm, curve_multipliers) * v.hp_multiplier * power_scale / max(hpc, 1e-9)
    hp_save = hp
    tq = Z6 * hp / max(rpm, 1.0)
    tq *= v.torque_multiplication * v.gear_ratios[gear] * (v.gear_efficiencies[gear] * efficiency_scale)
    q = _wind_q(rho, vel, env)
    drag = CMU * v.weight_lb + v.drag_coefficient * v.frontal_area_ft2 * q
    force = tq * v.final_drive_ratio * v.final_drive_efficiency / (max(tire_slip, 1e-9) * (v.tire_diameter_in / 24.0)) - drag
    ag = (0.96 if v.transmission_type == "converter" else 0.88) * force / v.weight_lb
    ags_max_launch = ag

    cg_h = float(v.cg_height_in) if v.cg_height_in is not None else v.tire_diameter_in / 2.0 + 3.75
    growth, tire_circ, tire_rad = _tire(v, vel, ag)
    delta_f = (
        ag * v.weight_lb * ((cg_h - tire_rad) + (FRCT / v.final_drive_efficiency) * tire_rad)
        + drag * cg_h
    ) / v.wheelbase_in
    static_front = float(v.static_front_weight_lb) if v.static_front_weight_lb is not None else delta_f
    static_rear = v.weight_lb - static_front
    if static_rear < 0:
        static_rear = v.weight_lb
    crtf = caxi * AX * v.tire_diameter_in * (v.tire_width_in + 1.0) * (0.92 + 0.08 * (static_rear / 1900.0) ** 2.15)
    if v.body_style == 8:
        crtf *= 0.5
    amax = (crtf - drag) / v.weight_lb
    launch_slip = 0
    if ag > amax:
        ag = amax
        launch_slip = 1
    if ag < AMIN:
        ag = AMIN
    ags_max = ags_max_launch

    # About fifteen calculations through rollout, per source.
    tsmax = dist_targets[0] * 0.11 * (max(hp * v.torque_multiplication / v.weight_lb, 1e-9)) ** (-1.0 / 3.0)
    tsmax /= 15.0
    tsmax = max(tsmax, 0.005)

    # State history used for jerk and inertia differences.
    prev_base_t = 0.0
    prev_base_ag = ag
    prev_rpm = rpm
    prev_wheel_rpm = wheel_rpm

    timing = TimingData()
    save_594: Optional[float] = None
    save_1254: Optional[float] = None
    next_dist_idx = 0
    next_speed_idx = 0
    rows: List[Dict[str, float]] = []
    slip_count = launch_slip
    inertia_iterations_total = 0
    candidate_revisions = 0

    def append_row(event: str = "step") -> None:
        rows.append({
            "physical_time_s": t,
            "et_clock_s": t if et_zeroed else -1.0,
            "axle_distance_ft": np.nan,  # legacy Dist is a modeled coordinate after overhang jump
            "timing_distance_ft": dist,
            "speed_fps": vel,
            "speed_mph": vel * Z5,
            "accel_g": ag,
            "gear": gear + 1,
            "engine_rpm": rpm,
            "wheel_rpm": wheel_rpm,
            "driveshaft_rpm": wheel_rpm * v.final_drive_ratio,
            "tire_growth": growth,
            "tire_slip_ratio": tire_slip,
            "traction_limited": float(launch_slip if len(rows) == 0 else 0),
            "event": event,
        })

    append_row("launch")

    for outer in range(opt.max_iterations):
        if t > opt.max_time_s or next_dist_idx >= len(dist_targets):
            break

        # Handle events already sitting at the current state.
        if next_dist_idx < len(dist_targets) and abs(dist - dist_targets[next_dist_idx]) <= 0.006:
            idx = next_dist_idx
            if idx == 0:
                # Stage beam: zero legacy ET clock, then add overhang correction to
                # the legacy distance variable exactly as TIMESLIP.FRM does.
                if v.rollout_in > 0:
                    # TIMESLIP.FRM literally resets only the current time value
                    # to zero at beam release.  It does *not* translate Time0 or
                    # TimePrint.  That means the immediately following jerk check
                    # sees a non-positive interval and falls back to zero jerk.
                    # Preserve that odd but important source behavior here.
                    t = 0.0
                    et_zeroed = True
                dist += ovradj
                next_dist_idx += 1
                append_row("rollout/beam")
                continue
            elif idx == 2:
                timing.sixty_ft_s = t
            elif idx == 3:
                timing.three_thirty_ft_s = t
            elif idx == 4:
                save_594 = t
            elif idx == 5:
                timing.eighth_mile_s = t
                if save_594 is not None and t > save_594:
                    timing.eighth_mile_mph = Z5 * 66.0 / (t - save_594)
                    save_594 = None
            elif idx == 6:
                timing.thousand_ft_s = t
            elif idx == 7:
                save_1254 = t
            elif idx == 8:
                timing.quarter_mile_s = t
                if save_1254 is not None and t > save_1254:
                    timing.quarter_mile_mph = Z5 * 66.0 / (t - save_1254)
                append_row("1320")
                break
            next_dist_idx += 1
            append_row(f"distance_{dist_targets[idx]:g}")
            continue

        # Source computes jerk from the previous segment before replacing base state.
        dt_prev = t - prev_base_t
        jerk = (ag - prev_base_ag) / dt_prev if dt_prev > 0 else 0.0
        jerk = max(JMIN, min(JMAX, jerk))
        base_t, base_dist, base_vel, base_ag, base_rpm, base_wheel = t, dist, vel, ag, rpm, wheel_rpm
        prev_base_t, prev_base_ag = base_t, base_ag

        growth, tire_circ, tire_rad = _tire(v, base_vel, base_ag)
        if base_rpm == v.launch_rpm and base_t == 0.0:
            base_rpm = stall
            if v.launch_rpm < stall:
                # Engine acceleration allowance in the original source.
                base_t = v.engine_pmi * (stall - v.launch_rpm) / 250000.0
                t = base_t

        # Source updates downtrack tire slip at the beginning of each base step.
        work = 0.005 * (v.traction_index - 1.0) + 3.0 * (track_effect - 1.0)
        tire_slip = 1.02 + work * (1.0 - (base_dist / 1320.0) ** 2)
        prev_wheel_rpm = base_wheel
        prev_rpm = base_rpm

        if shift_active:
            timestep = dt_shift
        else:
            ratio = max(ags_max / max(base_ag, AMIN), 1e-9)
            timestep = tsmax * ratio ** 4
            timestep = min(timestep, time_print_inc / K7)
            if next_print_time > base_t:
                timestep = min(timestep, next_print_time - base_t)
            if next_dist_idx > 0 and base_vel > 1e-9:
                interval = (dist_targets[next_dist_idx] - dist_targets[next_dist_idx - 1]) / base_vel / 4.5
                if interval > 0:
                    timestep = min(timestep, interval)
            timestep = min(timestep, 0.05)

        timestep = max(timestep, 1e-6)
        candidate_vel = base_vel + base_ag * GC * timestep + jerk * GC * timestep * timestep / 2.0
        if not shift_active and base_vel > 0 and base_rpm > stall and gear < v.n_gears - 1:
            sr = v.shift_rpms[gear] + shift_rpm_offset
            if sr > 0:
                vmax_shift = base_vel * (sr + 5.0) / base_rpm
                if candidate_vel > vmax_shift:
                    candidate_vel = vmax_shift
                    candidate_vel = max(candidate_vel, base_vel + 1e-8)

        # If simple kinematics would hit the next distance, source revises target
        # velocity to land on that event before entering the power/inertia solve.
        if next_dist_idx < len(dist_targets):
            dist_simple = base_dist + base_vel * timestep + base_ag * GC * timestep * timestep / 2.0
            if dist_simple >= dist_targets[next_dist_idx] - 0.005:
                work2 = base_vel * base_vel + 2.0 * base_ag * GC * (dist_targets[next_dist_idx] - base_dist)
                if work2 > 0:
                    candidate_vel = min(candidate_vel, np.sqrt(work2))

        # Recalculate candidate as source does when event matching revises velocity.
        for revision in range(25):
            vel2 = max(candidate_vel, base_vel + 1e-9)
            vel_sqrd = vel2 * vel2 - base_vel * base_vel
            wheel2 = tire_slip * vel2 * 60.0 / max(tire_circ, 1e-9)
            lock_rpm = wheel2 * v.final_drive_ratio * v.gear_ratios[gear]
            rpm2 = v.slippage * lock_rpm

            if v.transmission_type == "clutch":
                if rpm2 < stall and (gear == 0 or not v.lockup_after_first):
                    rpm2 = stall
                clutch_slip = lock_rpm / max(rpm2, 1e-9)
            else:
                if gear == 0 or not v.lockup_after_first:
                    zstall = stall
                    slip_ratio = v.slippage * lock_rpm / max(zstall, 1e-9)
                    if outer > 1 and slip_ratio > 0.6:
                        denom = (1.0 / v.slippage) - 0.6
                        if abs(denom) > 1e-12:
                            zstall = zstall * (1.0 + (v.slippage - 1.0) * (slip_ratio - 0.6) / denom)
                            slip_ratio = v.slippage * lock_rpm / max(zstall, 1e-9)
                    clutch_slip = 1.0 / max(v.slippage, 1e-9)
                    if rpm2 < zstall:
                        rpm2 = zstall
                        tm = v.torque_multiplication - (v.torque_multiplication - 1.0) * slip_ratio
                        clutch_slip = tm * lock_rpm / max(zstall, 1e-9)
                else:
                    rpm2 = 1.005 * lock_rpm
                    clutch_slip = lock_rpm / max(rpm2, 1e-9)
            clutch_slip = min(clutch_slip, 1.0)

            hp_raw = _interp_hp(v, rpm2, curve_multipliers) * v.hp_multiplier * power_scale / max(hpc, 1e-9)
            hp_save2 = hp_raw
            hp_clutch = hp_raw * clutch_slip

            q2 = _wind_q(rho, vel2, env)
            if v.body_style == 8:
                ref_area2 = v.frontal_area_ft2 + ((growth - 1.0) * v.tire_diameter_in / 2.0) * v.tire_width_in / 144.0
            else:
                ref_area2 = v.frontal_area_ft2 + ((growth - 1.0) * v.tire_diameter_in / 2.0) * (2.0 * v.tire_width_in) / 144.0
            downforce = v.weight_lb + v.lift_coefficient * ref_area2 * q2
            cmu1 = CMU - (base_dist / 1320.0) * CMUK
            drag2 = cmu1 * downforce + 0.0001 * downforce * (Z5 * vel2) + v.drag_coefficient * ref_area2 * q2
            drag_hp = drag2 * vel2 / 550.0

            delta_f2 = (
                base_ag * v.weight_lb * ((cg_h - tire_rad) + (FRCT / v.final_drive_efficiency) * tire_rad)
                + drag2 * cg_h
            ) / v.wheelbase_in
            dyn_front = static_front - delta_f2
            wheelbar = 0.0
            if dyn_front < 0:
                wheelbar = -dyn_front * v.wheelbase_in / 64.0
                dyn_front = 0.0
            dyn_rear = downforce - dyn_front - wheelbar
            if dyn_rear < 0:
                dyn_rear = v.weight_lb
            crtf2 = caxi * AX * v.tire_diameter_in * (v.tire_width_in + 1.0) * (0.92 + 0.08 * (dyn_rear / 1900.0) ** 2.15)
            if v.body_style == 8:
                crtf2 *= 0.5
            amax2 = ((crtf2 / max(growth, 1e-9)) - drag2) / v.weight_lb

            eff_gear = v.gear_efficiencies[gear] * efficiency_scale
            hp_available = hp_clutch * eff_gear * v.final_drive_efficiency / max(tire_slip, 1e-9) - drag_hp
            pqwt = 550.0 * GC * hp_available / v.weight_lb
            ag2 = pqwt / (vel2 * GC)
            pqwt, ag2, slip2 = _apply_traction_reflection(pqwt, ag2, amax2)
            if slip2:
                slip_count += 1
            time2 = vel_sqrd / (2.0 * pqwt) + base_t

            eng_acc = v.engine_pmi * rpm2 * (rpm2 - base_rpm)
            if eng_acc < 0:
                eng_acc *= KP22 if v.transmission_type == "converter" else KP21
            chassis_pmi = v.tires_pmi + v.transmission_pmi * v.final_drive_ratio ** 2 * v.gear_ratios[gear] ** 2
            chas_acc = chassis_pmi * wheel2 * (wheel2 - base_wheel)
            if chas_acc < 0:
                chas_acc = 0.0

            # Iteratively converge inertia transient using the legacy time-based
            # PMI conversion and relaxation factor.
            dtk1 = max(time2 - base_t, 1e-9)
            for k in range(1, 13):
                inertia_iterations_total += 1
                conv = (2.0 * PI / 60.0) ** 2 / (12.0 * 550.0 * dtk1)
                hp_eng_pmi = eng_acc * conv
                hp_chas_pmi = chas_acc * conv
                hp_i = (hp_save2 - hp_eng_pmi) * clutch_slip
                hp_i = ((hp_i * eff_gear * v.final_drive_efficiency - hp_chas_pmi) / max(tire_slip, 1e-9)) - drag_hp
                pq_i = 550.0 * GC * hp_i / v.weight_lb
                ag_i = pq_i / (vel2 * GC)
                jerk_i = (ag_i - base_ag) / dtk1 if dtk1 else 0.0
                if jerk_i < JMIN:
                    jerk_i = JMIN
                    ag_i = base_ag + jerk_i * dtk1
                    pq_i = ag_i * GC * vel2
                if jerk_i > JMAX:
                    jerk_i = JMAX
                    ag_i = base_ag + jerk_i * dtk1
                    pq_i = ag_i * GC * vel2
                pq_i, ag_i, slip_i = _apply_traction_reflection(pq_i, ag_i, amax2)
                if slip_i:
                    slip2 = 1
                time_new = vel_sqrd / (2.0 * pq_i) + base_t
                dtk2 = max(time_new - base_t, 1e-9)
                pqwt, ag2, time2 = pq_i, ag_i, time_new
                if k == 12 or abs(100.0 * (dtk2 - dtk1) / dtk2) <= 0.01:
                    break
                zrelax = hp_i / max(hp_save2, 1e-9)
                zrelax = max(K6, min(K61, zrelax))
                time2 = base_t + dtk1 + zrelax * (dtk2 - dtk1)
                dtk1 = max(time2 - base_t, 1e-9)

            # Source constant-power distance relation after convergence.
            term = 2.0 * pqwt * (time2 - base_t) + base_vel * base_vel
            dist2 = ((max(term, 0.0) ** 1.5) - base_vel ** 3) / (3.0 * pqwt) + base_dist

            # Event velocity revisions, mirroring the pre-print checks. The
            # smallest candidate velocity wins and the physics is recalculated.
            next_vel = vel2
            # Shift dwell is forced to exact duration.
            if shift_active and abs(shift_end_time - time2) >= TIME_TOL:
                w = 2.0 * pqwt * (shift_end_time - time2) + vel2 * vel2
                if w > 0:
                    vv = np.sqrt(w)
                    if base_vel < vv < next_vel:
                        next_vel = vv
            # Distance match.
            if next_dist_idx < len(dist_targets):
                target = dist_targets[next_dist_idx]
                dd = abs(target - dist2)
                if not (dd < 0.005 and dd / max(vel2, 1e-9) < TIME_TOL) and dist2 > target:
                    w = 3.0 * pqwt * (target - dist2) + vel2 ** 3
                    if w > 0:
                        vv = w ** (1.0 / 3.0)
                        if base_vel < vv < next_vel:
                            next_vel = vv
            # Time print match.
            if time2 > next_print_time and abs(next_print_time - time2) >= TIME_TOL:
                w = 2.0 * pqwt * (next_print_time - time2) + vel2 * vel2
                if w > 0:
                    vv = np.sqrt(w)
                    if base_vel < vv < next_vel:
                        next_vel = vv
            # 60/100 mph print event.
            if next_speed_idx < len(speed_targets) and vel2 > speed_targets[next_speed_idx] and abs(speed_targets[next_speed_idx] - vel2) >= KV:
                vv = speed_targets[next_speed_idx]
                if base_vel < vv < next_vel:
                    next_vel = vv
            # Exact shift RPM event.
            if gear < v.n_gears - 1:
                sr = v.shift_rpms[gear] + shift_rpm_offset
                if sr > 0 and rpm2 > sr and abs(sr - rpm2) >= shift_tol:
                    vv = vel2 * sr / rpm2
                    if base_vel < vv < next_vel:
                        next_vel = vv

            if next_vel < vel2 - 1e-8:
                candidate_vel = next_vel
                candidate_revisions += 1
                continue

            # Candidate accepted.
            t, dist, vel, ag, rpm, wheel_rpm = time2, dist2, vel2, ag2, rpm2, wheel2
            growth = float(growth)
            launch_slip = slip2
            break
        else:
            raise RuntimeError("Legacy reference event revision failed to converge")

        event = "step"
        # Event bookkeeping at accepted state.
        if next_print_time <= t + TIME_TOL:
            next_print_time += time_print_inc
            event = "time_print"
        if next_speed_idx < len(speed_targets) and abs(vel - speed_targets[next_speed_idx]) <= KV:
            next_speed_idx += 1
            event = "speed_print"

        if shift_active:
            if abs(t - shift_end_time) <= TIME_TOL or t >= shift_end_time:
                shift_active = False
                event = "shift_complete"
        elif gear < v.n_gears - 1:
            sr = v.shift_rpms[gear] + shift_rpm_offset
            if sr > 0 and abs(rpm - sr) <= shift_tol:
                gear += 1
                shift_active = True
                shift_end_time = t + dt_shift
                event = "shift_start"

        append_row(event)

    trace = pd.DataFrame(rows)
    if timing.quarter_mile_s is None:
        raise RuntimeError("Legacy reference solver did not reach 1320 ft")

    return SimulationResult(
        trace=trace,
        timing=timing,
        diagnostics={
            "solver": "Quarter Pro v3.21 source-faithful reference",
            "weather_density_lbm_ft3": rho,
            "weather_hp_correction": hpc,
            "overhang_adjust_ft": ovradj,
            "static_front_weight_lb": static_front,
            "static_front_pct": 100.0 * static_front / v.weight_lb,
            "launch_accel_unclipped_g": ags_max_launch,
            "launch_traction_limit_g": amax,
            "time_print_increment_s": time_print_inc,
            "adaptive_rollout_step_max_s": tsmax,
            "inertia_iterations": inertia_iterations_total,
            "event_velocity_revisions": candidate_revisions,
            "traction_limited_steps": slip_count,
            "states": len(trace),
            "source_note": "Ported from QCommon/TIMESLIP.FRM; not yet executable-capture verified.",
        },
    )
