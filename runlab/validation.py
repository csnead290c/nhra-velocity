from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

from .physics import SolverOptions, simulate
from .legacy_reference import simulate_legacy_reference
from .quarterpro import parse_quarter_pro_dat


def qpro_convergence_report(paths: Iterable[Path | str], dts: Sequence[float] = (0.010, 0.005, 0.0025)) -> pd.DataFrame:
    rows = []
    dts = tuple(float(x) for x in dts)
    if len(dts) < 2:
        raise ValueError("Use at least two time steps for a convergence check.")
    for raw in paths:
        path = Path(raw)
        vehicle, env, _ = parse_quarter_pro_dat(path)
        results = []
        for dt in dts:
            sim = simulate(vehicle, env, options=SolverOptions(dt_s=dt))
            results.append(sim)
            rows.append({
                "vehicle": path.stem,
                "dt_s": dt,
                "60ft_s": sim.timing.sixty_ft_s,
                "660ft_s": sim.timing.eighth_mile_s,
                "660ft_mph": sim.timing.eighth_mile_mph,
                "1320ft_s": sim.timing.quarter_mile_s,
                "1320ft_mph": sim.timing.quarter_mile_mph,
                "delta_ET_vs_finest_s": None,
                "delta_MPH_vs_finest": None,
                "stability": "",
            })
        fine = results[-1].timing
        for row in rows[-len(dts):]:
            row["delta_ET_vs_finest_s"] = None if fine.quarter_mile_s is None or row["1320ft_s"] is None else row["1320ft_s"] - fine.quarter_mile_s
            row["delta_MPH_vs_finest"] = None if fine.quarter_mile_mph is None or row["1320ft_mph"] is None else row["1320ft_mph"] - fine.quarter_mile_mph
        mid = results[-2].timing
        et_delta = abs((mid.quarter_mile_s or 0.0) - (fine.quarter_mile_s or 0.0))
        mph_delta = abs((mid.quarter_mile_mph or 0.0) - (fine.quarter_mile_mph or 0.0))
        if et_delta <= 0.005 and mph_delta <= 0.20:
            rating = "Strong"
        elif et_delta <= 0.020 and mph_delta <= 0.75:
            rating = "Usable / refine"
        else:
            rating = "Needs solver attention"
        for row in rows[-len(dts):]:
            row["stability"] = rating
    return pd.DataFrame(rows)


def qpro_validation_summary(report: pd.DataFrame) -> pd.DataFrame:
    if report.empty:
        return report
    finest = report.groupby("vehicle", as_index=False).tail(1).copy()
    grouped = []
    for vehicle, frame in report.groupby("vehicle", sort=True):
        f = frame.iloc[-1]
        m = frame.iloc[-2]
        grouped.append({
            "vehicle": vehicle,
            "finest_dt_s": float(f["dt_s"]),
            "1320ft_s": f["1320ft_s"],
            "1320ft_mph": f["1320ft_mph"],
            "ET_change_last_refinement_s": abs(float(m["1320ft_s"]) - float(f["1320ft_s"])) if pd.notna(f["1320ft_s"]) and pd.notna(m["1320ft_s"]) else None,
            "MPH_change_last_refinement": abs(float(m["1320ft_mph"]) - float(f["1320ft_mph"])) if pd.notna(f["1320ft_mph"]) and pd.notna(m["1320ft_mph"]) else None,
            "stability": f["stability"],
        })
    return pd.DataFrame(grouped)


def qpro_parity_report(paths: Iterable[Path | str], modern_dt_s: float = 0.0025) -> pd.DataFrame:
    """Compare the smooth optimization engine to the source-faithful reference.

    This is intentionally separate from the convergence report. A numerically
    converged modern answer can still be wrong relative to Quarter Pro.
    """
    rows = []
    for raw in paths:
        path = Path(raw)
        vehicle, env, _ = parse_quarter_pro_dat(path)
        modern = simulate(vehicle, env, options=SolverOptions(dt_s=float(modern_dt_s)))
        legacy = simulate_legacy_reference(vehicle, env)
        mt, lt = modern.timing, legacy.timing
        pairs = {
            "60ft_s": (mt.sixty_ft_s, lt.sixty_ft_s),
            "330ft_s": (mt.three_thirty_ft_s, lt.three_thirty_ft_s),
            "660ft_s": (mt.eighth_mile_s, lt.eighth_mile_s),
            "660ft_mph": (mt.eighth_mile_mph, lt.eighth_mile_mph),
            "1000ft_s": (mt.thousand_ft_s, lt.thousand_ft_s),
            "1320ft_s": (mt.quarter_mile_s, lt.quarter_mile_s),
            "1320ft_mph": (mt.quarter_mile_mph, lt.quarter_mile_mph),
        }
        row = {
            "vehicle": path.stem,
            "modern_dt_s": float(modern_dt_s),
            "modern_1320ft_s": mt.quarter_mile_s,
            "legacy_1320ft_s": lt.quarter_mile_s,
            "modern_1320ft_mph": mt.quarter_mile_mph,
            "legacy_1320ft_mph": lt.quarter_mile_mph,
        }
        for key, (m, l) in pairs.items():
            row[f"delta_{key}"] = None if m is None or l is None else float(m) - float(l)
        et = abs(row["delta_1320ft_s"]) if row["delta_1320ft_s"] is not None else 999
        mph = abs(row["delta_1320ft_mph"]) if row["delta_1320ft_mph"] is not None else 999
        if et <= 0.010 and mph <= 0.50:
            rating = "Parity target"
        elif et <= 0.050 and mph <= 1.50:
            rating = "Close / refine"
        elif et <= 0.150 and mph <= 3.00:
            rating = "Material gap"
        else:
            rating = "Priority physics gap"
        row["parity_status"] = rating
        rows.append(row)
    return pd.DataFrame(rows)


def qpro_parity_summary(report: pd.DataFrame) -> pd.DataFrame:
    if report.empty:
        return report
    cols = [
        "vehicle", "modern_1320ft_s", "legacy_1320ft_s", "delta_1320ft_s",
        "modern_1320ft_mph", "legacy_1320ft_mph", "delta_1320ft_mph", "parity_status"
    ]
    return report[cols].copy()
