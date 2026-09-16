from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6 import QtWidgets

from desktop import CursorBus, SessionStore, WaveformDisplay, Worksheet
from runlab.display_data import channel_xy
from runlab.models import Environment, TelemetryRun, TimingData
from runlab.telemetry import detect_drag_pass_window, launch_time_override


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _run(name="ui-smoke"):
    t = np.arange(0.0, 8.01, 0.01)
    speed = np.zeros_like(t)
    moving = t >= 0.8
    speed[moving] = np.minimum(205.0, (t[moving] - 0.8) * 34.0)
    rpm = np.where(t < 0.8, 6200.0, 7600.0 + 250.0 * np.sin((t - 0.8) * 5.0) + speed * 10.0)
    driveshaft = speed * 32.0
    throttle = np.where((t >= 0.4) & (t < 7.0), 100.0, 0.0)
    gear = np.select([t < 1.4, t < 2.3, t < 3.2, t < 4.2, t < 5.3], [1, 2, 3, 4, 5], default=6)
    long_g = np.gradient(speed * 0.44704, t) / 9.80665
    data = pd.DataFrame({
        "Time": t,
        "RPM": rpm,
        "Driveshaft": driveshaft,
        "Speed": speed,
        "Throttle": throttle,
        "Gear": gear,
        "Long G": long_g,
        "Lambda": 1.0 + 0.03 * np.sin(t * 3.0),
    })
    return TelemetryRun(
        name=name,
        data=data,
        channel_map={
            "time_s": "Time",
            "engine_rpm": "RPM",
            "driveshaft_rpm": "Driveshaft",
            "speed_mph": "Speed",
            "throttle_pct": "Throttle",
            "gear": "Gear",
            "longitudinal_g": "Long G",
            "lambda": "Lambda",
        },
        units={"Time": "s", "RPM": "rpm", "Driveshaft": "rpm", "Speed": "mph", "Throttle": "%", "Gear": "", "Long G": "g", "Lambda": "lambda"},
        timing=TimingData(sixty_ft_s=1.08, three_thirty_ft_s=2.86, eighth_mile_s=4.35, eighth_mile_mph=162.0, thousand_ft_s=5.68, quarter_mile_s=6.80, quarter_mile_mph=199.0),
        environment=Environment(),
    )


def test_waveform_stats_remove_and_rezero_are_live():
    app = _app()
    store = SessionStore(); cursors = CursorBus(); run = _run()
    handle = store.add("smoke.csv", run, activate=True)
    wave = WaveformDisplay(store, cursors)
    wave.channels = ["RPM", "Driveshaft", "Speed"]
    wave.refresh(); app.processEvents()

    wave.reference_visible = True
    cursors.a = 0.25; cursors.x = 1.25
    wave._set_readout_stat("show_stat_min", True)
    wave._set_readout_stat("show_stat_max", True)
    wave._set_readout_stat("show_stat_mean", True)
    wave._set_readout_stat("show_stat_std", True)
    wave._refresh_readout(); app.processEvents()
    assert wave.show_stat_min and wave.show_stat_max and wave.show_stat_mean and wave.show_stat_std
    summary = wave._data_cache.region_summary(run, "RPM", cursors.a, cursors.x, wave.x_mode, handle.time_alignment_s)
    assert summary["count"] > 10
    assert summary["max"] >= summary["mean"] >= summary["min"]

    wave.remove_channel("Speed")
    assert "Speed" not in wave.channels

    auto_launch = float(detect_drag_pass_window(run).launch_time_s)
    handle.time_alignment_s = 0.20
    cursors.a = 0.30; cursors.b = 1.00; cursors.x = 0.70
    expected = auto_launch + 0.70 - 0.20
    wave._set_launch_zero_from_cursor(); app.processEvents()
    first = float(launch_time_override(run))
    assert abs(first - expected) <= 0.011
    assert abs(handle.time_alignment_s) < 1e-12
    assert abs(cursors.x) < 1e-12
    x, _ = channel_xy(run, "RPM", "Time from Launch", 0.0)
    idx = int(np.argmin(np.abs(run.data["Time"].to_numpy(float) - first)))
    assert abs(float(x[idx])) <= 0.011

    cursors.x = 0.20
    old_effective = float(detect_drag_pass_window(run).launch_time_s)
    wave._set_launch_zero_from_cursor(); app.processEvents()
    second = float(launch_time_override(run))
    assert abs(second - (old_effective + 0.20)) <= 0.011
    assert abs(cursors.x) < 1e-12


def test_quick_analysis_displays_construct_and_refresh():
    app = _app()
    store = SessionStore(); cursors = CursorBus(); run = _run("analysis")
    store.add("analysis.csv", run, activate=True)
    sheet = Worksheet(store, cursors)
    sheet.waveforms[0].channels = ["RPM", "Driveshaft", "Speed", "Throttle", "Long G"]
    sheet.waveforms[0].refresh()
    cursors.a = 0.5; cursors.x = 2.0

    docks = [
        sheet.add_region_stats(),
        sheet.add_histogram(),
        sheet.add_scatter(),
        sheet.add_spectrum(),
        sheet.add_load_map(),
        sheet.add_sensor_health(),
    ]
    for dock in docks:
        widget = dock.widget()
        if hasattr(widget, "refresh"):
            widget.refresh()
        app.processEvents()
    stats = docks[0].widget()
    assert stats.rowCount() == len(sheet.waveforms[0].channels)


def test_all_daily_analysis_displays_construct_with_realistic_context():
    app = _app()
    store = SessionStore(); cursors = CursorBus()
    main = _run("main-analysis")
    ref = _run("reference-analysis")
    h1 = store.add("main.csv", main, activate=True)
    h2 = store.add("ref.csv", ref, activate=False)
    h2.role = "reference"
    sheet = Worksheet(store, cursors)
    sheet.waveforms[0].channels = ["RPM", "Driveshaft", "Speed", "Throttle", "Long G"]
    sheet.waveforms[0].refresh()
    cursors.a = 0.6; cursors.x = 2.1

    factories = [
        sheet.add_values,
        sheet.add_gauge,
        sheet.add_region_stats,
        sheet.add_scatter,
        sheet.add_histogram,
        sheet.add_spectrum,
        sheet.add_load_map,
        sheet.add_metric_report,
        sheet.add_strip_model,
        sheet.add_envelope,
        sheet.add_delta,
        sheet.add_audit,
        sheet.add_sensor_health,
        sheet.add_knowledge,
        sheet.add_events,
        sheet.add_alarm_status,
        sheet.add_comparison_summary,
        sheet.add_notepad,
    ]
    docks = []
    for factory in factories:
        dock = factory(); docks.append(dock)
        widget = dock.widget()
        if hasattr(widget, "refresh"):
            widget.refresh()
        app.processEvents()
        assert dock is not None and widget is not None

    # Construction should not mutate the authoritative source sessions.
    assert store.active is h1
    assert h2.role == "reference"
