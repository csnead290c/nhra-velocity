from pathlib import Path


DESKTOP = (Path(__file__).resolve().parents[1] / "desktop.py").read_text(encoding="utf-8")


def test_main_toolbar_stays_on_frequent_trackside_path():
    block = DESKTOP.split("def _build_toolbar(self):", 1)[1].split("def _build_docks(self):", 1)[0]
    assert "tb.addAction(self.a_fit_run)" in block
    assert "profile_selector" not in block
    assert "quick_graph" not in block
    assert "reference_selector.setVisible(False)" in block


def test_simple_workspace_keeps_run_context_without_showing_every_tool():
    block = DESKTOP.split("def _apply_workspace_layout(self, mode: str):", 1)[1].split("def _build_menus(self):", 1)[0]
    assert "'simple': {'RunBrowserDock','ParametersDock','RunWorkspaceDock'}" in block
    assert "'full': set(docks)" in block


def test_channel_explorer_defaults_to_essentials_and_searches_all():
    assert 'def set_run(self, run: Optional[TelemetryRun], filter_text: str = "", view_mode: str = "essentials")' in DESKTOP
    assert "if mode=='essentials' and not query and not favorite and rec.name not in essential:" in DESKTOP
    assert "self.channel_scope.addItem('Essentials','essentials')" in DESKTOP
    assert "self.channel_scope.addItem('All channels','all')" in DESKTOP


def test_standard_class_layout_is_one_core_waveform_not_many_panels():
    block = DESKTOP.split("def _apply_standard_profile_layout(self,key):", 1)[1].split("def _pro_stock_shift_report(self):", 1)[0]
    assert "resolve_profile_channels(h.run,p.key,limit=8)" in block
    assert "for group_name, _roles in p.waveform_groups" not in block
    assert "ws.add_waveform()" in block
    assert "attach_shift_report" not in block


def test_waveform_exposes_manual_launch_rezero_control():
    source = Path(__file__).resolve().parents[1].joinpath('desktop.py').read_text(encoding='utf-8')
    assert 'Set Cursor as Launch (T=0)' in source
    assert 'Use Auto-Detected Launch' in source
    assert 'Zero: Manual' in source
    assert 'Refresh View' in source
    assert 'Sync Tech Services' in source


def test_waveform_cursor_and_zoom_follow_atlas_style_interaction():
    source = Path(__file__).resolve().parents[1].joinpath('desktop.py').read_text(encoding='utf-8')
    # Hover should never move the engineering cursor; click positions it and
    # the InfiniteLine remains movable for click/drag scrubbing.
    assert 'sigMouseMoved' not in source
    assert 'sigMouseClicked.connect(self._scene_mouse_clicked)' in source
    assert "cursor = pg.InfiniteLine(angle=90, movable=True" in source
    # Waveform mouse interactions intentionally affect X only; Y scaling is
    # controlled by auto-range / trace properties rather than accidental wheel zoom.
    assert "p.setMouseEnabled(x=True, y=False)" in source


def test_run_browser_hides_opaque_remote_ids_and_surfaces_data_logs():
    source = Path(__file__).resolve().parents[1].joinpath('desktop.py').read_text(encoding='utf-8')
    block = source.split('class RunBrowser',1)[1].split('class AnalysisCaseBrowser',1)[0]
    assert "_friendly_run_label" in block
    assert "data_log_count" in block
    assert "local_data_log_count" in block
    assert "Attach Data Log…" in block
    assert "run_label=(r.get('run_key')" not in block


def test_waveform_readout_defaults_to_compact_columns():
    source = Path(__file__).resolve().parents[1].joinpath('desktop.py').read_text(encoding='utf-8')
    block = source.split('class WaveformDisplay',1)[1].split('class ValuesDisplay',1)[0]
    assert 'self.show_stat_min = False' in block
    assert 'self.show_stat_max = False' in block
    assert 'self.show_stat_mean = False' in block
    assert "readout_columns=more.addMenu('Readout columns')" in block
    assert 'setDefaultSectionSize(19)' in block
