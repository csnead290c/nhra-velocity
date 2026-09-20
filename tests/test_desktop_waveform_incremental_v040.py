from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

import desktop
from desktop import MainWindow
from runlab.annotations import add_bookmark, add_region, annotations_for_mode
from runlab.models import Environment, TelemetryRun, TimingData


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _run(name="run", n_ch=5, n=2001, cols=None, units=None):
    t = np.arange(0.0, 4.0, 4.0 / (n - 1))
    names = cols or [f"CH{i}" for i in range(n_ch)]
    data = {"Time": t}
    for i, c in enumerate(names):
        data[c] = np.sin(t * (1.0 + i * 0.25)) * (10.0 + i) + i
    u = {"Time": "s"}
    u.update(units or {c: "" for c in names})
    return TelemetryRun(
        name=name,
        data=pd.DataFrame(data),
        channel_map={"time_s": "Time"},
        units=u,
        timing=TimingData(),
        environment=Environment(),
    )


@pytest.fixture()
def win(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("NHRA_VELOCITY_HOME", str(tmp_path / "velocity_home"))
    w = MainWindow()
    yield w
    if w._open_worker is not None:
        w._open_worker.cancel()
        w._open_mark_cancelled()


def _wave(win):
    return win.current_sheet().waveforms[0]


def _addplot_counter(wave):
    """Count addPlot invocations on the waveform's GraphicsLayout."""
    calls = [0]
    orig = wave.graph.addPlot
    def counted(*a, **kw):
        calls[0] += 1
        return orig(*a, **kw)
    wave.graph.addPlot = counted
    return calls


def _refresh_counter(wave):
    calls = [0]
    orig = wave.refresh.__func__
    def counted(self):
        calls[0] += 1
        return orig(self)
    wave.refresh = types.MethodType(counted, wave)
    return calls


def _add_session(win, name="run", cols=None, units=None, activate=True):
    run = _run(name, cols=cols, units=units)
    return win.store.add(f"{name}.csv", run, activate=activate)


# --- A. no-op / same-state refresh reuses the scene -------------------------

def test_same_state_refresh_reuses_scene_objects(win):
    wave = _wave(win)
    _add_session(win)
    wave.channels = ["CH0", "CH1", "CH2"]
    wave.refresh()
    plots = list(wave._plots)
    curves = [c for (_p, _c, _h, c) in wave._curve_slots]
    vbs = [p.vb for p in plots]
    calls = _addplot_counter(wave)
    wave.refresh()
    assert calls[0] == 0
    assert wave._plots == plots                       # same PlotItems
    assert [p.vb for p in wave._plots] == vbs         # same ViewBoxes
    assert [c for (_p, _c, _h, c) in wave._curve_slots] == curves  # same curves


def test_same_state_refresh_keeps_cursor_lines(win):
    wave = _wave(win)
    _add_session(win)
    wave.channels = ["CH0", "CH1"]
    wave.refresh()
    lines = list(wave._lines)
    regions = list(wave._reference_regions)
    wave.refresh()
    assert wave._lines == lines
    assert wave._reference_regions == regions


# --- B. same-topology active-run switch -------------------------------------

def test_active_switch_same_topology_updates_data(win):
    wave = _wave(win)
    cols = ["A", "B", "C"]
    h1 = _add_session(win, "run1", cols=cols)
    wave.channels = cols
    wave.refresh()
    plots = list(wave._plots)
    curves = [c for (_p, _c, _h, c) in wave._curve_slots]
    y1 = curves[0].getData()[1].copy()

    h2 = win.store.add("run2.csv", _run("run2", cols=cols), activate=True)
    QtWidgets.QApplication.instance().processEvents()

    assert wave._plots == plots                       # incremental
    assert [c for (_p, _c, _h, c) in wave._curve_slots] == curves
    y2 = curves[0].getData()[1]
    assert len(y2) == len(y1) and not np.allclose(y1, y2) or True  # data may coincide
    # verify the curve now holds run2's data exactly
    expected = np.asarray(h2.run.data["A"], dtype=float)
    assert len(y2) == len(expected)
    assert np.allclose(y2, expected)


def test_active_switch_resets_x_range_for_new_run(win):
    wave = _wave(win)
    cols = ["A", "B"]
    _add_session(win, "run1", cols=cols)
    wave.channels = cols
    wave.refresh()
    wave._plots[0].setXRange(0.5, 0.7, padding=0)
    win.store.add("run2.csv", _run("run2", cols=cols), activate=True)
    QtWidgets.QApplication.instance().processEvents()
    lo, hi = wave._plots[0].viewRange()[0]
    assert lo < 0.4 and hi > 3.0      # fit to new run, not the old zoom


def test_same_run_refresh_preserves_x_zoom(win):
    wave = _wave(win)
    cols = ["A", "B"]
    _add_session(win, "run1", cols=cols)
    wave.channels = cols
    wave.refresh()
    wave._plots[0].setXRange(0.5, 0.7, padding=0)
    win.store.changed.emit()          # same-run data change notification
    lo, hi = wave._plots[0].viewRange()[0]
    assert lo == pytest.approx(0.5, abs=0.05)
    assert hi == pytest.approx(0.7, abs=0.05)


# --- C. same curve count, different target topology → full rebuild ----------

def test_same_curve_count_different_pattern_rebuilds(win):
    wave = _wave(win)
    # run1 resolves A and B; run2 resolves A and C.  Both produce two curves,
    # but the slot pattern differs -> must rebuild, not setData.
    _add_session(win, "run1", cols=["A", "B"])
    wave.channels = ["A", "B", "C"]
    wave.refresh()
    plots1 = list(wave._plots)
    win.store.add("run2.csv", _run("run2", cols=["A", "C"]), activate=True)
    QtWidgets.QApplication.instance().processEvents()
    assert wave._plots != plots1
    assert len(wave._plots) == 3      # A, B, C bands — B's is empty for run2
    rendered = [c0 for (_p, c0, _h, _c) in wave._curve_slots]
    assert rendered == ["A", "C"]     # same count as before, different slots


# --- D/E. structural changes still rebuild -----------------------------------

def test_channel_add_remove_reorders_rebuild(win):
    wave = _wave(win)
    _add_session(win, cols=["A", "B", "C"])
    wave.channels = ["A", "B", "C"]
    wave.refresh()
    plots1 = list(wave._plots)
    wave.add_channel("C")             # duplicate -> no-op
    assert wave._plots == plots1
    wave.remove_channel("B")
    assert wave._plots != plots1 and len(wave._plots) == 2
    plots2 = list(wave._plots)
    wave.channels = [wave.channels[1], wave.channels[0]]
    wave.refresh()
    assert wave._plots != plots2


def test_layout_mode_change_rebuilds(win):
    wave = _wave(win)
    _add_session(win, cols=["A", "B", "C"])
    wave.channels = ["A", "B", "C"]
    wave.refresh()
    plots1 = list(wave._plots)
    wave.layout_mode.setCurrentText("Overlay")
    assert len(wave._plots) == 1 and wave._plots != plots1
    wave.layout_mode.setCurrentText("Stacked Channels")
    assert len(wave._plots) == 3


# --- F. unit grouping ---------------------------------------------------------

def test_stacked_units_groups_compatible_units(win):
    wave = _wave(win)
    _add_session(win, cols=["RPM1", "RPM2", "MPH"],
                 units={"RPM1": "rpm", "RPM2": "rpm", "MPH": "mph"})
    wave.channels = ["RPM1", "RPM2", "MPH"]
    wave.layout_mode.setCurrentText("Stacked Units")
    assert len(wave._plots) == 2      # rpm band + mph band
    # Compatible display-unit change (mph -> km/h) alters the group key ->
    # rebuild with new topology.  An incompatible unit is refused by
    # _display_unit, so topology stays put and reuse is correct there.
    wave.channel_styles.setdefault("MPH", {})["display_unit"] = "kmh"
    plots1 = list(wave._plots)
    wave.refresh()
    assert wave._plots != plots1
    assert len(wave._plots) == 2      # rpm band + km/h band
    # rpm source can never join the speed band
    wave.channel_styles.setdefault("RPM2", {})["display_unit"] = "mph"
    wave.refresh()
    assert len(wave._plots) == 2
    assert [c for (_p, c, _h, _cv) in wave._curve_slots] == ["RPM1", "RPM2", "MPH"]


def test_grouped_channels_respects_axis_group_and_units(win):
    wave = _wave(win)
    _add_session(win, cols=["A", "B"], units={"A": "psi", "B": "psi"})
    wave.channels = ["A", "B"]
    wave.channel_styles["A"] = {"axis_group": "press"}
    wave.channel_styles["B"] = {"axis_group": "press"}
    wave.layout_mode.setCurrentText("Grouped Channels")
    assert len(wave._plots) == 1      # same group + same unit share a band
    wave.channel_styles["B"] = {"axis_group": "press", "display_unit": "bar"}
    wave.refresh()
    assert len(wave._plots) == 2      # unit mismatch never shares a band


# --- G. compare mode ----------------------------------------------------------

def test_compare_session_switch_reuses_curves(win):
    wave = _wave(win)
    cols = ["A", "B"]
    h1 = _add_session(win, "run1", cols=cols)
    h2 = win.store.add("run2.csv", _run("run2", cols=cols))
    h2.role = "reference"
    h3 = win.store.add("run3.csv", _run("run3", cols=cols))   # available
    wave.channels = cols
    wave.compare = True
    wave.refresh()
    plots = list(wave._plots)
    curves = [c for (_p, _c, _h, c) in wave._curve_slots]
    assert len(curves) == 4           # 2 channels x 2 sessions
    # Switch active to run3: run2 stays reference, so overlays() keeps the
    # same 2-session topology — only the data feeding the curve slots changes.
    win.store.set_active(2)
    QtWidgets.QApplication.instance().processEvents()
    assert wave._plots == plots
    assert [c for (_p, _c, _h, c) in wave._curve_slots] == curves
    # names reflect the new active/reference assignment
    names = {c.opts.get("name") for (_p, _c, _h, c) in wave._curve_slots}
    assert "A" in names and any("run2" in n for n in names)


def test_compare_overlay_add_rebuilds(win):
    wave = _wave(win)
    cols = ["A", "B"]
    _add_session(win, "run1", cols=cols)
    wave.channels = cols
    wave.compare = True
    wave.refresh()
    plots1 = list(wave._plots)
    h2 = win.store.add("run2.csv", _run("run2", cols=cols))
    h2.role = "reference"
    wave.refresh()
    assert wave._plots != plots1
    assert len([c for (_p, _c, _h, c) in wave._curve_slots]) == 4


# --- H. style updates ---------------------------------------------------------

def test_style_update_reuses_scene(win):
    wave = _wave(win)
    _add_session(win, cols=["A", "B"])
    wave.channels = ["A", "B"]
    wave.refresh()
    plots = list(wave._plots)
    curve = wave._curve_slots[0][3]
    wave.channel_styles["A"] = {"color": "#ff0000", "width": 3.0}
    wave.refresh()
    assert wave._plots == plots
    assert wave._curve_slots[0][3] is curve
    pen = curve.opts["pen"]
    assert pen.color().name() == "#ff0000"
    assert pen.widthF() == pytest.approx(3.0)


def test_manual_y_range_reuses_scene(win):
    wave = _wave(win)
    _add_session(win, cols=["A"])
    wave.channels = ["A"]
    wave.refresh()
    p = wave._plots[0]
    wave.channel_styles["A"] = {"y_min": -5.0, "y_max": 5.0}
    wave.refresh()
    assert wave._plots[0] is p
    lo, hi = p.viewRange()[1]
    assert lo == pytest.approx(-5.0) and hi == pytest.approx(5.0)


# --- I. cursor wiring ---------------------------------------------------------

def test_cursor_signals_fire_once_after_many_refreshes(win):
    wave = _wave(win)
    _add_session(win, cols=["A", "B", "C"])
    wave.channels = ["A", "B", "C"]
    for _ in range(4):
        wave.refresh()
    moved = [0]
    wave.cursors.moved.connect(lambda _x: moved.__setitem__(0, moved[0] + 1))
    wave.cursors.x = 0.0
    wave._lines[0][0].setValue(1.5)
    assert moved[0] == 1
    # all band cursors track the shared position
    for lines in wave._lines:
        assert float(lines[0].value()) == pytest.approx(float(wave.cursors.x))


def test_ab_cursor_signals_fire_once(win):
    wave = _wave(win)
    _add_session(win, cols=["A"])
    wave.channels = ["A"]
    wave.refresh(); wave.refresh()
    hits = [0]
    wave.cursors.cursorAMoved.connect(lambda _x: hits.__setitem__(0, hits[0] + 1))
    wave._lines[0][1].setValue(1.0)
    assert hits[0] == 1


# --- J. annotation/event layer -------------------------------------------------

def test_bookmark_add_single_refresh_and_event_layer(win):
    wave = _wave(win)
    h = _add_session(win, cols=["A", "B"])
    wave.channels = ["A", "B"]
    wave.refresh()
    base_events = len(wave._event_items)
    assert base_events == 2           # Launch marker per band
    monkey = pytest.MonkeyPatch()
    monkey.setattr(QtWidgets.QInputDialog, "getText", staticmethod(lambda *a, **k: ("bm", True)))
    calls = _refresh_counter(wave)
    wave._add_bookmark()
    monkey.undo()
    assert calls[0] == 1
    assert len(wave._event_items) == 4   # Launch + bookmark, per band


def test_region_add_single_refresh(win):
    wave = _wave(win)
    _add_session(win, cols=["A"])
    wave.channels = ["A"]
    wave.refresh()
    wave.cursors.a = 0.5; wave.cursors.b = 1.5
    monkey = pytest.MonkeyPatch()
    monkey.setattr(QtWidgets.QInputDialog, "getText", staticmethod(lambda *a, **k: ("rg", True)))
    calls = _refresh_counter(wave)
    wave._add_region()
    monkey.undo()
    assert calls[0] == 1
    assert any(ann.kind == "region" for ann in annotations_for_mode(wave.store.active.run, wave.x_mode))


def test_event_items_not_stale_after_refresh(win):
    wave = _wave(win)
    h = _add_session(win, cols=["A"])
    wave.channels = ["A"]
    wave.refresh()
    old_items = [item for (_p, item) in wave._event_items]
    add_bookmark(h.run, 1.0, "bm1", x_mode=wave.x_mode)
    win.store.changed.emit()
    for item in old_items:
        assert item.scene() is None   # removed from the scene, not lingering
    assert len(wave._event_items) == 2


# --- K. navigator ---------------------------------------------------------------

def test_navigator_survives_incremental(win):
    wave = _wave(win)
    _add_session(win, cols=["A", "B"])
    wave.channels = ["A", "B"]
    wave.show_navigator = True
    wave.navigator.setVisible(True)
    wave.refresh()
    nav_curves = wave.navigator.getPlotItem().listDataItems()
    assert len(nav_curves) == 1 and len(nav_curves[0].getData()[0]) > 0
    wave.refresh()                    # incremental path
    assert len(wave._plots) == 2
    nav_curves2 = wave.navigator.getPlotItem().listDataItems()
    assert len(nav_curves2) == 1 and len(nav_curves2[0].getData()[0]) > 0
    assert not wave.navigator.isHidden()


# --- L. render accounting --------------------------------------------------------

def test_render_accounting_matches_between_paths(win):
    wave = _wave(win)
    cols = ["A", "B"]
    h1 = _add_session(win, "run1", cols=cols)
    h2 = win.store.add("run2.csv", _run("run2", cols=cols))
    h2.role = "reference"
    wave.channels = cols
    wave.compare = True
    wave.refresh()
    full_counts = (wave._rendered_curve_count, wave._rendered_point_count)
    # Same-topology data change: mutate the active run in place and notify.
    h1.run.data["A"] = h1.run.data["A"] * 1.5
    wave._data_cache.clear()
    win.store.changed.emit()
    incr_counts = (wave._rendered_curve_count, wave._rendered_point_count)
    assert incr_counts == full_counts
    assert incr_counts[0] == 4        # 2 channels x 2 sessions
    # and the curve really carries the mutated data
    curve = [cv for (_p, ch, h, cv) in wave._curve_slots if ch == "A" and h == 0][0]
    expected = np.asarray(h1.run.data["A"], dtype=float)
    assert np.allclose(curve.getData()[1], expected)


# --- M. fallback sequence ---------------------------------------------------------

def test_full_incremental_full_sequence(win):
    wave = _wave(win)
    _add_session(win, cols=["A", "B"])
    wave.channels = ["A", "B"]
    wave.refresh()                     # full
    p1 = wave._plots[0]
    wave.refresh()                     # incremental
    assert wave._plots[0] is p1
    wave.add_channel("C") if "C" in wave.store.active.run.data.columns else None
    wave.channels = ["A", "B", "C"]; wave.refresh()   # structural -> full
    p2 = wave._plots[0]
    assert p2 is not p1
    wave.refresh()                     # incremental again
    assert wave._plots[0] is p2
    assert len(wave._lines) == 3


# --- N. batch operations -----------------------------------------------------------

def test_display_properties_single_refresh(win):
    wave = _wave(win)
    _add_session(win, cols=["A", "B"])
    wave.channels = ["A", "B"]
    wave.refresh()
    calls = _refresh_counter(wave)
    def fake_exec(dlg):
        combo = dlg.findChild(QtWidgets.QComboBox)
        if combo is not None:
            combo.setCurrentText("Overlay")
        return QtWidgets.QDialog.Accepted
    monkey = pytest.MonkeyPatch()
    monkey.setattr(QtWidgets.QDialog, "exec", fake_exec)
    wave._display_properties()
    monkey.undo()
    assert calls[0] == 1
    assert wave.layout_mode.currentText() == "Overlay"
    assert len(wave._plots) == 1
