from __future__ import annotations

"""Safe calculated-channel support for desktop telemetry projects.

Expressions use ordinary arithmetic and may reference source channels with
backticks, for example::

    (`Engine RPM` / `Clutch RPM`) * 100

Only numeric constants, channel references, parentheses, arithmetic operators
and a small engineering whitelist are accepted. Attribute access, indexing,
imports and arbitrary Python execution are deliberately rejected.

Whitelisted functions: abs(x), sqrt(x), clip(x, lo, hi), smooth(x, seconds),
derivative(x), integral(x), lowpass(x, cutoff_hz[, order]),
highpass(x, cutoff_hz[, order]), bandpass(x, low_hz, high_hz[, order]),
rollingmean(x, seconds), rollingrms(x, seconds), rollingmin(x, seconds),
rollingmax(x, seconds), and rollingstd(x, seconds). Time-domain engineering
functions use the run's canonical time channel and fail closed when a valid
monotonic timebase is absent.
"""

from dataclasses import dataclass
import ast
import re
from typing import Dict, Tuple, Any

import numpy as np
import pandas as pd

from .models import TelemetryRun
from .importers import CANONICAL_CHANNELS
from .units import normalize_unit, UNITS
from .signal_analysis import filter_on_original_timebase


_BACKTICK = re.compile(r"`([^`]+)`")
_CANONICAL_REF = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)")


@dataclass
class MathChannelDefinition:
    name: str
    expression: str
    unit: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {"name": self.name, "expression": self.expression, "unit": self.unit}


_ALLOWED_BINOPS = {
    ast.Add: np.add,
    ast.Sub: np.subtract,
    ast.Mult: np.multiply,
    ast.Div: np.divide,
    ast.Pow: np.power,
    ast.Mod: np.mod,
}
_ALLOWED_UNARY = {ast.UAdd: lambda x: x, ast.USub: np.negative}


def _prepare(expression: str, columns) -> Tuple[str, Dict[str, str]]:
    mapping: Dict[str, str] = {}
    counter = 0

    def repl(match):
        nonlocal counter
        channel = match.group(1)
        if channel not in columns:
            raise ValueError(f"Unknown channel in expression: {channel!r}")
        key = f"__calc_ch_{counter}"
        counter += 1
        mapping[key] = channel
        return key

    prepared = _BACKTICK.sub(repl, str(expression))
    # Identifier-safe column names may be referenced without backticks.
    for col in columns:
        c = str(col)
        if c.isidentifier() and c not in mapping:
            mapping.setdefault(c, c)
    return prepared, mapping


def _time_vector(df: pd.DataFrame, time_column: str | None = None) -> np.ndarray:
    candidate = time_column
    if not candidate:
        for name in ("__time_s", "time_s", "Time", "Time [s]", "TIME"):
            if name in df.columns:
                candidate = name; break
    if not candidate or candidate not in df.columns:
        raise ValueError("This math function requires a mapped time channel.")
    t = pd.to_numeric(df[candidate], errors="coerce").to_numpy(dtype=float)
    if len(t) < 2 or not np.all(np.isfinite(t)) or np.any(np.diff(t) <= 0):
        raise ValueError("Derivative/integral math requires a finite, strictly increasing timebase.")
    return t


def _eval_node(node: ast.AST, env: Dict[str, np.ndarray], df: pd.DataFrame, time_column: str | None = None):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, env, df, time_column)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        raise ValueError("Only numeric constants are allowed in math channels.")
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise ValueError(f"Unknown channel or symbol: {node.id!r}")
        return env[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        left = _eval_node(node.left, env, df, time_column)
        right = _eval_node(node.right, env, df, time_column)
        with np.errstate(all="ignore"):
            return _ALLOWED_BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
        return _ALLOWED_UNARY[type(node.op)](_eval_node(node.operand, env, df, time_column))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fname = node.func.id.lower()
        if fname not in {"abs","sqrt","clip","smooth","derivative","integral","lowpass","highpass","bandpass","rollingmean","rollingrms","rollingmin","rollingmax","rollingstd"}:
            raise ValueError(f"Math function {fname!r} is not allowed.")
        args=[_eval_node(a,env,df,time_column) for a in node.args]
        if fname=="abs" and len(args)==1:
            return np.abs(args[0])
        if fname=="sqrt" and len(args)==1:
            with np.errstate(invalid="ignore"): return np.sqrt(args[0])
        if fname=="clip" and len(args)==3:
            return np.clip(args[0],float(np.asarray(args[1]).flat[0]),float(np.asarray(args[2]).flat[0]))
        if fname=="smooth" and len(args)==2:
            arr=np.asarray(args[0],dtype=float); seconds=float(np.asarray(args[1]).flat[0]); t=_time_vector(df,time_column)
            if seconds<=0:return arr
            dt=float(np.nanmedian(np.diff(t))); n=max(1,int(round(seconds/max(dt,1e-12))))
            if n<=1:return arr
            if n%2==0:n+=1
            return pd.Series(arr).rolling(n,center=True,min_periods=1).mean().to_numpy(float)
        if fname=="derivative" and len(args)==1:
            arr=np.asarray(args[0],dtype=float); t=_time_vector(df,time_column)
            return np.gradient(arr,t)
        if fname=="integral" and len(args)==1:
            arr=np.asarray(args[0],dtype=float); t=_time_vector(df,time_column)
            dt=np.diff(t,prepend=t[0]); dt[0]=0.0
            # trapezoidal cumulative integral
            prev=np.r_[arr[0],arr[:-1]]
            return np.cumsum(0.5*(arr+prev)*dt)
        if fname in {"lowpass","highpass"} and len(args) in {2,3}:
            arr=np.asarray(args[0],dtype=float); t=_time_vector(df,time_column)
            cutoff=float(np.asarray(args[1]).flat[0]); order=int(float(np.asarray(args[2]).flat[0])) if len(args)==3 else 4
            return filter_on_original_timebase(t,arr,kind=fname,cutoff_hz=cutoff,order=order)
        if fname=="bandpass" and len(args) in {3,4}:
            arr=np.asarray(args[0],dtype=float); t=_time_vector(df,time_column)
            lo=float(np.asarray(args[1]).flat[0]); hi=float(np.asarray(args[2]).flat[0]); order=int(float(np.asarray(args[3]).flat[0])) if len(args)==4 else 4
            return filter_on_original_timebase(t,arr,kind='bandpass',cutoff_hz=(lo,hi),order=order)
        if fname in {"rollingmean","rollingrms","rollingmin","rollingmax","rollingstd"} and len(args)==2:
            arr=np.asarray(args[0],dtype=float); t=_time_vector(df,time_column)
            seconds=float(np.asarray(args[1]).flat[0])
            if seconds<=0: raise ValueError('Rolling window must be positive.')
            dt=float(np.nanmedian(np.diff(t))); n=max(1,int(round(seconds/max(dt,1e-12))))
            series=pd.Series(arr); rolling=series.rolling(n,center=True,min_periods=1)
            if fname=='rollingmean': return rolling.mean().to_numpy(float)
            if fname=='rollingmin': return rolling.min().to_numpy(float)
            if fname=='rollingmax': return rolling.max().to_numpy(float)
            if fname=='rollingstd': return rolling.std(ddof=0).fillna(0.0).to_numpy(float)
            return np.sqrt(series.pow(2).rolling(n,center=True,min_periods=1).mean().to_numpy(float))
        raise ValueError(f"Invalid arguments for math function {fname!r}.")
    raise ValueError(
        "Unsupported expression element. Math channels allow channel references, numeric constants, "
        "parentheses, arithmetic and the approved engineering functions only."
    )



def resolve_expression_references(run: TelemetryRun, expression: str) -> str:
    """Resolve portable common-channel and display-alias references.

    ``@engine_rpm`` style references are intentionally stable across logger
    vendors. Backtick references may use either an actual source-channel name
    or the run-local display alias. The returned expression contains only
    concrete dataframe channel names and can be evaluated by the safe AST
    engine below.
    """
    text = str(expression or "")

    def common_repl(match: re.Match[str]) -> str:
        canonical = match.group(1)
        if canonical not in CANONICAL_CHANNELS:
            raise ValueError(f"Unknown common channel reference: @{canonical}")
        source = run.channel_map.get(canonical)
        if not source or source not in run.data.columns:
            raise ValueError(
                f"Common channel @{canonical} is not mapped for this data set. "
                "Assign it in Data > Common Channel Mapping first."
            )
        return f"`{source}`"

    text = _CANONICAL_REF.sub(common_repl, text)

    # Resolve backtick aliases after canonical references have been expanded.
    from .workstation import resolve_channel

    def alias_repl(match: re.Match[str]) -> str:
        requested = match.group(1)
        if requested in run.data.columns:
            resolved = requested
        else:
            resolved = resolve_channel(run, requested)
        if not resolved or resolved not in run.data.columns:
            raise ValueError(f"Unknown channel or alias in expression: {requested!r}")
        return f"`{resolved}`"

    return _BACKTICK.sub(alias_repl, text)


def evaluate_run_expression(run: TelemetryRun, expression: str) -> np.ndarray:
    resolved = resolve_expression_references(run, expression)
    return evaluate_expression(run.data, resolved, time_column=run.channel_map.get("time_s"))

def evaluate_expression(df: pd.DataFrame, expression: str, *, time_column: str | None = None) -> np.ndarray:
    if not str(expression).strip():
        raise ValueError("Math expression is blank.")
    prepared, mapping = _prepare(expression, df.columns)
    try:
        tree = ast.parse(prepared, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid math expression: {exc.msg}") from exc
    env: Dict[str, np.ndarray] = {}
    for key, channel in mapping.items():
        env[key] = pd.to_numeric(df[channel], errors="coerce").to_numpy(dtype=float)
    result = _eval_node(tree, env, df, time_column)
    if np.isscalar(result):
        result = np.full(len(df), float(result), dtype=float)
    result = np.asarray(result, dtype=float)
    if result.shape != (len(df),):
        raise ValueError("Math expression did not produce one value per telemetry sample.")
    return result


def add_math_channel(
    run: TelemetryRun,
    name: str,
    expression: str,
    unit: str = "",
    *,
    persist: bool = True,
    replace: bool = False,
) -> TelemetryRun:
    cname = str(name or "").strip()
    if not cname:
        raise ValueError("Calculated channel name is required.")
    if cname in run.data.columns and not replace:
        raise ValueError(f"A channel named {cname!r} already exists.")
    unit_key = normalize_unit(unit)
    if unit and unit_key not in UNITS:
        raise ValueError(f"Unknown engineering unit: {unit!r}")
    if unit_key:
        validate_expression_unit(run, expression, unit_key)
    values = evaluate_run_expression(run, expression)
    run.data[cname] = values
    run.units[cname] = unit_key
    run.metadata.setdefault("unit_provenance", {})[cname] = (
        f"calculated channel: {expression}" + (f" [{unit_key}]" if unit_key else " [unit unassigned]")
    )
    if persist:
        defs = [d for d in run.metadata.get("math_channels", []) if str(d.get("name", "")) != cname]
        defs.append(MathChannelDefinition(cname, str(expression), unit_key).to_dict())
        run.metadata["math_channels"] = defs
    return run


def _math_definition_order(definitions) -> list[dict]:
    """Return calculated-channel definitions in dependency-safe order.

    Run-local math channels may reference other calculated channels by their
    backtick name.  Recalculation after remapping must therefore never depend
    on whatever stale calculated columns happened to be left in the dataframe.
    """
    records: dict[str, dict] = {}
    insertion: list[str] = []
    for rec in definitions or []:
        if not isinstance(rec, dict):
            continue
        name = str(rec.get("name", "")).strip()
        expression = str(rec.get("expression", "")).strip()
        if not name or not expression:
            continue
        if name not in records:
            insertion.append(name)
        records[name] = dict(rec)
    names = set(records)
    deps: dict[str, set[str]] = {}
    for name, rec in records.items():
        refs = set(_BACKTICK.findall(str(rec.get("expression", ""))))
        deps[name] = {ref for ref in refs if ref in names and ref != name}
        if name in refs:
            raise ValueError(f"Calculated channel dependency cycle: {name} -> {name}")
    out: list[str] = []
    pending = set(names)
    while pending:
        ready = [name for name in insertion if name in pending and deps[name].issubset(set(out))]
        if not ready:
            cycle = " -> ".join(sorted(pending))
            raise ValueError(f"Calculated channel dependency cycle: {cycle}")
        for name in ready:
            out.append(name)
            pending.remove(name)
    return [records[name] for name in out]


def reapply_math_channels(run: TelemetryRun, definitions) -> TelemetryRun:
    ordered = _math_definition_order(definitions)
    math_names = {str(rec.get("name", "")).strip() for rec in ordered}
    # Remove the previous calculated results first.  This guarantees that a
    # missing or out-of-order dependency cannot be accidentally satisfied by a
    # stale result from the previous mapping/evaluation.
    for name in math_names:
        if name in run.data.columns:
            run.data.drop(columns=[name], inplace=True, errors="ignore")
        run.units.pop(name, None)
        run.metadata.get("unit_provenance", {}).pop(name, None)
    for rec in ordered:
        add_math_channel(
            run,
            str(rec.get("name", "")),
            str(rec.get("expression", "")),
            str(rec.get("unit", "")),
            persist=False,
            replace=True,
        )
    run.metadata["math_channels"] = [
        MathChannelDefinition(
            str(rec.get("name", "")).strip(),
            str(rec.get("expression", "")).strip(),
            normalize_unit(str(rec.get("unit", ""))),
        ).to_dict()
        for rec in ordered
    ]
    return run

# ---- Conservative unit/dimension inference ---------------------------------

def infer_expression_dimension(run: TelemetryRun, expression: str) -> str:
    """Infer the output engineering dimension when it is unambiguous.

    This is intentionally conservative. Unknown/compound dimensions remain
    ``unknown`` rather than being guessed. It is primarily a safety guard that
    prevents assigning e.g. psi to an expression that is clearly still RPM.
    """
    from .units import dimension
    resolved=resolve_expression_references(run,expression)
    prepared,mapping=_prepare(resolved,run.data.columns)
    try: tree=ast.parse(prepared,mode='eval')
    except SyntaxError as exc: raise ValueError(f'Invalid math expression: {exc.msg}') from exc
    dims={key:dimension(run.units.get(channel,'')) for key,channel in mapping.items()}

    def walk(node):
        if isinstance(node,ast.Expression):return walk(node.body)
        if isinstance(node,ast.Constant):return 'ratio'
        if isinstance(node,ast.Name):return dims.get(node.id,'unknown')
        if isinstance(node,ast.UnaryOp):return walk(node.operand)
        if isinstance(node,ast.BinOp):
            a,b=walk(node.left),walk(node.right)
            if isinstance(node.op,(ast.Add,ast.Sub)):
                if a=='unknown' or b=='unknown':return 'unknown'
                if a==b:return a
                raise ValueError(f'Cannot add/subtract incompatible dimensions: {a} and {b}.')
            if isinstance(node.op,ast.Div):
                if a==b and a!='unknown':return 'ratio'
                if b=='ratio':return a
                return 'unknown'
            if isinstance(node.op,ast.Mult):
                if a=='ratio':return b
                if b=='ratio':return a
                return 'unknown'
            if isinstance(node.op,(ast.Pow,ast.Mod)):return 'unknown'
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name):
            fname=node.func.id.lower(); args=[walk(x) for x in node.args]
            if fname in {'abs','clip','smooth','lowpass','highpass','bandpass','rollingmean','rollingrms','rollingmin','rollingmax','rollingstd'}:
                return args[0] if args else 'unknown'
            if fname=='sqrt':return 'unknown'
            if fname in {'derivative','integral'}:return 'unknown'
        return 'unknown'
    return walk(tree)


def validate_expression_unit(run: TelemetryRun, expression: str, unit: str) -> str:
    from .units import dimension
    inferred=infer_expression_dimension(run,expression)
    out_dim=dimension(unit)
    if inferred!='unknown' and out_dim!='unknown' and inferred!=out_dim:
        raise ValueError(f'Calculated-channel unit is dimensionally incompatible: expression is {inferred}, selected unit is {out_dim}.')
    return inferred
