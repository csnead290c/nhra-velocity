from __future__ import annotations

"""Portable rule-generated events and historical alarm state."""

from dataclasses import asdict, dataclass
import copy
from typing import Any

import numpy as np
import pandas as pd

from .definition_library import DefinitionLibrary, EventRuleDefinition, apply_library, materialize_expression
from .models import TelemetryRun
from .workstation import evaluate_gate
from .telemetry import detect_drag_pass_window


@dataclass(frozen=True)
class RuleEvent:
    rule: str
    event_type: str
    severity: str
    start_s: float
    end_s: float
    duration_s: float
    trigger: str
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _time_from_launch(run: TelemetryRun) -> np.ndarray:
    tc = run.channel_map.get("time_s")
    if not tc or tc not in run.data.columns:
        raise ValueError("Rule events require a mapped rectangular time channel.")
    t = pd.to_numeric(run.data[tc], errors="coerce").to_numpy(float)
    if len(t) < 2 or not np.all(np.isfinite(t)) or np.any(np.diff(t) <= 0):
        raise ValueError("Rule events require a finite, strictly increasing timebase.")
    try:
        launch = float(detect_drag_pass_window(run).launch_time_s)
    except Exception:
        launch = float(t[0])
    return t - launch


def _intervals(mask: np.ndarray, t: np.ndarray) -> list[tuple[int, int, float, float]]:
    mask = np.asarray(mask, dtype=bool)
    if len(mask) != len(t):
        raise ValueError("Rule mask/timebase length mismatch.")
    starts = np.flatnonzero(mask & np.r_[True, ~mask[:-1]])
    ends = np.flatnonzero(mask & np.r_[~mask[1:], True])
    return [(int(a), int(b), float(t[a]), float(t[b])) for a, b in zip(starts, ends)]


def _evaluate_rule_on_prepared(lib: DefinitionLibrary, work: TelemetryRun, rule: EventRuleDefinition, t: np.ndarray) -> list[RuleEvent]:
    expr = materialize_expression(work, lib, rule.expression, gate=True)
    mask = evaluate_gate(work, expr)
    trigger = str(rule.trigger or "interval").lower().strip()
    if trigger not in {"interval", "rising", "falling"}:
        raise ValueError(f"Unknown event trigger: {rule.trigger!r}")
    out: list[RuleEvent] = []
    for _a, b, start, end in _intervals(mask, t):
        duration = max(0.0, end - start)
        if duration + 1e-12 < float(rule.min_duration_s or 0.0):
            continue
        if trigger == "rising":
            end = start; duration = 0.0
        elif trigger == "falling":
            # A falling edge occurs at the first false sample when one exists.
            edge = float(t[b + 1]) if b + 1 < len(t) else end
            start = end = edge; duration = 0.0
        out.append(RuleEvent(rule.name, rule.event_type, rule.severity, start, end, duration, trigger, rule.description))
    return out


def evaluate_event_rule(lib: DefinitionLibrary, run: TelemetryRun, rule: EventRuleDefinition) -> list[RuleEvent]:
    work = copy.deepcopy(run)
    apply_library(work, lib)
    t = _time_from_launch(work)
    return _evaluate_rule_on_prepared(lib, work, rule, t)


def evaluate_event_rules(lib: DefinitionLibrary, run: TelemetryRun) -> pd.DataFrame:
    # Prepare portable constants/calculated channels/gates exactly once even when
    # many historical rules are evaluated against the same Run.
    work = copy.deepcopy(run)
    apply_library(work, lib)
    t = _time_from_launch(work)
    rows: list[dict[str, Any]] = []
    for rule in lib.event_rules.values():
        rows.extend(e.to_dict() for e in _evaluate_rule_on_prepared(lib, work, rule, t))
    cols = ["rule", "event_type", "severity", "start_s", "end_s", "duration_s", "trigger", "description"]
    frame = pd.DataFrame(rows, columns=cols)
    if not frame.empty:
        frame = frame.sort_values(["start_s", "rule"], kind="stable").reset_index(drop=True)
    return frame


def alarm_states_at(lib: DefinitionLibrary, run: TelemetryRun, time_s: float) -> list[dict[str, Any]]:
    frame = evaluate_event_rules(lib, run)
    out: list[dict[str, Any]] = []
    target = float(time_s)
    for name, rule in lib.event_rules.items():
        matching = frame[frame["rule"] == name]
        active = False
        if rule.trigger == "interval" and not matching.empty:
            active = bool(((matching["start_s"] <= target) & (matching["end_s"] >= target)).any())
        last = matching[matching["start_s"] <= target].tail(1)
        out.append({
            "rule": name,
            "active": active,
            "severity": rule.severity,
            "event_type": rule.event_type,
            "last_event_s": None if last.empty else float(last.iloc[0]["start_s"]),
            "description": rule.description,
        })
    return out
