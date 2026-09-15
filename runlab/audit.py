from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Any

import numpy as np
import pandas as pd

from .models import TelemetryRun
from .units import CANONICAL_TARGET_UNITS, display_label, dimension, plausible_range
from .plotability import choose_default_plot_channels
from .display_data import channel_xy, prepare_plot_series


@dataclass
class AuditIssue:
    severity: str  # ERROR | WARNING | INFO | OK
    category: str
    item: str
    message: str


def audit_run(run: TelemetryRun) -> pd.DataFrame:
    issues: List[AuditIssue] = []
    m = run.channel_map
    units = run.units
    prov = run.metadata.get('unit_provenance', {})

    decoder = run.metadata.get('import_decoder')
    probe = run.metadata.get('import_probe_reason')
    if decoder:
        issues.append(AuditIssue('INFO', 'Import', 'decoder', f'{decoder}' + (f' — {probe}' if probe else '')))
    plot = run.metadata.get('plotability', {}) or {}
    if plot:
        sev = 'OK' if plot.get('plotable') else 'ERROR'
        defaults = ', '.join(map(str, plot.get('default_channels') or [])) or 'none'
        issues.append(AuditIssue(sev, 'Viewer', 'plotability', f"X axis: {plot.get('timebase','unknown')}; default traces: {defaults}."))

    for warning in run.metadata.get('data_warnings', []):
        sev = 'ERROR' if str(warning).startswith('Rejected') else 'WARNING'
        issues.append(AuditIssue(sev, 'Import', 'mapping/unit', str(warning)))

    # Exercise the same final X/Y preparation used by the desktop renderer.
    # This distinguishes "decoded" from "drawable" and records repairs such
    # as a duplicate timestamp / clock reset in the Data Integrity panel.
    for source in choose_default_plot_channels(run, limit=5):
        try:
            x,y=channel_xy(run,source,'Time from Launch')
            prepared=prepare_plot_series(x,y,max_points=50000)
            if prepared.output_points < 2:
                issues.append(AuditIssue('ERROR','Renderer',source,prepared.warning or 'Fewer than two drawable X/Y samples.'))
            elif prepared.monotonic_repair:
                issues.append(AuditIssue('WARNING','Renderer',source,f'{prepared.output_points:,} drawable points; {prepared.warning}.'))
            else:
                suffix='; peak-preserving display decimation active' if prepared.decimated else ''
                issues.append(AuditIssue('OK','Renderer',source,f'{prepared.output_points:,} drawable points{suffix}.'))
        except Exception as exc:
            issues.append(AuditIssue('ERROR','Renderer',source,f'Waveform preparation failed: {exc}'))

    # Canonical channel contract.
    for canonical, target in CANONICAL_TARGET_UNITS.items():
        if canonical not in m:
            if canonical in ('time_s',):
                issues.append(AuditIssue('WARNING', 'Canonical', canonical, 'Time is not safely mapped. Viewer can use Sample Index, but time/distance/derivative physics tools are unavailable.'))
            continue
        col = m[canonical]
        unit = units.get(col, '')
        if unit and dimension(unit) != dimension(target):
            issues.append(AuditIssue('ERROR', 'Units', canonical, f'{col} is {unit}; expected {target}.'))
        else:
            p = prov.get(col, 'unit provenance unavailable')
            issues.append(AuditIssue('OK', 'Units', canonical, f'{col} → {display_label(unit)}; {p}'))

    # Timebase integrity.
    if 'time_s' in m:
        t = pd.to_numeric(run.data[m['time_s']], errors='coerce').dropna().to_numpy(float)
        if len(t) < 4:
            issues.append(AuditIssue('ERROR', 'Timebase', 'samples', 'Fewer than four valid time samples.'))
        else:
            dt = np.diff(t)
            positive = dt[np.isfinite(dt) & (dt > 0)]
            if len(positive) < max(2, int(0.8 * len(dt))):
                issues.append(AuditIssue('WARNING', 'Timebase', 'monotonicity', 'Many duplicate/non-increasing timestamps.'))
            if len(positive):
                med = float(np.median(positive))
                hz = 1.0 / med
                sev = 'OK' if 0.1 <= hz <= 100000 else 'ERROR'
                issues.append(AuditIssue(sev, 'Timebase', 'sample rate', f'Median dt {med:.9g} s ({hz:.3f} Hz).'))
                q1, q99 = np.quantile(positive, [0.01, 0.99])
                if q1 > 0 and q99 / q1 > 50:
                    issues.append(AuditIssue('WARNING', 'Timebase', 'jitter/gaps', f'dt 1–99% span is {q1:.6g}..{q99:.6g} s.'))

    # Central-range plausibility. Importer already removes bad mappings; repeat
    # here so the UI has an explicit audit trail.
    for canonical, col in m.items():
        band = plausible_range(canonical)
        if not band or col not in run.data.columns:
            continue
        vals = pd.to_numeric(run.data[col], errors='coerce')
        vals = vals[np.isfinite(vals)]
        if len(vals) < 3:
            continue
        q01, q99 = float(vals.quantile(.01)), float(vals.quantile(.99))
        ok = q01 >= band[0] and q99 <= band[1]
        sev = 'OK' if ok else 'ERROR'
        issues.append(AuditIssue(sev, 'Range', canonical, f'1–99%: {q01:.5g}..{q99:.5g}; guard band {band[0]:g}..{band[1]:g}.'))

    # Derivative safety checks used by reconstruction.
    if 'time_s' in m and 'speed_mph' in m:
        t = pd.to_numeric(run.data[m['time_s']], errors='coerce').to_numpy(float)
        v = pd.to_numeric(run.data[m['speed_mph']], errors='coerce').to_numpy(float)
        good = np.isfinite(t) & np.isfinite(v)
        if good.sum() >= 5:
            tt, vv = t[good], v[good]
            order = np.argsort(tt)
            tt, vv = tt[order], vv[order]
            uniq = np.r_[True, np.diff(tt) > 1e-9]
            tt, vv = tt[uniq], vv[uniq]
            if len(tt) >= 5:
                accel_g = np.gradient(vv * 1.4666666666667, tt) / 32.17404856
                central = np.abs(accel_g[np.isfinite(accel_g)])
                if len(central):
                    q99 = float(np.quantile(central, .99))
                    sev = 'OK' if q99 <= 10 else ('WARNING' if q99 <= 25 else 'ERROR')
                    issues.append(AuditIssue(sev, 'Derivative', 'speed acceleration', f'99th percentile |a| = {q99:.3g} g.'))

    if not issues:
        issues.append(AuditIssue('INFO', 'Audit', 'run', 'No audit checks were applicable.'))
    order = {'ERROR': 0, 'WARNING': 1, 'INFO': 2, 'OK': 3}
    rows = [i.__dict__ for i in issues]
    return pd.DataFrame(rows).sort_values('severity', key=lambda s: s.map(order)).reset_index(drop=True)


def reconstruction_blockers(run: TelemetryRun) -> List[str]:
    table = audit_run(run)
    blockers = []
    for _, row in table.iterrows():
        if row['severity'] != 'ERROR':
            continue
        # Missing canonical power is irrelevant; derivative/time/speed errors are not.
        if row['category'] in ('Timebase', 'Derivative') or row['item'] in ('time_s', 'speed_mph', 'engine_rpm'):
            blockers.append(f"{row['category']} / {row['item']}: {row['message']}")
    for needed in ('time_s', 'speed_mph', 'engine_rpm'):
        if needed not in run.channel_map:
            blockers.append(f'Required canonical channel {needed} is not safely mapped.')
    return list(dict.fromkeys(blockers))
