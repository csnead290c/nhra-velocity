from __future__ import annotations

from pathlib import Path


def test_dev20_daily_workflow_contract_is_present():
    root=Path(__file__).resolve().parents[1]
    text=(root/'desktop.py').read_text(encoding='utf-8')
    assert "Compare Workspace Manager…" in text
    assert "Ctrl+Shift+R" in text
    assert "Save Worksheet as Template…" in text
    assert "Apply Worksheet Template…" in text
    assert "Ctrl+Alt+T" in text
    assert "Grouped Channels" in text
    assert "Axis group" in text
    assert "Auto-align compare Runs to Main" in text


def test_dev20_portable_template_contract_refuses_fuzzy_guessing():
    root=Path(__file__).resolve().parents[1]
    text=(root/'runlab'/'layout_profiles.py').read_text(encoding='utf-8')
    assert 'never performs fuzzy channel-name matching' in text
    assert 'kind != "common"' in text
    assert 'kind == "source"' in text
