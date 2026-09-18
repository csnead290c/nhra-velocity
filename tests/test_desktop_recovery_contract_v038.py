from __future__ import annotations

import ast
from pathlib import Path

from runlab.project_io import atomic_write_json, read_project_json, projects_equivalent


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


def test_corpus_audit_never_auto_installs_unreviewed_racepak_evidence():
    script = (Path(__file__).resolve().parents[1] / "scripts" / "Audit-NHRA-Velocity-Data.cmd").read_text(encoding="utf-8")
    assert "--install" not in script
    assert "Strong/native logger files found" in script
    assert "fewer than 10 strong/native logger files" in script
