from pathlib import Path


def _desktop_source() -> str:
    return (Path(__file__).resolve().parents[1] / "desktop.py").read_text(encoding="utf-8")


def test_dev13_waveform_stats_and_channel_management_contract():
    source = _desktop_source()
    assert 'self.stats_button = QtWidgets.QToolButton()' in source
    for key, attr in [
        ('M', 'show_stat_min'),
        ('X', 'show_stat_max'),
        ('N', 'show_stat_mean'),
        ('E', 'show_stat_delta'),
        ('Q', 'show_stat_std'),
    ]:
        assert f"_bind_waveform_shortcut('{key}'" in source
        assert attr in source
    assert "region_summary(handle.run,channel,self.cursors.a,self.cursors.x" in source
    assert "Remove from active waveform" in source
    assert "self.graph.customContextMenuRequested.connect(self._waveform_context_menu)" in source
    assert "self.remove_channel_menu = more.addMenu(\"Remove channel\")" in source


def test_dev13_analysis_cursor_model_is_reference_to_live_cursor():
    source = _desktop_source()
    assert "Cursor Region Statistics" in source
    assert "region_statistics(h.run,channels,self.cursors.a,self.cursors.x" in source
    assert "Reference-to-cursor only" in source
    assert "a=min(float(self.cursors.a),float(self.cursors.x))" in source
    assert "quick=m.addMenu('Quick Analysis')" in source


def test_dev13_launch_zero_clears_display_alignment_and_persists_effective_sample():
    source = _desktop_source()
    assert "selected_logger_time=old_launch + selected_x - old_alignment" in source
    assert "effective=float(detect_drag_pass_window(handle.run).launch_time_s)" in source
    assert "handle.time_alignment_s=0.0" in source
    assert "offset_s=-scale * effective" in source
    assert "coordinate_shift=old_launch - effective - old_alignment" in source
