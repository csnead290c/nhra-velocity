from __future__ import annotations

"""Display-only drag-run fit windows.

A fit window is UI state only; it never modifies logger time, official timing,
or source telemetry.
"""

from dataclasses import dataclass
import numpy as np

from .models import TelemetryRun
from .telemetry import detect_drag_pass_window


@dataclass(frozen=True)
class RunFitWindow:
    x_min: float
    x_max: float
    basis: str


def fit_window(
    run: TelemetryRun,
    x_mode: str = "Time from Launch",
    *,
    finish_distance_ft: int = 1320,
    pre_margin_s: float = 0.50,
    post_margin_s: float = 0.75,
) -> RunFitWindow:
    mode = str(x_mode or "Time from Launch").strip().lower()
    finish_distance_ft = 1000 if int(finish_distance_ft) <= 1000 else 1320
    timing = run.timing.to_dict()
    official = timing.get("thousand_ft_s") if finish_distance_ft == 1000 else timing.get("quarter_mile_s")
    pass_window = None
    try:
        pass_window = detect_drag_pass_window(run)
    except Exception:
        pass

    if mode.startswith("normalized"):
        return RunFitWindow(-5.0, 105.0, "normalized run")
    if mode.startswith("distance"):
        return RunFitWindow(-25.0, float(finish_distance_ft) + 50.0, f"{finish_distance_ft} ft profile")
    if mode.startswith("sample"):
        if pass_window is not None:
            lo = max(0.0, float(pass_window.start_index))
            hi = max(lo + 1.0, float(pass_window.end_index))
            return RunFitWindow(lo, hi, "detected pass samples")
        n = max(1, len(run.data))
        return RunFitWindow(0.0, float(n - 1), "full sample range fallback")

    if official is not None and np.isfinite(float(official)) and float(official) > 0:
        duration = float(official)
        basis = f"official {finish_distance_ft} ft timing"
    elif pass_window is not None:
        # The speed/RPM peak is normally near the finish line and avoids showing
        # the long shutdown tail that made the old full-log Fit command useless.
        duration = max(0.5, float(pass_window.peak_time_s - pass_window.launch_time_s))
        basis = "detected drag pass peak"
    else:
        duration = 8.0 if finish_distance_ft == 1320 else 5.0
        basis = "class-profile fallback"

    if mode.startswith("logger") and pass_window is not None:
        launch = float(pass_window.launch_time_s)
        return RunFitWindow(launch - pre_margin_s, launch + duration + post_margin_s, basis)
    return RunFitWindow(-pre_margin_s, duration + post_margin_s, basis)
