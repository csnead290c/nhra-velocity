from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Set

import numpy as np
import pandas as pd

from .inverse import FitRun
from .models import VehicleConfig


@dataclass
class EvidenceSummary:
    n_runs: int
    n_timing_runs: int
    n_telemetry_runs: int
    channels: Set[str]
    timing_fields: Set[str]
    condition_spread: Dict[str, float]


def _summary(runs: Sequence[FitRun]) -> EvidenceSummary:
    channels: Set[str] = set()
    timing_fields: Set[str] = set()
    n_timing = 0
    n_tel = 0
    temps, baros, winds, track_temps = [], [], [], []
    for run in runs:
        if run.timing.count():
            n_timing += 1
            for key, value in run.timing.to_dict().items():
                if value is not None:
                    timing_fields.add(key)
        if run.telemetry is not None:
            n_tel += 1
            channels.update(run.telemetry.channel_map.keys())
        temps.append(float(run.environment.temperature_f))
        baros.append(float(run.environment.barometer_inhg))
        winds.append(float(run.environment.wind_mph))
        track_temps.append(float(run.environment.track_temperature_f))
    def spread(vals: List[float]) -> float:
        return float(np.nanmax(vals) - np.nanmin(vals)) if vals else 0.0
    return EvidenceSummary(
        n_runs=len(runs), n_timing_runs=n_timing, n_telemetry_runs=n_tel,
        channels=channels, timing_fields=timing_fields,
        condition_spread={
            "temperature_f": spread(temps), "barometer_inhg": spread(baros),
            "wind_mph": spread(winds), "track_temperature_f": spread(track_temps),
        },
    )


def _status(score: int) -> str:
    if score >= 4:
        return "Strong"
    if score == 3:
        return "Good"
    if score == 2:
        return "Partial"
    if score == 1:
        return "Weak"
    return "Not observable"


def assess_observability(vehicle: VehicleConfig, runs: Sequence[FitRun], unknowns: Sequence[str]) -> pd.DataFrame:
    """Engineering preflight for an inverse fit.

    This is deliberately conservative.  It does not claim formal structural
    identifiability; it asks whether the uploaded measurements contain the kinds
    of independent evidence that physically constrain each selected parameter.
    """
    s = _summary(runs)
    unknown_set = set(unknowns)
    ch = s.channels
    tf = s.timing_fields
    has_speed = "speed_mph" in ch
    has_rpm = "engine_rpm" in ch
    has_ds = "driveshaft_rpm" in ch
    has_wheel = "wheel_speed_mph" in ch or "wheel_rpm" in ch
    has_g = "longitudinal_g" in ch
    has_gear = "gear" in ch
    has_60 = "sixty_ft_s" in tf
    has_330 = "three_thirty_ft_s" in tf
    has_660 = "eighth_mile_s" in tf
    has_660mph = "eighth_mile_mph" in tf
    has_1320 = "quarter_mile_s" in tf
    has_1320mph = "quarter_mile_mph" in tf
    multi = s.n_runs >= 2
    varied_air = s.condition_spread["temperature_f"] >= 15 or s.condition_spread["barometer_inhg"] >= 0.25 or s.condition_spread["wind_mph"] >= 5
    varied_track = s.condition_spread["track_temperature_f"] >= 20

    rows = []
    for name in unknowns:
        score = 0
        evidence: List[str] = []
        confounds: List[str] = []
        next_measurement = ""

        if name == "power_scale" or name.startswith("curve_node_"):
            if s.n_timing_runs and (has_660 or has_1320):
                score += 1; evidence.append("downtrack official ET")
            if has_speed:
                score += 1; evidence.append("speed trace")
            if has_rpm:
                score += 1; evidence.append("engine RPM trace")
            if multi:
                score += 1; evidence.append("multiple passes")
            if name.startswith("curve_node_") and not has_rpm:
                score = min(score, 1); confounds.append("curve shape needs RPM-domain evidence")
            if "weight_lb" in unknown_set:
                confounds.append("power and weight trade almost directly")
            if "efficiency_scale" in unknown_set or "final_drive_efficiency" in unknown_set:
                confounds.append("flywheel power and driveline loss are coupled")
            next_measurement = "Engine RPM + vehicle speed through the whole pass; keep race weight independently known."

        elif name == "cda_ft2":
            if has_1320mph or has_660mph:
                score += 2; evidence.append("official trap speed")
            if has_speed:
                score += 1; evidence.append("high-speed speed trace")
            if multi:
                score += 1; evidence.append("multiple passes")
            if varied_air:
                score += 1; evidence.append("meaningfully different air/wind")
            if "power_scale" in unknown_set and not multi:
                confounds.append("high-speed power and drag can trade off on one pass")
            next_measurement = "A clean high-speed speed trace plus passes in different air/wind, with power configuration unchanged."

        elif name == "cla_ft2":
            if has_g and has_speed:
                score += 2; evidence.append("acceleration + speed trace")
            if has_60 or has_330:
                score += 1; evidence.append("early incrementals")
            if multi and varied_track:
                score += 1; evidence.append("passes with different track temperature")
            confounds.append("downforce, traction and CG/load transfer all affect available tire force")
            next_measurement = "Independent aero/downforce information, or multiple runs where power is fixed and traction/load evidence is strong."

        elif name == "traction_index":
            if has_60: score += 1; evidence.append("60-ft")
            if has_g or has_speed: score += 1; evidence.append("early acceleration trace")
            if has_ds: score += 1; evidence.append("driveshaft RPM")
            if multi: score += 1; evidence.append("multiple launches")
            if varied_track: score += 1; evidence.append("track-temperature spread")
            if "cg_height_in" in unknown_set or "static_front_weight_lb" in unknown_set:
                confounds.append("traction and dynamic rear load can mimic each other")
            next_measurement = "High-rate driveshaft RPM or longitudinal G through the first 2 seconds, plus accurate 60-ft."

        elif name in {"stall_rpm", "slippage", "torque_multiplication"}:
            if has_rpm: score += 1; evidence.append("engine RPM")
            if has_ds: score += 2; evidence.append("driveshaft RPM")
            if has_speed: score += 1; evidence.append("vehicle speed")
            if has_60: score += 1; evidence.append("60-ft")
            if not (has_rpm and has_ds):
                confounds.append("input/output speed relationship is missing")
            next_measurement = "Engine RPM and driveshaft/input-shaft RPM at high sample rate from launch through lockup."

        elif name == "final_drive_ratio":
            if has_ds and has_speed: score += 3; evidence.append("driveshaft RPM + vehicle speed")
            if has_wheel and has_ds: score += 2; evidence.append("wheel + driveshaft relationship")
            if has_rpm and has_gear and has_speed: score += 1; evidence.append("engine RPM + gear + speed")
            if "tire_diameter_in" in unknown_set:
                confounds.append("final ratio and effective tire circumference are coupled")
            next_measurement = "Driveshaft RPM and GPS/true vehicle speed in a steady high gear, with measured tire circumference."

        elif name == "tire_diameter_in" or name == "tire_growth_scale":
            if has_ds and has_speed: score += 3; evidence.append("driveshaft RPM + speed")
            if has_wheel and has_speed: score += 2; evidence.append("wheel speed + vehicle speed")
            if has_1320mph: score += 1; evidence.append("finish-line trap")
            if name == "tire_growth_scale" and not has_speed:
                score = min(score, 1)
            if "final_drive_ratio" in unknown_set:
                confounds.append("tire circumference and final-drive ratio are coupled")
            next_measurement = "Measured rollout/circumference at rest plus driveshaft RPM and GPS speed at high speed."

        elif name == "weight_lb":
            if has_g or has_speed: score += 1; evidence.append("acceleration evidence")
            if s.n_timing_runs: score += 1; evidence.append("official timing")
            if multi: score += 1; evidence.append("multiple passes")
            if "power_scale" in unknown_set or any(x.startswith("curve_node_") for x in unknown_set):
                score = min(score, 1); confounds.append("mass and power are fundamentally confounded without an independent anchor")
            next_measurement = "Scale the vehicle. Race weight is cheap to measure and should normally be fixed rather than inferred."

        elif name in {"efficiency_scale", "final_drive_efficiency"}:
            if has_rpm and has_ds and has_speed: score += 2; evidence.append("input/output speed + vehicle speed")
            if multi: score += 1; evidence.append("multiple passes")
            confounds.append("speed-only data cannot cleanly separate mechanical efficiency from engine power")
            if "power_scale" in unknown_set: confounds.append("power scale selected simultaneously")
            next_measurement = "Known engine power/torque or torque measurement on one side of the driveline; otherwise fix efficiency to a credible prior."

        elif name in {"cg_height_in", "static_front_weight_lb"}:
            if has_g: score += 2; evidence.append("longitudinal G")
            if has_60: score += 1; evidence.append("60-ft")
            if has_ds: score += 1; evidence.append("launch driveshaft RPM")
            if multi: score += 1; evidence.append("multiple launches")
            if "traction_index" in unknown_set: confounds.append("load transfer and tire-force limit are strongly coupled")
            next_measurement = "Static axle weights / CG-height test. Those measurements are far stronger than trying to infer chassis geometry from ET."

        elif name in {"front_overhang_in", "rollout_in"}:
            if has_60: score += 2; evidence.append("60-ft timing")
            if has_speed: score += 1; evidence.append("launch speed trace")
            if s.n_timing_runs: score += 1; evidence.append("official timing system")
            if "front_overhang_in" in unknown_set and "rollout_in" in unknown_set:
                confounds.append("both alter early timing-beam geometry")
            next_measurement = "Physically measure rollout and front overhang; use inverse fitting mainly as a consistency check."

        elif name.startswith("gear_ratio_"):
            if has_rpm and has_ds: score += 3; evidence.append("engine RPM + driveshaft RPM")
            if has_gear: score += 1; evidence.append("logged gear")
            if has_speed: score += 1; evidence.append("vehicle speed")
            if "slippage" in unknown_set: confounds.append("ratio and slip are coupled during non-locked portions")
            next_measurement = "Engine RPM and driveshaft RPM in each gear; logged gear channel makes this almost direct."

        elif name.startswith("shift_rpm_") or name == "shift_rpm_offset":
            if has_rpm: score += 3; evidence.append("engine RPM")
            if has_gear or has_ds: score += 1; evidence.append("gear/shaft evidence")
            if multi: score += 1; evidence.append("multiple shifts")
            next_measurement = "Engine RPM with a gear or shift-state channel."

        else:
            if s.n_timing_runs: score += 1; evidence.append("official timing")
            if s.n_telemetry_runs: score += 1; evidence.append("telemetry")
            next_measurement = "Add a direct measurement sensitive to this parameter."

        score = max(0, min(5, score))
        rows.append({
            "parameter": name,
            "preflight": _status(score),
            "score_0_to_5": score,
            "evidence_present": "; ".join(evidence) if evidence else "none",
            "important_confounds": "; ".join(confounds) if confounds else "none obvious from selected unknowns",
            "best_next_measurement": next_measurement,
        })
    return pd.DataFrame(rows)


def summarize_observability(table: pd.DataFrame) -> str:
    if table is None or table.empty:
        return "No parameters selected."
    weak = table[table["score_0_to_5"] <= 1]
    partial = table[table["score_0_to_5"] == 2]
    if not weak.empty:
        names = ", ".join(weak["parameter"].astype(str))
        return f"Preflight warning: {names} are weak or not observable with the current measurements. The optimizer can still run, but treat those estimates as priors/search results rather than measurements."
    if not partial.empty:
        names = ", ".join(partial["parameter"].astype(str))
        return f"Preflight: usable, but {names} have only partial independent evidence. More telemetry or another run should tighten them."
    return "Preflight: the selected unknowns have good/strong supporting evidence in the supplied data. Correlation can still emerge during the numerical fit."
