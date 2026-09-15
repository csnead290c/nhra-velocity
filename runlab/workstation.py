from __future__ import annotations

"""Reusable analysis-workstation primitives.

This module deliberately sits below Qt.  Gates, segments, KPIs and channel
metadata are shared by desktop displays, reports, batch jobs and future live
telemetry so the application does not grow separate analysis dialects.
"""

from dataclasses import dataclass, asdict
import ast
import re
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from .models import TelemetryRun
from .display_data import channel_xy, prepare_plot_series
from .units import dimension, normalize_unit

_BACKTICK = re.compile(r"`([^`]+)`")


@dataclass(frozen=True)
class ChannelDescriptor:
    name: str
    unit: str = ""
    dimension: str = "unknown"
    canonical_role: str = ""
    alias: str = ""
    source_kind: str = "rectangular"  # native | rectangular | calculated
    sample_rate_hz: float | None = None
    numeric: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GateDefinition:
    name: str
    expression: str
    description: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class SegmentDefinition:
    name: str
    x_mode: str
    start: float
    end: float
    source: str = "manual"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    channel: str
    statistic: str = "mean"
    gate: str = ""
    unit: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _visible_names(run: TelemetryRun) -> list[str]:
    names: list[str] = []
    for n in run.native_channels:
        if str(n) not in names:
            names.append(str(n))
    for n in run.data.columns:
        s = str(n)
        if s.startswith("__"):
            continue
        if s not in names:
            names.append(s)
    return names


def channel_aliases(run: TelemetryRun) -> dict[str, str]:
    raw = run.metadata.get("channel_aliases", {})
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def set_channel_alias(run: TelemetryRun, channel: str, alias: str) -> None:
    if channel not in _visible_names(run):
        raise ValueError(f"Unknown channel: {channel!r}")
    aliases = channel_aliases(run)
    text = str(alias or "").strip()
    if text:
        aliases[str(channel)] = text
    else:
        aliases.pop(str(channel), None)
    run.metadata["channel_aliases"] = aliases


def resolve_channel(run: TelemetryRun, name_or_alias: str) -> str | None:
    needle = str(name_or_alias or "").strip()
    if not needle:
        return None
    names = _visible_names(run)
    if needle in names:
        return needle
    low = needle.lower()
    exact = [n for n in names if n.lower() == low]
    if len(exact) == 1:
        return exact[0]
    aliases = channel_aliases(run)
    hits = [channel for channel, alias in aliases.items() if alias.lower() == low and channel in names]
    if len(hits) == 1:
        return hits[0]
    # Canonical role is also a stable lookup key.
    virtual_roles = {}
    for key in ("model_virtual_channels", "model_residual_channels"):
        raw = run.metadata.get(key, {})
        if isinstance(raw, dict):
            for channel, role in raw.items():
                if channel in names and str(role): virtual_roles[str(role)] = str(channel)
    vsrc = virtual_roles.get(needle) or virtual_roles.get(low)
    if vsrc in names:
        return str(vsrc)
    originals = run.metadata.get("original_channel_map", {}) if isinstance(run.metadata.get("original_channel_map", {}), dict) else {}
    src = originals.get(needle) or originals.get(low)
    if src in names:
        return str(src)
    mapped = run.channel_map.get(needle) or run.channel_map.get(low)
    if mapped in names:
        return str(mapped)
    return None


def channel_catalog(run: TelemetryRun, query: str = "") -> list[ChannelDescriptor]:
    aliases = channel_aliases(run)
    originals = run.metadata.get("original_channel_map", {}) if isinstance(run.metadata.get("original_channel_map", {}), dict) else {}
    math_names = {str(x.get("name", "")) for x in run.metadata.get("math_channels", []) if isinstance(x, dict)}
    reverse_roles: dict[str, str] = {}
    virtual_kinds: dict[str, str] = {}
    for key, kind in (("model_virtual_channels","model"),("model_residual_channels","residual")):
        raw=run.metadata.get(key,{})
        if isinstance(raw,dict):
            for channel,role in raw.items():
                reverse_roles.setdefault(str(channel),str(role)); virtual_kinds[str(channel)]=kind
    for role, src in originals.items():
        if src:
            reverse_roles.setdefault(str(src), str(role))
    for role, mapped in run.channel_map.items():
        if mapped and not str(mapped).startswith("__"):
            reverse_roles.setdefault(str(mapped), str(role))

    q = str(query or "").strip().lower()
    out: list[ChannelDescriptor] = []
    for name in _visible_names(run):
        unit = normalize_unit(run.units.get(name, ""))
        dim = dimension(unit)
        if name in math_names:
            kind = "calculated"
        elif name in virtual_kinds:
            kind = virtual_kinds[name]
        elif name in run.native_channels:
            kind = "native"
        else:
            kind = "rectangular"
        sr = None
        if name in run.native_channels:
            try:
                val = run.native_channels[name].sample_rate_hz
                sr = float(val) if val is not None else None
            except Exception:
                sr = None
        numeric = True
        if name in run.data.columns:
            numeric = bool(pd.to_numeric(run.data[name], errors="coerce").notna().any())
        rec = ChannelDescriptor(
            name=name,
            unit=unit,
            dimension=dim,
            canonical_role=reverse_roles.get(name, ""),
            alias=aliases.get(name, ""),
            source_kind=kind,
            sample_rate_hz=sr,
            numeric=numeric,
        )
        hay = " ".join([rec.name, rec.alias, rec.unit, rec.dimension, rec.canonical_role, rec.source_kind]).lower()
        if q and q not in hay:
            continue
        out.append(rec)
    return sorted(out, key=lambda r: (r.dimension, r.alias.lower() or r.name.lower(), r.name.lower()))


# ---- Safe boolean gates ----------------------------------------------------

_ALLOWED_COMPARE = {
    ast.Lt: np.less,
    ast.LtE: np.less_equal,
    ast.Gt: np.greater,
    ast.GtE: np.greater_equal,
    ast.Eq: np.equal,
    ast.NotEq: np.not_equal,
}
_ALLOWED_BIN = {
    ast.Add: np.add,
    ast.Sub: np.subtract,
    ast.Mult: np.multiply,
    ast.Div: np.divide,
    ast.Pow: np.power,
    ast.Mod: np.mod,
}


def _prepare_gate(expression: str, columns: Iterable[str]) -> tuple[str, dict[str, str]]:
    cols = [str(c) for c in columns]
    mapping: dict[str, str] = {}
    counter = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal counter
        channel = match.group(1)
        if channel not in cols:
            raise ValueError(f"Unknown channel in gate: {channel!r}")
        key = f"__gate_ch_{counter}"
        counter += 1
        mapping[key] = channel
        return key

    prepared = _BACKTICK.sub(repl, str(expression))
    for col in cols:
        if col.isidentifier():
            mapping.setdefault(col, col)
    return prepared, mapping


def _gate_eval(node: ast.AST, env: dict[str, np.ndarray], length: int):
    if isinstance(node, ast.Expression):
        return _gate_eval(node.body, env, length)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return np.full(length, bool(node.value), dtype=bool)
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError("Gates allow only numeric/boolean constants.")
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise ValueError(f"Unknown gate symbol: {node.id!r}")
        return env[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return np.logical_not(np.asarray(_gate_eval(node.operand, env, length), dtype=bool))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _gate_eval(node.operand, env, length)
        return value if isinstance(node.op, ast.UAdd) else np.negative(value)
    if isinstance(node, ast.BoolOp):
        values = [np.asarray(_gate_eval(v, env, length), dtype=bool) for v in node.values]
        if not values:
            return np.ones(length, dtype=bool)
        out = values[0]
        for val in values[1:]:
            out = np.logical_and(out, val) if isinstance(node.op, ast.And) else np.logical_or(out, val)
        return out
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BIN:
        with np.errstate(all="ignore"):
            return _ALLOWED_BIN[type(node.op)](_gate_eval(node.left, env, length), _gate_eval(node.right, env, length))
    if isinstance(node, ast.Compare):
        left = _gate_eval(node.left, env, length)
        result = np.ones(length, dtype=bool)
        current = left
        for op, comparator in zip(node.ops, node.comparators):
            if type(op) not in _ALLOWED_COMPARE:
                raise ValueError("Unsupported comparison in gate.")
            right = _gate_eval(comparator, env, length)
            result &= np.asarray(_ALLOWED_COMPARE[type(op)](current, right), dtype=bool)
            current = right
        return result
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fname = node.func.id.lower()
        args = [_gate_eval(a, env, length) for a in node.args]
        if fname == "abs" and len(args) == 1:
            return np.abs(args[0])
        if fname == "isfinite" and len(args) == 1:
            return np.isfinite(args[0])
        if fname == "between" and len(args) == 3:
            return (np.asarray(args[0]) >= args[1]) & (np.asarray(args[0]) <= args[2])
        raise ValueError(f"Gate function {fname!r} is not allowed.")
    raise ValueError("Unsupported gate expression element.")


def evaluate_gate(run: TelemetryRun, expression: str) -> np.ndarray:
    """Evaluate a vector boolean condition against the rectangular analysis table.

    Native-only mixed-rate channels must first be normalized/mapped into the
    analysis table before they can participate in a cross-channel gate.  This is
    intentional: silently interpolating unrelated clocks inside a condition is
    unsafe.
    """
    text = str(expression or "").strip()
    if not text:
        return np.ones(len(run.data), dtype=bool)
    prepared, mapping = _prepare_gate(text, run.data.columns)
    try:
        tree = ast.parse(prepared, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid gate expression: {exc.msg}") from exc
    env = {key: pd.to_numeric(run.data[channel], errors="coerce").to_numpy(float) for key, channel in mapping.items()}
    result = np.asarray(_gate_eval(tree, env, len(run.data)), dtype=bool)
    if result.shape != (len(run.data),):
        raise ValueError("Gate did not produce one boolean value per analysis sample.")
    return result & np.isfinite(np.arange(len(result), dtype=float))


def save_gate(run: TelemetryRun, definition: GateDefinition) -> None:
    rows = [x for x in run.metadata.get("gates", []) if isinstance(x, dict) and str(x.get("name", "")) != definition.name]
    rows.append(definition.to_dict())
    run.metadata["gates"] = rows


def gates(run: TelemetryRun) -> list[GateDefinition]:
    out: list[GateDefinition] = []
    for rec in run.metadata.get("gates", []):
        if isinstance(rec, dict) and str(rec.get("name", "")).strip() and str(rec.get("expression", "")).strip():
            out.append(GateDefinition(str(rec["name"]), str(rec["expression"]), str(rec.get("description", ""))))
    return out


def named_gate_expression(run: TelemetryRun, name: str) -> str:
    for gate in gates(run):
        if gate.name == name:
            return gate.expression
    return ""


# ---- Segments and metrics --------------------------------------------------

def official_drag_segments(run: TelemetryRun, x_mode: str = "Time from Launch") -> list[SegmentDefinition]:
    mode = str(x_mode or "Time from Launch")
    if mode.lower().startswith("distance"):
        points = [("Launch", 0.0), ("60 ft", 60.0), ("330 ft", 330.0), ("660 ft", 660.0), ("1000 ft", 1000.0), ("1320 ft", 1320.0)]
    elif mode.lower().startswith("normalized"):
        points = [("Launch", 0.0), ("Finish", 100.0)]
    else:
        t = run.timing
        vals = [
            ("Launch", 0.0),
            ("60 ft", t.sixty_ft_s),
            ("330 ft", t.three_thirty_ft_s),
            ("660 ft", t.eighth_mile_s),
            ("1000 ft", t.thousand_ft_s),
            ("1320 ft", t.quarter_mile_s),
        ]
        points = [(name, float(value)) for name, value in vals if value is not None]
    out: list[SegmentDefinition] = []
    for (a, x1), (b, x2) in zip(points[:-1], points[1:]):
        if x2 > x1:
            out.append(SegmentDefinition(f"{a} → {b}", mode, float(x1), float(x2), "official"))
    if len(points) >= 2:
        out.insert(0, SegmentDefinition(f"{points[0][0]} → {points[-1][0]}", mode, float(points[0][1]), float(points[-1][1]), "official"))
    return out


def _statistic(statistic: str, x: np.ndarray, y: np.ndarray) -> float:
    key = str(statistic or "mean").strip().lower().replace(" ", "_")
    finite = np.isfinite(x) & np.isfinite(y)
    x = x[finite]; y = y[finite]
    if len(y) == 0:
        return float("nan")
    if key == "min": return float(np.min(y))
    if key == "max": return float(np.max(y))
    if key == "mean": return float(np.mean(y))
    if key == "median": return float(np.median(y))
    if key in {"std", "stdev", "standard_deviation"}: return float(np.std(y))
    if key == "rms": return float(np.sqrt(np.mean(y ** 2)))
    if key == "range": return float(np.max(y) - np.min(y))
    if key == "start": return float(y[0])
    if key == "end": return float(y[-1])
    if key in {"delta", "change"}: return float(y[-1] - y[0])
    if key == "integral": return float(np.trapz(y, x)) if len(y) >= 2 else 0.0
    if key == "slope":
        if len(y) < 2 or np.ptp(x) <= 0: return float("nan")
        return float(np.polyfit(x, y, 1)[0])
    if key == "count": return float(len(y))
    if key.startswith("p") and key[1:].replace(".", "", 1).isdigit():
        p = float(key[1:])
        if not (0 <= p <= 100): raise ValueError("Percentile must be between 0 and 100.")
        return float(np.percentile(y, p))
    raise ValueError(f"Unknown metric statistic: {statistic!r}")


def evaluate_metric(run: TelemetryRun, metric: MetricDefinition, segment: SegmentDefinition) -> dict[str, Any]:
    channel = resolve_channel(run, metric.channel) or metric.channel
    x, y = channel_xy(run, channel, segment.x_mode)
    p = prepare_plot_series(x, y, max_points=None)
    if p.output_points < 1:
        value = float("nan")
        count = 0
    else:
        lo, hi = sorted((float(segment.start), float(segment.end)))
        mask = (p.x >= lo) & (p.x <= hi)
        xx = p.x[mask]; yy = p.y[mask]
        # Gates are evaluated without hidden resampling. They can therefore be
        # applied only when this channel shares the rectangular analysis clock.
        gate_expr = named_gate_expression(run, metric.gate) if metric.gate else ""
        if gate_expr:
            if channel not in run.data.columns:
                raise ValueError(f"Gate {metric.gate!r} cannot be applied to native-only channel {channel!r} without an explicit normalized channel.")
            tc = run.channel_map.get("time_s")
            if not tc or tc not in run.data.columns:
                raise ValueError("Gated metrics require a mapped analysis time channel.")
            gx, _ = channel_xy(run, channel, segment.x_mode)
            gmask = evaluate_gate(run, gate_expr)
            n = min(len(gx), len(gmask), len(run.data[channel]))
            gx = np.asarray(gx[:n], float); gy = pd.to_numeric(run.data[channel].iloc[:n], errors="coerce").to_numpy(float); gmask = gmask[:n]
            smask = (gx >= lo) & (gx <= hi) & gmask
            xx, yy = gx[smask], gy[smask]
        value = _statistic(metric.statistic, np.asarray(xx, float), np.asarray(yy, float))
        count = int(np.isfinite(yy).sum())
    return {
        "metric": metric.name,
        "channel": channel,
        "statistic": metric.statistic,
        "segment": segment.name,
        "x_mode": segment.x_mode,
        "start": float(segment.start),
        "end": float(segment.end),
        "gate": metric.gate,
        "unit": metric.unit or normalize_unit(run.units.get(channel, "")),
        "value": value,
        "count": count,
    }


def metric_report(
    runs: Sequence[tuple[str, TelemetryRun]],
    metrics: Sequence[MetricDefinition],
    segments: Sequence[SegmentDefinition],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for label, run in runs:
        for segment in segments:
            for metric in metrics:
                rec = evaluate_metric(run, metric, segment)
                rec["run"] = str(label)
                rows.append(rec)
    cols = ["run", "segment", "metric", "channel", "statistic", "gate", "value", "unit", "count", "x_mode", "start", "end"]
    return pd.DataFrame(rows, columns=cols)


def drag_metric_report(
    runs: Sequence[tuple[str, TelemetryRun]],
    metrics: Sequence[MetricDefinition],
    *,
    x_mode: str = "Time from Launch",
) -> pd.DataFrame:
    """Evaluate named KPIs over each run's own official NHRA segments.

    In time mode, Q1's 60→330 window should use Q1's official 60/330 times and
    Q2 should use Q2's.  Reusing the Main run's timestamps across every run is
    a subtle comparison error, so this helper regenerates official segments for
    each run independently while preserving common segment names.
    """
    rows: list[dict[str, Any]] = []
    for label, run in runs:
        for segment in official_drag_segments(run, x_mode):
            for metric in metrics:
                rec = evaluate_metric(run, metric, segment)
                rec["run"] = str(label)
                rows.append(rec)
    cols = ["run", "segment", "metric", "channel", "statistic", "gate", "value", "unit", "count", "x_mode", "start", "end"]
    return pd.DataFrame(rows, columns=cols)
