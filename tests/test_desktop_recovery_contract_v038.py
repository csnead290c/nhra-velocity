from __future__ import annotations

import ast
from pathlib import Path

from runlab.project_io import (
    atomic_write_json,
    read_project_json,
    projects_equivalent,
    recovery_path,
    legacy_recovery_path,
    recovery_source_path,
    RECOVERY_FILENAME,
)


def test_project_recovery_helpers_round_trip_atomically(tmp_path):
    path = tmp_path / "autosave-recovery.nhratech"
    payload = {"sessions": [{"path": "run.rpk"}], "saved_at_utc": "one"}
    atomic_write_json(path, payload)
    loaded = read_project_json(path)
    assert loaded == payload
    assert projects_equivalent(payload, {**payload, "saved_at_utc": "two"})


def test_desktop_imports_every_recovery_helper_it_calls():
    """Prevent a background-only NameError in timed autosave/recovery.

    This intentionally uses AST rather than importing the Qt desktop module so
    the contract is enforced even in headless environments where PySide6 is not
    installed and the GUI test module is skipped.
    """
    source = (Path(__file__).resolve().parents[1] / "desktop.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    required = {"atomic_write_json", "read_project_json", "is_recovery_newer", "projects_equivalent"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "runlab.project_io":
            imported.update(alias.asname or alias.name for alias in node.names)
    assert required <= imported


def test_recovery_path_follows_isolated_app_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("NHRA_VELOCITY_HOME", str(tmp_path / "velocity_home"))
    assert recovery_path() == tmp_path / "velocity_home" / RECOVERY_FILENAME


def test_recovery_source_prefers_new_then_legacy_then_none(tmp_path):
    new = tmp_path / "new" / RECOVERY_FILENAME
    legacy = tmp_path / "legacy" / RECOVERY_FILENAME
    assert recovery_source_path(new, legacy) is None
    legacy.parent.mkdir(parents=True)
    atomic_write_json(legacy, {"sessions": []})
    assert recovery_source_path(new, legacy) == legacy
    new.parent.mkdir(parents=True)
    atomic_write_json(new, {"sessions": []})
    assert recovery_source_path(new, legacy) == new


def test_recovery_write_never_touches_legacy_location(tmp_path, monkeypatch):
    """Isolated-state contract: a recovery write under NHRA_VELOCITY_HOME must
    not create or modify the legacy QStandardPaths recovery file."""
    monkeypatch.setenv("NHRA_VELOCITY_HOME", str(tmp_path / "velocity_home"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local_app_data"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "app_data"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
    target = recovery_path()
    legacy = legacy_recovery_path()
    assert target != legacy
    atomic_write_json(target, {"sessions": [{"path": "run.rpk"}]})
    assert target.exists()
    assert not legacy.exists()


def test_corpus_audit_never_auto_installs_unreviewed_racepak_evidence():
    script = (Path(__file__).resolve().parents[1] / "scripts" / "Audit-NHRA-Velocity-Data.cmd").read_text(encoding="utf-8")
    assert "--install" not in script
    assert "Strong/native logger files found" in script
    assert "fewer than 10 strong/native logger files" in script
