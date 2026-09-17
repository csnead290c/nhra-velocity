from __future__ import annotations

"""Empirical RacePak channel-id knowledge built from NHRA's own corpus.

RacePak raw DDF recordings expose stable ``_CONNECT4_COMMAND`` channel ids but
not necessarily the human-readable names/units carried by a matching RCG/RPK
configuration.  This module mines trusted RCG/RPK definitions and builds a
*consensus* dictionary by channel id.

The library is intentionally conservative:

* repeated runs from one identical configuration do not out-vote other cars;
  evidence is counted by distinct definition/config signatures;
* only conflict-free ids seen in at least three distinct configurations are
  eligible for automatic fallback naming;
* two-source agreement is retained as a useful suggestion but is not applied
  automatically;
* conflicting ids are never guessed; and
* this layer supplies source-channel identity only.  It never assigns a
  VELOCITY Common Channel engineering role.
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
from .units import normalize_unit

LIBRARY_VERSION = 1
_AUTO_MIN_CONFIGS = 3


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _name_key(name: str) -> str:
    # Normalize spelling/punctuation only.  Do NOT turn semantically similar
    # names (RPM/Engine Speed/etc.) into the same thing by fuzzy logic.
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
class RacePakChannelConsensus:
    channel_id: int
    consensus_name: str
    consensus_unit: str
    confidence: str
    safe_for_fallback: bool
    distinct_configurations: int
    file_occurrences: int
    distinct_names: tuple[str, ...]
    distinct_units: tuple[str, ...]
    sample_rates_hz: tuple[float, ...]
    source_kinds: tuple[str, ...]
    example_files: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # JSON/CSV friendliness.
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
    warnings = []
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


def _definition_files(paths: Iterable[str | Path], recursive: bool) -> tuple[list[Path], list[Path]]:
    rcg: list[Path] = []
    rpk: list[Path] = []
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
    key = lambda x: str(x).lower()
    return sorted(set(rcg), key=key), sorted(set(rpk), key=key)


def _quick_rpk_selection(files: Sequence[Path], limit: int = 250) -> list[Path]:
    """One representative RPK per leaf folder, capped deterministically.

    RPKs can be tens of MB each.  RCGs are always scanned in full; quick mode
    samples RPK folders to extend coverage without reading tens of gigabytes.
    Full mode scans every RPK.
    """
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


def consensus_from_evidence(evidence: Sequence[RacePakDefinitionEvidence]) -> list[RacePakChannelConsensus]:
    by_id: dict[int, list[RacePakDefinitionEvidence]] = {}
    for rec in evidence:
        by_id.setdefault(int(rec.channel_id), []).append(rec)

    out: list[RacePakChannelConsensus] = []
    for cid, rows in sorted(by_id.items()):
        # Each distinct config gets one vote. Repeated race files from one team
        # cannot manufacture confidence merely by occurring more often.
        by_config: dict[str, list[RacePakDefinitionEvidence]] = {}
        for row in rows:
            by_config.setdefault(row.config_signature, []).append(row)
        votes = [items[0] for items in by_config.values()]

        names = sorted({r.normalized_name for r in votes if r.normalized_name})
        units = sorted({r.unit for r in votes if r.unit})
        rates = sorted({round(float(r.sample_rate_hz), 9) for r in votes if r.sample_rate_hz})
        conflict = len(names) != 1 or len(units) > 1
        config_count = len(by_config)
        if conflict:
            confidence = "conflict"
        elif config_count >= _AUTO_MIN_CONFIGS:
            confidence = "verified"
        elif config_count >= 2:
            confidence = "supported"
        else:
            confidence = "single-source"

        consensus_name = ""
        if len(names) == 1:
            matching = [r.name for r in rows if r.normalized_name == names[0] and r.name]
            if matching:
                # Favor the most common human spelling, deterministic on ties.
                counts: dict[str, int] = {}
                for name in matching:
                    counts[name] = counts.get(name, 0) + 1
                consensus_name = sorted(counts, key=lambda n: (-counts[n], n.lower(), n))[0]
        consensus_unit = units[0] if len(units) == 1 else ""
        examples = tuple(dict.fromkeys(Path(r.source_path).name for r in rows))[:5]
        out.append(
            RacePakChannelConsensus(
                channel_id=cid,
                consensus_name=consensus_name,
                consensus_unit=consensus_unit,
                confidence=confidence,
                safe_for_fallback=bool(confidence == "verified" and consensus_name),
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


def build_channel_id_census(
    paths: Iterable[str | Path],
    *,
    recursive: bool = True,
    rpk_mode: str = "quick",
    rpk_quick_limit: int = 250,
) -> dict[str, Any]:
    """Scan available definition sources and return a consensus payload.

    ``rpk_mode``:
      * ``none``  - RCG files only
      * ``quick`` - every RCG + one representative RPK per folder, capped
      * ``all``   - every RCG and every RPK
    """
    mode = str(rpk_mode or "quick").strip().lower()
    if mode not in {"none", "quick", "all"}:
        raise ValueError("rpk_mode must be one of: none, quick, all")
    rcg_files, rpk_files = _definition_files(paths, recursive)
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
    for source in selected:
        rows, issues = inspect_definition_source(source)
        warnings.extend(issues)
        if rows:
            usable_sources += 1
            evidence.extend(rows)
        else:
            parse_failures += 1

    consensus = consensus_from_evidence(evidence)
    return {
        "version": LIBRARY_VERSION,
        "generated_at": _utc_now(),
        "policy": {
            "automatic_fallback_min_distinct_configurations": _AUTO_MIN_CONFIGS,
            "automatic_fallback_requires_conflict_free_name": True,
            "automatic_fallback_requires_conflict_free_unit_when_unit_is_known": True,
            "common_channel_assignment": "never automatic from RacePak numeric id",
        },
        "scan": {
            "recursive": bool(recursive),
            "rpk_mode": mode,
            "rcg_files_found": len(rcg_files),
            "rpk_files_found": len(rpk_files),
            "rpk_files_scanned": len(selected_rpk),
            "definition_files_scanned": len(selected),
            "definition_files_with_evidence": usable_sources,
            "definition_files_without_evidence": parse_failures,
            "evidence_records": len(evidence),
        },
        "summary": {
            "channel_ids": len(consensus),
            "verified_ids": sum(1 for r in consensus if r.confidence == "verified"),
            "supported_ids": sum(1 for r in consensus if r.confidence == "supported"),
            "single_source_ids": sum(1 for r in consensus if r.confidence == "single-source"),
            "conflicted_ids": sum(1 for r in consensus if r.confidence == "conflict"),
        },
        "channels": [r.to_dict() for r in consensus],
        "warnings": warnings,
    }


def default_library_path() -> Path:
    p = app_data_root() / "racepak_channel_id_library.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


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


def install_census(payload: Mapping[str, Any], path: str | Path | None = None) -> Path:
    """Install a consensus library used only as a low-authority DDF fallback."""
    return _atomic_json(Path(path) if path is not None else default_library_path(), payload)


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


def lookup_verified_channel(channel_id: int, *, path: str | Path | None = None) -> dict[str, Any]:
    """Return a conflict-free empirically verified source definition.

    This deliberately does not return two-source/single-source guesses.  Exact
    RCG/RPK bindings and context profiles remain higher authority in the DDF
    importer; this function is only consulted when those are absent.
    """
    obj = load_census(path)
    for raw in obj.get("channels", []) if isinstance(obj.get("channels"), list) else []:
        if not isinstance(raw, Mapping):
            continue
        try:
            cid = int(raw.get("channel_id"))
        except Exception:
            continue
        if cid == int(channel_id) and bool(raw.get("safe_for_fallback")):
            return dict(raw)
    return {}
