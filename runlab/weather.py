from __future__ import annotations

from dataclasses import dataclass
from .models import Environment


@dataclass
class WeatherResult:
    density_lbm_ft3: float
    horsepower_correction: float
    dry_air_pressure_psi: float
    water_air_ratio: float


def quarterpro_weather(env: Environment) -> WeatherResult:
    """Port of Quarter Pro's Weather() routine.

    `horsepower_correction` is the divisor applied to the sea-level/raw dyno
    curve in the legacy Quarter Pro solver. Fuel-system codes follow the original program:
      1 gas carb, 2 gas injector, 3 methanol carb, 4 methanol injector,
      5 nitro injector, 6 supercharged gas, 7 supercharged methanol,
      8 supercharged nitro, 9 flat-rate/uncorrected power.
    """
    tstd = 519.67
    pstd = 14.696
    bstd = 29.92
    wtair = 28.9669
    wth2o = 18.016
    rstd = 1545.32

    cps = [
        0.0205558,
        0.00118163,
        0.0000154988,
        0.00000040245,
        0.000000000434856,
        0.00000000002096,
    ]
    t = float(env.temperature_f)
    psdry = sum(c * (t ** i) for i, c in enumerate(cps))
    pwv = (float(env.humidity_pct) / 100.0) * psdry
    pamb = (pstd * float(env.barometer_inhg) / bstd) * (
        (tstd - 0.00356616 * float(env.elevation_ft)) / tstd
    ) ** 5.25588
    pair = max(1e-9, pamb - pwv)
    delta = pair / pstd
    war = (pwv * wth2o) / (pair * wtair)

    theta = (t + 459.67) / tstd
    rgas = rstd * ((1.0 / wtair) + (war / wth2o)) / (1.0 + war)
    rgrs = rgas / (rstd / wtair)
    rho = 144.0 * pamb / (rgas * (t + 459.67))

    fs = int(env.fuel_system)
    if fs == 1:
        ifuel, icarb = 1, 1
    elif fs == 2:
        ifuel, icarb = 1, 2
    elif fs == 3:
        ifuel, icarb = 2, 1
    elif fs == 4:
        ifuel, icarb = 2, 2
    elif fs == 5:
        ifuel, icarb = 3, 2
    elif fs == 6:
        ifuel, icarb = 1, 3
    elif fs in (7, 9):
        ifuel, icarb = 2, 3
    elif fs == 8:
        ifuel, icarb = 3, 3
    else:
        ifuel, icarb = 1, 2

    kwar = 1.0 + 2.48 * max(0.0, war) ** 1.5
    if ifuel == 1:
        px, tx, mech = 1.0, 0.6, 0.15
    elif ifuel == 2:
        px, tx, mech = 1.0, 0.3, 0.13
    else:
        px, tx, mech = 0.85, 0.5, 0.055

    if icarb == 2:
        mech -= 0.005
    if icarb == 3:
        px = 0.95
        dtx = ((1.35 - 1.0) / 1.35) / 0.85
        px = px - dtx * tx
        tx = tx + dtx
        mech = 0.6 * mech

    hpc = (delta ** px) / ((rgrs ** 0.5) * (theta ** tx))
    hpc = (1.0 + mech) * kwar / max(hpc, 1e-9) - mech
    if fs == 9:
        hpc = 1.0

    return WeatherResult(
        density_lbm_ft3=float(rho),
        horsepower_correction=float(hpc),
        dry_air_pressure_psi=float(pair),
        water_air_ratio=float(war),
    )
