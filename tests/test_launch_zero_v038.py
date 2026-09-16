import numpy as np
import pandas as pd

from runlab.display_data import channel_xy
from runlab.models import TelemetryRun
from runlab.telemetry import (
    clear_launch_time_override,
    detect_drag_pass_window,
    launch_time_override,
    set_launch_time_override,
)


def _run():
    t = np.arange(0.0, 8.01, 0.01)
    # Real pass starts near 1.0 s, but the speed sensor shows a small false
    # pre-launch movement beginning at 0.2 s. This mimics the kind of log where
    # automatic launch detection can legitimately need an engineer correction.
    speed = np.zeros_like(t)
    speed[(t >= 0.2) & (t < 1.0)] = 5.0
    after = t >= 1.0
    speed[after] = np.minimum(200.0, 5.0 + (t[after] - 1.0) * 35.0)
    rpm = np.where(t < 1.0, 2500.0, 6500.0 + (t - 1.0) * 400.0)
    data = pd.DataFrame({"Time": t, "Speed": speed, "RPM": rpm})
    return TelemetryRun(
        name="launch-zero-test",
        data=data,
        channel_map={"time_s": "Time", "speed_mph": "Speed", "engine_rpm": "RPM"},
        units={"Time": "s", "Speed": "mph", "RPM": "rpm"},
    )


def test_manual_launch_override_controls_pass_zero_and_waveform_x():
    run = _run()
    auto = detect_drag_pass_window(run)
    assert auto.launch_time_s < 1.0

    set_launch_time_override(run, 1.0)
    manual = detect_drag_pass_window(run)
    assert manual.confidence == "Manual"
    assert manual.method.startswith("manual launch zero")
    assert abs(manual.launch_time_s - 1.0) < 0.011
    assert abs(launch_time_override(run) - 1.0) < 1e-12

    x, _ = channel_xy(run, "RPM", "Time from Launch")
    idx = int(np.argmin(np.abs(run.data["Time"].to_numpy(float) - 1.0)))
    assert abs(float(x[idx])) < 0.011


def test_clear_launch_override_returns_to_auto_detection():
    run = _run()
    auto = detect_drag_pass_window(run).launch_time_s
    set_launch_time_override(run, 1.0)
    clear_launch_time_override(run)
    restored = detect_drag_pass_window(run)
    assert launch_time_override(run) is None
    assert restored.confidence != "Manual"
    assert abs(restored.launch_time_s - auto) < 1e-12


def test_manual_launch_override_keeps_raw_logger_time_unchanged():
    run = _run()
    raw_before = run.data["Time"].to_numpy(float).copy()
    set_launch_time_override(run, 1.25)
    x_logger, _ = channel_xy(run, "RPM", "Logger Time")
    np.testing.assert_allclose(x_logger, raw_before)
    np.testing.assert_allclose(run.data["Time"].to_numpy(float), raw_before)
