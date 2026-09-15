from __future__ import annotations

"""Development importer for authoritative NHRA event-run exports.

Production identity will come directly from NHRA Tech Services. The CSV path is
kept only as a development/validation bridge until the real API adapter is bound.
It never attaches telemetry or other engineering files to runs.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional
import csv
import hashlib
import math
import re

from .catalog import LocalCatalog, UNASSIGNED_EVENT_CODE


CATEGORY_ALIASES: Dict[str, str] = {
    "TF": "TOP FUEL",
    "FC": "FUNNY CAR",
    "PS": "PRO STOCK",
    "PSM": "PRO STOCK MOTORCYCLE",
    "PM": "PRO MOD",
    "FSS": "FACTORY STOCK SHOWDOWN",
    "TAD": "TOP ALCOHOL DRAGSTER",
    "TAFC": "TOP ALCOHOL FUNNY CAR",
    "TD": "TOP DRAGSTER",
    "TS": "TOP SPORTSMAN",
    "SC": "SUPER COMP",
    "SG": "SUPER GAS",
    "SST": "SUPER STREET",
    "STK": "STOCK",
    "SS": "SUPER STOCK",
}


@dataclass(frozen=True)
class OfficialRunRow:
    source_row: int
    run_datetime: str
    driver: str
    category_code: str
    category: str
    round: str
    lane: str
    timing: Dict[str, Any]


@dataclass
class OfficialImportResult:
    event_id: str
    event_name: str
    event_code: str
    source_path: str
    source_sha256: str
    rows_seen: int = 0
    rows_imported: int = 0
    duplicate_rows_merged: int = 0
    runs_created: int = 0
    runs_updated: int = 0
    drivers_created: int = 0
    entries_created: int = 0
    warnings: List[str] = field(default_factory=list)
    run_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "event_code": self.event_code,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "rows_seen": self.rows_seen,
            "rows_imported": self.rows_imported,
            "duplicate_rows_merged": self.duplicate_rows_merged,
            "runs_created": self.runs_created,
            "runs_updated": self.runs_updated,
            "drivers_created": self.drivers_created,
            "entries_created": self.entries_created,
            "warnings": list(self.warnings),
            "run_ids": list(self.run_ids),
        }


def _clean_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _value(row: Mapping[str, Any], *names: str) -> str:
    lookup = {_clean_header(k): v for k, v in row.items()}
    for name in names:
        val = lookup.get(_clean_header(name))
        if val is not None:
            return str(val).strip()
    return ""


def _float(value: Any) -> Optional[float]:
    if value is None or str(value).strip() == "":
        return None
    try:
        out = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def normalize_category(value: str, aliases: Mapping[str, str] | None = None) -> str:
    token = re.sub(r"\s+", " ", str(value or "").strip()).upper()
    mapping = dict(CATEGORY_ALIASES)
    if aliases:
        mapping.update({str(k).strip().upper(): str(v).strip().upper() for k, v in aliases.items()})
    return mapping.get(token, token)


def normalize_lane(value: str) -> str:
    token = str(value or "").strip().upper()
    return {"L": "Left", "LEFT": "Left", "R": "Right", "RIGHT": "Right"}.get(token, str(value or "").strip())


def _parse_time(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    # Preserve event-local wall-clock semantics.  Do not invent a timezone.
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"):
        try:
            return datetime.strptime(text, fmt).isoformat(timespec="seconds")
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text).isoformat(timespec="seconds")
    except ValueError:
        return text


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return text[:80] or "unknown"


def infer_event_code(path: str | Path) -> str:
    name = Path(path).stem
    m = re.search(r"event[-_ ]?runs[-_ ]?(\d{8,})", name, re.I)
    return m.group(1) if m else name.upper().replace(" ", "-")


def read_official_run_csv(path: str | Path, *, category_aliases: Mapping[str, str] | None = None) -> tuple[List[OfficialRunRow], List[str]]:
    source = Path(path)
    rows: List[OfficialRunRow] = []
    warnings: List[str] = []
    with source.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError("Official run CSV does not contain a header row")
        headers = {_clean_header(x) for x in reader.fieldnames}
        missing = [name for name in ("Time", "Driver", "Class") if _clean_header(name) not in headers]
        if missing:
            raise ValueError("Official run CSV is missing required column(s): " + ", ".join(missing))
        for source_row, raw in enumerate(reader, start=2):
            if not any(str(v or "").strip() for v in raw.values()):
                continue
            driver = _value(raw, "Driver")
            category_code = _value(raw, "Class")
            run_datetime = _parse_time(_value(raw, "Time"))
            if not driver or not category_code or not run_datetime:
                warnings.append(f"Row {source_row}: skipped because Time, Driver or Class is blank")
                continue
            timing: Dict[str, Any] = {
                "reaction_time_s": _float(_value(raw, "RT", "Reaction Time")),
                "sixty_ft_s": _float(_value(raw, "60ft", "60 ft")),
                "three_thirty_ft_s": _float(_value(raw, "330ft", "330 ft")),
                "eighth_mile_s": _float(_value(raw, "660ft", "660 ft")),
                "eighth_mile_mph": _float(_value(raw, "660 MPH", "660MPH")),
                "thousand_ft_s": _float(_value(raw, "1000ft", "1000 ft")),
                "quarter_mile_s": _float(_value(raw, "ET", "1320ft", "1320 ft")),
                "quarter_mile_mph": _float(_value(raw, "MPH", "1320 MPH")),
                "correction_factor": _float(_value(raw, "CF", "Correction Factor")),
            }
            timing = {k: v for k, v in timing.items() if v is not None}
            rows.append(
                OfficialRunRow(
                    source_row=source_row,
                    run_datetime=run_datetime,
                    driver=driver,
                    category_code=category_code.strip().upper(),
                    category=normalize_category(category_code, category_aliases),
                    round=_value(raw, "Rnd", "Round"),
                    lane=normalize_lane(_value(raw, "Ln", "Lane")),
                    timing=timing,
                )
            )
    return rows, warnings


def official_run_key(event_code: str, row: OfficialRunRow) -> str:
    stamp = re.sub(r"[^0-9]", "", row.run_datetime)[:14]
    return f"official:{_slug(event_code)}:{stamp}:{_slug(row.category_code)}:{_slug(row.round)}:{_slug(row.driver)}"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _coalesce_official_rows(event_code: str, rows: Iterable[OfficialRunRow]) -> tuple[List[tuple[OfficialRunRow, List[int]]], List[str], int]:
    """Merge repeated export rows that resolve to the same official run identity.

    Some NHRA event exports contain a complete timing row plus a later summary
    row for the same pass that carries only CF.  Treating those as sequential
    authoritative replacements would erase valid timing.  We therefore merge
    duplicate identities field-by-field, prefer the most complete row when two
    populated values conflict, and surface every true conflict as a warning.
    """
    grouped: Dict[str, List[OfficialRunRow]] = {}
    order: List[str] = []
    for row in rows:
        key = official_run_key(event_code, row)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(row)

    merged: List[tuple[OfficialRunRow, List[int]]] = []
    warnings: List[str] = []
    duplicate_count = 0
    for key in order:
        group = grouped[key]
        duplicate_count += max(0, len(group) - 1)
        # Start from the richest timing record. Ties keep the earliest row so
        # file ordering cannot unpredictably change canonical values.
        richest = max(group, key=lambda r: (len(r.timing), -r.source_row))
        timing = dict(richest.timing)
        for row in group:
            for name, value in row.timing.items():
                if name not in timing:
                    timing[name] = value
                    continue
                current = timing[name]
                try:
                    differs = not math.isclose(float(current), float(value), rel_tol=1e-9, abs_tol=1e-12)
                except Exception:
                    differs = current != value
                if differs:
                    warnings.append(
                        f"Rows {richest.source_row} and {row.source_row}: conflicting {name} for {key}; "
                        f"kept value from the more complete row ({current!r} vs {value!r})"
                    )
        lanes = {r.lane for r in group if r.lane}
        if len(lanes) > 1:
            warnings.append(f"Rows {', '.join(str(r.source_row) for r in group)}: conflicting lane values for {key}: {sorted(lanes)}")
        representative = OfficialRunRow(
            source_row=richest.source_row,
            run_datetime=richest.run_datetime,
            driver=richest.driver,
            category_code=richest.category_code,
            category=richest.category,
            round=richest.round,
            lane=richest.lane,
            timing=timing,
        )
        merged.append((representative, [r.source_row for r in group]))
    return merged, warnings, duplicate_count


def import_official_run_csv(
    catalog: LocalCatalog,
    path: str | Path,
    *,
    event_name: str = "",
    event_code: str = "",
    season: int | None = None,
    track_name: str = "",
    track_id: str = "",
    location: str = "",
    category_aliases: Mapping[str, str] | None = None,
) -> OfficialImportResult:
    source = Path(path).expanduser().resolve()
    parsed, warnings = read_official_run_csv(source, category_aliases=category_aliases)
    code = str(event_code or infer_event_code(source)).strip()
    if not code:
        raise ValueError("An event code is required for deterministic official-run identity")
    if season is None:
        try:
            season = int(parsed[0].run_datetime[:4]) if parsed else None
        except Exception:
            season = None
    name = str(event_name or f"NHRA Event {code}").strip()
    event_id = catalog.upsert_event(
        name,
        season=season,
        event_code=code,
        track_name=track_name,
        track_id=track_id,
        location=location,
        sync_state="official",
    )
    digest = _sha256(source)
    parse_skips = sum(1 for warning in warnings if "skipped because" in warning)
    merged_rows, merge_warnings, duplicate_count = _coalesce_official_rows(code, parsed)
    warnings.extend(merge_warnings)
    result = OfficialImportResult(
        event_id, name, code, str(source), digest,
        rows_seen=len(parsed) + parse_skips,
        duplicate_rows_merged=duplicate_count,
        warnings=warnings,
    )
    known_drivers = {str(x.get("name", "")).strip().lower() for x in catalog.list_drivers()}
    known_entries = {(str(x.get("event_id")), str(x.get("driver_id")), str(x.get("category", "")).upper()) for x in catalog.list_entries(event_id=event_id)}

    for row, source_rows in merged_rows:
        driver_was_new = row.driver.strip().lower() not in known_drivers
        driver_id = catalog.find_or_create_driver(row.driver)
        if driver_was_new:
            result.drivers_created += 1
            known_drivers.add(row.driver.strip().lower())
        entry_key = (event_id, driver_id, row.category.upper())
        entry_was_new = entry_key not in known_entries
        entry_id = catalog.find_or_create_entry(event_id, driver_id=driver_id, category=row.category)
        if entry_was_new:
            result.entries_created += 1
            known_entries.add(entry_key)

        key = official_run_key(code, row)
        source_meta = {
            "kind": "nhra_official_run_csv",
            "filename": source.name,
            "sha256": digest,
            "row": row.source_row,
            "source_rows": source_rows,
            "event_code": code,
            "source_class": row.category_code,
        }
        run_id, created = catalog.upsert_run(
            run_key=key,
            event_id=event_id,
            entry_id=entry_id,
            driver_id=driver_id,
            run_datetime=row.run_datetime,
            round=row.round,
            lane=row.lane,
            category=row.category,
            timing=row.timing,
            timing_provenance="official",
            source=source_meta,
            sync_state="official",
        )
        result.rows_imported += 1
        result.runs_created += int(created)
        result.runs_updated += int(not created)
        result.run_ids.append(run_id)
    return result
