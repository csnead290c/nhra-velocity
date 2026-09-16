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
