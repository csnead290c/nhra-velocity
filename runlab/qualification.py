from __future__ import annotations

"""Batch telemetry corpus qualification for real-world logger archives."""

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List
import hashlib
import math

import numpy as np

from .importers import load_telemetry, telemetry_file_candidate
from .import_registry import spec_for_path
from .plotability import assess_plotability


@dataclass
class QualificationRecord:
    path: str
    filename: str
    sha256: str = ""
    status: str = "failed"
    vendor: str = ""
    decoder: str = ""
    format_key: str = ""
    format_status: str = ""
    probe_reason: str = ""
    plotable: bool = False
    rows: int = 0
    numeric_channels: int = 0
    native_channels: int = 0
    canonical_channels: int = 0
    duration_s: float | None = None
    sample_rate_max_hz: float | None = None
    time_nonpositive_steps: int = 0
    duplicate_columns: int = 0
    nan_heavy_channels: int = 0
    constant_numeric_channels: int = 0
    integrity_flags: str = ""
    warnings: str = ""
    error: str = ""

    def to_dict(self):
        return asdict(self)


def _sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def _integrity_summary(run, report) -> dict[str, object]:
    """Cheap, decoder-agnostic checks for data that can open but is suspicious.

    This intentionally avoids vendor-specific assumptions.  The goal is to
    catch corpus issues that otherwise look like a successful import: duplicate
    channel labels, broken/non-monotonic time, mostly-empty channels, or flat
    numeric channels.
    """
    flags: list[str] = []
    duplicate_columns = int(getattr(run.data.columns, "duplicated", lambda: [])().sum()) if len(run.data.columns) else 0
    if duplicate_columns:
        flags.append(f"{duplicate_columns} duplicate column name(s)")

    time_nonpositive_steps = 0
    tc = run.channel_map.get("time_s")
    if tc and tc in run.data.columns:
        raw = np.asarray(run.data[tc], dtype=float)
        finite = raw[np.isfinite(raw)]
        if len(finite) >= 2:
            dt = np.diff(finite)
            time_nonpositive_steps = int(np.count_nonzero(~np.isfinite(dt) | (dt <= 0)))
            if time_nonpositive_steps:
                flags.append(f"{time_nonpositive_steps} non-increasing time step(s)")

    nan_heavy = 0
    constant = 0
    for name in report.numeric_channels:
        try:
            values = np.asarray(run.data[name], dtype=float) if name in run.data.columns else np.asarray(run.native_channels[name].values, dtype=float)
        except Exception:
            continue
        if not len(values):
            continue
        finite = values[np.isfinite(values)]
        if len(finite) / len(values) < 0.5:
            nan_heavy += 1
        if len(finite) >= 2 and float(np.nanmax(finite) - np.nanmin(finite)) == 0.0:
            constant += 1
    if nan_heavy:
        flags.append(f"{nan_heavy} numeric channel(s) <50% finite")
    # Constant channels are common for status bits and unused sensors. Keep the
    # count for review, but only flag it when flat data dominates the recording.
    numeric_total = max(1, len(report.numeric_channels))
    if constant >= 3 and constant / numeric_total >= 0.8:
        flags.append(f"{constant}/{numeric_total} numeric channels are constant")
    return {
        "time_nonpositive_steps": time_nonpositive_steps,
        "duplicate_columns": duplicate_columns,
        "nan_heavy_channels": nan_heavy,
        "constant_numeric_channels": constant,
        "integrity_flags": " | ".join(flags),
    }


def qualify_file(path: str | Path, *, compute_sha: bool = True) -> QualificationRecord:
    p=Path(path)
    rec=QualificationRecord(path=str(p),filename=p.name)
    if compute_sha:
        try: rec.sha256=_sha(p)
        except Exception: pass
    spec=spec_for_path(p)
    if spec is not None:
        rec.format_key=spec.key
        rec.format_status=spec.status
    try:
        run=load_telemetry(p)
        report=assess_plotability(run)
        rec.status='pass' if report.plotable else 'decoded-not-plotable'
        rec.vendor=run.vendor
        rec.decoder=str(run.metadata.get('import_decoder',''))
        rec.probe_reason=str(run.metadata.get('import_probe_reason',''))
        rec.plotable=bool(report.plotable)
        rec.rows=len(run.data)
        rec.numeric_channels=len(report.numeric_channels)
        rec.native_channels=len(run.native_channels)
        rec.canonical_channels=len(run.channel_map)
        rates=[float(ch.sample_rate_hz) for ch in run.native_channels.values() if ch.sample_rate_hz and math.isfinite(float(ch.sample_rate_hz))]
        rec.sample_rate_max_hz=max(rates) if rates else None
        tc=run.channel_map.get('time_s')
        if tc and tc in run.data.columns:
            arr=np.asarray(run.data[tc],dtype=float);finite=arr[np.isfinite(arr)]
            if len(finite)>=2:rec.duration_s=float(finite[-1]-finite[0])
        elif run.native_channels:
            spans=[]
            for ch in run.native_channels.values():
                t=np.asarray(ch.time_s,dtype=float);f=t[np.isfinite(t)]
                if len(f)>=2:spans.append(float(f[-1]-f[0]))
            if spans:rec.duration_s=max(spans)
        integrity = _integrity_summary(run, report)
        for key, value in integrity.items():
            setattr(rec, key, value)
        rec.warnings=' | '.join(str(x) for x in run.metadata.get('data_warnings',[]) or [])
    except Exception as exc:
        rec.error=str(exc)
    return rec


def expand_candidates(paths: Iterable[str | Path], *, recursive: bool = False) -> List[Path]:
    out=[]
    for raw in paths:
        p=Path(raw)
        if p.is_dir():
            it=p.rglob('*') if recursive else p.glob('*')
            out.extend(x for x in it if x.is_file() and telemetry_file_candidate(x))
        elif p.is_file() and telemetry_file_candidate(p):
            out.append(p)
    # Stable order + same physical path only once.
    return sorted({x.resolve() for x in out},key=lambda x:str(x).lower())


def _sample_candidates_per_format(paths: List[Path], per_format: int) -> List[Path]:
    """Choose a deterministic spread of files from each recognized family."""
    if per_format <= 0:
        return paths
    groups: dict[str, list[Path]] = {}
    for path in paths:
        spec = spec_for_path(path)
        key = spec.key if spec is not None else path.suffix.lower() or "unknown"
        groups.setdefault(key, []).append(path)
    sampled: list[Path] = []
    for key in sorted(groups):
        items = groups[key]
        if len(items) <= per_format:
            sampled.extend(items)
            continue
        if per_format == 1:
            sampled.append(items[len(items)//2])
            continue
        indexes = np.linspace(0, len(items)-1, num=per_format)
        sampled.extend(items[int(round(index))] for index in indexes)
    return sorted(set(sampled), key=lambda x: str(x).lower())


def qualify_corpus(
    paths: Iterable[str | Path],
    *,
    recursive: bool = False,
    sample_per_format: int = 0,
    compute_sha: bool = True,
) -> List[QualificationRecord]:
    candidates = expand_candidates(paths, recursive=recursive)
    candidates = _sample_candidates_per_format(candidates, int(sample_per_format or 0))
    return [qualify_file(p, compute_sha=compute_sha) for p in candidates]


def extension_inventory(paths: Iterable[str | Path], *, recursive: bool = False) -> list[dict[str, object]]:
    """Inventory every file extension, including families VELOCITY does not know.

    Qualification intentionally scans recognized data-log candidates only.  This
    companion inventory is the gap detector: an unexpected extension cannot be
    silently omitted from a corpus review merely because it is absent from the
    registry.
    """
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            iterator = p.rglob('*') if recursive else p.glob('*')
            files.extend(x for x in iterator if x.is_file())
        elif p.is_file():
            files.append(p)

    groups: dict[tuple[str, str], dict[str, object]] = {}
    for path in sorted({x.resolve() for x in files}, key=lambda x: str(x).lower()):
        spec = spec_for_path(path)
        if spec is not None:
            matched = max((ext for ext in spec.extensions if path.name.lower().endswith(ext)), key=len)
            extension = matched
            key = spec.key
            status = spec.status
            label = spec.label
            candidate = telemetry_file_candidate(path)
        else:
            extension = path.suffix.lower() or '(no extension)'
            key = ''
            status = 'unrecognized'
            label = ''
            candidate = False
        group_key = (extension, key)
        row = groups.setdefault(group_key, {
            'extension': extension,
            'count': 0,
            'format_key': key,
            'format_label': label,
            'format_status': status,
            'data_log_candidate': bool(candidate),
            'examples': [],
        })
        row['count'] = int(row['count']) + 1
        examples = row['examples']
        if isinstance(examples, list) and len(examples) < 3:
            examples.append(str(path))
    return sorted(groups.values(), key=lambda row: (-int(row['count']), str(row['extension'])))
