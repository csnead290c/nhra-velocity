from __future__ import annotations

"""Standardized drag-racing shift analysis.

The report is deliberately channel-name agnostic.  Canonical roles resolve the
source signals and the resulting rows are derived metadata, never source data.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any
import hashlib
import json

import numpy as np

from .display_data import channel_xy
from .models import TelemetryRun
from .workstation import resolve_channel


REPORT_VERSION = 1


@dataclass(frozen=True)
class ShiftEvent:
    shift: int
    time_s: float
    engine_rpm: float
    post_shift_rpm: float
    rpm_drop: float
    driveshaft_rpm: float | None = None
    clutch_rpm: float | None = None
    gear_before: float | None = None
    gear_after: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finite_xy(run: TelemetryRun, channel: str) -> tuple[np.ndarray, np.ndarray]:
    x, y = channel_xy(run, channel, "Time from Launch", 0.0)
    n = min(len(x), len(y))
    x = np.asarray(x[:n], dtype=float)
    y = np.asarray(y[:n], dtype=float)
    keep = np.isfinite(x) & np.isfinite(y)
    x, y = x[keep], y[keep]
    if len(x) > 1 and not np.all(np.diff(x) > 0):
        order = np.argsort(x, kind="mergesort")
        x, y = x[order], y[order]
        keep = np.r_[np.diff(x) > 0, True]
        x, y = x[keep], y[keep]
    return x, y


def _smooth(y: np.ndarray, points: int) -> np.ndarray:
    n = max(1, int(points))
    if n <= 1 or len(y) < n:
        return y.astype(float, copy=True)
    kernel = np.ones(n, dtype=float) / n
    return np.convolve(y, kernel, mode="same")


def _interp_channel(run: TelemetryRun, role: str, t: float) -> float | None:
    ch = resolve_channel(run, role)
    if not ch:
        return None
    x, y = _finite_xy(run, ch)
    if len(x) < 2 or t < x[0] or t > x[-1]:
        return None
    value = float(np.interp(float(t), x, y))
    return value if np.isfinite(value) else None


def _gear_transition_seeds(run: TelemetryRun, start_s: float, end_s: float) -> list[float]:
    channel = resolve_channel(run, "gear")
    if not channel:
        return []
    x, y = _finite_xy(run, channel)
    if len(x) < 3:
        return []
    rounded = np.rint(y)
    changed = np.flatnonzero(np.diff(rounded) > 0.5) + 1
    return [float(x[i]) for i in changed if start_s <= x[i] <= end_s]


def detect_shifts(
    run: TelemetryRun,
    *,
    start_s: float = 0.15,
    end_s: float | None = None,
    min_engine_rpm: float = 5000.0,
    min_drop_rpm: float = 250.0,
    min_spacing_s: float = 0.35,
    max_shifts: int = 8,
) -> list[ShiftEvent]:
    engine = resolve_channel(run, "engine_rpm")
    if not engine:
        raise ValueError("Shift report requires a mapped engine RPM channel.")
    t, rpm = _finite_xy(run, engine)
    if len(t) < 10:
        raise ValueError("Engine RPM channel has too few finite samples for shift analysis.")
    if end_s is None:
        timing = run.timing.to_dict()
        finish = timing.get("quarter_mile_s") or timing.get("thousand_ft_s")
        end_s = float(finish) + 0.35 if finish else min(float(t[-1]), 12.0)
    end_s = float(end_s)
    dt = float(np.nanmedian(np.diff(t))) if len(t) > 2 else 0.02
    if not np.isfinite(dt) or dt <= 0:
        dt = 0.02
    sm = _smooth(rpm, max(1, int(round(0.025 / dt))))

    seeds = _gear_transition_seeds(run, start_s, end_s)
    if not seeds:
        derivative = np.gradient(sm, t)
        mask = (t >= start_s) & (t <= end_s) & (sm >= min_engine_rpm)
        # Candidate down-slopes.  Group contiguous points and choose the most
        # negative derivative in each group; pre/post windows validate the drop.
        idx = np.flatnonzero(mask & (derivative < -8000.0))
        groups: list[np.ndarray] = []
        if len(idx):
            split = np.where(np.diff(idx) > max(1, int(round(0.06 / dt))))[0] + 1
            groups = [g for g in np.split(idx, split) if len(g)]
        seeds = [float(t[g[int(np.argmin(derivative[g]))]]) for g in groups]

    events: list[ShiftEvent] = []
    last_time = -1e9
    for seed in seeds:
        if seed - last_time < min_spacing_s:
            continue
        pre = (t >= seed - 0.18) & (t <= seed + 0.025)
        post = (t >= seed) & (t <= seed + 0.24)
        if not np.any(pre) or not np.any(post):
            continue
        pre_idx = np.flatnonzero(pre)
        i_peak = int(pre_idx[np.argmax(sm[pre])])
        shift_time = float(t[i_peak])
        pre_rpm = float(sm[i_peak])
        post_vals = sm[post]
        post_rpm = float(np.nanmin(post_vals)) if len(post_vals) else np.nan
        drop = pre_rpm - post_rpm
        if not np.isfinite(drop) or drop < min_drop_rpm or pre_rpm < min_engine_rpm:
            continue
        gear_ch = resolve_channel(run, "gear")
        gear_before = gear_after = None
        if gear_ch:
            gx, gy = _finite_xy(run, gear_ch)
            if len(gx) >= 2:
                gear_before = float(np.interp(shift_time - 0.05, gx, gy))
                gear_after = float(np.interp(shift_time + 0.12, gx, gy))
        events.append(ShiftEvent(
            shift=len(events) + 1,
            time_s=shift_time,
            engine_rpm=pre_rpm,
            post_shift_rpm=post_rpm,
            rpm_drop=drop,
            driveshaft_rpm=_interp_channel(run, "driveshaft_rpm", shift_time),
            clutch_rpm=_interp_channel(run, "clutch_rpm", shift_time),
            gear_before=gear_before,
            gear_after=gear_after,
        ))
        last_time = shift_time
        if len(events) >= int(max_shifts):
            break
    return events


def build_shift_report(run: TelemetryRun, *, profile: str = "pro_stock") -> dict[str, Any]:
    events = detect_shifts(run)
    source_roles = {}
    for role in ("engine_rpm", "driveshaft_rpm", "clutch_rpm", "gear"):
        src = resolve_channel(run, role)
        if src:
            source_roles[role] = src
    payload: dict[str, Any] = {
        "report_type": "pro_stock_shift" if profile == "pro_stock" else "shift",
        "report_version": REPORT_VERSION,
        "profile": str(profile),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_name": run.name,
        "source_file": run.metadata.get("source_file", ""),
        "source_roles": source_roles,
        "events": [event.to_dict() for event in events],
    }
    stable = dict(payload)
    stable.pop("generated_at_utc", None)
    payload["fingerprint_sha256"] = hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return payload


def attach_shift_report(run: TelemetryRun, *, profile: str = "pro_stock") -> dict[str, Any]:
    report = build_shift_report(run, profile=profile)
    derived = run.metadata.setdefault("derived_analyses", {})
    derived["pro_stock_shift_report" if profile == "pro_stock" else "shift_report"] = report
    return report


def compare_shift_reports(current: dict[str, Any], reference: dict[str, Any], *, rpm_alert: float = 150.0, time_alert_s: float = 0.08) -> list[dict[str, Any]]:
    a = list(current.get("events", []) or [])
    b = list(reference.get("events", []) or [])
    rows: list[dict[str, Any]] = []
    for i in range(max(len(a), len(b))):
        cur = a[i] if i < len(a) else {}
        ref = b[i] if i < len(b) else {}
        crpm = cur.get("engine_rpm"); rrpm = ref.get("engine_rpm")
        ct = cur.get("time_s"); rt = ref.get("time_s")
        drpm = float(crpm) - float(rrpm) if crpm is not None and rrpm is not None else None
        dt = float(ct) - float(rt) if ct is not None and rt is not None else None
        rows.append({
            "shift": i + 1,
            "current_rpm": crpm,
            "reference_rpm": rrpm,
            "delta_rpm": drpm,
            "current_time_s": ct,
            "reference_time_s": rt,
            "delta_time_s": dt,
            "alert": bool((drpm is not None and abs(drpm) >= rpm_alert) or (dt is not None and abs(dt) >= time_alert_s)),
        })
    return rows
