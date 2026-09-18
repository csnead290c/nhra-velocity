from __future__ import annotations

"""RacePak corpus evidence for recovering missing DDF definitions safely.

Raw RacePak ``.ddf`` recordings preserve numeric ``_CONNECT4_COMMAND`` channel
ids, sample rates, scaling flags and descriptor order.  A matching ``.rcg`` or
self-describing ``.rpk`` provides the human-readable source channel names and
units.

This module deliberately separates two kinds of corpus knowledge:

1. **Channel-id history** -- useful evidence only.  Seeing one numeric id called
   ``OIL PRESSURE`` in many configurations never makes that id a global truth.
   ID-only history is surfaced as a suggestion/provenance aid and is *never*
   used to rename an otherwise unknown DDF channel automatically.
2. **Exact DDF descriptor fingerprints** -- a much stronger relationship.  When
   NHRA already has a DDF whose complete raw descriptor table has been bound to
   an unambiguous sibling RCG, that exact descriptor SHA-256 may safely recover
   source names/units for another DDF with the identical descriptor table.  Any
   conflicting definition observed for the same fingerprint disables automatic
   recovery.

Neither layer assigns VELOCITY Common Channels.  Source identity and engineering
role remain separate concepts.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import mmap
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable, Mapping, Sequence

from .diagnostics import app_data_root
from .racepak import _attribute, parse_channel_definitions
from .racepak_ddf import DdfStructure, parse_ddf_structure
from .units import normalize_unit

LIBRARY_VERSION = 2


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _name_key(name: str) -> str:
    # Normalize spelling/punctuation only.  Do NOT merge semantically similar
    # names such as RPM / Engine Speed / Tach.
    return re.sub(r"[^a-z0-9]+", " ", str(name or "").strip().lower()).strip()


def _unit_key(unit: str) -> str:
    raw = str(unit or "").strip()
    if not raw:
        return ""
    return normalize_unit(raw) or raw.lower()


def _channel_id(definition) -> int | None:
    raw = _attribute(definition.description, "_CONNECT4_COMMAND")
    if raw in (None, ""):
        return None
    try:
        return int(str(raw), 0)
    except Exception:
        return None


def _source_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    return "RCG" if suffix == ".rcg" else "RPK" if suffix == ".rpk" else suffix.lstrip(".").upper()


def _config_signature(rows: Sequence[tuple[int, str, str, str, float | None]]) -> str:
    """Semantic configuration signature used only to de-duplicate evidence.

    The signature includes names/units/storage/rates because two files with the
    same physical slot layout but different semantics must count as different
    evidence, not as repeated copies of one configuration.
    """
    payload = [
        [int(cid), name_key, unit_key, storage, None if rate is None else round(float(rate), 9)]
        for cid, name_key, unit_key, storage, rate in sorted(rows, key=lambda r: (r[0], r[1], r[2], r[3]))
    ]
    return sha256(json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RacePakDefinitionEvidence:
    channel_id: int
    name: str
    normalized_name: str
    unit: str
    storage_type: str
    sample_rate_hz: float | None
    source_path: str
    source_kind: str
    config_signature: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RacePakChannelEvidenceSummary:
    channel_id: int
    suggested_name: str
    suggested_unit: str
    evidence_level: str
    suggestion_only: bool
    automatic_naming_allowed: bool
    distinct_configurations: int
    file_occurrences: int
    distinct_names: tuple[str, ...]
    distinct_units: tuple[str, ...]
    sample_rates_hz: tuple[float, ...]
    source_kinds: tuple[str, ...]
    example_files: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for key in ("distinct_names", "distinct_units", "sample_rates_hz", "source_kinds", "example_files"):
            d[key] = list(d[key])
        return d


def inspect_definition_source(path: str | Path) -> tuple[list[RacePakDefinitionEvidence], list[str]]:
    """Extract channel-id evidence from one RCG/RPK without loading huge RPKs into RAM."""
    source = Path(path).expanduser().resolve()
    if source.suffix.lower() not in {".rcg", ".rpk"}:
        return [], [f"{source}: not an RCG/RPK definition source"]
    if not source.is_file():
        return [], [f"{source}: file not found"]
    if source.stat().st_size <= 0:
        return [], [f"{source}: empty file"]

    try:
        with source.open("rb") as fh:
            with mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                definitions = parse_channel_definitions(mm)
    except Exception as exc:
        return [], [f"{source}: {exc}"]

    raw_rows: list[tuple[int, str, str, str, float | None, Any]] = []
    counts: dict[int, int] = {}
    for definition in definitions:
        cid = _channel_id(definition)
        if cid is None:
            continue
        counts[cid] = counts.get(cid, 0) + 1
        name = str(definition.name or "").strip()
        unit = _unit_key(definition.unit)
        rate = float(definition.sample_rate_hz) if definition.sample_rate_hz else None
        raw_rows.append((cid, _name_key(name), unit, str(definition.storage_type or ""), rate, definition))

    duplicates = {cid for cid, count in counts.items() if count > 1}
    warnings: list[str] = []
    if duplicates:
        warnings.append(
            f"{source}: duplicate _CONNECT4_COMMAND ids excluded from evidence: "
            + ", ".join(str(x) for x in sorted(duplicates)[:20])
        )
    usable = [r for r in raw_rows if r[0] not in duplicates]
    if not usable:
        if not warnings:
            warnings.append(f"{source}: no usable _CONNECT4_COMMAND channel definitions found")
        return [], warnings

    signature = _config_signature([(a, b, c, d, e) for a, b, c, d, e, _ in usable])
    evidence: list[RacePakDefinitionEvidence] = []
    for cid, name_key, unit, storage, rate, definition in usable:
        evidence.append(
            RacePakDefinitionEvidence(
                channel_id=cid,
                name=str(definition.name or "").strip(),
                normalized_name=name_key,
                unit=unit,
                storage_type=storage,
                sample_rate_hz=rate,
                source_path=str(source),
                source_kind=_source_kind(source),
                config_signature=signature,
            )
        )
    return evidence, warnings


def _corpus_files(paths: Iterable[str | Path], recursive: bool) -> tuple[list[Path], list[Path], list[Path]]:
    rcg: list[Path] = []
    rpk: list[Path] = []
    ddf: list[Path] = []
    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_dir():
            iterator = p.rglob("*") if recursive else p.glob("*")
            items = (x for x in iterator if x.is_file())
        elif p.is_file():
            items = (p,)
        else:
            continue
        for item in items:
            suffix = item.suffix.lower()
            if suffix == ".rcg":
                rcg.append(item.resolve())
            elif suffix == ".rpk":
                rpk.append(item.resolve())
            elif suffix == ".ddf":
                ddf.append(item.resolve())
    key = lambda x: str(x).lower()
    return sorted(set(rcg), key=key), sorted(set(rpk), key=key), sorted(set(ddf), key=key)


def _quick_rpk_selection(files: Sequence[Path], limit: int = 250) -> list[Path]:
    """One representative RPK per leaf folder, capped deterministically."""
    by_parent: dict[str, list[Path]] = {}
    for path in files:
        by_parent.setdefault(str(path.parent).lower(), []).append(path)
    reps = [sorted(items, key=lambda x: x.name.lower())[len(items) // 2] for _, items in sorted(by_parent.items())]
    if limit <= 0 or len(reps) <= limit:
        return reps
    if limit == 1:
        return [reps[len(reps) // 2]]
    indexes = [round(i * (len(reps) - 1) / (limit - 1)) for i in range(limit)]
    return [reps[int(i)] for i in indexes]


def channel_evidence_from_records(evidence: Sequence[RacePakDefinitionEvidence]) -> list[RacePakChannelEvidenceSummary]:
    """Summarize ID history without ever granting ID-only naming authority."""
    by_id: dict[int, list[RacePakDefinitionEvidence]] = {}
    for rec in evidence:
        by_id.setdefault(int(rec.channel_id), []).append(rec)

    out: list[RacePakChannelEvidenceSummary] = []
    for cid, rows in sorted(by_id.items()):
        # One semantic configuration gets one vote. Repeated run files from one
        # configuration cannot manufacture apparent confidence.
        by_config: dict[str, list[RacePakDefinitionEvidence]] = {}
        for row in rows:
            by_config.setdefault(row.config_signature, []).append(row)
        votes = [items[0] for items in by_config.values()]

        names = sorted({r.normalized_name for r in votes if r.normalized_name})
        units = sorted({r.unit for r in votes if r.unit})
        rates = sorted({round(float(r.sample_rate_hz), 9) for r in votes if r.sample_rate_hz})
        config_count = len(by_config)
        conflict = len(names) > 1 or len(units) > 1
        if conflict:
            level = "conflict"
        elif config_count >= 3:
            level = "consistent-3plus"
        elif config_count == 2:
            level = "consistent-2"
        else:
            level = "single-source"

        suggested_name = ""
        if len(names) == 1:
            matching = [r.name for r in rows if r.normalized_name == names[0] and r.name]
            if matching:
                counts: dict[str, int] = {}
                for name in matching:
                    counts[name] = counts.get(name, 0) + 1
                suggested_name = sorted(counts, key=lambda n: (-counts[n], n.lower(), n))[0]
        suggested_unit = units[0] if len(units) == 1 else ""
        examples = tuple(dict.fromkeys(Path(r.source_path).name for r in rows))[:5]
        out.append(
            RacePakChannelEvidenceSummary(
                channel_id=cid,
                suggested_name=suggested_name,
                suggested_unit=suggested_unit,
                evidence_level=level,
                suggestion_only=True,
                automatic_naming_allowed=False,
                distinct_configurations=config_count,
                file_occurrences=len({r.source_path for r in rows}),
                distinct_names=tuple(names),
                distinct_units=tuple(units),
                sample_rates_hz=tuple(rates),
                source_kinds=tuple(sorted({r.source_kind for r in rows})),
                example_files=examples,
            )
        )
    return out


def _rows_match_ddf(rows: Sequence[RacePakDefinitionEvidence], structure: DdfStructure) -> bool:
    """Return True only when one config fully identifies every recorded DDF channel.

    This is intentionally stricter than a partial/fuzzy match: every recorded
    DDF id must exist and every configuration sample rate must be known and
    exactly equal. Extra config channels are allowed because DataLink configs
    can contain channels that were not active in a particular recording.
    """
    by_id = {int(r.channel_id): r for r in rows}
    if len(by_id) != len(rows):
        return False
    for desc in structure.recorded_descriptors:
        rec = by_id.get(int(desc.channel_id))
        if rec is None or rec.sample_rate_hz is None:
            return False
        if abs(float(rec.sample_rate_hz) - float(desc.sample_rate_hz)) > 1e-6:
            return False
    return True


def _descriptor_profile_from_evidence(
    descriptor_signature: str,
    structure: DdfStructure,
    candidates: Sequence[tuple[Path, Sequence[RacePakDefinitionEvidence]]],
    ddf_paths: Sequence[Path],
) -> dict[str, Any]:
    """Build an exact-descriptor profile from one or more known config bindings."""
    usable: list[tuple[Path, Sequence[RacePakDefinitionEvidence]]] = [
        (path, rows) for path, rows in candidates if _rows_match_ddf(rows, structure)
    ]
    # De-duplicate repeated copies of the same semantic config.
    by_config: dict[str, tuple[Path, Sequence[RacePakDefinitionEvidence]]] = {}
    for path, rows in usable:
        if rows:
            by_config.setdefault(rows[0].config_signature, (path, rows))

    per_id: dict[int, dict[str, set[str]]] = {}
    human_name: dict[int, list[str]] = {}
    sample_rate: dict[int, float] = {int(d.channel_id): float(d.sample_rate_hz) for d in structure.recorded_descriptors}
    for _, rows in by_config.values():
        row_map = {int(r.channel_id): r for r in rows}
        for desc in structure.recorded_descriptors:
            rec = row_map[int(desc.channel_id)]
            bucket = per_id.setdefault(int(desc.channel_id), {"names": set(), "units": set()})
            if rec.normalized_name:
                bucket["names"].add(rec.normalized_name)
            if rec.unit:
                bucket["units"].add(rec.unit)
            if rec.name:
                human_name.setdefault(int(desc.channel_id), []).append(rec.name)

    conflict = False
    channel_defs: list[dict[str, Any]] = []
    for desc in structure.recorded_descriptors:
        cid = int(desc.channel_id)
        bucket = per_id.get(cid, {"names": set(), "units": set()})
        names = sorted(bucket["names"])
        units = sorted(bucket["units"])
        if len(names) != 1 or len(units) > 1:
            conflict = True
        display_name = ""
        if len(names) == 1:
            spellings = human_name.get(cid, [])
            counts: dict[str, int] = {}
            for name in spellings:
                counts[name] = counts.get(name, 0) + 1
            if counts:
                display_name = sorted(counts, key=lambda n: (-counts[n], n.lower(), n))[0]
        channel_defs.append(
            {
                "channel_id": cid,
                "name": display_name,
                "unit": units[0] if len(units) == 1 else "",
                "sample_rate_hz": sample_rate[cid],
                "distinct_names": names,
                "distinct_units": units,
            }
        )

    # Exact descriptor recovery is only allowed when at least one real DDF has
    # been bound to a matching sibling RCG and every observed definition for the
    # exact same descriptor table agrees.  ID frequency by itself never enters
    # this decision.
    safe = bool(by_config) and not conflict and all(str(row.get("name") or "").strip() for row in channel_defs)
    return {
        "descriptor_signature_sha256": descriptor_signature,
        "safe_for_exact_descriptor_recovery": safe,
        "confidence": "exact-descriptor-conflict" if conflict else ("exact-descriptor-known" if by_config else "unbound"),
        "recorded_channel_count": len(structure.recorded_descriptors),
        "distinct_bound_configurations": len(by_config),
        "known_ddf_occurrences": len({str(p) for p in ddf_paths}),
        "channels": channel_defs,
        "config_examples": [str(path.name) for path, _ in list(by_config.values())[:5]],
        "ddf_examples": [str(path.name) for path in list(ddf_paths)[:5]],
    }


def _build_descriptor_profiles(
    ddf_files: Sequence[Path],
    rcg_evidence_by_path: Mapping[str, Sequence[RacePakDefinitionEvidence]],
) -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    """Learn exact DDF descriptor fingerprints only from sibling RCG evidence.

    We intentionally do not infer a pairing between arbitrary RPKs and DDFs.
    A DDF contributes to an automatic corpus profile only when its own folder
    contains one or more RCGs that fully match all recorded ids and rates.
    """
    rcg_by_parent: dict[str, list[Path]] = {}
    for source in rcg_evidence_by_path:
        p = Path(source)
        rcg_by_parent.setdefault(str(p.parent).lower(), []).append(p)

    grouped: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    scanned = 0
    with_sibling_rcg = 0
    bound_occurrences = 0
    for ddf in ddf_files:
        siblings = rcg_by_parent.get(str(ddf.parent).lower(), [])
        if not siblings:
            continue
        with_sibling_rcg += 1
        try:
            structure = parse_ddf_structure(ddf)
            scanned += 1
        except Exception as exc:
            warnings.append(f"{ddf}: descriptor fingerprint scan failed: {exc}")
            continue
        candidates = [(rcg, rcg_evidence_by_path.get(str(rcg), ())) for rcg in siblings]
        matching = [(p, rows) for p, rows in candidates if rows and _rows_match_ddf(rows, structure)]
        if not matching:
            continue
        bound_occurrences += 1
        bucket = grouped.setdefault(
            structure.descriptor_signature,
            {"structure": structure, "configs": {}, "ddfs": []},
        )
        bucket["ddfs"].append(ddf)
        for p, rows in matching:
            if rows:
                bucket["configs"].setdefault(rows[0].config_signature, (p, rows))

    profiles: list[dict[str, Any]] = []
    for signature, bucket in sorted(grouped.items()):
        profile = _descriptor_profile_from_evidence(
            signature,
            bucket["structure"],
            list(bucket["configs"].values()),
            bucket["ddfs"],
        )
        profiles.append(profile)

    stats = {
        "ddf_files_with_sibling_rcg": with_sibling_rcg,
        "ddf_descriptor_headers_scanned": scanned,
        "ddf_occurrences_with_matching_sibling_rcg": bound_occurrences,
        "exact_descriptor_profiles": len(profiles),
        "safe_exact_descriptor_profiles": sum(1 for p in profiles if p.get("safe_for_exact_descriptor_recovery")),
        "conflicted_exact_descriptor_profiles": sum(1 for p in profiles if p.get("confidence") == "exact-descriptor-conflict"),
    }
    return profiles, stats, warnings


def build_channel_id_census(
    paths: Iterable[str | Path],
    *,
    recursive: bool = True,
    rpk_mode: str = "quick",
    rpk_quick_limit: int = 250,
) -> dict[str, Any]:
    """Build RacePak channel-id evidence plus exact descriptor fingerprints.

    ``rpk_mode`` controls definition-history mining only:
      * ``none``  - RCG files only
      * ``quick`` - every RCG + one representative RPK per folder, capped
      * ``all``   - every RCG and every RPK

    DDF descriptor fingerprint discovery reads only descriptor tables from DDFs
    that have sibling RCG candidates; source files are never modified.
    """
    mode = str(rpk_mode or "quick").strip().lower()
    if mode not in {"none", "quick", "all"}:
        raise ValueError("rpk_mode must be one of: none, quick, all")
    roots = [Path(p) for p in paths]
    rcg_files, rpk_files, ddf_files = _corpus_files(roots, recursive)
    if mode == "none":
        selected_rpk: list[Path] = []
    elif mode == "all":
        selected_rpk = list(rpk_files)
    else:
        selected_rpk = _quick_rpk_selection(rpk_files, int(rpk_quick_limit or 0))

    selected = [*rcg_files, *selected_rpk]
    evidence: list[RacePakDefinitionEvidence] = []
    warnings: list[str] = []
    parse_failures = 0
    usable_sources = 0
    source_evidence: dict[str, list[RacePakDefinitionEvidence]] = {}
    for source in selected:
        rows, issues = inspect_definition_source(source)
        warnings.extend(issues)
        if rows:
            usable_sources += 1
            evidence.extend(rows)
            source_evidence[str(source)] = rows
        else:
            parse_failures += 1

    channel_summary = channel_evidence_from_records(evidence)
    # Descriptor profiles use RCG evidence only because those pairings are
    # physically local and explicit. Arbitrary RPK-to-DDF pairing would be an
    # inference and is intentionally not used for automatic recovery.
    rcg_evidence = {str(p): source_evidence.get(str(p), []) for p in rcg_files if source_evidence.get(str(p))}
    descriptor_profiles, descriptor_stats, descriptor_warnings = _build_descriptor_profiles(ddf_files, rcg_evidence)
    warnings.extend(descriptor_warnings)

    return {
        "version": LIBRARY_VERSION,
        "generated_at": _utc_now(),
        "policy": {
            "channel_id_history_is_suggestion_only": True,
            "channel_id_history_automatic_naming": "never",
            "exact_descriptor_recovery_requires_known_matching_sibling_rcg": True,
            "exact_descriptor_recovery_fails_closed_on_conflict": True,
            "partial_layout_matching_automatic_naming": "never",
            "common_channel_assignment": "never automatic from RacePak corpus evidence",
        },
        "scan": {
            "roots": [str(p) for p in roots],
            "recursive": bool(recursive),
            "rpk_mode": mode,
            "rcg_files_found": len(rcg_files),
            "rpk_files_found": len(rpk_files),
            "ddf_files_found": len(ddf_files),
            "rpk_files_scanned": len(selected_rpk),
            "definition_files_scanned": len(selected),
            "definition_files_with_evidence": usable_sources,
            "definition_files_without_evidence": parse_failures,
            "evidence_records": len(evidence),
            **descriptor_stats,
        },
        "summary": {
            "channel_ids": len(channel_summary),
            "consistent_3plus_ids": sum(1 for r in channel_summary if r.evidence_level == "consistent-3plus"),
            "consistent_2_ids": sum(1 for r in channel_summary if r.evidence_level == "consistent-2"),
            "single_source_ids": sum(1 for r in channel_summary if r.evidence_level == "single-source"),
            "conflicted_ids": sum(1 for r in channel_summary if r.evidence_level == "conflict"),
            "exact_descriptor_profiles": len(descriptor_profiles),
            "safe_exact_descriptor_profiles": sum(1 for p in descriptor_profiles if p.get("safe_for_exact_descriptor_recovery")),
        },
        "channels": [r.to_dict() for r in channel_summary],
        "descriptor_profiles": descriptor_profiles,
        "warnings": warnings,
    }


def default_library_path() -> Path:
    p = app_data_root() / "racepak_channel_evidence_library.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _legacy_library_path() -> Path:
    return app_data_root() / "racepak_channel_id_library.json"


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except Exception:
            pass
    return path


def save_census(payload: Mapping[str, Any], path: str | Path) -> Path:
    return _atomic_json(Path(path), payload)


def install_census(
    payload: Mapping[str, Any],
    path: str | Path | None = None,
    *,
    allow_empty: bool = False,
) -> Path:
    """Install corpus evidence used by exact-descriptor recovery and suggestions.

    An empty/failed scan must never erase a previously useful evidence library.
    Callers that intentionally need to clear the library must opt in explicitly.
    """
    channels = payload.get("channels", []) if isinstance(payload, Mapping) else []
    profiles = payload.get("descriptor_profiles", []) if isinstance(payload, Mapping) else []
    if not allow_empty and not channels and not profiles:
        raise ValueError("RacePak corpus scan produced no evidence; existing installed library was left unchanged")
    target = Path(path) if path is not None else default_library_path()
    installed = _atomic_json(target, payload)
    # A dev.22 v1 library could have allowed ID-only automatic naming.  Remove
    # that legacy default-path artifact when installing the v2 evidence model so
    # an older file cannot be mistaken for current authority by future code.
    if path is None:
        legacy = _legacy_library_path()
        if legacy != target and legacy.exists():
            try:
                legacy.unlink()
            except Exception:
                pass
    return installed


def load_census(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path is not None else default_library_path()
    if not p.is_file():
        return {}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(obj, dict) or int(obj.get("version", 0) or 0) != LIBRARY_VERSION:
        return {}
    return obj


def lookup_channel_evidence(channel_id: int, *, path: str | Path | None = None) -> dict[str, Any]:
    """Return corpus history for an id as *evidence only*.

    Callers must not use this function to rename a DDF channel automatically.
    The returned record explicitly carries ``automatic_naming_allowed=False``.
    """
    obj = load_census(path)
    for raw in obj.get("channels", []) if isinstance(obj.get("channels"), list) else []:
        if not isinstance(raw, Mapping):
            continue
        try:
            cid = int(raw.get("channel_id"))
        except Exception:
            continue
        if cid == int(channel_id):
            rec = dict(raw)
            rec["suggestion_only"] = True
            rec["automatic_naming_allowed"] = False
            return rec
    return {}


def lookup_exact_descriptor_profile(
    descriptor_signature_sha256: str,
    *,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Return a safe profile for an *exact* DDF descriptor-table fingerprint."""
    signature = str(descriptor_signature_sha256 or "").strip().lower()
    if not signature:
        return {}
    obj = load_census(path)
    for raw in obj.get("descriptor_profiles", []) if isinstance(obj.get("descriptor_profiles"), list) else []:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("descriptor_signature_sha256") or "").strip().lower() != signature:
            continue
        if bool(raw.get("safe_for_exact_descriptor_recovery")):
            return dict(raw)
        return {}
    return {}


def lookup_verified_channel(channel_id: int, *, path: str | Path | None = None) -> dict[str, Any]:
    """Compatibility shim: ID-only automatic naming is intentionally disabled.

    dev.22 exposed this helper.  It now always returns an empty mapping so code
    written against the old API cannot silently re-enable the unsafe behavior.
    Use :func:`lookup_channel_evidence` for suggestions or
    :func:`lookup_exact_descriptor_profile` for safe automatic recovery.
    """
    _ = (channel_id, path)
    return {}
