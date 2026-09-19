"""Project/recovery JSON persistence helpers.

This module deliberately has no Qt dependency so the durability contract can be
regression-tested headlessly.  Project writes use a same-directory temporary
file followed by os.replace(), which prevents a partially-written JSON project
from replacing the last good copy if the process is interrupted mid-write.
"""
from __future__ import annotations

import json
import os
import platform
import tempfile
from pathlib import Path
from typing import Any, Mapping, Optional

from .diagnostics import app_data_root

RECOVERY_FILENAME = "autosave-recovery.nhratech"


def recovery_path() -> Path:
    """Canonical autosave/recovery location under the unified app-data root.

    Recovery state follows ``NHRA_VELOCITY_HOME`` like the catalog, object
    cache and logs so isolated/test environments never write into the real
    user application-state directory.
    """
    return app_data_root() / RECOVERY_FILENAME


def legacy_recovery_path(app_org: str = "NHRA", app_id: str = "NHRA.Velocity") -> Path:
    """Pre-unification autosave location (QStandardPaths.AppLocalDataLocation).

    Older builds wrote the recovery snapshot outside the app-data root.  The
    path is retained for read-side compatibility only; new writes never go
    here.
    """
    system = platform.system().lower()
    if system == "windows":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
    elif system == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return root / app_org / app_id / RECOVERY_FILENAME


def recovery_source_path(
    new_path: str | os.PathLike[str] | None = None,
    legacy_path: str | os.PathLike[str] | None = None,
) -> Optional[Path]:
    """Resolve which recovery snapshot may be read.

    The unified app-data-root location always wins.  A legacy snapshot is only
    used when no new-location file exists, so existing users keep one
    recovery chance without the application migrating or deleting anything.
    """
    new = Path(new_path) if new_path is not None else recovery_path()
    if new.exists():
        return new
    legacy = Path(legacy_path) if legacy_path is not None else legacy_recovery_path()
    if legacy.exists():
        return legacy
    return None


def atomic_write_json(path: str | os.PathLike[str], payload: Mapping[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    return target


def read_project_json(path: str | os.PathLike[str]) -> dict[str, Any]:
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("Project file root must be a JSON object")
    return obj


def is_recovery_newer(recovery_path: str | os.PathLike[str], project_path: str | os.PathLike[str] | None) -> bool:
    recovery = Path(recovery_path)
    if not recovery.exists() or recovery.stat().st_size <= 0:
        return False
    if not project_path:
        return True
    project = Path(project_path)
    if not project.exists():
        return True
    return recovery.stat().st_mtime > project.stat().st_mtime


def _stable_project_payload(obj: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(obj)
    out.pop("saved_at_utc", None)
    out.pop("source_project_path", None)
    return out


def projects_equivalent(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """Compare persisted workspace content while ignoring save bookkeeping."""
    return _stable_project_payload(a) == _stable_project_payload(b)
