from __future__ import annotations

"""Synchronized AnalysisCase review/playback helpers.

The AnalysisCase clock is the only review cursor.  Every source position is
resolved from that cursor through the stored, auditable mappings:

    case time -> Run time -> Asset time

This module contains no media framework and never rewrites raw evidence.  The
Qt desktop, CLI and tests all use the same headless mapping logic.
"""

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
import math

import numpy as np
import pandas as pd

from .catalog import LocalCatalog
from .models import TelemetryRun


_MEDIA_TYPES = {"video", "audio"}
_NUMERIC_TYPES = {"telemetry", "idr", "data", "logger"}


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _nested_get(mapping: Mapping[str, Any] | None, keys: Sequence[str]) -> Any:
    cur: Any = mapping or {}
    for key in keys:
        if not isinstance(cur, Mapping) or key not in cur:
            return None
        cur = cur[key]
    return cur


def asset_duration_s(asset: Mapping[str, Any]) -> float | None:
    """Read an optional source duration from server/file metadata.

    The real Tech Services asset contract is still being mapped, so this accepts
    a small set of non-destructive metadata spellings without making any of them
    authoritative schema requirements.
    """
    meta = asset.get("metadata") if isinstance(asset, Mapping) else {}
    candidates = [
        asset.get("duration_s"),
        _nested_get(meta, ("duration_s",)),
        _nested_get(meta, ("duration_seconds",)),
        _nested_get(meta, ("media", "duration_s")),
        _nested_get(meta, ("media", "duration_seconds")),
        _nested_get(meta, ("probe", "duration_s")),
    ]
    for value in candidates:
        duration = _finite(value)
        if duration is not None and duration >= 0:
            return duration
    return None


def asset_frame_rate_hz(asset: Mapping[str, Any]) -> float | None:
    meta = asset.get("metadata") if isinstance(asset, Mapping) else {}
    for value in (
        asset.get("frame_rate_hz"),
        _nested_get(meta, ("frame_rate_hz",)),
        _nested_get(meta, ("fps",)),
        _nested_get(meta, ("media", "frame_rate_hz")),
        _nested_get(meta, ("media", "fps")),
    ):
        rate = _finite(value)
        if rate is not None and rate > 0:
            return rate
    return None


def asset_kind(asset: Mapping[str, Any]) -> str:
    typ = str(asset.get("asset_type") or "other").strip().lower()
    mime = str(asset.get("mime_type") or "").strip().lower()
    suffix = Path(str(asset.get("filename") or "")).suffix.lower()
    if typ in _MEDIA_TYPES:
        return typ
    if mime.startswith("video/") or suffix in {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}:
        return "video"
    if mime.startswith("audio/") or suffix in {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}:
        return "audio"
    if typ == "idr":
        return "idr"
    if typ in _NUMERIC_TYPES:
        return "telemetry"
    return typ or "other"


@dataclass(frozen=True)
class SourcePlaybackState:
    case_id: str
    case_time_s: float
    run_id: str
    run_role: str
    run_time_s: float
    asset_id: str
    asset_type: str
    source_kind: str
    filename: str
    asset_time_s: float | None
    mapped: bool
    cached: bool
    local_path: str
    duration_s: float | None
    in_range: bool | None
    frame_rate_hz: float | None = None
    frame_index: int | None = None
    mapping_method: str = ""
    mapping_uncertainty_s: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CasePlaybackFrame:
    case_id: str
    case_time_s: float
    sources: tuple[SourcePlaybackState, ...]
    active_markers: tuple[dict[str, Any], ...] = ()
    previous_marker: dict[str, Any] | None = None
    next_marker: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "case_time_s": self.case_time_s,
            "sources": [s.to_dict() for s in self.sources],
            "active_markers": [dict(m) for m in self.active_markers],
            "previous_marker": None if self.previous_marker is None else dict(self.previous_marker),
            "next_marker": None if self.next_marker is None else dict(self.next_marker),
        }


def source_playback_state(catalog: LocalCatalog, case_id: str, asset_id: str, case_time_s: float) -> SourcePlaybackState:
    asset = catalog.get_asset(asset_id)
    if asset is None:
        raise KeyError(asset_id)
    run_id = str(asset["run_id"])
    alignment = catalog.get_case_run_alignment(case_id, run_id)
    if alignment is None:
        raise KeyError(f"Run {run_id} is not a member of AnalysisCase {case_id}")
    run_time = catalog.map_case_time_to_run(case_id, run_id, float(case_time_s))
    mapping = catalog.get_time_mapping(asset_id)
    asset_time: float | None = None
    mapped = mapping is not None
    if mapped:
        asset_time = catalog.map_case_time_to_asset(case_id, asset_id, float(case_time_s))
    duration = asset_duration_s(asset)
    in_range: bool | None
    if asset_time is None or duration is None:
        in_range = None
    else:
        # Give the end point a tiny numerical tolerance so exact-duration seeks
        # do not flicker out of range due to floating-point mapping noise.
        in_range = -1e-9 <= asset_time <= duration + 1e-9
    rate = asset_frame_rate_hz(asset)
    frame_index = None
    if asset_time is not None and rate is not None and asset_time >= 0:
        frame_index = max(0, int(round(asset_time * rate)))
    local_path = str(asset.get("local_path") or "")
    cached = bool(local_path and Path(local_path).is_file() and catalog.asset_cache_valid(asset_id))
    role = str(alignment.get("role") or "")
    if not role:
        for row in catalog.list_case_runs(case_id):
            if str(row["id"]) == run_id:
                role = str(row.get("role") or "reference")
                break
    return SourcePlaybackState(
        case_id=str(case_id),
        case_time_s=float(case_time_s),
        run_id=run_id,
        run_role=role or "reference",
        run_time_s=float(run_time),
        asset_id=str(asset_id),
        asset_type=str(asset.get("asset_type") or "other"),
        source_kind=asset_kind(asset),
        filename=str(asset.get("filename") or asset_id),
        asset_time_s=None if asset_time is None else float(asset_time),
        mapped=bool(mapped),
        cached=cached,
        local_path=local_path,
        duration_s=duration,
        in_range=in_range,
        frame_rate_hz=rate,
        frame_index=frame_index,
        mapping_method=str((mapping or {}).get("method") or ""),
        mapping_uncertainty_s=(None if (mapping or {}).get("uncertainty_s") is None else float(mapping["uncertainty_s"])),
    )


def _marker_neighbors(markers: Sequence[Mapping[str, Any]], case_time_s: float) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    previous = None
    next_item = None
    for marker in markers:
        t = float(marker["case_start_s"])
        if t < case_time_s - 1e-12:
            previous = dict(marker)
        elif t > case_time_s + 1e-12 and next_item is None:
            next_item = dict(marker)
    return previous, next_item


def case_playback_frame(catalog: LocalCatalog, case_id: str, case_time_s: float, *, marker_tolerance_s: float = 0.015) -> CasePlaybackFrame:
    if catalog.get_analysis_case(case_id) is None:
        raise KeyError(case_id)
    states: list[SourcePlaybackState] = []
    for run in catalog.list_case_runs(case_id):
        for asset in catalog.list_assets(str(run["id"])):
            states.append(source_playback_state(catalog, case_id, str(asset["id"]), case_time_s))
    markers = catalog.list_case_markers(case_id)
    active = []
    for marker in markers:
        start = float(marker["case_start_s"])
        end_raw = marker.get("case_end_s")
        if end_raw is None:
            if abs(float(case_time_s) - start) <= max(0.0, float(marker_tolerance_s)):
                active.append(dict(marker))
        else:
            end = float(end_raw)
            lo, hi = sorted((start, end))
            if lo - marker_tolerance_s <= case_time_s <= hi + marker_tolerance_s:
                active.append(dict(marker))
    previous, next_item = _marker_neighbors(markers, float(case_time_s))
    return CasePlaybackFrame(
        case_id=str(case_id),
        case_time_s=float(case_time_s),
        sources=tuple(states),
        active_markers=tuple(active),
        previous_marker=previous,
        next_marker=next_item,
    )


def case_time_extent(catalog: LocalCatalog, case_id: str, *, default_before_s: float = 2.0, default_after_s: float = 3.0) -> tuple[float, float]:
    """Return a useful review range in Case seconds.

    Evidence duration, marker positions and official ETs all contribute.  This
    is a viewing range only; it is never persisted as evidence.
    """
    if catalog.get_analysis_case(case_id) is None:
        raise KeyError(case_id)
    points: list[float] = []
    runs = catalog.list_case_runs(case_id)
    for run in runs:
        run_id = str(run["id"])
        # Launch/run zero is always meaningful on the canonical Run timeline.
        try:
            points.append(catalog.map_run_time_to_case(case_id, run_id, 0.0))
        except Exception:
            pass
        timing = run.get("timing") or {}
        et = _finite(timing.get("quarter_mile_s") or timing.get("elapsed_time_s") or timing.get("et_s"))
        if et is not None and et >= 0:
            points.append(catalog.map_run_time_to_case(case_id, run_id, et))
        for asset in catalog.list_assets(run_id):
            duration = asset_duration_s(asset)
            if duration is None or catalog.get_time_mapping(str(asset["id"])) is None:
                continue
            try:
                points.append(catalog.map_asset_time_to_case(case_id, str(asset["id"]), 0.0))
                points.append(catalog.map_asset_time_to_case(case_id, str(asset["id"]), duration))
            except Exception:
                pass
    for marker in catalog.list_case_markers(case_id):
        points.append(float(marker["case_start_s"]))
        if marker.get("case_end_s") is not None:
            points.append(float(marker["case_end_s"]))
    points = [p for p in points if math.isfinite(float(p))]
    if not points:
        return (-float(default_before_s), 15.0)
    lo = min(points) - float(default_before_s)
    hi = max(points) + float(default_after_s)
    if hi - lo < 1.0:
        hi = lo + 1.0
    return float(lo), float(hi)


def nearest_marker_time(catalog: LocalCatalog, case_id: str, case_time_s: float, direction: int) -> float | None:
    markers = catalog.list_case_markers(case_id)
    times = sorted({float(m["case_start_s"]) for m in markers})
    if direction < 0:
        eligible = [x for x in times if x < case_time_s - 1e-9]
        return max(eligible) if eligible else None
    eligible = [x for x in times if x > case_time_s + 1e-9]
    return min(eligible) if eligible else None


class CasePlaybackController:
    """Small headless cursor state machine used by the desktop and tests."""

    def __init__(self, catalog: LocalCatalog, case_id: str, *, case_time_s: float = 0.0):
        if catalog.get_analysis_case(case_id) is None:
            raise KeyError(case_id)
        self.catalog = catalog
        self.case_id = str(case_id)
        self.minimum_s, self.maximum_s = case_time_extent(catalog, case_id)
        self.case_time_s = self.clamp(case_time_s)

    def clamp(self, value: float) -> float:
        return min(self.maximum_s, max(self.minimum_s, float(value)))

    def set_time(self, value: float) -> CasePlaybackFrame:
        self.case_time_s = self.clamp(value)
        return self.frame()

    def step(self, seconds: float) -> CasePlaybackFrame:
        return self.set_time(self.case_time_s + float(seconds))

    def jump_marker(self, direction: int) -> CasePlaybackFrame:
        target = nearest_marker_time(self.catalog, self.case_id, self.case_time_s, direction)
        return self.frame() if target is None else self.set_time(target)

    def frame(self) -> CasePlaybackFrame:
        return case_playback_frame(self.catalog, self.case_id, self.case_time_s)


def _rectangular_time(run: TelemetryRun) -> np.ndarray | None:
    tc = run.channel_map.get("time_s")
    if tc and tc in run.data.columns:
        t = pd.to_numeric(run.data[tc], errors="coerce").to_numpy(float)
        if np.isfinite(t).sum() >= 1:
            return t
    return None


def sample_telemetry_at_asset_time(run: TelemetryRun, asset_time_s: float, channels: Iterable[str] | None = None, *, max_channels: int = 32) -> list[dict[str, Any]]:
    """Nearest-sample readout for telemetry-like/IDR numeric sources.

    This is intentionally a readout primitive rather than an IDR decoder.  Any
    IDR export that is already represented as TelemetryRun can participate in
    synchronized review immediately; native IDR formats can add decoders later.
    """
    requested = list(channels or [])
    if not requested:
        requested = list(run.native_channels.keys())
        for col in run.data.columns:
            if str(col).startswith("__") or col in requested:
                continue
            try:
                pd.to_numeric(run.data[col], errors="raise")
            except Exception:
                continue
            requested.append(str(col))
        requested = requested[: max(1, int(max_channels))]
    out: list[dict[str, Any]] = []
    rectangular_t = _rectangular_time(run)
    for name in requested[: max(1, int(max_channels))]:
        if name in run.native_channels:
            ch = run.native_channels[name]
            t = np.asarray(ch.time_s, dtype=float)
            y = np.asarray(ch.values, dtype=float)
            unit = str(getattr(ch, "unit", "") or "")
        elif name in run.data.columns and rectangular_t is not None:
            t = rectangular_t
            y = pd.to_numeric(run.data[name], errors="coerce").to_numpy(float)
            unit = str(getattr(run, 'units', {}).get(name, ''))
        else:
            continue
        n = min(len(t), len(y))
        if n == 0:
            continue
        good = np.isfinite(t[:n]) & np.isfinite(y[:n])
        if not np.any(good):
            continue
        tt = t[:n][good]
        yy = y[:n][good]
        idx = int(np.argmin(np.abs(tt - float(asset_time_s))))
        out.append({"channel": str(name), "sample_time_s": float(tt[idx]), "value": float(yy[idx]), "unit": unit})
    return out
