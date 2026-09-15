from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple, List

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter

from .models import Environment, TelemetryRun, VehicleConfig
from .weather import quarterpro_weather
from .physics import GC, Z5, CMU, CMUK, KP21, KP22, _relative_wind_fps, _tire_state, _tire_slip_ratio
from .telemetry import detect_drag_pass_window
from .audit import reconstruction_blockers


@dataclass
class ReconstructionResult:
    samples: pd.DataFrame
    dyno_curve: pd.DataFrame
    gear_summary: pd.DataFrame
    diagnostics: Dict[str, Any]


def _finite_xy(t: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    mask = np.isfinite(t) & np.isfinite(y)
    t, y = t[mask], y[mask]
    if len(t) == 0:
        return t, y
    order = np.argsort(t)
    t, y = t[order], y[order]
    # Drop duplicate timestamps.
    keep = np.r_[True, np.diff(t) > 1e-9]
    return t[keep], y[keep]


def _smooth_derivative(t: np.ndarray, y: np.ndarray, smoothing_s: float = 0.12) -> Tuple[np.ndarray, np.ndarray]:
    if len(t) < 5:
        return y, np.gradient(y, t) if len(t) > 1 else np.zeros_like(y)
    dt = np.nanmedian(np.diff(t))
    if not np.isfinite(dt) or dt <= 0:
        return y, np.gradient(y, t)
    window = int(round(smoothing_s / dt))
    window = max(5, window)
    if window % 2 == 0:
        window += 1
    max_window = len(y) if len(y) % 2 == 1 else len(y) - 1
    window = min(window, max_window)
    if window < 5:
        return y, np.gradient(y, t)
    poly = min(3, window - 2)
    smooth = savgol_filter(y, window_length=window, polyorder=poly, mode="interp")
    deriv = np.gradient(smooth, t)
    return smooth, deriv


def _launch_index(run: TelemetryRun) -> int:
    return int(detect_drag_pass_window(run).launch_index)


def _assign_gears(
    run: TelemetryRun,
    vehicle: VehicleConfig,
    rpm: np.ndarray,
    dsrpm: np.ndarray,
) -> np.ndarray:
    m, df = run.channel_map, run.data
    if "gear" in m:
        raw = pd.to_numeric(df[m["gear"]], errors="coerce").to_numpy(float)
        if len(raw) == len(rpm):
            out = np.where(np.isfinite(raw), np.rint(raw), np.nan)
            valid = (out >= 1) & (out <= vehicle.n_gears)
            if valid.sum() > max(10, int(.5 * len(out))):
                # Fill gaps by nearest valid sample.
                s = pd.Series(out).where(valid).ffill().bfill()
                return s.to_numpy(int)

    # Infer gear from engine/driveshaft speed ratio. Ratio ~= trans ratio * slip.
    ratios = np.asarray(vehicle.gear_ratios, dtype=float)
    observed = np.divide(rpm, dsrpm, out=np.full_like(rpm, np.nan), where=np.abs(dsrpm) > 50)
    out = np.ones(len(rpm), dtype=int)
    for i, r in enumerate(observed):
        if not np.isfinite(r):
            out[i] = out[i - 1] if i else 1
            continue
        errors = np.abs(ratios * vehicle.slippage - r)
        out[i] = int(np.argmin(errors)) + 1
    return out


def reconstruct_delivered_power(
    run: TelemetryRun,
    vehicle: VehicleConfig,
    env: Optional[Environment] = None,
    *,
    smoothing_s: float = 0.12,
    rpm_bin: float = 250.0,
    min_throttle_pct: float = 80.0,
) -> ReconstructionResult:
    """Back-calculate apparent delivered engine torque/HP from a telemetry pass.

    Required canonical channels: time + vehicle speed + engine RPM. Driveshaft
    RPM and gear improve ratio/slip diagnostics but are not strictly required.

    The result is *delivered/apparent* engine torque based on the supplied
    driveline assumptions. Converter torque multiplication, unmeasured clutch
    losses and tire spin remain confounded unless separately measured/fitted.
    """
    v = vehicle.normalized()
    env = env or run.environment
    blockers = reconstruction_blockers(run)
    if blockers:
        raise ValueError(
            "Power reconstruction blocked by telemetry audit:\n- " + "\n- ".join(blockers)
            + "\nCorrect channel mappings/units before derivative-based reconstruction."
        )
    m, df = run.channel_map, run.data
    required = ["time_s", "speed_mph", "engine_rpm"]
    missing = [x for x in required if x not in m]
    if missing:
        raise ValueError(f"Run reconstruction requires mapped channels: {', '.join(required)}. Missing: {', '.join(missing)}")

    t_raw = pd.to_numeric(df[m["time_s"]], errors="coerce").to_numpy(float)
    sp_raw = pd.to_numeric(df[m["speed_mph"]], errors="coerce").to_numpy(float)
    rpm_raw = pd.to_numeric(df[m["engine_rpm"]], errors="coerce").to_numpy(float)
    pass_window = detect_drag_pass_window(run)
    launch = int(pass_window.launch_index)
    if launch >= len(t_raw): launch = 0
    t0 = t_raw[launch] if np.isfinite(t_raw[launch]) else np.nanmin(t_raw)
    t = t_raw - t0
    powered_end_rel_s = max(0.0, float(pass_window.peak_time_s - t0) + 0.35)

    # Resample all required channels to a clean common time basis using valid time samples.
    mask_t = np.isfinite(t)
    t_valid = t[mask_t]
    if len(t_valid) < 10:
        raise ValueError("Not enough valid timestamp samples for reconstruction.")
    order = np.argsort(t_valid)
    t_valid = t_valid[order]
    # unique time grid from original logger samples
    uniq, uniq_idx = np.unique(t_valid, return_index=True)
    t_grid = uniq

    def interp_channel(arr: np.ndarray) -> np.ndarray:
        arr2 = arr[mask_t][order][uniq_idx]
        good = np.isfinite(arr2)
        if good.sum() < 2:
            return np.full(len(t_grid), np.nan)
        return np.interp(t_grid, t_grid[good], arr2[good])

    speed_mph = interp_channel(sp_raw)
    rpm = interp_channel(rpm_raw)
    speed_fps = speed_mph / Z5
    speed_smooth, accel_fps2 = _smooth_derivative(t_grid, speed_fps, smoothing_s=smoothing_s)
    accel_g = accel_fps2 / GC

    # Use recorder longitudinal G when available as an additional reference, but
    # keep speed-derived G for the force balance because it is kinematically consistent.
    logger_g = np.full(len(t_grid), np.nan)
    if "longitudinal_g" in m:
        logger_g = interp_channel(pd.to_numeric(df[m["longitudinal_g"]], errors="coerce").to_numpy(float))

    # Distance from numerical integration of the smoothed speed.
    dt = np.diff(t_grid, prepend=t_grid[0])
    dt[0] = 0.0
    distance_ft = np.cumsum(np.maximum(0.0, speed_smooth) * np.maximum(0.0, dt))

    # Driveshaft RPM: use measured if available, otherwise estimate from tire circumference and final drive.
    if "driveshaft_rpm" in m:
        dsrpm = interp_channel(pd.to_numeric(df[m["driveshaft_rpm"]], errors="coerce").to_numpy(float))
    else:
        dsrpm = np.zeros(len(t_grid))
        for i in range(len(t_grid)):
            _, cir, _ = _tire_state(speed_smooth[i], accel_g[i], v)
            wheel_rpm = speed_smooth[i] * 60.0 / max(cir, 1e-6)
            dsrpm[i] = wheel_rpm * v.final_drive_ratio

    # Gear must use the resampled series. Create a temporary telemetry view on t_grid when raw gear exists.
    if "gear" in m:
        gear_vals = interp_channel(pd.to_numeric(df[m["gear"]], errors="coerce").to_numpy(float))
        gears = np.clip(np.rint(gear_vals), 1, v.n_gears).astype(int)
    else:
        ratios = np.asarray(v.gear_ratios, dtype=float)
        observed = np.divide(rpm, dsrpm, out=np.full_like(rpm, np.nan), where=np.abs(dsrpm) > 50)
        gears = np.ones(len(rpm), dtype=int)
        for i, rr in enumerate(observed):
            if np.isfinite(rr):
                gears[i] = int(np.argmin(np.abs(ratios * v.slippage - rr))) + 1
            elif i:
                gears[i] = gears[i-1]

    throttle = np.full(len(t_grid), 100.0)
    if "throttle_pct" in m:
        throttle = interp_channel(pd.to_numeric(df[m["throttle_pct"]], errors="coerce").to_numpy(float))

    wx = quarterpro_weather(env)
    aero_force = np.zeros(len(t_grid))
    rolling_force = np.zeros(len(t_grid))
    total_drag = np.zeros(len(t_grid))
    drive_force = np.zeros(len(t_grid))
    wheel_torque = np.zeros(len(t_grid))
    engine_torque = np.zeros(len(t_grid))
    hp = np.zeros(len(t_grid))
    hp_no_inertia = np.zeros(len(t_grid))
    tire_radius_ft = np.zeros(len(t_grid))
    tire_slip = np.ones(len(t_grid))
    power_transfer = np.ones(len(t_grid))
    engine_inertia_hp = np.zeros(len(t_grid))
    chassis_inertia_hp = np.zeros(len(t_grid))
    trans_ratio = np.zeros(len(t_grid))
    ratio_observed = np.divide(rpm, dsrpm, out=np.full_like(rpm, np.nan), where=np.abs(dsrpm) > 50)

    # Rotating inertia is not optional when reconstructing a dyno curve from an
    # accelerating pass.  Quarter Pro explicitly subtracts engine and chassis
    # acceleration power in the forward model; the inverse balance must add it
    # back.  Smooth the RPM channels before differentiating to avoid turning
    # quantization/noise into hundreds of fake horsepower.
    rpm_smooth, rpm_rate = _smooth_derivative(t_grid, rpm, smoothing_s=max(0.06, smoothing_s))
    wheel_rpm_raw = dsrpm / max(v.final_drive_ratio, 1e-9)
    wheel_rpm_smooth, wheel_rpm_rate = _smooth_derivative(t_grid, wheel_rpm_raw, smoothing_s=max(0.06, smoothing_s))

    for i in range(len(t_grid)):
        growth, cir, radius_in = _tire_state(speed_smooth[i], accel_g[i], v)
        radius_ft = radius_in / 12.0
        tire_radius_ft[i] = radius_ft
        tire_slip[i] = _tire_slip_ratio(distance_ft[i], v, env)

        wind = _relative_wind_fps(speed_smooth[i], env)
        q = wx.density_lbm_ft3 * wind * wind / (2.0 * GC)
        if v.body_style == 8:
            area = v.frontal_area_ft2 + ((growth - 1.0) * v.tire_diameter_in / 2.0) * v.tire_width_in / 144.0
        else:
            area = v.frontal_area_ft2 + ((growth - 1.0) * v.tire_diameter_in / 2.0) * (2.0 * v.tire_width_in) / 144.0
        downforce = v.weight_lb + v.lift_coefficient * area * q
        cmu = max(0.0, CMU - max(0.0, distance_ft[i]) / 1320.0 * CMUK)
        roll = cmu * downforce + 0.0001 * downforce * speed_mph[i]
        aero = v.drag_coefficient * area * q
        aero_force[i] = aero
        rolling_force[i] = roll
        total_drag[i] = aero + roll
        drive_force[i] = v.weight_lb * accel_g[i] + total_drag[i]
        wheel_torque[i] = drive_force[i] * radius_ft

        gi = max(1, min(v.n_gears, int(gears[i]))) - 1
        gr = v.gear_ratios[gi]
        geff = v.gear_efficiencies[gi]
        trans_ratio[i] = gr
        lock_rpm = dsrpm[i] * gr

        # Reconstruct the same power-transfer term used by QPro.  For a clutch
        # it is simply lock RPM / engine RPM.  For a converter, torque
        # multiplication can make delivered power exceed the raw speed ratio
        # while it is loose; the multiplier decays toward 1 as it couples.
        if rpm_smooth[i] > 1 and np.isfinite(lock_rpm):
            if v.transmission_type == "converter" and (gi == 0 or not v.lockup_after_first):
                slip_ratio = np.clip(v.slippage * lock_rpm / max(v.stall_rpm, 1.0), 0.0, 1.5)
                tq_mult_eff = v.torque_multiplication - (v.torque_multiplication - 1.0) * np.clip(slip_ratio, 0.0, 1.0)
                power_transfer[i] = np.clip(tq_mult_eff * lock_rpm / rpm_smooth[i], 0.05, 1.0)
            else:
                power_transfer[i] = np.clip(lock_rpm / rpm_smooth[i], 0.05, 1.0)

        # QPro PMI units are lb-in-sec^2.  In derivative form its incremental
        # formula becomes I * RPM * dRPM/dt * (2pi/60)^2 / (12*550).
        conv = (2.0 * np.pi / 60.0) ** 2 / (12.0 * 550.0)
        eihp = v.engine_pmi * rpm_smooth[i] * rpm_rate[i] * conv
        if eihp < 0:
            eihp *= KP22 if v.transmission_type == "converter" else KP21
        engine_inertia_hp[i] = eihp

        chassis_pmi = v.tires_pmi + v.transmission_pmi * v.final_drive_ratio ** 2 * gr ** 2
        cihp = chassis_pmi * wheel_rpm_smooth[i] * wheel_rpm_rate[i] * conv
        chassis_inertia_hp[i] = max(0.0, cihp)

        # Translational + road-load power is what must arrive after the tire
        # slip term.  Reverse QPro's power path to estimate flywheel power.
        net_accel_hp = v.weight_lb * accel_g[i] * speed_smooth[i] / 550.0
        drag_hp = total_drag[i] * speed_smooth[i] / 550.0
        downstream_hp = net_accel_hp + drag_hp
        denom = max(0.05, power_transfer[i] * geff * v.final_drive_efficiency)
        base_hp = (downstream_hp * tire_slip[i]) / denom
        hp_no_inertia[i] = base_hp
        hp[i] = (downstream_hp * tire_slip[i] + chassis_inertia_hp[i]) / denom + engine_inertia_hp[i]
        engine_torque[i] = hp[i] * 5252.113 / max(rpm_smooth[i], 1.0)

    # Catastrophic unit/mapping guard.  A drag-racing engine can legitimately be
    # very powerful, so this threshold is intentionally generous. Values beyond
    # it almost always indicate a broken timebase/channel/unit contract.
    finite_hp = hp[np.isfinite(hp)]
    if len(finite_hp):
        hp_q99 = float(np.quantile(np.abs(finite_hp), 0.99))
        if hp_q99 > 100000.0:
            raise ValueError(
                f"Reconstruction produced an implausible 99th-percentile power of {hp_q99:,.0f} hp. "
                "The result has been rejected instead of displayed. Check time units, vehicle-speed mapping, "
                "RPM mapping, gearing and rotational-inertia inputs."
            )

    # Shift periods and very loose launch regions are intentionally excluded
    # from the dyno binning. They remain in the sample table for diagnosis.
    gear_change = np.r_[False, np.diff(gears) != 0]
    shift_guard = pd.Series(gear_change).rolling(window=7, center=True, min_periods=1).max().to_numpy(bool)
    valid = (
        np.isfinite(rpm_smooth) & np.isfinite(hp) & np.isfinite(engine_torque)
        & (rpm_smooth > 500) & (throttle >= min_throttle_pct)
        & (t_grid >= 0) & (t_grid <= powered_end_rel_s) & (speed_mph >= 10)
        & (engine_torque > 0) & (hp > 0)
        & (power_transfer >= 0.45) & (~shift_guard)
    )

    samples = pd.DataFrame({
        "time_s": t_grid,
        "distance_ft": distance_ft,
        "speed_mph": speed_mph,
        "speed_smooth_mph": speed_smooth * Z5,
        "accel_g_speed": accel_g,
        "accel_g_logger": logger_g,
        "engine_rpm": rpm,
        "engine_rpm_smooth": rpm_smooth,
        "engine_rpm_rate": rpm_rate,
        "driveshaft_rpm": dsrpm,
        "wheel_rpm_smooth": wheel_rpm_smooth,
        "observed_engine_to_dshaft_ratio": ratio_observed,
        "gear": gears,
        "trans_ratio": trans_ratio,
        "throttle_pct": throttle,
        "tire_slip_model": tire_slip,
        "power_transfer_fraction": power_transfer,
        "aero_drag_lb": aero_force,
        "rolling_drag_lb": rolling_force,
        "total_drag_lb": total_drag,
        "required_drive_force_lb": drive_force,
        "wheel_torque_lbft": wheel_torque,
        "engine_inertia_hp": engine_inertia_hp,
        "chassis_inertia_hp": chassis_inertia_hp,
        "apparent_engine_hp_no_inertia": hp_no_inertia,
        "apparent_engine_torque_lbft": engine_torque,
        "apparent_engine_hp": hp,
        "valid_for_dyno": valid,
    })

    usable = samples[valid].copy()
    if usable.empty:
        dyno = pd.DataFrame(columns=["rpm", "hp_median", "hp_p10", "hp_p90", "torque_median", "samples"])
    else:
        usable["rpm_bin"] = (np.round(usable["engine_rpm_smooth"] / rpm_bin) * rpm_bin).astype(int)
        grouped = usable.groupby("rpm_bin")
        dyno = grouped.agg(
            hp_median=("apparent_engine_hp", "median"),
            hp_p10=("apparent_engine_hp", lambda x: np.percentile(x, 10)),
            hp_p90=("apparent_engine_hp", lambda x: np.percentile(x, 90)),
            torque_median=("apparent_engine_torque_lbft", "median"),
            samples=("apparent_engine_hp", "size"),
        ).reset_index().rename(columns={"rpm_bin": "rpm"})
        dyno = dyno[dyno["samples"] >= 2].reset_index(drop=True)

    gear_rows: List[Dict[str, Any]] = []
    for g in range(1, v.n_gears + 1):
        sel = samples[
            (samples["gear"] == g)
            & np.isfinite(samples["observed_engine_to_dshaft_ratio"])
            & (samples["driveshaft_rpm"] > 300)
            & (samples["time_s"] >= 0.0)
            & (samples["time_s"] <= powered_end_rel_s)
            & (samples["speed_mph"] >= 5.0)
        ]
        if sel.empty:
            continue
        obs = sel["observed_engine_to_dshaft_ratio"].to_numpy(float)
        gear_rows.append({
            "gear": g,
            "configured_ratio": v.gear_ratios[g-1],
            "observed_engine/ds_ratio_median": float(np.median(obs)),
            "observed_ratio_p10": float(np.percentile(obs, 10)),
            "observed_ratio_p90": float(np.percentile(obs, 90)),
            "implied_slippage_vs_config": float(np.median(obs) / max(v.gear_ratios[g-1], 1e-9)),
            "samples": len(obs),
        })
    gear_summary = pd.DataFrame(gear_rows)

    diagnostics = {
        "launch_time_in_log_s": float(t0),
        "pass_detection_method": pass_window.method,
        "pass_detection_confidence": pass_window.confidence,
        "detected_peak_speed_mph": pass_window.peak_speed_mph,
        "detected_peak_time_in_log_s": pass_window.peak_time_s,
        "powered_analysis_end_after_launch_s": powered_end_rel_s,
        "usable_dyno_samples": int(valid.sum()),
        "total_samples": int(len(samples)),
        "smoothing_s": float(smoothing_s),
        "rpm_bin": float(rpm_bin),
        "weather_density_lbm_ft3": wx.density_lbm_ft3,
        "weather_hp_correction": wx.horsepower_correction,
        "median_engine_inertia_hp": float(np.nanmedian(engine_inertia_hp[valid])) if valid.any() else np.nan,
        "median_chassis_inertia_hp": float(np.nanmedian(chassis_inertia_hp[valid])) if valid.any() else np.nan,
        "median_power_transfer_fraction": float(np.nanmedian(power_transfer[valid])) if valid.any() else np.nan,
        "warning": "Apparent flywheel power reverses the Quarter Pro road-load, tire-slip, driveline-efficiency and rotating-inertia power path. Converter/clutch behavior and sensor bias can still remain coupled unless independently constrained.",
    }
    return ReconstructionResult(samples=samples, dyno_curve=dyno, gear_summary=gear_summary, diagnostics=diagnostics)
