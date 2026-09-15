from __future__ import annotations

"""Portable analysis definitions and saved reports.

The library is deliberately Qt-independent.  It describes reusable engineering
logic (constants, calculated channels, gates, segments, KPIs, conditions and
reports) using canonical channel roles where possible so one definition can be
applied across logger vendors without mutating raw telemetry.
"""

from dataclasses import asdict, dataclass, field
import ast
import copy
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from .math_channels import add_math_channel
from .models import TelemetryRun
from .workstation import GateDefinition, MetricDefinition, SegmentDefinition, evaluate_metric, resolve_channel, save_gate

from .product_manifest import ANALYSIS_LIBRARY_FORMAT_VERSION

LIBRARY_VERSION = ANALYSIS_LIBRARY_FORMAT_VERSION
_LIBRARY_EXT = ".nhralib"
_BACKTICK = re.compile(r"`([^`]+)`")
_MATH_FUNCS = {"abs", "sqrt", "clip", "smooth", "derivative", "integral", "lowpass", "highpass", "bandpass", "rollingmean", "rollingrms"}
_GATE_FUNCS = {"abs", "isfinite", "between"}


@dataclass(frozen=True)
class ConstantDefinition:
    name: str
    value: float
    unit: str = ""
    description: str = ""


@dataclass(frozen=True)
class CalculatedChannelDefinition:
    name: str
    expression: str
    unit: str = ""
    description: str = ""


@dataclass(frozen=True)
class PortableGateDefinition:
    name: str
    expression: str
    description: str = ""


@dataclass(frozen=True)
class SegmentTemplate:
    name: str
    x_mode: str = "Time from Launch"
    source: str = "manual"  # manual | official
    start: float | None = None
    end: float | None = None
    start_ref: str = ""
    end_ref: str = ""
    description: str = ""


@dataclass(frozen=True)
class PortableMetricDefinition:
    name: str
    channel: str
    statistic: str = "mean"
    gate: str = ""
    unit: str = ""
    description: str = ""


@dataclass(frozen=True)
class EventRuleDefinition:
    name: str
    expression: str
    event_type: str = "event"
    severity: str = "info"
    trigger: str = "interval"  # interval | rising | falling
    min_duration_s: float = 0.0
    description: str = ""


@dataclass(frozen=True)
class ConditionalRule:
    name: str
    metric: str
    segment: str = ""
    operator: str = ">"
    threshold: float = 0.0
    threshold_high: float | None = None
    severity: str = "warning"
    message: str = ""


@dataclass(frozen=True)
class ReportDefinition:
    name: str
    metrics: list[str] = field(default_factory=list)
    segments: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class LibraryValidation:
    valid: bool
    missing: list[str] = field(default_factory=list)
    cycles: list[list[str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dependencies: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DefinitionLibrary:
    version: int = LIBRARY_VERSION
    name: str = "Analysis Library"
    description: str = ""
    constants: dict[str, ConstantDefinition] = field(default_factory=dict)
    calculated_channels: dict[str, CalculatedChannelDefinition] = field(default_factory=dict)
    gates: dict[str, PortableGateDefinition] = field(default_factory=dict)
    segments: dict[str, SegmentTemplate] = field(default_factory=dict)
    metrics: dict[str, PortableMetricDefinition] = field(default_factory=dict)
    conditions: dict[str, ConditionalRule] = field(default_factory=dict)
    event_rules: dict[str, EventRuleDefinition] = field(default_factory=dict)
    reports: dict[str, ReportDefinition] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": int(self.version),
            "name": self.name,
            "description": self.description,
            "constants": {k: asdict(v) for k, v in self.constants.items()},
            "calculated_channels": {k: asdict(v) for k, v in self.calculated_channels.items()},
            "gates": {k: asdict(v) for k, v in self.gates.items()},
            "segments": {k: asdict(v) for k, v in self.segments.items()},
            "metrics": {k: asdict(v) for k, v in self.metrics.items()},
            "conditions": {k: asdict(v) for k, v in self.conditions.items()},
            "event_rules": {k: asdict(v) for k, v in self.event_rules.items()},
            "reports": {k: asdict(v) for k, v in self.reports.items()},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "DefinitionLibrary":
        d = dict(data or {})
        def build(key: str, typ):
            out = {}
            raw = d.get(key, {})
            if isinstance(raw, list):
                raw = {str(x.get("name", "")): x for x in raw if isinstance(x, dict)}
            if isinstance(raw, dict):
                for name, rec in raw.items():
                    if not isinstance(rec, dict):
                        continue
                    payload = dict(rec); payload.setdefault("name", str(name))
                    try:
                        obj = typ(**{k: v for k, v in payload.items() if k in typ.__dataclass_fields__})
                    except (TypeError, ValueError):
                        continue
                    if str(getattr(obj, "name", "")).strip(): out[str(obj.name)] = obj
            return out
        return cls(
            version=int(d.get("version", LIBRARY_VERSION) or LIBRARY_VERSION),
            name=str(d.get("name", "Analysis Library")),
            description=str(d.get("description", "")),
            constants=build("constants", ConstantDefinition),
            calculated_channels=build("calculated_channels", CalculatedChannelDefinition),
            gates=build("gates", PortableGateDefinition),
            segments=build("segments", SegmentTemplate),
            metrics=build("metrics", PortableMetricDefinition),
            conditions=build("conditions", ConditionalRule),
            event_rules=build("event_rules", EventRuleDefinition),
            reports=build("reports", ReportDefinition),
        )

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        if target.suffix.lower() != _LIBRARY_EXT:
            target = target.with_suffix(_LIBRARY_EXT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path) -> "DefinitionLibrary":
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(obj, dict): raise ValueError("Analysis library root must be a JSON object.")
        return cls.from_dict(obj)


def starter_library() -> DefinitionLibrary:
    lib = DefinitionLibrary(name="NHRA Drag Analysis Starter", description="Portable starter definitions using canonical channel roles.")
    lib.segments["Full Run"] = SegmentTemplate("Full Run", source="official", start_ref="launch", end_ref="finish")
    lib.segments["60 → 330"] = SegmentTemplate("60 → 330", source="official", start_ref="60", end_ref="330")
    lib.segments["330 → 660"] = SegmentTemplate("330 → 660", source="official", start_ref="330", end_ref="660")
    lib.metrics["Peak Engine RPM"] = PortableMetricDefinition("Peak Engine RPM", "engine_rpm", "max")
    lib.metrics["Peak Longitudinal G"] = PortableMetricDefinition("Peak Longitudinal G", "longitudinal_g", "max")
    lib.reports["Drag Run Review"] = ReportDefinition("Drag Run Review", metrics=["Peak Engine RPM", "Peak Longitudinal G"], segments=["Full Run"])
    return lib


def _symbol_refs(expression: str, allowed_functions: set[str]) -> set[str]:
    refs = set(_BACKTICK.findall(str(expression or "")))
    prepared = _BACKTICK.sub("0", str(expression or ""))
    try:
        tree = ast.parse(prepared, mode="eval")
    except SyntaxError:
        return refs
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in allowed_functions:
            refs.add(node.id)
    return refs


def dependency_graph(lib: DefinitionLibrary) -> dict[str, list[str]]:
    graph: dict[str, list[str]] = {}
    known_defs = set(lib.calculated_channels) | set(lib.constants)
    for name, rec in lib.calculated_channels.items():
        graph[f"calc:{name}"] = sorted(r for r in _symbol_refs(rec.expression, _MATH_FUNCS) if r in known_defs)
    for name, rec in lib.gates.items():
        graph[f"gate:{name}"] = sorted(r for r in _symbol_refs(rec.expression, _GATE_FUNCS) if r in known_defs)
    for name, rec in lib.event_rules.items():
        graph[f"event:{name}"] = sorted(r for r in _symbol_refs(rec.expression, _GATE_FUNCS) if r in known_defs)
    for name, rec in lib.metrics.items():
        deps = [rec.channel]
        if rec.gate: deps.append(f"gate:{rec.gate}")
        graph[f"metric:{name}"] = deps
    for name, rec in lib.reports.items():
        graph[f"report:{name}"] = [*(f"metric:{x}" for x in rec.metrics), *(f"segment:{x}" for x in rec.segments), *(f"condition:{x}" for x in rec.conditions)]
    return graph


def _calc_cycles(lib: DefinitionLibrary) -> list[list[str]]:
    names = set(lib.calculated_channels)
    deps = {n: {r for r in _symbol_refs(d.expression, _MATH_FUNCS) if r in names} for n, d in lib.calculated_channels.items()}
    cycles: list[list[str]] = []
    state: dict[str, int] = {}
    stack: list[str] = []
    def visit(n: str):
        state[n] = 1; stack.append(n)
        for d in deps.get(n, set()):
            if state.get(d, 0) == 0: visit(d)
            elif state.get(d) == 1:
                i = stack.index(d); cyc = stack[i:] + [d]
                if cyc not in cycles: cycles.append(cyc)
        stack.pop(); state[n] = 2
    for n in sorted(names):
        if state.get(n, 0) == 0: visit(n)
    return cycles


def _topological_calcs(lib: DefinitionLibrary) -> list[str]:
    cycles = _calc_cycles(lib)
    if cycles:
        raise ValueError("Calculated-channel dependency cycle: " + " -> ".join(cycles[0]))
    names = set(lib.calculated_channels)
    deps = {n: {r for r in _symbol_refs(d.expression, _MATH_FUNCS) if r in names} for n, d in lib.calculated_channels.items()}
    out: list[str] = []
    pending = set(names)
    while pending:
        ready = sorted(n for n in pending if deps[n].issubset(set(out)))
        if not ready: raise ValueError("Could not resolve calculated-channel dependency order.")
        out.extend(ready); pending.difference_update(ready)
    return out


def _constant_column(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", str(name)).strip("_") or "value"
    return f"__lib_const_{safe}"


def _install_constants(run: TelemetryRun, lib: DefinitionLibrary) -> None:
    for name, rec in lib.constants.items():
        col = _constant_column(name)
        run.data[col] = np.full(len(run.data), float(rec.value), dtype=float)
        run.units[col] = str(rec.unit or "")
        run.metadata.setdefault("unit_provenance", {})[col] = f"analysis-library constant: {name}"


def _portable_token(run: TelemetryRun, lib: DefinitionLibrary, token: str) -> tuple[str, str]:
    """Return (kind, materialized token)."""
    if token in lib.constants:
        return "constant", f"`{_constant_column(token)}`"
    if token in lib.calculated_channels:
        # Calculated definitions are materialized with their declared names.
        return "calculated", f"`{token}`"
    channel = resolve_channel(run, token)
    if channel:
        return "channel", f"`{channel}`"
    return "missing", token


def materialize_expression(run: TelemetryRun, lib: DefinitionLibrary, expression: str, *, gate: bool = False) -> str:
    allowed = _GATE_FUNCS if gate else _MATH_FUNCS
    expr = str(expression or "")
    placeholders: dict[str, str] = {}
    def backtick(match: re.Match[str]) -> str:
        key = f"__portable_ref_{len(placeholders)}"
        kind, value = _portable_token(run, lib, match.group(1))
        if kind == "missing": raise ValueError(f"Missing channel/library reference: {match.group(1)!r}")
        placeholders[key] = value
        return key
    prepared = _BACKTICK.sub(backtick, expr)
    try:
        tree = ast.parse(prepared, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid portable expression: {exc.msg}") from exc
    class X(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name):
            if node.id in placeholders or node.id in allowed:
                return node
            kind, value = _portable_token(run, lib, node.id)
            if kind in {"constant", "channel", "calculated"}:
                key = f"__portable_ref_{len(placeholders)}"; placeholders[key] = value
                return ast.copy_location(ast.Name(id=key, ctx=ast.Load()), node)
            raise ValueError(f"Missing channel/library reference: {node.id!r}")
    tree = X().visit(tree); ast.fix_missing_locations(tree)
    text = ast.unparse(tree.body)
    # Replace only identifier placeholders produced above.
    for key, value in sorted(placeholders.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"\b{re.escape(key)}\b", value, text)
    return text


def validate_library(lib: DefinitionLibrary, run: TelemetryRun | None = None) -> LibraryValidation:
    missing: list[str] = []
    warnings: list[str] = []
    cycles = _calc_cycles(lib)
    if run is not None:
        for kind, records, funcs in (("calc", lib.calculated_channels, _MATH_FUNCS), ("gate", lib.gates, _GATE_FUNCS)):
            for name, rec in records.items():
                for ref in sorted(_symbol_refs(rec.expression, funcs)):
                    if ref in lib.constants or ref in lib.calculated_channels: continue
                    if resolve_channel(run, ref) is None: missing.append(f"{kind}:{name} -> {ref}")
        for name, rec in lib.event_rules.items():
            for ref in sorted(_symbol_refs(rec.expression, _GATE_FUNCS)):
                if ref in lib.constants or ref in lib.calculated_channels: continue
                if resolve_channel(run, ref) is None: missing.append(f"event:{name} -> {ref}")
        for name, rec in lib.metrics.items():
            if rec.channel not in lib.calculated_channels and resolve_channel(run, rec.channel) is None:
                missing.append(f"metric:{name} -> {rec.channel}")
            if rec.gate and rec.gate not in lib.gates: missing.append(f"metric:{name} -> gate:{rec.gate}")
    for name, rec in lib.reports.items():
        for metric in rec.metrics:
            if metric not in lib.metrics: missing.append(f"report:{name} -> metric:{metric}")
        for segment in rec.segments:
            if segment not in lib.segments: missing.append(f"report:{name} -> segment:{segment}")
        for cond in rec.conditions:
            if cond not in lib.conditions: missing.append(f"report:{name} -> condition:{cond}")
    for name, rec in lib.conditions.items():
        if rec.metric not in lib.metrics: missing.append(f"condition:{name} -> metric:{rec.metric}")
        if rec.segment and rec.segment not in lib.segments: missing.append(f"condition:{name} -> segment:{rec.segment}")
    missing = sorted(set(missing))
    return LibraryValidation(not missing and not cycles, missing, cycles, warnings, dependency_graph(lib))


def apply_library(run: TelemetryRun, lib: DefinitionLibrary) -> dict[str, Any]:
    check = validate_library(lib, run)
    # Missing references to calculated channels are okay at preflight because they
    # are materialized in dependency order; everything else is a hard failure.
    hard = [m for m in check.missing if not any(f" -> {name}" in m for name in lib.calculated_channels)]
    if hard or check.cycles:
        raise ValueError("Analysis library cannot be applied: " + "; ".join(hard or ["dependency cycle"]))
    _install_constants(run, lib)
    applied_calcs: list[str] = []
    for name in _topological_calcs(lib):
        rec = lib.calculated_channels[name]
        expr = materialize_expression(run, lib, rec.expression, gate=False)
        add_math_channel(run, rec.name, expr, rec.unit, persist=True, replace=True)
        applied_calcs.append(rec.name)
    applied_gates: list[str] = []
    for name, rec in lib.gates.items():
        expr = materialize_expression(run, lib, rec.expression, gate=True)
        save_gate(run, GateDefinition(rec.name, expr, rec.description)); applied_gates.append(rec.name)
    run.metadata["analysis_library_name"] = lib.name
    run.metadata["analysis_library_version"] = lib.version
    return {"calculated_channels": applied_calcs, "gates": applied_gates}


_OFFICIAL_TIME = {
    "launch": lambda r: 0.0,
    "60": lambda r: r.timing.sixty_ft_s,
    "60 ft": lambda r: r.timing.sixty_ft_s,
    "330": lambda r: r.timing.three_thirty_ft_s,
    "330 ft": lambda r: r.timing.three_thirty_ft_s,
    "660": lambda r: r.timing.eighth_mile_s,
    "660 ft": lambda r: r.timing.eighth_mile_s,
    "1000": lambda r: r.timing.thousand_ft_s,
    "1000 ft": lambda r: r.timing.thousand_ft_s,
    "1320": lambda r: r.timing.quarter_mile_s,
    "1320 ft": lambda r: r.timing.quarter_mile_s,
    "finish": lambda r: r.timing.quarter_mile_s or r.timing.thousand_ft_s or r.timing.eighth_mile_s,
}
_OFFICIAL_DISTANCE = {"launch": 0.0, "60": 60.0, "60 ft": 60.0, "330": 330.0, "330 ft": 330.0, "660": 660.0, "660 ft": 660.0, "1000": 1000.0, "1000 ft": 1000.0, "1320": 1320.0, "1320 ft": 1320.0, "finish": 1320.0}


def resolve_segment(run: TelemetryRun, template: SegmentTemplate) -> SegmentDefinition:
    if template.source != "official":
        if template.start is None or template.end is None: raise ValueError(f"Manual segment {template.name!r} needs start/end values.")
        return SegmentDefinition(template.name, template.x_mode, float(template.start), float(template.end), "manual")
    mode = template.x_mode
    a = str(template.start_ref or "launch").lower().strip(); b = str(template.end_ref or "finish").lower().strip()
    if mode.lower().startswith("distance"):
        if a not in _OFFICIAL_DISTANCE or b not in _OFFICIAL_DISTANCE: raise ValueError(f"Unknown official segment boundary: {a!r}/{b!r}")
        x1, x2 = _OFFICIAL_DISTANCE[a], _OFFICIAL_DISTANCE[b]
    elif mode.lower().startswith("normalized"):
        x1 = 0.0 if a == "launch" else None; x2 = 100.0 if b in {"finish", "1320", "1320 ft"} else None
    else:
        if a not in _OFFICIAL_TIME or b not in _OFFICIAL_TIME: raise ValueError(f"Unknown official segment boundary: {a!r}/{b!r}")
        x1, x2 = _OFFICIAL_TIME[a](run), _OFFICIAL_TIME[b](run)
    if x1 is None or x2 is None: raise ValueError(f"Run is missing official timing needed for segment {template.name!r} ({a} → {b}).")
    if float(x2) <= float(x1): raise ValueError(f"Segment {template.name!r} end must be after start.")
    return SegmentDefinition(template.name, mode, float(x1), float(x2), "official")


def _condition_match(value: float, rule: ConditionalRule) -> bool:
    if not math.isfinite(float(value)): return False
    op = rule.operator.strip().lower()
    v, t = float(value), float(rule.threshold)
    if op == ">": return v > t
    if op == ">=": return v >= t
    if op == "<": return v < t
    if op == "<=": return v <= t
    if op in {"==", "="}: return v == t
    if op == "!=": return v != t
    if op in {"between", "inside"}:
        if rule.threshold_high is None: raise ValueError(f"Conditional rule {rule.name!r} requires threshold_high.")
        lo, hi = sorted((t, float(rule.threshold_high))); return lo <= v <= hi
    if op in {"outside", "not_between"}:
        if rule.threshold_high is None: raise ValueError(f"Conditional rule {rule.name!r} requires threshold_high.")
        lo, hi = sorted((t, float(rule.threshold_high))); return v < lo or v > hi
    raise ValueError(f"Unknown conditional operator: {rule.operator!r}")


def run_saved_report(lib: DefinitionLibrary, report_name: str, runs: Sequence[tuple[str, TelemetryRun]]) -> pd.DataFrame:
    if report_name not in lib.reports: raise KeyError(f"Unknown report: {report_name!r}")
    report = lib.reports[report_name]
    rows: list[dict[str, Any]] = []
    for label, source_run in runs:
        run = copy.deepcopy(source_run)
        apply_library(run, lib)
        for segment_name in report.segments:
            seg = resolve_segment(run, lib.segments[segment_name])
            for metric_name in report.metrics:
                m = lib.metrics[metric_name]
                rec = evaluate_metric(run, MetricDefinition(m.name, m.channel, m.statistic, m.gate, m.unit), seg)
                rec["run"] = str(label); rec["status"] = "ok"; rec["severity"] = ""; rec["message"] = ""
                for cond_name in report.conditions:
                    rule = lib.conditions[cond_name]
                    if rule.metric != metric_name: continue
                    if rule.segment and rule.segment != segment_name: continue
                    if _condition_match(float(rec["value"]), rule):
                        rec["status"] = rule.name; rec["severity"] = rule.severity; rec["message"] = rule.message or rule.name
                rows.append(rec)
    cols = ["run", "segment", "metric", "value", "unit", "status", "severity", "message", "channel", "statistic", "gate", "count", "x_mode", "start", "end"]
    return pd.DataFrame(rows, columns=cols)


def trend_frame(lib: DefinitionLibrary, report_name: str, runs: Sequence[tuple[str, TelemetryRun]], metric: str, segment: str) -> pd.DataFrame:
    frame = run_saved_report(lib, report_name, runs)
    if frame.empty: return frame
    return frame[(frame["metric"] == metric) & (frame["segment"] == segment)].reset_index(drop=True)


def export_report(frame: pd.DataFrame, path: str | Path) -> Path:
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    suffix = target.suffix.lower()
    if suffix == ".csv": frame.to_csv(target, index=False)
    elif suffix == ".json": target.write_text(frame.to_json(orient="records", indent=2), encoding="utf-8")
    elif suffix in {".xlsx", ".xlsm"}:
        with pd.ExcelWriter(target, engine="openpyxl") as writer:
            frame.to_excel(writer, index=False, sheet_name="Report")
            ws = writer.book["Report"]
            ws.freeze_panes = "A2"; ws.auto_filter.ref = ws.dimensions
            for column_cells in ws.columns:
                width = min(42, max(10, max(len(str(c.value or "")) for c in column_cells) + 2))
                ws.column_dimensions[column_cells[0].column_letter].width = width
    else: raise ValueError("Report export must use .csv, .json or .xlsx.")
    return target


def capture_from_run(run: TelemetryRun, *, name: str = "Captured Analysis") -> DefinitionLibrary:
    lib = DefinitionLibrary(name=name)
    for rec in run.metadata.get("math_channels", []):
        if isinstance(rec, dict) and rec.get("name") and rec.get("expression"):
            d = CalculatedChannelDefinition(str(rec["name"]), str(rec["expression"]), str(rec.get("unit", "")))
            lib.calculated_channels[d.name] = d
    for rec in run.metadata.get("gates", []):
        if isinstance(rec, dict) and rec.get("name") and rec.get("expression"):
            d = PortableGateDefinition(str(rec["name"]), str(rec["expression"]), str(rec.get("description", "")))
            lib.gates[d.name] = d
    return lib
