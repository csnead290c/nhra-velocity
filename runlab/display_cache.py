from __future__ import annotations

"""Small, format-neutral cache for interactive telemetry displays.

Cursor motion is a hot path.  Rebuilding X/Y mappings, sorting timestamps and
scanning entire channels for every mouse event makes otherwise modest logs feel
sluggish.  This cache keeps those immutable display views for the lifetime of a
worksheet/render state.  Call ``clear()`` whenever the underlying Run/session
mapping changes.
"""

from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterable, Tuple

import numpy as np

from .display_data import channel_xy
from .models import TelemetryRun


@dataclass(frozen=True)
class CacheStats:
    xy_hits: int = 0
    xy_misses: int = 0
    interpolation_hits: int = 0
    interpolation_misses: int = 0


class DisplaySeriesCache:
    """Bounded cache for channel X/Y mapping, interpolation and snap grids."""

    def __init__(self, max_entries: int = 256):
        self.max_entries = max(16, int(max_entries))
        self._xy: "OrderedDict[tuple, Tuple[np.ndarray, np.ndarray]]" = OrderedDict()
        self._interp: "OrderedDict[tuple, Tuple[np.ndarray, np.ndarray]]" = OrderedDict()
        self._grid: "OrderedDict[tuple, np.ndarray]" = OrderedDict()
        self._xy_hits = 0
        self._xy_misses = 0
        self._interp_hits = 0
        self._interp_misses = 0

    @staticmethod
    def _key(run: TelemetryRun, channel: str, x_mode: str, alignment_s: float) -> tuple:
        # The desktop clears the cache on store/session changes.  Object identity
        # therefore avoids hashing large dataframes while remaining deterministic
        # inside one display state.
        return (id(run), str(channel), str(x_mode), round(float(alignment_s), 12))

    @staticmethod
    def _touch(cache: OrderedDict, key, value, max_entries: int):
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > max_entries:
            cache.popitem(last=False)

    def clear(self) -> None:
        self._xy.clear()
        self._interp.clear()
        self._grid.clear()

    def stats(self) -> CacheStats:
        return CacheStats(
            xy_hits=self._xy_hits,
            xy_misses=self._xy_misses,
            interpolation_hits=self._interp_hits,
            interpolation_misses=self._interp_misses,
        )

    def xy(self, run: TelemetryRun, channel: str, x_mode: str, alignment_s: float = 0.0) -> Tuple[np.ndarray, np.ndarray]:
        key = self._key(run, channel, x_mode, alignment_s)
        cached = self._xy.get(key)
        if cached is not None:
            self._xy_hits += 1
            self._xy.move_to_end(key)
            return cached
        self._xy_misses += 1
        x, y = channel_xy(run, channel, x_mode, alignment_s)
        value = (np.asarray(x, dtype=float), np.asarray(y, dtype=float))
        self._touch(self._xy, key, value, self.max_entries)
        return value

    def interpolation_view(self, run: TelemetryRun, channel: str, x_mode: str, alignment_s: float = 0.0) -> Tuple[np.ndarray, np.ndarray]:
        key = self._key(run, channel, x_mode, alignment_s)
        cached = self._interp.get(key)
        if cached is not None:
            self._interp_hits += 1
            self._interp.move_to_end(key)
            return cached
        self._interp_misses += 1
        x, y = self.xy(run, channel, x_mode, alignment_s)
        n = min(len(x), len(y))
        if n < 2:
            value = (np.array([], dtype=float), np.array([], dtype=float))
            self._touch(self._interp, key, value, self.max_entries)
            return value
        xx = np.asarray(x[:n], dtype=float)
        yy = np.asarray(y[:n], dtype=float)
        mask = np.isfinite(xx) & np.isfinite(yy)
        xx = xx[mask]
        yy = yy[mask]
        if len(xx) < 2:
            value = (np.array([], dtype=float), np.array([], dtype=float))
            self._touch(self._interp, key, value, self.max_entries)
            return value

        # Most logger clocks are already ordered.  Avoid an O(n log n) sort in
        # that common case.  When a source has a reset/out-of-order sample,
        # stable-sort once and collapse duplicate X values deterministically.
        if not bool(np.all(np.diff(xx) > 0)):
            order = np.argsort(xx, kind="mergesort")
            xx = xx[order]
            yy = yy[order]
            if len(xx) > 1:
                keep = np.r_[np.diff(xx) > 0, True]  # keep the last sample at duplicate X
                xx = xx[keep]
                yy = yy[keep]

        value = (xx, yy)
        self._touch(self._interp, key, value, self.max_entries)
        return value

    def sample_many(
        self,
        run: TelemetryRun,
        channel: str,
        positions: Iterable[float],
        x_mode: str,
        alignment_s: float = 0.0,
    ) -> np.ndarray:
        pos = np.asarray(list(positions), dtype=float)
        xx, yy = self.interpolation_view(run, channel, x_mode, alignment_s)
        if len(xx) < 2:
            return np.full(pos.shape, np.nan, dtype=float)
        out = np.interp(pos, xx, yy)
        outside = (~np.isfinite(pos)) | (pos < xx[0]) | (pos > xx[-1])
        out = np.asarray(out, dtype=float)
        out[outside] = np.nan
        return out


    def region_summary(
        self,
        run: TelemetryRun,
        channel: str,
        x1: float,
        x2: float,
        x_mode: str,
        alignment_s: float = 0.0,
    ) -> dict[str, float]:
        """Fast statistics between two display X positions.

        Uses the same cached, strictly increasing interpolation view as cursor
        sampling.  This keeps reference-to-current Min/Max/Mean useful during
        interactive review without rebuilding/sorting channel arrays.
        """
        xx, yy = self.interpolation_view(run, channel, x_mode, alignment_s)
        if len(xx) < 1:
            return {"min": np.nan, "max": np.nan, "mean": np.nan, "std": np.nan, "count": 0.0}
        lo, hi = sorted((float(x1), float(x2)))
        left = int(np.searchsorted(xx, lo, side="left"))
        right = int(np.searchsorted(xx, hi, side="right"))
        vals = np.asarray(yy[left:right], dtype=float)
        vals = vals[np.isfinite(vals)]
        if not len(vals):
            return {"min": np.nan, "max": np.nan, "mean": np.nan, "std": np.nan, "count": 0.0}
        return {
            "min": float(np.min(vals)),
            "max": float(np.max(vals)),
            "mean": float(np.mean(vals)),
            "std": float(np.std(vals)),
            "count": float(len(vals)),
        }

    def snap_grid(self, run: TelemetryRun, channel: str, x_mode: str, alignment_s: float = 0.0) -> np.ndarray:
        key = self._key(run, channel, x_mode, alignment_s)
        cached = self._grid.get(key)
        if cached is not None:
            self._grid.move_to_end(key)
            return cached
        x, _ = self.xy(run, channel, x_mode, alignment_s)
        xx = np.asarray(x, dtype=float)
        xx = xx[np.isfinite(xx)]
        if len(xx) and not bool(np.all(np.diff(xx) > 0)):
            xx = np.unique(np.sort(xx))
        self._touch(self._grid, key, xx, self.max_entries)
        return xx

    @staticmethod
    def nearest(grid: np.ndarray, x: float) -> float:
        values = np.asarray(grid, dtype=float)
        if not len(values):
            return float(x)
        target = float(x)
        idx = int(np.searchsorted(values, target, side="left"))
        if idx <= 0:
            return float(values[0])
        if idx >= len(values):
            return float(values[-1])
        before = float(values[idx - 1])
        after = float(values[idx])
        return before if abs(target - before) <= abs(after - target) else after
