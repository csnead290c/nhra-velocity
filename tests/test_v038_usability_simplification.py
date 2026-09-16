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
    assert "self.refresh_btn=QtWidgets.QPushButton('Refresh')" in source
    assert 'Sync Tech Services' in source


def test_waveform_cursor_and_zoom_follow_atlas_style_interaction():
    source = Path(__file__).resolve().parents[1].joinpath('desktop.py').read_text(encoding='utf-8')
    # Hover never moves engineering state. Click positions the cursor, and
    # left-drag anywhere in the ViewBox continuously scrubs it.
    assert 'sigMouseMoved' not in source
    assert 'sigMouseClicked.connect(self._scene_mouse_clicked)' in source
    assert 'class VelocityWaveformViewBox' in source
    assert 'if ev.button() == QtCore.Qt.LeftButton' in source
    assert 'self.cursorDragged.emit(float(pos.x()))' in source
    assert "cursor = pg.InfiniteLine(angle=90, movable=True" in source
    # Navigation is X-only and the ATLAS-style keyboard surface is bound even
    # when focus belongs to a pyqtgraph child.
    assert "p.setMouseEnabled(x=True, y=False)" in source
    assert "self._bind_waveform_shortcut('R', self._toggle_reference_cursor)" in source
    assert "self._bind_waveform_shortcut('+', lambda: self._zoom_x(0.70))" in source
    assert "self._bind_waveform_shortcut('-', lambda: self._zoom_x(1.40))" in source


def test_run_browser_hides_opaque_remote_ids_and_surfaces_data_logs():
    source = Path(__file__).resolve().parents[1].joinpath('desktop.py').read_text(encoding='utf-8')
    block = source.split('class RunBrowser',1)[1].split('class AnalysisCaseBrowser',1)[0]
    assert "_friendly_run_label" in block
    assert "data_log_count" in block
    assert "local_data_log_count" in block
    assert "Attach Data…" in block
    assert "run_label=(r.get('run_key')" not in block


def test_waveform_values_live_in_each_plot_band_by_default():
    source = Path(__file__).resolve().parents[1].joinpath('desktop.py').read_text(encoding='utf-8')
    block = source.split('class WaveformDisplay',1)[1].split('class ValuesDisplay',1)[0]
    assert 'self.show_readout = False' in block
    assert 'self.show_stat_min = False' in block
    assert 'self.show_stat_max = False' in block
    assert 'self.show_stat_mean = False' in block
    assert 'Detailed channel table' in block
    assert 'band_header = pg.TextItem' in block
    assert '_refresh_plot_headers' in block


def test_reference_cursor_shortcut_captures_current_cursor_and_shows_range():
    source = Path(__file__).resolve().parents[1].joinpath('desktop.py').read_text(encoding='utf-8')
    block = source.split('class WaveformDisplay',1)[1].split('class ValuesDisplay',1)[0]
    assert 'self.reference_visible = False' in block
    assert 'self.cursors.a = float(self.cursors.x)' in block
    assert "ca = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen('#ff5252'" in block
    assert 'ref_region = pg.LinearRegionItem' in block
    assert '_update_reference_regions' in block


def test_workbook_shell_has_compact_document_tabs_and_focus_mode():
    source = Path(__file__).resolve().parents[1].joinpath('desktop.py').read_text(encoding='utf-8')
    assert 'self.worksheets.setDocumentMode(True)' in source
    assert "self.new_sheet_button.setText('+')" in source
    assert "self.a_focus_analysis.setShortcut('Ctrl+Enter')" in source
    assert "self.resizeDocks([left], [320]" in source
    assert "self.resizeDocks([right], [300]" in source


def test_run_browser_actions_do_not_force_an_overwide_left_dock():
    source = Path(__file__).resolve().parents[1].joinpath('desktop.py').read_text(encoding='utf-8')
    block = source.split('class RunBrowser',1)[1].split('class AnalysisCaseBrowser',1)[0]
    assert "self.open_btn=QtWidgets.QPushButton('Open')" in block
    assert "self.attach_btn=QtWidgets.QPushButton('Attach Data…')" in block
    assert 'primary=QtWidgets.QHBoxLayout()' in block
    assert 'secondary=QtWidgets.QHBoxLayout()' in block


def test_compact_waveform_headers_refresh_on_every_cursor_or_reference_motion():
    source = Path(__file__).resolve().parents[1].joinpath('desktop.py').read_text(encoding='utf-8')
    block = source.split('def _schedule_readout(self, *_args):',1)[1].split('def _set_navigator_visible',1)[0]
    assert 'if not self.show_readout' not in block
    assert 'self._readout_timer.start()' in block
    refresh = source.split('def _refresh_readout(self):',1)[1].split('def refresh(self):',1)[0]
    assert 'self._refresh_plot_headers()' in refresh
    assert 'self._update_reference_regions()' in refresh


def test_run_browser_compact_scope_uses_current_or_last_completed_not_future_db_tail():
    source = Path(__file__).resolve().parents[1].joinpath('desktop.py').read_text(encoding='utf-8')
    block = source.split('class RunBrowser',1)[1].split('class AnalysisCaseBrowser',1)[0]
    assert "Current / last completed" in block
    assert 'if start is not None and end is not None and start <= now <= end:' in block
    assert 'if end is not None and end < now:' in block
    assert 'if start is not None and start > now:' in block
    assert 'events=self._trackside_event_order(events)' in block


def test_attached_local_run_data_auto_reopens_when_run_is_selected_again():
    source = Path(__file__).resolve().parents[1].joinpath('desktop.py').read_text(encoding='utf-8')
    block = source.split('def _catalog_run_selected(self, run_id: str):',1)[1].split('def _active_handle_for_catalog_run',1)[0]
    assert '_auto_open_selected_run_data' in block
    assert 'QTimer.singleShot(300' in block
    assert 'local_asset_read_path' in source
