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


def test_recovery_source_prefers_new_then_legacy_then_none(tmp_path, monkeypatch):
    # Fallback ordering is exercised with no explicit state home configured;
    # deleting the vars also keeps this test deterministic on machines that
    # happen to export NHRA_VELOCITY_HOME in their environment.
    monkeypatch.delenv("NHRA_VELOCITY_HOME", raising=False)
    monkeypatch.delenv("NHRA_TECH_DATA_HOME", raising=False)
    new = tmp_path / "new" / RECOVERY_FILENAME
    legacy = tmp_path / "legacy" / RECOVERY_FILENAME
    assert recovery_source_path(new, legacy) is None
    legacy.parent.mkdir(parents=True)
    atomic_write_json(legacy, {"sessions": []})
    assert recovery_source_path(new, legacy) == legacy
    new.parent.mkdir(parents=True)
    atomic_write_json(new, {"sessions": []})
    assert recovery_source_path(new, legacy) == new


def _isolate_platform_roots(monkeypatch, tmp_path):
    """Redirect every platform-specific state root under tmp_path.

    legacy_recovery_path()/app_data_root() resolve LOCALAPPDATA/APPDATA on
    Windows, XDG_DATA_HOME/XDG_STATE_HOME on Linux, and Path.home() on macOS,
    so all of them must be redirected for a test to stay inside tmp_path on
    every CI platform.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local_app_data"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "app_data"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg_state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def test_recovery_source_never_leaves_isolated_home(tmp_path, monkeypatch):
    """NHRA_VELOCITY_HOME alone is a hard state sandbox: the legacy
    QStandardPaths location is never consulted, even when a real legacy
    snapshot exists. No LOCALAPPDATA redirection is required for isolation."""
    monkeypatch.setenv("NHRA_VELOCITY_HOME", str(tmp_path / "velocity_home"))
    # A simulated 'real' user profile containing a valid legacy snapshot.
    _isolate_platform_roots(monkeypatch, tmp_path)
    legacy = legacy_recovery_path()
    legacy.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(legacy, {"sessions": [{"path": "real_user_run.rpk"}]})

    # Canonical location empty: the legacy file must NOT be selected or read.
    assert recovery_source_path() is None

    # A snapshot inside the isolated home is selected normally.
    canonical = recovery_path()
    canonical.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(canonical, {"sessions": [{"path": "isolated_run.rpk"}]})
    assert recovery_source_path() == canonical


def test_recovery_source_legacy_fallback_when_unset(tmp_path, monkeypatch):
    """Normal production mode (no explicit state home): the canonical
    location wins when present, the legacy location is consulted when it is
    absent, and source selection never deletes or modifies either file."""
    monkeypatch.delenv("NHRA_VELOCITY_HOME", raising=False)
    monkeypatch.delenv("NHRA_TECH_DATA_HOME", raising=False)
    _isolate_platform_roots(monkeypatch, tmp_path)

    legacy = legacy_recovery_path()
    legacy.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(legacy, {"sessions": [{"path": "legacy_run.rpk"}]})
    legacy_payload = legacy.read_bytes()

    assert recovery_source_path() == legacy
    # Selection is read-only: the legacy file is untouched.
    assert legacy.read_bytes() == legacy_payload

    canonical = recovery_path()
    canonical.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(canonical, {"sessions": [{"path": "canonical_run.rpk"}]})
    assert recovery_source_path() == canonical
    # Canonical winning must not disturb the legacy snapshot either.
    assert legacy.exists() and legacy.read_bytes() == legacy_payload


def test_recovery_write_never_touches_legacy_location(tmp_path, monkeypatch):
    """Isolated-state contract: a recovery write under NHRA_VELOCITY_HOME must
    not create or modify the legacy QStandardPaths recovery file."""
    monkeypatch.setenv("NHRA_VELOCITY_HOME", str(tmp_path / "velocity_home"))
    _isolate_platform_roots(monkeypatch, tmp_path)
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
