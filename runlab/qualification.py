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
    warnings: str = ""
    error: str = ""

    def to_dict(self):
        return asdict(self)


def _sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def qualify_file(path: str | Path) -> QualificationRecord:
    p=Path(path)
    rec=QualificationRecord(path=str(p),filename=p.name)
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
        elif p.is_file():
            out.append(p)
    # Stable order + same physical path only once.
    return sorted({x.resolve() for x in out},key=lambda x:str(x).lower())


def qualify_corpus(paths: Iterable[str | Path], *, recursive: bool = False) -> List[QualificationRecord]:
    return [qualify_file(p) for p in expand_candidates(paths,recursive=recursive)]
