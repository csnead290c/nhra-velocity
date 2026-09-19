from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6 import QtCore, QtWidgets

import desktop
from desktop import MainWindow
from runlab.models import Environment, TelemetryRun, TimingData

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "native_demo_maxxecu.MaxxECU-log"
DEMOS = [
    ROOT / "examples" / "native_demo_racepak.rpk",
    ROOT / "examples" / "native_demo_motec.ld",
    ROOT / "examples" / "native_demo_maxxecu.MaxxECU-log",
]


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _wait_for(app, cond, timeout=15.0):
    deadline = time.time() + timeout
    while not cond():
        if time.time() > deadline:
            return False
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    return True


def _run(name="decode-job"):
    t = np.arange(0.0, 2.01, 0.01)
    return TelemetryRun(
        name=name,
        data=pd.DataFrame({"Time": t, "RPM": 5000.0 + t * 100.0, "Speed": t * 60.0}),
        channel_map={"time_s": "Time", "engine_rpm": "RPM", "speed_mph": "Speed"},
        units={"Time": "s", "RPM": "rpm", "Speed": "mph"},
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
        app = QtWidgets.QApplication.instance()
        _wait_for(app, lambda: w._open_worker is None)


def _slow_decoder(monkeypatch, delay_s):
    real = desktop.load_telemetry

    def slow(path, **kw):
        time.sleep(delay_s)
        return real(path, **kw)

    monkeypatch.setattr(desktop, "load_telemetry", slow)


def test_successful_background_decode_adds_and_activates(win):
    app = QtWidgets.QApplication.instance()
    win._open_paths([str(DEMO)])
    assert _wait_for(app, lambda: win._open_worker is None)
    assert len(win.store.runs) == 1
    assert win.store.active is win.store.runs[0]
    assert "engine_rpm" in win.store.runs[0].run.channel_map


def test_multiple_files_decode_in_order_and_last_is_active(win):
    app = QtWidgets.QApplication.instance()
    win._open_paths([str(p) for p in DEMOS])
    assert _wait_for(app, lambda: win._open_worker is None)
    assert [Path(h.path).name for h in win.store.runs] == [p.name for p in DEMOS]
    assert win.store.active is win.store.runs[-1]


def test_decode_failure_isolated_and_aggregated(win, tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance()
    bad = tmp_path / "corrupt.rpk"
    bad.write_bytes(os.urandom(512))
    warnings = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a, **k: warnings.append(a))
    win._open_paths([str(bad), str(DEMO)])
    assert _wait_for(app, lambda: win._open_worker is None)
    # The bad file did not stop the later good file from loading.
    assert len(win.store.runs) == 1
    assert Path(win.store.runs[0].path).name == DEMO.name
    # Aggregated error dialog still reports the failed file.
    assert warnings and "corrupt.rpk" in str(warnings[0])


def test_decode_executes_off_gui_thread(win, monkeypatch):
    app = QtWidgets.QApplication.instance()
    real = desktop.load_telemetry
    gui_thread = win.thread()
    seen = []

    def probe(path, **kw):
        seen.append(QtCore.QThread.currentThread())
        return real(path, **kw)

    monkeypatch.setattr(desktop, "load_telemetry", probe)
    win._open_paths([str(DEMO)])
    assert _wait_for(app, lambda: win._open_worker is None)
    assert seen and all(t is not gui_thread for t in seen)


def test_gui_event_loop_stays_responsive_during_slow_decode(win, monkeypatch):
    app = QtWidgets.QApplication.instance()
    _slow_decoder(monkeypatch, 0.5)
    ticks = [0]
    timer = QtCore.QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: ticks.__setitem__(0, ticks[0] + 1))
    timer.start()
    win._open_paths([str(DEMO)])
    try:
        assert _wait_for(app, lambda: win._open_worker is None)
    finally:
        timer.stop()
    assert len(win.store.runs) == 1
    # ~500 ms of decode with a 20 ms timer must yield many ticks, not ~0.
    assert ticks[0] >= 10


def test_cancel_between_files_keeps_completed_only(win, monkeypatch):
    app = QtWidgets.QApplication.instance()
    gate = threading.Event()
    real = desktop.load_telemetry
    count = [0]

    def gated(path, **kw):
        count[0] += 1
        if count[0] > 1:
            gate.wait(timeout=10.0)
        return real(path, **kw)

    monkeypatch.setattr(desktop, "load_telemetry", gated)
    win._open_paths([str(p) for p in DEMOS])
    # File 1 decodes freely; file 2 is blocked on the gate when cancel lands.
    assert _wait_for(app, lambda: len(win.store.runs) == 1)
    win._open_progress.canceled.emit()
    gate.set()
    assert _wait_for(app, lambda: win._open_worker is None)
    assert len(win.store.runs) == 1


def test_cancel_during_decode_discards_result(win, monkeypatch):
    app = QtWidgets.QApplication.instance()
    gate = threading.Event()
    real = desktop.load_telemetry

    def gated(path, **kw):
        gate.wait(timeout=10.0)
        return real(path, **kw)

    monkeypatch.setattr(desktop, "load_telemetry", gated)
    win._open_paths([str(DEMO)])
    # Decode is in flight (blocked on the gate); cancel then release it.
    time.sleep(0.2)
    app.processEvents()
    win._open_progress.canceled.emit()
    gate.set()
    assert _wait_for(app, lambda: win._open_worker is None)
    assert len(win.store.runs) == 0


def test_stale_queued_result_is_ignored(win, monkeypatch):
    app = QtWidgets.QApplication.instance()
    gate = threading.Event()
    real = desktop.load_telemetry

    def gated(path, **kw):
        gate.wait(timeout=10.0)
        return real(path, **kw)

    monkeypatch.setattr(desktop, "load_telemetry", gated)
    win._open_paths([str(DEMO)])
    worker = win._open_worker
    time.sleep(0.2)
    app.processEvents()
    win._open_progress.canceled.emit()
    # A result emitted after cancellation must not reach SessionStore.
    worker.decoded.emit(win._open_job_id, str(DEMO), _run())
    gate.set()
    assert _wait_for(app, lambda: win._open_worker is None)
    assert len(win.store.runs) == 0


def test_second_open_request_rejected_while_busy(win, monkeypatch):
    app = QtWidgets.QApplication.instance()
    _slow_decoder(monkeypatch, 0.4)
    win._open_paths([str(DEMOS[0])])
    first_worker = win._open_worker
    assert first_worker is not None
    other = DEMOS[1]
    messages = []
    win.statusBar().messageChanged.connect(lambda m: messages.append(m))
    win._open_paths([str(other)])
    # The running job is untouched and the second batch was not substituted.
    assert win._open_worker is first_worker
    assert any("currently loading" in m for m in messages)
    assert _wait_for(app, lambda: win._open_worker is None)
    assert [Path(h.path).name for h in win.store.runs] == [DEMOS[0].name]


class _CloseSpyWindow(MainWindow):
    def __init__(self):
        super().__init__()
        self.close_results = []

    def closeEvent(self, event):
        super().closeEvent(event)
        self.close_results.append(event.isAccepted())


def test_window_close_deferred_during_decode(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("NHRA_VELOCITY_HOME", str(tmp_path / "velocity_home"))
    app = QtWidgets.QApplication.instance()
    gate = threading.Event()
    real = desktop.load_telemetry

    def gated(path, **kw):
        gate.wait(timeout=10.0)
        return real(path, **kw)

    monkeypatch.setattr(desktop, "load_telemetry", gated)
    w = _CloseSpyWindow()
    w._open_paths([str(DEMO)])
    time.sleep(0.2)
    app.processEvents()
    # The close request is deferred, not honoured while a decode is running.
    assert w.close() is False
    assert w._open_pending_close
    gate.set()
    assert _wait_for(app, lambda: w._open_worker is None)
    # The deferred close retried automatically after worker cleanup.
    assert w.close_results == [False, True]
    assert len(w.store.runs) == 0


def test_cli_arg_open_scheduled_on_event_loop(win):
    # Mirrors main(): CLI file args are opened via singleShot(0) so the async
    # job starts inside a running event loop.
    app = QtWidgets.QApplication.instance()
    QtCore.QTimer.singleShot(0, lambda: win._open_paths([str(DEMO)]))
    assert _wait_for(app, lambda: len(win.store.runs) == 1)
    assert _wait_for(app, lambda: win._open_worker is None)
