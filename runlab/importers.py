from __future__ import annotations

import csv
import io
import os
import re
import zipfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Iterable, Any

import numpy as np
import pandas as pd

from .models import TelemetryRun
from .import_registry import spec_for_path, telemetry_candidate, pending_message
from .units import (
    CANONICAL_TARGET_UNITS, compatible, convert_value, extract_unit_from_label,
    normalize_unit, plausible_range, display_label,
)


CANONICAL_CHANNELS: Dict[str, List[str]] = {
    "time_s": [
        "time", "elapsed time", "elapsed", "time sec", "time s", "seconds", "sec", "timestamp",
    ],
    "engine_rpm": [
        "engine rpm", "eng rpm", "rpm engine", "motor rpm", "engine speed", "engine", "rpm",
    ],
    "driveshaft_rpm": [
        "driveshaft rpm", "drive shaft rpm", "drive shaft", "driveshaft", "shaft rpm", "ds rpm", "propshaft rpm", "prop shaft rpm",
    ],
    "speed_mph": [
        "vehicle speed", "ground speed", "gps speed", "speed mph", "vehicle mph", "gps mph", "fw speed", "front wheel speed", "mph", "speed",
    ],
    "gear": ["gear", "current gear", "selected gear"],
    "throttle_pct": ["throttle", "throttle position", "tps", "tps pct", "throttle pct", "pedal"],
    "longitudinal_g": ["longitudinal g", "long accel", "longitudinal accel", "accel g", "g force x", "gx", "g meter", "g-meter"],
    "boost_psi": ["boost", "boost pressure", "manifold pressure", "map psi", "boost psi"],
    "lambda": ["lambda", "afr lambda", "wideband lambda"],
    "afr": ["afr", "air fuel ratio", "a f ratio"],
    "wheel_speed_mph": ["wheel speed", "rear wheel speed", "driven wheel speed"],
    "clutch_rpm": ["clutch rpm", "input shaft rpm"],
    "lateral_g": ["lateral g", "lat accel", "lateral accel", "accel y", "g force y", "gy"],
    "vertical_g": ["vertical g", "vert accel", "vertical accel", "accel z", "g force z", "gz"],
    "gps_latitude_deg": ["gps latitude", "latitude", "lat gps", "gps lat"],
    "gps_longitude_deg": ["gps longitude", "longitude", "lon gps", "long gps", "gps lon", "gps long"],
    "heading_deg": ["heading", "gps heading", "course", "course over ground"],
    "altitude_ft": ["altitude", "gps altitude", "height", "gps height"],
    "yaw_rate_degps": ["yaw rate", "yaw velocity", "yaw speed"],
    "battery_voltage": ["battery voltage", "battery volts", "batt voltage", "batt volts", "system voltage", "ecu voltage"],
    "brake_pressure_psi": ["brake pressure", "brake psi", "front brake pressure", "rear brake pressure"],
    "steering_angle_deg": ["steering angle", "steer angle", "steering"],
    "power_hp": ["engine power", "power hp", "horsepower", "bhp", "wheel horsepower", "whp", "power"],
    "torque_lbft": ["engine torque", "torque lb ft", "torque lb-ft", "torque", "wheel torque"],
    "ignition_timing_deg": ["ignition timing", "ign timing", "spark timing", "spark advance", "timing advance", "efi ign timing"],
    "oil_pressure_psi": ["oil pressure", "oil psi", "engine oil pressure"],
    "fuel_pressure_psi": ["fuel pressure", "fuel psi", "fuel rail pressure", "rail pressure"],
    "coolant_temp_f": ["coolant temp", "coolant temperature", "water temp", "engine coolant temp"],
    "oil_temp_f": ["oil temp", "oil temperature", "engine oil temp"],
    "intake_air_temp_f": ["intake air temp", "iat", "air temp", "inlet air temp"],
    "fuel_temp_f": ["fuel temp", "fuel temperature"],
    "injector_duty_pct": ["injector duty", "injector duty cycle", "inj duty", "duty cycle"],
}


UNIT_HINTS = {
    # Accepted source labels. Values are normalized by runlab.units.
    "km/h": "kmh", "kph": "kmh", "kmh": "kmh",
    "mph": "mph", "mi/h": "mph",
    "m/s": "mps", "mps": "mps", "ft/s": "fps", "fps": "fps",
    "rpm": "rpm", "rev/min": "rpm",
    "s": "s", "sec": "s", "seconds": "s",
    "ms": "ms", "msec": "ms", "millisecond": "ms", "milliseconds": "ms",
    "us": "us", "µs": "us", "μs": "us", "microsecond": "us", "microseconds": "us",
    "min": "min", "minute": "min", "minutes": "min",
    "psi": "psi", "kpa": "kpa", "bar": "bar", "pa": "pa",
    "%": "pct", "percent": "pct", "fraction": "fraction",
    "g": "g", "m/s2": "mps2", "m/s^2": "mps2", "m/s²": "mps2",
    "deg/s": "degps", "degree/s": "degps", "degrees/s": "degps", "°/s": "degps",
    "ft/s2": "fps2", "ft/s^2": "fps2", "ft/s²": "fps2",
    "hp": "hp", "bhp": "hp", "horsepower": "hp", "kw": "kw", "w": "w", "ps": "ps",
    "lb-ft": "lbft", "lb ft": "lbft", "ft-lb": "lbft", "n-m": "nm", "nm": "nm",
}



def _norm(text: str) -> str:
    text = str(text or "").lower().strip()
    text = re.sub(r"\([^)]*\)|\[[^]]*\]", " ", text)
    text = text.replace("_", " ").replace("-", " ").replace("/", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9.%]+", " ", text)).strip()


def _guess_unit(label: str) -> Optional[str]:
    return extract_unit_from_label(label)


def auto_map_channels(
    columns: Iterable[str],
    units: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Choose likely source channels for the canonical engineering signals.

    Name matching remains the primary signal, but when native channel units are
    available they materially affect the score.  This prevents status/limit
    channels such as ``Engine.Speed.Limit.State`` from beating the actual
    ``Engine.Speed`` measurement merely because the text happens to be longer.
    """
    cols = list(columns)
    units = units or {}
    result: Dict[str, str] = {}

    state_words = {
        "state", "status", "limit", "limiter", "diagnostic", "diag",
        "switch", "flag", "fault", "error", "warning", "target", "aim",
        "enable", "enabled", "mode", "request", "counter", "count",
    }
    measurement_canonicals = {
        "engine_rpm", "driveshaft_rpm", "clutch_rpm", "speed_mph",
        "wheel_speed_mph", "throttle_pct", "longitudinal_g", "boost_psi",
        "power_hp", "torque_lbft", "ignition_timing_deg", "oil_pressure_psi",
        "fuel_pressure_psi", "coolant_temp_f", "oil_temp_f", "intake_air_temp_f",
        "fuel_temp_f", "injector_duty_pct",
    }

    for canonical, synonyms in CANONICAL_CHANNELS.items():
        best: Tuple[float, Optional[str]] = (0.0, None)
        target_unit = CANONICAL_TARGET_UNITS.get(canonical, "")
        for col in cols:
            nc = _norm(col)
            tokens = set(nc.split())
            score = 0.0
            for synonym in synonyms:
                ns = _norm(synonym)
                if nc == ns:
                    score = max(score, 100.0)
                elif ns and ns in nc:
                    score = max(score, 80.0 + 10.0 * len(ns) / max(len(nc), 1))
                else:
                    a = set(ns.split())
                    b = tokens
                    if a and b:
                        overlap = len(a & b) / len(a | b)
                        score = max(score, 60.0 * overlap)

            # Existing ambiguity guards plus role-specific RPM separation.
            if canonical == "engine_rpm" and any(
                k in tokens for k in ("drive", "driveshaft", "ds", "shaft", "clutch", "wheel", "tire")
            ):
                score -= 65
            if canonical == "driveshaft_rpm" and any(
                k in tokens for k in ("engine", "motor", "mag", "clutch", "wheel")
            ):
                score -= 55
            if canonical == "clutch_rpm" and not ({"clutch", "input"} & tokens):
                score -= 35
            if canonical == "speed_mph" and "wheel" in tokens:
                score -= 25
            if canonical == "time_s":
                # Event timers/runtime counters are useful channels, but they are
                # not the logger clock. A false timebase is much more dangerous
                # than falling back to Sample Index until a real clock is known.
                if tokens & {"after", "launch", "shift", "runtime", "timer", "ign", "on"}:
                    score -= 70

            # Pressure channels are especially dangerous to cross-map because
            # psi is shared by unrelated systems. Require role words, not merely
            # a generic pressure/unit coincidence.
            pressure_roles = {
                "oil_pressure_psi": {"oil"},
                "fuel_pressure_psi": {"fuel", "rail"},
                "brake_pressure_psi": {"brake"},
                "boost_psi": {"boost", "map", "manifold"},
            }
            if canonical in pressure_roles and not (tokens & pressure_roles[canonical]):
                score -= 85
            if canonical in pressure_roles:
                foreign = {"oil", "fuel", "rail", "brake", "boost", "map", "manifold"} - pressure_roles[canonical]
                if tokens & foreign:
                    score -= 65

            # Measurement channels should not silently map to state/limit/target
            # values when a real engineering signal is present.
            if canonical in measurement_canonicals and tokens & state_words:
                score -= 45

            source_unit = normalize_unit(units.get(col) or _guess_unit(col))
            if target_unit and source_unit:
                if compatible(source_unit, target_unit):
                    score += 28
                else:
                    # A known incompatible unit is stronger evidence than a
                    # textual coincidence. Keep unknown units neutral.
                    score -= 55
            elif target_unit and canonical in measurement_canonicals and not source_unit:
                score -= 4

            # Tiny preference for shorter, direct measurement labels when all
            # other evidence is equal.
            score -= min(len(nc), 120) * 0.01
            if score > best[0]:
                best = (score, col)
        if best[0] >= 45 and best[1] is not None:
            result[canonical] = best[1]
    return result


def _detect_delimiter(lines: List[str]) -> str:
    candidates = ["\t", ",", ";", "|"]
    best = (0, ",")
    for delim in candidates:
        counts = [ln.count(delim) for ln in lines[:20] if ln.strip()]
        if counts:
            score = sum(1 for c in counts if c >= 2) * 10 + max(counts)
            if score > best[0]:
                best = (score, delim)
    return best[1]


def _find_header_line(lines: List[str], delimiter: str) -> int:
    best_idx, best_score = 0, -1.0
    # Normalized canonical synonyms and per-cell labels are loop invariants.
    # Computing them inside the cell loop made header detection cost
    # lines x columns x synonyms regex calls even on small files.
    normalized_synonyms = tuple(
        _norm(synonym)
        for vals in CANONICAL_CHANNELS.values()
        for synonym in vals
    )
    for i, line in enumerate(lines[:80]):
        parts = [p.strip().strip('"') for p in line.split(delimiter)]
        if len(parts) < 2:
            continue
        alpha = sum(bool(re.search(r"[A-Za-z]", p)) for p in parts)
        numeric = sum(_is_number(p) for p in parts)
        known = sum(
            any(ns in np for ns in normalized_synonyms)
            for np in (_norm(p) for p in parts)
        )
        # Headers tend to be alpha-heavy and followed by numeric rows.
        next_numeric = 0
        if i + 1 < len(lines):
            nxt = [p.strip().strip('"') for p in lines[i + 1].split(delimiter)]
            next_numeric = sum(_is_number(p) for p in nxt)
        score = alpha * 2.0 + known * 6.0 + next_numeric * 0.5 - numeric
        if score > best_score:
            best_idx, best_score = i, score
    return best_idx


def _is_number(value: str) -> bool:
    try:
        float(str(value).strip())
        return True
    except Exception:
        return False


def _units_from_second_row(df_raw: pd.DataFrame, header: List[str]) -> Tuple[Dict[str, str], int]:
    """Detect a vendor unit row immediately below the channel names."""
    if df_raw.empty:
        return {}, 0
    row = df_raw.iloc[0]
    units: Dict[str, str] = {}
    matches = 0
    for col, val in zip(header, row):
        sval = str(val).strip().lower()
        unit = normalize_unit(UNIT_HINTS.get(sval) or _guess_unit(sval))
        if unit:
            units[col] = unit
            matches += 1
    if matches >= max(2, len(header) // 5):
        return units, 1
    return {}, 0


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        s = out[col].astype(str).str.strip()
        converted = pd.to_numeric(s, errors="coerce")
        if converted.notna().sum() >= max(3, int(0.65 * len(out))):
            out[col] = converted
    out = out.dropna(how="all")
    return out.reset_index(drop=True)


def apply_channel_overrides(
    run: TelemetryRun,
    channel_overrides: Optional[Dict[str, str]] = None,
    unit_overrides: Optional[Dict[str, str]] = None,
) -> TelemetryRun:
    """Apply explicit canonical→source mappings and canonical/source unit hints.

    Examples:
      channel_overrides={"engine_rpm": "EngSpd", "speed_mph": "GPS_V"}
      unit_overrides={"speed_mph": "kmh", "longitudinal_g": "mps2"}
    """
    original_map = dict(run.metadata.get("original_channel_map", {}))
    # Start from original source channels when available. That allows a unit
    # override to re-normalize from raw data instead of accidentally converting
    # an already-normalized __speed_mph/__time_s column a second time.
    mapping = dict(original_map or run.channel_map)
    units = dict(run.units)
    for canonical, source in (channel_overrides or {}).items():
        canonical = str(canonical).strip()
        source = str(source or "").strip()
        if canonical not in CANONICAL_CHANNELS:
            raise ValueError(f"Unknown canonical channel override: {canonical}")
        # An explicit blank override means "do not assign this common role".
        # This is different from simply omitting the override, which allows the
        # importer's automatic mapping to remain in force.
        if not source:
            mapping.pop(canonical, None)
            continue
        if source not in run.data.columns:
            raise ValueError(f"Channel override for {canonical} refers to missing source column: {source}")
        mapping[canonical] = source
    for key, unit in (unit_overrides or {}).items():
        key = str(key).strip()
        unit = str(unit).strip().lower()
        source = (channel_overrides or {}).get(key) or mapping.get(key, key)
        if source not in run.data.columns:
            raise ValueError(f"Unit override refers to unmapped/missing channel: {key}")
        units[source] = UNIT_HINTS.get(unit, unit)
    # ``original_channel_map`` is the durable canonical->raw-source record.
    # Keep it in sync with user overrides so preferences, portable math and the
    # UI all resolve the same source after a remap/reopen.
    run.metadata["original_channel_map"] = dict(mapping)
    run.channel_map = mapping
    run.units = units
    return _normalize_canonical(run)


def _normalized_numeric(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(df[col], errors="coerce")


def _normalize_canonical(run: TelemetryRun) -> TelemetryRun:
    """Create explicit canonical channels in known internal engineering units.

    Raw source columns are never modified. Every converted canonical channel is
    materialized as ``__<canonical>`` and its unit/provenance is recorded. This
    avoids the previous failure mode where a column could be converted twice or
    a guessed source mapping could feed physically impossible values into the
    inverse power calculation.
    """
    df = run.data.copy()
    m = dict(run.channel_map)
    units = {str(k): normalize_unit(v) for k, v in dict(run.units).items()}
    provenance = dict(run.metadata.get("unit_provenance", {}))
    warnings = list(run.metadata.get("data_warnings", []))
    original_map = dict(run.metadata.get("original_channel_map", m))

    def src_unit(col: str) -> str:
        if col in units and units[col]:
            return units[col]
        guessed = _guess_unit(col) or ""
        if guessed:
            provenance.setdefault(col, "inferred from channel label")
            units[col] = normalize_unit(guessed)
        return normalize_unit(guessed)

    # Normalize each canonical role with a declared target unit.
    for canonical, target in CANONICAL_TARGET_UNITS.items():
        if canonical not in m:
            continue
        col = m[canonical]
        if col not in df.columns:
            warnings.append(f"Mapped {canonical} channel {col!r} is missing.")
            m.pop(canonical, None)
            continue
        arr = pd.to_numeric(df[col], errors="coerce")
        source_unit = src_unit(col)
        if source_unit:
            if not compatible(source_unit, target):
                warnings.append(
                    f"Rejected mapping {canonical} -> {col}: source unit {display_label(source_unit) or source_unit} "
                    f"is incompatible with expected {display_label(target)}."
                )
                m.pop(canonical, None)
                continue
            try:
                arr = convert_value(arr, source_unit, target)
            except Exception as exc:
                warnings.append(f"Could not convert {col} from {source_unit} to {target}: {exc}")
                m.pop(canonical, None)
                continue
        elif canonical == "throttle_pct":
            finite = arr[np.isfinite(arr)]
            if len(finite) and finite.abs().quantile(0.99) <= 1.5:
                arr = arr * 100.0
                source_unit = "fraction"
                provenance.setdefault(col, "range inference (0-1 fraction)")

        derived = f"__{canonical}"
        df[derived] = arr
        units[derived] = target
        provenance[derived] = f"canonical conversion from {col}" + (f" [{source_unit}]" if source_unit else " [unit unknown]")
        m[canonical] = derived

    # If a canonical channel has no target conversion (gear/lambda/AFR), copy it
    # into a private canonical column so source data remains immutable.
    for canonical in ("gear", "lambda", "afr"):
        if canonical not in m:
            continue
        col = m[canonical]
        if col not in df.columns:
            m.pop(canonical, None)
            continue
        derived = f"__{canonical}"
        df[derived] = pd.to_numeric(df[col], errors="coerce")
        units[derived] = units.get(col, "")
        provenance[derived] = f"canonical copy from {col}"
        m[canonical] = derived

    # Time is represented relative to the first valid source sample, while the
    # raw source channel remains unchanged for forensic inspection.
    if "time_s" in m:
        tc = m["time_s"]
        valid = pd.to_numeric(df[tc], errors="coerce")
        if valid.notna().any():
            first = float(valid.dropna().iloc[0])
            df[tc] = valid - first

    run.data = df
    run.channel_map = m
    run.units = units
    run.metadata["unit_provenance"] = provenance
    run.metadata["original_channel_map"] = original_map
    run.metadata["data_warnings"] = warnings
    return _validate_canonical_mappings(run)


def _validate_canonical_mappings(run: TelemetryRun) -> TelemetryRun:
    """Fail closed on canonical mappings that are dimensionally implausible.

    This is a guardrail, not a substitute for user confirmation. Suspicious
    mappings are removed from the canonical map but raw channels remain visible
    in the viewer. That prevents an accidental DS-RPM-as-speed mapping from
    creating absurd acceleration and multi-million-horsepower reconstructions.
    """
    m = dict(run.channel_map)
    warnings = list(run.metadata.get("data_warnings", []))
    quality = dict(run.metadata.get("channel_quality", {}))
    for canonical, col in list(m.items()):
        if col not in run.data.columns:
            continue
        band = plausible_range(canonical)
        if not band:
            continue
        vals = pd.to_numeric(run.data[col], errors="coerce")
        finite = vals[np.isfinite(vals)]
        if len(finite) < 3:
            continue
        lo, hi = band
        q01 = float(finite.quantile(0.01))
        q99 = float(finite.quantile(0.99))
        # Quantiles tolerate one-off logger spikes while catching unit/map errors.
        ok = q01 >= lo and q99 <= hi
        quality[canonical] = {"source": col, "q01": q01, "q99": q99, "plausible": bool(ok)}
        if not ok:
            warnings.append(
                f"Rejected automatic {canonical} mapping to {col}: central range {q01:.3g}..{q99:.3g} "
                f"is outside broad plausibility band {lo:g}..{hi:g}. Raw channel is still available."
            )
            m.pop(canonical, None)

    # Timebase checks are particularly important because derivatives scale
    # inversely with dt and a 1000x time-unit error becomes a 1000x inertia HP error.
    if "time_s" in m:
        t = pd.to_numeric(run.data[m["time_s"]], errors="coerce").dropna().to_numpy(float)
        if len(t) >= 4:
            dt = np.diff(t)
            dt = dt[np.isfinite(dt) & (dt > 0)]
            if len(dt):
                med = float(np.median(dt))
                hz = 1.0 / med if med > 0 else np.nan
                quality["timebase"] = {"median_dt_s": med, "sample_rate_hz": hz}
                if not (0.1 <= hz <= 100000):
                    warnings.append(
                        f"Suspicious telemetry timebase: median dt={med:.6g}s ({hz:.6g} Hz). "
                        "Confirm the source time unit before derivative-based power reconstruction."
                    )

    run.channel_map = m
    run.metadata["channel_quality"] = quality
    run.metadata["data_warnings"] = warnings
    return run


def parse_delimited(path: str | Path, vendor: str = "generic") -> TelemetryRun:
    path = Path(path)
    raw = path.read_text(errors="replace")
    lines = raw.splitlines()
    if not lines:
        raise ValueError(f"{path.name}: empty file")

    delimiter = _detect_delimiter(lines)
    header_idx = _find_header_line(lines, delimiter)
    metadata_lines = lines[:header_idx]

    text = "\n".join(lines[header_idx:])
    try:
        df = pd.read_csv(io.StringIO(text), sep=delimiter, engine="python")
    except Exception:
        df = pd.read_csv(io.StringIO(text), sep=delimiter, engine="python", on_bad_lines="skip")

    # Clean duplicate/blank headers.
    cols: List[str] = []
    seen: Dict[str, int] = {}
    for i, c in enumerate(df.columns):
        c = str(c).strip().strip('"') or f"channel_{i+1}"
        if c in seen:
            seen[c] += 1
            c = f"{c}_{seen[c]}"
        else:
            seen[c] = 1
        cols.append(c)
    df.columns = cols

    units, skip = _units_from_second_row(df, cols)
    if skip:
        df = df.iloc[skip:].reset_index(drop=True)
    for c in cols:
        if c not in units:
            u = _guess_unit(c)
            if u:
                units[c] = u

    df = _coerce_numeric(df)
    channel_map = auto_map_channels(df.columns, units)
    metadata = {
        "source_file": path.name,
        "delimiter": "tab" if delimiter == "\t" else delimiter,
        "header_line": header_idx + 1,
        "preamble": "\n".join(metadata_lines[-20:]),
        "original_channel_map": dict(channel_map),
    }
    run = TelemetryRun(
        name=path.stem,
        data=df,
        channel_map=channel_map,
        units=units,
        vendor=vendor,
        metadata=metadata,
    )
    return _normalize_canonical(run)



def _dedupe_columns(columns: Iterable[Any]) -> List[str]:
    out: List[str] = []
    seen: Dict[str, int] = {}
    for i, raw in enumerate(columns):
        name = str(raw).strip().strip('"') if raw is not None else ""
        name = name or f"channel_{i+1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        out.append(name)
    return out


def parse_excel_telemetry(path: str | Path) -> TelemetryRun:
    """Open an XLSX/XLSM telemetry table without treating the workbook as authority.

    Sheets are scored for telemetry-like numeric content. The chosen sheet uses
    the same unit/canonical logic as delimited imports and the source workbook is
    never modified.
    """
    path = Path(path)
    book = pd.ExcelFile(path, engine="openpyxl")
    best: tuple[float, str, pd.DataFrame] | None = None
    for sheet in book.sheet_names[:50]:
        raw = pd.read_excel(book, sheet_name=sheet, header=None, dtype=object)
        if raw.empty or raw.shape[1] < 2:
            continue
        raw = raw.dropna(how="all").reset_index(drop=True)
        if raw.empty:
            continue
        header_idx = 0
        header_score = float('-inf')
        for i in range(min(80, len(raw))):
            vals = ["" if pd.isna(x) else str(x).strip() for x in raw.iloc[i].tolist()]
            alpha = sum(bool(re.search(r"[A-Za-z]", x)) for x in vals)
            known = sum(any(_norm(syn) in _norm(x) for names in CANONICAL_CHANNELS.values() for syn in names) for x in vals if x)
            nxt = raw.iloc[i + 1].tolist() if i + 1 < len(raw) else []
            numeric_next = sum(pd.to_numeric(pd.Series([x]), errors="coerce").notna().iloc[0] for x in nxt if not pd.isna(x))
            score = alpha * 2.0 + known * 6.0 + numeric_next * 0.5
            if score > header_score:
                header_idx, header_score = i, score
        header = _dedupe_columns(raw.iloc[header_idx].tolist())
        body = raw.iloc[header_idx + 1:].copy().reset_index(drop=True)
        body.columns = header
        units, skip = _units_from_second_row(body, header)
        if skip:
            body = body.iloc[skip:].reset_index(drop=True)
        for c in header:
            if c not in units:
                guessed = _guess_unit(c)
                if guessed:
                    units[c] = guessed
        body = _coerce_numeric(body)
        numeric = sum(pd.to_numeric(body[c], errors="coerce").notna().sum() >= 3 for c in body.columns)
        mappings = auto_map_channels(body.columns, units)
        score = numeric * 4.0 + len(mappings) * 8.0 + min(len(body), 10000) / 10000.0
        if best is None or score > best[0]:
            best = (score, sheet, body)
            best_units = units
            best_map = mappings
            best_header_idx = header_idx
    if best is None:
        raise ValueError("Workbook contains no telemetry-like sheet with at least two columns.")
    _score, sheet, df = best
    run = TelemetryRun(
        name=path.stem,
        data=df,
        channel_map=best_map,
        units=best_units,
        vendor="Excel",
        metadata={
            "source_file": path.name,
            "workbook_sheet": sheet,
            "header_line": best_header_idx + 1,
            "original_channel_map": dict(best_map),
        },
    )
    return _normalize_canonical(run)


def parse_tunerstudio(path: str | Path) -> TelemetryRun:
    path = Path(path)
    head = path.read_bytes()[:8192]
    if _looks_binary(head):
        raise ValueError(
            "Binary TunerStudio/MegaSquirt log detected. Text MSL/MLG logs are supported, "
            "but binary MLG requires a separately qualified decoder and is intentionally rejected."
        )
    return parse_delimited(path, vendor="TunerStudio/MegaSquirt")


def _vbox_elapsed_seconds(values: pd.Series) -> np.ndarray:
    raw = pd.to_numeric(values, errors="coerce").to_numpy(float)
    if not np.isfinite(raw).any():
        return np.arange(len(raw), dtype=float)
    out = np.full(len(raw), np.nan, dtype=float)
    # VBO clock is commonly HHMMSS.sss. Values below 240000 with plausible
    # minute/second fields are interpreted as time-of-day, then unwrapped.
    finite = raw[np.isfinite(raw)]
    looks_hms = bool(len(finite) and np.nanmax(np.abs(finite)) <= 240000.999)
    if looks_hms:
        prev = None
        day = 0.0
        for i, val in enumerate(raw):
            if not np.isfinite(val):
                continue
            av = abs(val)
            hh = int(av // 10000)
            mm = int((av - hh * 10000) // 100)
            ss = av - hh * 10000 - mm * 100
            if hh > 23 or mm > 59 or ss >= 60:
                looks_hms = False
                break
            sec = hh * 3600 + mm * 60 + ss
            if prev is not None and sec + day < prev - 12 * 3600:
                day += 24 * 3600
            out[i] = sec + day
            prev = out[i]
    if not looks_hms:
        out = raw.copy()
    good = np.flatnonzero(np.isfinite(out))
    if len(good):
        out = out - out[good[0]]
    return out


def _vbox_coord_decimal(values: pd.Series, *, latitude: bool) -> np.ndarray:
    arr = pd.to_numeric(values, errors="coerce").to_numpy(float)
    finite = np.abs(arr[np.isfinite(arr)])
    limit = 90.0 if latitude else 180.0
    if not len(finite) or np.nanmax(finite) <= limit:
        return arr
    out = arr.copy()
    for i, val in enumerate(arr):
        if not np.isfinite(val):
            continue
        sign = -1.0 if val < 0 else 1.0
        av = abs(val)
        deg = int(av // 100.0)
        minutes = av - deg * 100.0
        if deg <= limit and 0.0 <= minutes < 60.0:
            out[i] = sign * (deg + minutes / 60.0)
    return out


def parse_vbox_vbo(path: str | Path) -> TelemetryRun:
    """Parse the documented sectioned Racelogic VBOX VBO text format."""
    path = Path(path)
    text = path.read_text(errors="replace")
    sections: Dict[str, List[str]] = {}
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^\[([^]]+)\]$", line)
        if m:
            current = m.group(1).strip().lower()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    columns_lines = sections.get("column names") or sections.get("columns") or []
    data_lines = sections.get("data") or []
    if not columns_lines or not data_lines:
        raise ValueError("VBO file is missing [column names] or [data] sections.")
    columns = _dedupe_columns(re.split(r"\s+", " ".join(columns_lines).strip()))
    rows = []
    for line in data_lines:
        parts = re.split(r"\s+", line.strip())
        if len(parts) < len(columns):
            continue
        rows.append(parts[:len(columns)])
    if not rows:
        raise ValueError("VBO [data] section contains no complete rows.")
    df = _coerce_numeric(pd.DataFrame(rows, columns=columns))
    units: Dict[str, str] = {}
    # Channel-units section may be positional tokens or name/unit pairs.
    unit_lines = sections.get("channel units") or []
    tokens = re.split(r"\s+", " ".join(unit_lines).strip()) if unit_lines else []
    if len(tokens) == len(columns):
        for c, unit in zip(columns, tokens):
            key = normalize_unit(unit)
            if key:
                units[c] = key
    common = {
        "velocity": "kmh", "speed": "kmh", "height": "m", "altitude": "m",
        "heading": "deg", "latacc": "g", "longacc": "g", "vertacc": "g",
    }
    for c in columns:
        nc = _norm(c).replace(" ", "")
        if c not in units and nc in common:
            units[c] = common[nc]
        elif c not in units:
            guessed = _guess_unit(c)
            if guessed:
                units[c] = guessed
    # Preserve the raw VBOX time column and add an engineering elapsed clock.
    time_col = next((c for c in columns if _norm(c) in {"time", "utc time", "vbox time"}), None)
    if time_col is not None:
        df["VBOX Elapsed Time"] = _vbox_elapsed_seconds(df[time_col])
        units["VBOX Elapsed Time"] = "s"
    lat_col = next((c for c in columns if _norm(c) in {"lat", "latitude", "gps latitude"}), None)
    lon_col = next((c for c in columns if _norm(c) in {"long", "lon", "longitude", "gps longitude"}), None)
    if lat_col:
        df["GPS Latitude Decimal"] = _vbox_coord_decimal(df[lat_col], latitude=True)
        units["GPS Latitude Decimal"] = "deg"
    if lon_col:
        df["GPS Longitude Decimal"] = _vbox_coord_decimal(df[lon_col], latitude=False)
        units["GPS Longitude Decimal"] = "deg"
    mapping = auto_map_channels(df.columns, units)
    # VBOX documents a bare ``velocity`` channel. Keep this mapping local to
    # the VBOX adapter rather than making a globally ambiguous synonym.
    velocity_col = next((c for c in columns if _norm(c) == "velocity"), None)
    if velocity_col is not None and "speed_mph" not in mapping:
        mapping["speed_mph"] = velocity_col
    if time_col is not None:
        mapping["time_s"] = "VBOX Elapsed Time"
    if lat_col:
        mapping["gps_latitude_deg"] = "GPS Latitude Decimal"
    if lon_col:
        mapping["gps_longitude_deg"] = "GPS Longitude Decimal"
    run = TelemetryRun(
        name=path.stem,
        data=df,
        channel_map=mapping,
        units=units,
        vendor="Racelogic VBOX",
        metadata={
            "source_file": path.name,
            "vbox_header": "\n".join(sections.get("header", [])[-50:]),
            "original_channel_map": dict(mapping),
        },
    )
    return _normalize_canonical(run)

def _looks_like_maxxecu(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".maxxlog") or name.endswith(".maxxecu-log") or "maxxecu" in name


def parse_maxxecu(path: str | Path) -> TelemetryRun:
    path = Path(path)
    if path.suffix.lower() in {".zip", ".maxxecu-zip-log", ".zip-log"} or "zip" in path.name.lower():
        with zipfile.ZipFile(path, "r") as zf:
            members = [n for n in zf.namelist() if not n.endswith("/")]
            candidates = [n for n in members if n.lower().endswith((".maxxlog", ".maxxecu-log", ".csv", ".txt"))]
            if not candidates:
                raise ValueError("MaxxECU zip log did not contain a recognizable log file")
            # Prefer native MaxxECU log over exported CSV.
            candidates.sort(key=lambda n: (not n.lower().endswith((".maxxlog", ".maxxecu-log")), len(n)))
            name = candidates[0]
            data = zf.read(name)
            log_rate_s: float | None = None
            metadata_member = next((n for n in members if n.lower().endswith(".logmetadata")), None)
            if metadata_member:
                try:
                    meta_text = zf.read(metadata_member).decode("utf-8", errors="replace")
                    match = re.search(r"(?im)^\s*LogRate\s*=\s*([0-9.eE+-]+)\s*$", meta_text)
                    if match:
                        candidate = float(match.group(1))
                        if np.isfinite(candidate) and 1e-6 <= candidate <= 10.0:
                            log_rate_s = candidate
                except Exception:
                    log_rate_s = None
            with tempfile.TemporaryDirectory(prefix="nhra_tech_maxx_") as td:
                temp = Path(td) / Path(name).name
                temp.write_bytes(data)
                run = parse_delimited(temp, vendor="MaxxECU")
                if log_rate_s is not None and len(run.data):
                    # The package metadata is the native sampling-clock authority.
                    # Publish a derived elapsed clock while preserving every raw
                    # source channel exactly as logged.
                    clock_name = "MaxxECU Logger Time"
                    run.data[clock_name] = np.arange(len(run.data), dtype=float) * log_rate_s
                    run.units[clock_name] = "s"
                    run.channel_map["time_s"] = clock_name
                    run.metadata.setdefault("unit_provenance", {})[clock_name] = f"MaxxECU package LogRate={log_rate_s:g}s"
                    run = _normalize_canonical(run)
                    run.metadata["maxxecu_log_rate_s"] = log_rate_s
                    run.metadata["maxxecu_metadata_member"] = metadata_member
                run.name = path.stem
                run.metadata["zip_member"] = name
                run.metadata["source_file"] = path.name
                return run
    return parse_delimited(path, vendor="MaxxECU")


def parse_telemetry_archive(path: str | Path) -> TelemetryRun:
    """Open a zip containing one primary telemetry log and optional sidecars.

    The archive is only a transport container; the selected member is decoded
    by the exact same native importer as a standalone file.  For MoTeC, a
    matching .ldx sidecar is extracted beside the .ld automatically.
    """
    path = Path(path)
    with zipfile.ZipFile(path, 'r') as zf:
        members = [n for n in zf.namelist() if not n.endswith('/')]
        if not members:
            raise ValueError('Telemetry archive is empty')
        lower = {n: n.lower() for n in members}
        priority = ('.ld', '.rpk', '.maxxecu-log', '.maxxlog', '.vbo', '.msl', '.mlg', '.xlsx', '.xlsm', '.ftlog', '.ftml', '.mf4', '.mdf', '.xrk', '.xrz', '.drk', '.dl', '.dlz', '.hpl', '.csv', '.tsv', '.txt', '.log')
        candidates = [n for ext in priority for n in members if lower[n].endswith(ext)]
        if not candidates:
            raise ValueError('Archive contains no recognized telemetry member.')
        primary = candidates[0]
        with tempfile.TemporaryDirectory(prefix='nhra_tech_archive_') as td:
            root = Path(td)
            primary_path = root / Path(primary).name
            primary_path.write_bytes(zf.read(primary))
            if primary.lower().endswith('.ld'):
                target_ldx = str(Path(primary).with_suffix('.ldx')).replace('\\', '/')
                for member in members:
                    if member.replace('\\', '/').lower() == target_ldx.lower() or Path(member).name.lower() == Path(target_ldx).name.lower():
                        (root / Path(target_ldx).name).write_bytes(zf.read(member))
                        break
            # Avoid recursive archive handling; primary is an actual log.
            run = load_telemetry(primary_path, vendor='Auto')
            run.name = path.stem
            run.metadata['archive_file'] = path.name
            run.metadata['archive_member'] = primary
            run.metadata['source_file'] = path.name
            run.metadata['source_path'] = str(path)
            return run


def _looks_binary(data: bytes) -> bool:
    if not data:
        return False
    sample = data[:8192]
    if b"\x00" in sample:
        return True
    textish = sum((32 <= b <= 126) or b in (9, 10, 13) for b in sample)
    return (textish / max(len(sample), 1)) < 0.80


def _sniff_vendor_bytes(path: Path) -> Tuple[str, str]:
    """Best-effort content probe used in addition to filename/extension.

    Returns ``(vendor, reason)``.  It intentionally only recognizes signatures
    we can defend; unknown binary files are not handed to pandas as text.
    """
    try:
        with path.open('rb') as fh:
            head = fh.read(262144)
    except Exception as exc:
        return "Unknown", f"could not read file header: {exc}"
    if len(head) >= 4 and int.from_bytes(head[:4], 'little', signed=False) == 64 and path.stat().st_size >= 1700:
        return "MoTeC", "MoTeC LD header marker 64"
    # Validated legacy RacePak/DataLink recordings contain DataLink metadata
    # followed by serialized ScaledBuffer/Timer objects.  Both real NHRA demo
    # fixtures use the 0x5c07 prefix, but we require the structure tokens too.
    if (head[:2] == b"\\\x07" or b"ScaledBuffer" in head) and b"Timer_" in head:
        return "RacePak", "RacePak/DataLink ScaledBuffer + Timer structure"
    if not _looks_binary(head):
        return "Delimited", "text/delimited content"
    return "Unknown", "unrecognized binary content"


def telemetry_file_candidate(path: str | Path) -> bool:
    """Return True for any registry-recognized telemetry/interchange file.

    Recognition is deliberately broader than decoding so folder scans can tell
    the user *why* a proprietary file cannot yet be opened.
    """
    return telemetry_candidate(path)


def detect_vendor(path: str | Path) -> str:
    path = Path(path)
    name = path.name.lower()
    ext = path.suffix.lower()
    spec = spec_for_path(path)
    if spec is not None and spec.key == "vbox_vbo":
        return "VBOX"
    if spec is not None and spec.key == "tunerstudio":
        return "TunerStudio"
    if spec is not None and spec.key == "excel":
        return "Excel"
    if spec is not None and spec.status in {"pending", "bridge", "support"}:
        return spec.decoder_key or spec.label
    if _looks_like_maxxecu(path) or "maxxecu" in name:
        return "MaxxECU"
    if ext == ".ld" or name.endswith('.ld.bin') or "motec" in name or "i2" in name:
        return "MoTeC"
    if ext == ".ddf":
        return "RacePak DDF"
    if "racepak" in name or ext == ".rpk" or '.rpk.' in name:
        return "RacePak"
    if "fueltech" in name or ext in {".ftml", ".ftlog"}:
        return "FuelTech"
    if ext in {".csv", ".tsv", ".txt", ".log", ".maxxlog", ".maxxecu-log"}:
        return "Delimited"
    if ext == ".zip":
        try:
            with zipfile.ZipFile(path, "r") as zf:
                names = " ".join(zf.namelist()).lower()
                if "maxx" in names:
                    return "MaxxECU"
                return "Archive"
        except Exception:
            pass
    sniffed, _reason = _sniff_vendor_bytes(path)
    return sniffed


def _finalize_loaded_run(run: TelemetryRun, path: Path, selected: str, reason: str = "") -> TelemetryRun:
    from .plotability import require_plotable
    report = require_plotable(run)
    run.metadata.setdefault('source_file', path.name)
    run.metadata.setdefault('source_path', str(path))
    run.metadata['import_decoder'] = selected
    if reason:
        run.metadata['import_probe_reason'] = reason
    # Surface plotability warnings in the same Data Integrity path as unit/map
    # warnings, without rejecting otherwise usable source channels.
    warnings = list(run.metadata.get('data_warnings', []))
    for warning in report.warnings:
        if warning not in warnings:
            warnings.append(warning)
    run.metadata['data_warnings'] = warnings
    return run


def load_telemetry(
    path: str | Path,
    vendor: str = "Auto",
    channel_overrides: Optional[Dict[str, str]] = None,
    unit_overrides: Optional[Dict[str, str]] = None,
    racepak_config_path: str | Path | None = None,
) -> TelemetryRun:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    selected = str(vendor or "Auto")
    probe_reason = "explicit vendor selection"
    registry_spec = spec_for_path(path)
    if selected.lower() == "auto":
        # A recognized direct binary extension is the decoder-dispatch contract.
        # The decoder itself still validates structure and fails closed. Content
        # signatures are only a fallback for ambiguous wrappers/unknown names;
        # otherwise a coincidental first integer (for example 64 in a RacePak
        # file) can incorrectly route a valid .rpk into the MoTeC parser.
        if registry_spec is not None and registry_spec.status in {"direct", "container", "interchange"} and registry_spec.decoder_key:
            selected = registry_spec.decoder_key
            probe_reason = f"import registry extension match ({registry_spec.key})"
        else:
            selected, probe_reason = _sniff_vendor_bytes(path)
            named = detect_vendor(path)
            if named != "Unknown" and (selected in ("Unknown", "Delimited") or named in ("MoTeC", "RacePak", "MaxxECU", "FuelTech")):
                selected = named
                probe_reason = f"filename/extension + content probe ({probe_reason})"

    key = selected.strip().lower()
    if registry_spec is not None and registry_spec.status in {"pending", "bridge", "support"} and key not in {"fueltech"}:
        # Do not allow a recognized proprietary binary to fall through merely
        # because its header happens to contain text strings.
        raise ValueError(pending_message(registry_spec))
    try:
        if key == "archive":
            run = parse_telemetry_archive(path)
        elif key == "maxxecu":
            run = parse_maxxecu(path)
        elif key == "racepak":
            from .racepak import parse_racepak_rpk
            run = parse_racepak_rpk(path)
        elif key in {"racepak ddf", "racepak_ddf", "ddf"}:
            from .racepak_ddf import parse_racepak_ddf
            run = parse_racepak_ddf(path, config_path=racepak_config_path)
        elif key == "motec":
            from .motec_ld import parse_motec_ld
            run = parse_motec_ld(path)
        elif key == "holley":
            from .holley import parse_holley
            run = parse_holley(path)
        elif key in {"vbox", "vbox vbo", "racelogic vbox"}:
            run = parse_vbox_vbo(path)
        elif key in {"tunerstudio", "efi analytics", "megasquirt"}:
            run = parse_tunerstudio(path)
        elif key in {"excel", "xlsx", "xlsm"}:
            run = parse_excel_telemetry(path)
        elif key == "fueltech":
            if path.suffix.lower() in {".ftml", ".ftlog"}:
                raise ValueError(
                    "Native FuelTech FTML/FTLOG decoding is not qualified in this build. "
                    "FuelTech CSV exports are supported, and current Vision software can export MoTeC i2 .ld logs. "
                    "The native binary file is intentionally rejected rather than treated as text or silently mis-decoded."
                )
            run = parse_delimited(path, vendor="FuelTech")
        elif key in {"delimited", "generic", "csv", "text"}:
            run = parse_delimited(path, vendor="generic")
        else:
            # Only feed a file to pandas when the content probe says it is text.
            sniffed, why = _sniff_vendor_bytes(path)
            if sniffed == "Delimited":
                run = parse_delimited(path, vendor="generic")
                selected = "Delimited"
                probe_reason = why
            else:
                raise ValueError(
                    f"Unsupported or unrecognized telemetry format ({why}). "
                    "The file was not sent to the CSV parser because it appears binary."
                )
    except Exception as exc:
        raise ValueError(
            f"Import failed during {selected} decode for {path.name}: {exc}"
        ) from exc

    if channel_overrides or unit_overrides:
        run = apply_channel_overrides(run, channel_overrides, unit_overrides)
    return _finalize_loaded_run(run, path, selected, probe_reason)

def channel_summary(run: TelemetryRun) -> pd.DataFrame:
    rows = []
    reverse = {v: k for k, v in run.channel_map.items()}
    for c in run.data.columns:
        s = pd.to_numeric(run.data[c], errors="coerce")
        numeric = int(s.notna().sum())
        rows.append({
            "source_channel": c,
            "canonical": reverse.get(c, ""),
            "unit": run.units.get(c, ""),
            "samples": len(run.data),
            "numeric_samples": numeric,
            "min": float(s.min()) if numeric else None,
            "max": float(s.max()) if numeric else None,
        })
    return pd.DataFrame(rows)
