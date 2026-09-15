from __future__ import annotations

"""Map telemetry/media/IDR clocks onto a canonical run timeline.

A simple affine mapping is intentionally the first representation because it
handles both offset and constant clock-rate drift while remaining auditable.
Future video workflows can layer piecewise mappings on top without changing the
run/asset catalog contract.
"""

from dataclasses import dataclass
from typing import Iterable, List, Sequence
import numpy as np


@dataclass(frozen=True)
class TimeAnchor:
    asset_time_s: float
    run_time_s: float


@dataclass(frozen=True)
class TimeMapping:
    scale: float = 1.0
    offset_s: float = 0.0
    method: str = "manual"
    confidence: float | None = None
    uncertainty_s: float | None = None
    anchors: tuple[TimeAnchor, ...] = ()

    def to_run_time(self, asset_time_s):
        arr = np.asarray(asset_time_s, dtype=float)
        out = arr * float(self.scale) + float(self.offset_s)
        return float(out) if out.ndim == 0 else out

    def to_asset_time(self, run_time_s):
        if abs(float(self.scale)) < 1e-12:
            raise ValueError("Time mapping scale cannot be zero")
        arr = np.asarray(run_time_s, dtype=float)
        out = (arr - float(self.offset_s)) / float(self.scale)
        return float(out) if out.ndim == 0 else out

    def to_dict(self):
        return {
            "scale": float(self.scale),
            "offset_s": float(self.offset_s),
            "method": self.method,
            "confidence": self.confidence,
            "uncertainty_s": self.uncertainty_s,
            "anchors": [
                {"asset_time_s": float(a.asset_time_s), "run_time_s": float(a.run_time_s)}
                for a in self.anchors
            ],
        }


def fit_time_mapping(
    anchors: Iterable[TimeAnchor | Sequence[float] | dict],
    *,
    method: str = "anchors",
    confidence: float | None = None,
) -> TimeMapping:
    parsed: List[TimeAnchor] = []
    for a in anchors:
        if isinstance(a, TimeAnchor):
            parsed.append(a)
        elif isinstance(a, dict):
            parsed.append(TimeAnchor(float(a["asset_time_s"]), float(a["run_time_s"])))
        else:
            parsed.append(TimeAnchor(float(a[0]), float(a[1])))
    if not parsed:
        return TimeMapping(method=method, confidence=confidence)
    x = np.asarray([a.asset_time_s for a in parsed], dtype=float)
    y = np.asarray([a.run_time_s for a in parsed], dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    x, y = x[valid], y[valid]
    parsed = [a for a, ok in zip(parsed, valid) if ok]
    if len(x) == 0:
        raise ValueError("No finite synchronization anchors")
    if len(x) == 1:
        scale = 1.0
        offset = float(y[0] - x[0])
        uncertainty = None
    else:
        if float(np.ptp(x)) <= 1e-12:
            raise ValueError("Synchronization anchors must span different asset times")
        A = np.column_stack([x, np.ones_like(x)])
        scale, offset = np.linalg.lstsq(A, y, rcond=None)[0]
        residual = y - (scale * x + offset)
        uncertainty = float(np.sqrt(np.mean(residual ** 2))) if len(x) > 2 else 0.0
    if not (0.5 <= float(scale) <= 1.5):
        raise ValueError(f"Implausible clock scale {scale:.6g}; check synchronization anchors")
    return TimeMapping(
        scale=float(scale),
        offset_s=float(offset),
        method=method,
        confidence=confidence,
        uncertainty_s=uncertainty,
        anchors=tuple(parsed),
    )
