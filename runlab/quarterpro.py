from __future__ import annotations

import shlex
from pathlib import Path
from typing import Dict, Any, List, Tuple
import numpy as np

from .models import VehicleConfig, Environment, DynoCurve


def _tokens(line: str) -> List[str]:
    lexer = shlex.shlex(line, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _floats(line: str) -> List[float]:
    vals = []
    for token in _tokens(line):
        try:
            vals.append(float(token))
        except ValueError:
            pass
    return vals


def _flag(line: str, default: bool = False) -> bool:
    toks = _tokens(line)
    for tok in toks[::-1]:
        s = str(tok).strip().upper()
        if s in {"Y", "YES", "TRUE"}:
            return True
        if s in {"N", "NO", "FALSE"}:
            return False
    return default


def parse_quarter_pro_dat(path: str | Path) -> Tuple[VehicleConfig, Environment, Dict[str, Any]]:
    """Parse the classic QUARTER Pro 3.21 .DAT layout found in the legacy Quarter Pro source.

    The legacy files do not explicitly store every modern internal field.  We
    preserve the known values and make conservative defaults for body style,
    transmission type, and CG.  The returned metadata records those assumptions.
    """
    path = Path(path)
    lines = [ln.rstrip("\r\n") for ln in path.read_text(errors="replace").splitlines() if ln.strip()]
    if len(lines) < 18:
        raise ValueError(f"{path.name}: expected at least 18 nonblank lines for a Quarter Pro DAT file")

    version = " ".join(_tokens(lines[0])).strip()
    note = " ".join(_tokens(lines[1])).strip()

    weather_row = _floats(lines[2])
    aero_row = _floats(lines[3])
    rpm_row = _floats(lines[4])
    hp_row = _floats(lines[5])
    hptq_fuel = _floats(lines[6])
    gear_ratios = _floats(lines[7])
    gear_eff = _floats(lines[8])
    shift_rpm = _floats(lines[9])
    launch_row = _floats(lines[10])
    lockup = _flag(lines[10], False)
    final_row = _floats(lines[11])
    pmi_row = _floats(lines[12])
    wind_row = _floats(lines[13])
    ref_area_ws = _floats(lines[14])
    motorcycle_ws = _floats(lines[15])
    tire_width_ws = _floats(lines[16])
    engine_pmi_ws = _floats(lines[17])
    trans_pmi_ws = _floats(lines[18]) if len(lines) > 18 else []
    tire_pmi_ws = _floats(lines[19]) if len(lines) > 19 else []

    if len(weather_row) < 8 or len(aero_row) < 4:
        raise ValueError(f"{path.name}: malformed environment/vehicle rows")

    # Original row: elevation, temperature, barometer, humidity, track temp,
    # weight, wheelbase, rollout.
    env = Environment(
        elevation_ft=weather_row[0],
        temperature_f=weather_row[1],
        barometer_inhg=weather_row[2],
        humidity_pct=weather_row[3],
        track_temperature_f=weather_row[4],
        wind_mph=wind_row[0] if wind_row else 0.0,
        wind_angle_deg=wind_row[1] if len(wind_row) > 1 else 0.0,
        fuel_system=int(hptq_fuel[1]) if len(hptq_fuel) > 1 else 9,
    )

    rollout_in = weather_row[7]
    final_ratio, final_eff, tire_value, tire_width, traction = final_row[:5]
    # In the files shipped with QPro, values around 100 are circumference/rollout.
    tire_dia = tire_value / np.pi if tire_value > 60 else tire_value

    ratios = [x for x in gear_ratios[:6] if x > 0]
    n = len(ratios)
    effs = [x for x in gear_eff[:n]]
    shifts = [x for x in shift_rpm[:n]]

    # Quarter Pro does not persist BodyStyle in the v3.21 DAT.  The source
    # reconstructs it deterministically on load: vehicles over 800 lb are
    # treated as the car family (BodyStyle=1); 800 lb and below are motorcycles
    # (BodyStyle=8).  Keep that exact rule here rather than inferring from the
    # worksheet fields.
    motorcycle_like = weather_row[5] <= 800
    body_style = 8 if motorcycle_like else 1

    # The first item on line 10 is launch RPM, second is explicit stall/slip RPM
    # (or legacy index when <=220), then torque multiplication and slippage.
    launch_rpm = launch_row[0] if launch_row else rpm_row[0]
    stall_rpm = launch_row[1] if len(launch_row) > 1 else launch_rpm
    torque_mult = launch_row[2] if len(launch_row) > 2 else 1.0
    slippage = launch_row[3] if len(launch_row) > 3 else 1.005

    # QPro reconstructs transmission type directly from the persisted torque
    # multiplication value: exactly 1.0 means clutch; anything else means
    # converter.  (MDI.FRM: gc_TransType.Value = IIf(tmult = 1, False, True)).
    transmission_type = "clutch" if abs(torque_mult - 1.0) < 1e-12 else "converter"

    v = VehicleConfig(
        name=path.stem,
        weight_lb=weather_row[5],
        wheelbase_in=weather_row[6],
        rollout_in=rollout_in,
        front_overhang_in=aero_row[0],
        frontal_area_ft2=aero_row[1],
        drag_coefficient=aero_row[2],
        lift_coefficient=aero_row[3],
        body_style=body_style,
        traction_index=traction,
        transmission_type=transmission_type,
        launch_rpm=launch_rpm,
        stall_rpm=stall_rpm,
        slippage=slippage,
        torque_multiplication=torque_mult,
        lockup_after_first=lockup,
        final_drive_ratio=final_ratio,
        final_drive_efficiency=final_eff,
        tire_diameter_in=tire_dia,
        tire_width_in=tire_width,
        gear_ratios=ratios,
        gear_efficiencies=effs,
        shift_rpms=shifts,
        hp_multiplier=hptq_fuel[0] if hptq_fuel else 1.0,
        engine_pmi=pmi_row[0] if pmi_row else 0.0,
        transmission_pmi=pmi_row[1] if len(pmi_row) > 1 else 0.0,
        tires_pmi=pmi_row[2] if len(pmi_row) > 2 else 0.0,
        dyno=DynoCurve(rpm=rpm_row[:len(hp_row)], hp=hp_row[:len(rpm_row)]),
    ).normalized()

    meta: Dict[str, Any] = {
        "version": version,
        "note": note,
        "source_format": "Quarter Pro DAT",
        "assumptions": {
            "body_style": "Quarter Pro source rule: <=800 lb motorcycle (8), >800 lb car family (1)",
            "transmission_type": f"Quarter Pro source rule from torque multiplication: {transmission_type}",
            "tire_value_interpretation": "rollout/circumference" if tire_value > 60 else "diameter",
        },
        "worksheets": {
            "reference_area": ref_area_ws,
            "motorcycle_final_drive": motorcycle_ws,
            "tire_width": tire_width_ws,
            "engine_pmi": engine_pmi_ws,
            "transmission_pmi": trans_pmi_ws,
            "tire_pmi": tire_pmi_ws,
        },
    }
    return v, env, meta
