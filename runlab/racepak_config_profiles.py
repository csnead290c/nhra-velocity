from __future__ import annotations

"""Context-scoped RacePak DDF configuration management.

A RacePak ``.ddf`` recording can be decoded without DataLink, but a matching
``.rcg`` (or prior ``.rpk`` containing the same definitions) supplies the
human-readable channel names and units.  Those files are *not* universal by
vendor: the correct config can legitimately differ by driver/category/vehicle
and can change over time.

This module therefore keeps two deliberately separate layers:

* reusable profiles, scoped to Driver+Category or Vehicle+Category; and
* exact per-data-log bindings, which live in LocalCatalog telemetry-session
  settings and always take precedence over a reusable profile.

Selected configs are copied into a small content-addressed store under the
Velocity app-data root so a saved profile does not depend on the user's source
folder continuing to exist.
"""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Optional
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone

from .diagnostics import app_data_root
from .racepak import _attribute, parse_channel_definitions


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _token(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _profile_file() -> Path:
    p = app_data_root() / "racepak_ddf_profiles.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _config_store_dir() -> Path:
    p = app_data_root() / "racepak_configs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _read_profiles(path: Optional[Path] = None) -> dict[str, Any]:
    p = path or _profile_file()
    if not p.exists():
        return {"version": 1, "profiles": {}}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "profiles": {}}
    if not isinstance(obj, dict):
        return {"version": 1, "profiles": {}}
    if not isinstance(obj.get("profiles"), dict):
        obj["profiles"] = {}
    obj["version"] = max(1, int(obj.get("version", 1) or 1))
    return obj


def _atomic_write_json(path: Path, obj: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except Exception:
            pass


@dataclass(frozen=True)
class RacePakConfigRecord:
    filename: str
    sha256: str
    managed_path: str
    source_path: str
    suffix: str
    channel_definition_count: int
    connect4_definition_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "sha256": self.sha256,
            "managed_path": self.managed_path,
            "source_path": self.source_path,
            "suffix": self.suffix,
            "channel_definition_count": self.channel_definition_count,
            "connect4_definition_count": self.connect4_definition_count,
        }


def inspect_racepak_config(path: str | Path) -> RacePakConfigRecord:
    """Validate and copy one RCG/RPK configuration into Velocity-managed storage."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    suffix = source.suffix.lower()
    if suffix not in {".rcg", ".rpk"}:
        raise ValueError("RacePak DDF configuration must be an .rcg or .rpk file.")
    data = source.read_bytes()
    if not data:
        raise ValueError(f"{source.name}: configuration file is empty")
    definitions = parse_channel_definitions(data)
    if not definitions:
        raise ValueError(f"{source.name}: no RacePak channel definitions were found")
    connect4 = []
    for definition in definitions:
        raw = _attribute(definition.description, "_CONNECT4_COMMAND")
        if raw not in (None, ""):
            connect4.append(raw)
    if not connect4:
        raise ValueError(
            f"{source.name}: no _CONNECT4_COMMAND channel ids were found; "
            "this file cannot safely identify DDF channels"
        )
    digest = sha256(data).hexdigest()
    managed = _config_store_dir() / f"{digest}{suffix}"
    if not managed.exists():
        tmp = managed.with_suffix(managed.suffix + ".tmp")
        shutil.copy2(source, tmp)
        os.replace(tmp, managed)
    return RacePakConfigRecord(
        filename=source.name,
        sha256=digest,
        managed_path=str(managed),
        source_path=str(source),
        suffix=suffix,
        channel_definition_count=len(definitions),
        connect4_definition_count=len(connect4),
    )


def _context_from_mapping(record: Mapping[str, Any]) -> dict[str, str]:
    return {
        "category": _token(record.get("catalog_category") or record.get("official_category") or record.get("category")),
        "driver_id": _token(record.get("catalog_driver_id") or record.get("driver_id")),
        "driver_name": _token(record.get("catalog_driver_name") or record.get("driver_name")),
        "vehicle_id": _token(record.get("catalog_vehicle_id") or record.get("vehicle_id")),
        "vehicle_name": _token(record.get("catalog_vehicle_name") or record.get("vehicle_name")),
        "car_number": _token(record.get("catalog_car_number") or record.get("car_number")),
    }


def context_from_run(run: Any) -> dict[str, str]:
    md = getattr(run, "metadata", {}) if run is not None else {}
    return _context_from_mapping(md if isinstance(md, Mapping) else {})


def context_from_catalog_record(record: Mapping[str, Any]) -> dict[str, str]:
    return _context_from_mapping(record)


def _profile_key(context: Mapping[str, str], scope: str) -> str:
    scope = str(scope or "").strip()
    category = _token(context.get("category"))
    if not category:
        raise ValueError("A RacePak config profile requires an authoritative category.")
    if scope == "driver_category":
        identity = _token(context.get("driver_id")) or _token(context.get("driver_name"))
        if not identity:
            raise ValueError("Driver + Category RacePak config requires an authoritative driver.")
        return f"driver_category|{category}|{identity}"
    if scope == "vehicle_category":
        identity = _token(context.get("vehicle_id")) or _token(context.get("car_number")) or _token(context.get("vehicle_name"))
        if not identity:
            raise ValueError("Vehicle + Category RacePak config requires an authoritative vehicle/car identity.")
        return f"vehicle_category|{category}|{identity}"
    raise ValueError(f"Unsupported RacePak config profile scope: {scope!r}")


def profile_scope_options(record_or_run: Any) -> list[tuple[str, str]]:
    if hasattr(record_or_run, "metadata"):
        context = context_from_run(record_or_run)
        md = getattr(record_or_run, "metadata", {}) or {}
        driver_label = str(md.get("catalog_driver_name") or md.get("driver_name") or "this driver")
        category_label = str(md.get("catalog_category") or md.get("official_category") or md.get("category") or "this category")
        vehicle_label = str(md.get("catalog_vehicle_name") or md.get("vehicle_name") or md.get("catalog_car_number") or md.get("car_number") or "this vehicle")
    else:
        rec = record_or_run if isinstance(record_or_run, Mapping) else {}
        context = context_from_catalog_record(rec)
        driver_label = str(rec.get("driver_name") or "this driver")
        category_label = str(rec.get("category") or "this category")
        vehicle_label = str(rec.get("vehicle_name") or rec.get("car_number") or "this vehicle")
    out: list[tuple[str, str]] = []
    if context.get("category") and (context.get("driver_id") or context.get("driver_name")):
        out.append(("driver_category", f"Driver + Category — {driver_label} / {category_label}"))
    if context.get("category") and (context.get("vehicle_id") or context.get("car_number") or context.get("vehicle_name")):
        out.append(("vehicle_category", f"Vehicle + Category — {vehicle_label} / {category_label}"))
    return out


def save_profile(
    record_or_run: Any,
    config_path: str | Path,
    *,
    scope: str = "driver_category",
    path: Optional[Path] = None,
) -> dict[str, Any]:
    context = context_from_run(record_or_run) if hasattr(record_or_run, "metadata") else context_from_catalog_record(record_or_run)
    key = _profile_key(context, scope)
    cfg = inspect_racepak_config(config_path)
    p = path or _profile_file()
    obj = _read_profiles(p)
    rec = {
        "scope": scope,
        "context": dict(context),
        "config": cfg.to_dict(),
        "updated_at": _utc_now(),
    }
    obj.setdefault("profiles", {})[key] = rec
    _atomic_write_json(p, obj)
    out = dict(rec)
    out["profile_key"] = key
    return out


def delete_profile(record_or_run: Any, scope: str, *, path: Optional[Path] = None) -> bool:
    context = context_from_run(record_or_run) if hasattr(record_or_run, "metadata") else context_from_catalog_record(record_or_run)
    key = _profile_key(context, scope)
    p = path or _profile_file()
    obj = _read_profiles(p)
    profiles = obj.get("profiles", {})
    if key not in profiles:
        return False
    del profiles[key]
    _atomic_write_json(p, obj)
    return True


def _validated_profile(rec: Mapping[str, Any]) -> dict[str, Any]:
    cfg = rec.get("config") if isinstance(rec, Mapping) else None
    if not isinstance(cfg, Mapping):
        return {}
    managed = Path(str(cfg.get("managed_path") or ""))
    digest = str(cfg.get("sha256") or "")
    if not managed.is_file() or not digest:
        return {}
    try:
        if sha256(managed.read_bytes()).hexdigest() != digest:
            return {}
    except Exception:
        return {}
    return dict(rec)


def matching_profile(record_or_run: Any, *, path: Optional[Path] = None) -> dict[str, Any]:
    context = context_from_run(record_or_run) if hasattr(record_or_run, "metadata") else context_from_catalog_record(record_or_run)
    obj = _read_profiles(path)
    profiles = obj.get("profiles", {}) if isinstance(obj.get("profiles", {}), dict) else {}
    # Vehicle is intentionally narrower than Driver+Category when both exist.
    for scope in ("vehicle_category", "driver_category"):
        try:
            key = _profile_key(context, scope)
        except ValueError:
            continue
        rec = profiles.get(key)
        if isinstance(rec, Mapping):
            valid = _validated_profile(rec)
            if valid:
                valid["profile_key"] = key
                return valid
    return {}


def config_path_from_profile(profile: Mapping[str, Any]) -> str:
    cfg = profile.get("config") if isinstance(profile, Mapping) else None
    if not isinstance(cfg, Mapping):
        return ""
    p = Path(str(cfg.get("managed_path") or ""))
    return str(p) if p.is_file() else ""


def exact_binding_from_settings(settings: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(settings, Mapping):
        return {}
    rec = settings.get("racepak_ddf_config")
    if not isinstance(rec, Mapping):
        return {}
    cfg = rec.get("config") if isinstance(rec.get("config"), Mapping) else rec
    if not isinstance(cfg, Mapping):
        return {}
    p = Path(str(cfg.get("managed_path") or ""))
    digest = str(cfg.get("sha256") or "")
    if not p.is_file() or not digest:
        return {}
    try:
        if sha256(p.read_bytes()).hexdigest() != digest:
            return {}
    except Exception:
        return {}
    return dict(rec)


def exact_binding_record(config_path: str | Path | Mapping[str, Any], *, source: str = "explicit") -> dict[str, Any]:
    if isinstance(config_path, Mapping):
        cfg = dict(config_path)
        managed = Path(str(cfg.get("managed_path") or ""))
        digest = str(cfg.get("sha256") or "")
        if not managed.is_file() or not digest:
            raise ValueError("RacePak config record does not reference a valid managed file.")
        if sha256(managed.read_bytes()).hexdigest() != digest:
            raise ValueError("RacePak config managed copy failed SHA-256 verification.")
    else:
        cfg = inspect_racepak_config(config_path).to_dict()
    return {
        "source": source,
        "config": cfg,
        "pinned_at": _utc_now(),
    }


def resolve_config_path(
    record_or_run: Any,
    *,
    session_settings: Mapping[str, Any] | None = None,
    path: Optional[Path] = None,
) -> tuple[str, str, dict[str, Any]]:
    """Return ``(managed_path, source, record)`` using conservative precedence.

    Exact data-log binding wins; then a matching contextual profile.  No vendor-
    global fallback exists here.  Sibling discovery remains parser-local and is
    only used when neither saved layer has an answer.
    """
    exact = exact_binding_from_settings(session_settings)
    if exact:
        cfg = exact.get("config") if isinstance(exact.get("config"), Mapping) else exact
        managed = str(cfg.get("managed_path") or "") if isinstance(cfg, Mapping) else ""
        if managed:
            return managed, "exact_data_log", exact
    profile = matching_profile(record_or_run, path=path)
    managed = config_path_from_profile(profile)
    if managed:
        return managed, "context_profile", profile
    return "", "", {}
