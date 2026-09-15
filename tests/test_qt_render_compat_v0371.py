from pathlib import Path


def test_waveform_plot_path_avoids_unsafe_pyqtgraph_constructor_flags():
    """Prepared traces are already bounded/monotonic; do not re-enable the
    pyqtgraph clip/downsample constructor path that failed on Windows 0.14.x.
    """
    desktop = (Path(__file__).resolve().parents[1] / "desktop.py").read_text(encoding="utf-8")
    assert "clipToView=True" not in desktop
    assert "autoDownsample=True" not in desktop
    assert "downsampleMethod='peak'" not in desktop


def test_prepared_waveform_decimation_remains_enabled():
    desktop = (Path(__file__).resolve().parents[1] / "desktop.py").read_text(encoding="utf-8")
    assert "prepare_plot_series(x,y,max_points=self.max_render_points)" in desktop
    assert "prepare_plot_series(x,y,max_points=10000)" in desktop
