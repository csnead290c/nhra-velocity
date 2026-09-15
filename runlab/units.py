from __future__ import annotations

"""Engineering-unit handling for telemetry channels.

The telemetry layer intentionally keeps raw source channels untouched.  Canonical
channels are derived into explicit internal units and carry provenance so the UI
can show the user where a unit came from (native file, header, inferred name,
manual override, or derived math).

This is deliberately small and deterministic rather than depending on a general
unit package inside the physics core.  It covers the quantities used by the
current drag-racing workflow and can be extended without changing file parsers.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple
import math
import re


@dataclass(frozen=True)
class UnitSpec:
    key: str
    dimension: str
    label: str
    # linear conversion to a dimension base: base = value * scale + offset
    scale: float = 1.0
    offset: float = 0.0


# Base units are s, mph, g, rpm, psi, hp, lb-ft, lb, in, degF where practical.
UNITS: Dict[str, UnitSpec] = {
    "": UnitSpec("", "unknown", ""),
    "ratio": UnitSpec("ratio", "ratio", ""),
    "fraction": UnitSpec("fraction", "ratio", "", 1.0),
    "pct": UnitSpec("pct", "ratio", "%", 0.01),

    "s": UnitSpec("s", "time", "s", 1.0),
    "ms": UnitSpec("ms", "time", "ms", 0.001),
    "us": UnitSpec("us", "time", "µs", 1e-6),
    "min": UnitSpec("min", "time", "min", 60.0),

    "mph": UnitSpec("mph", "speed", "mph", 1.0),
    "kmh": UnitSpec("kmh", "speed", "km/h", 0.621371192237334),
    "mps": UnitSpec("mps", "speed", "m/s", 2.2369362920544),
    "fps": UnitSpec("fps", "speed", "ft/s", 3600.0 / 5280.0),

    "g": UnitSpec("g", "acceleration", "g", 1.0),
    "mps2": UnitSpec("mps2", "acceleration", "m/s²", 1.0 / 9.80665),
    "fps2": UnitSpec("fps2", "acceleration", "ft/s²", 1.0 / 32.17404856),

    "rpm": UnitSpec("rpm", "angular_speed", "rpm", 1.0),
    "rps": UnitSpec("rps", "angular_speed", "rev/s", 60.0),
    "radps": UnitSpec("radps", "angular_speed", "rad/s", 60.0 / (2.0 * math.pi)),

    "psi": UnitSpec("psi", "pressure", "psi", 1.0),
    "kpa": UnitSpec("kpa", "pressure", "kPa", 0.14503773773020923),
    "bar": UnitSpec("bar", "pressure", "bar", 14.503773773),
    "pa": UnitSpec("pa", "pressure", "Pa", 0.00014503773773020923),

    "hp": UnitSpec("hp", "power", "hp", 1.0),
    "kw": UnitSpec("kw", "power", "kW", 1.341022089595),
    "w": UnitSpec("w", "power", "W", 0.001341022089595),
    "ps": UnitSpec("ps", "power", "PS", 0.9863200706),

    "lbft": UnitSpec("lbft", "torque", "lb-ft", 1.0),
    "lbin": UnitSpec("lbin", "torque", "lb-in", 1.0 / 12.0),
    "nm": UnitSpec("nm", "torque", "N·m", 0.737562149277),

    "lb": UnitSpec("lb", "mass_or_weight", "lb", 1.0),
    "kg": UnitSpec("kg", "mass_or_weight", "kg", 2.20462262185),

    "in": UnitSpec("in", "length", "in", 1.0),
    "ft": UnitSpec("ft", "length", "ft", 12.0),
    "mm": UnitSpec("mm", "length", "mm", 1.0 / 25.4),
    "cm": UnitSpec("cm", "length", "cm", 10.0 / 25.4),
    "m": UnitSpec("m", "length", "m", 39.3700787402),

    "f": UnitSpec("f", "temperature", "°F", 1.0, 0.0),
    # temperature conversions are special-cased below because affine units
    "c": UnitSpec("c", "temperature", "°C", 1.0, 0.0),

    "v": UnitSpec("v", "voltage", "V", 1.0),
    "a": UnitSpec("a", "current", "A", 1.0),
    "deg": UnitSpec("deg", "angle", "deg", 1.0),
    "degps": UnitSpec("degps", "angular_rate", "deg/s", 1.0),
}


ALIASES = {
    # time
    "sec": "s", "secs": "s", "second": "s", "seconds": "s",
    "msec": "ms", "millisecond": "ms", "milliseconds": "ms",
    "usec": "us", "microsecond": "us", "microseconds": "us", "µs": "us", "μs": "us",
    "minute": "min", "minutes": "min",
    # speed
    "km/h": "kmh", "kph": "kmh", "kmph": "kmh", "km/hr": "kmh",
    "mi/h": "mph", "mi/hr": "mph",
    "m/s": "mps", "m/sec": "mps",
    "ft/s": "fps", "ft/sec": "fps",
    # acceleration
    "g's": "g", "gs": "g", "g-force": "g", "g force": "g",
    "m/s2": "mps2", "m/s^2": "mps2", "m/s²": "mps2",
    "ft/s2": "fps2", "ft/s^2": "fps2", "ft/s²": "fps2",
    # angular
    "rev/min": "rpm", "r/min": "rpm", "1/min": "rpm",
    "rev/s": "rps", "rad/s": "radps",
    # pressure
    "kilopascal": "kpa", "kilopascals": "kpa", "psig": "psi", "psia": "psi",
    # power
    "horsepower": "hp", "bhp": "hp", "whp": "hp",
    "kilowatt": "kw", "kilowatts": "kw", "watt": "w", "watts": "w",
    # torque
    "lb-ft": "lbft", "lb ft": "lbft", "lbf-ft": "lbft", "ft-lb": "lbft", "ft lb": "lbft",
    "lb-in": "lbin", "lb in": "lbin", "lbf-in": "lbin",
    "n-m": "nm", "n m": "nm", "n·m": "nm", "nm": "nm",
    # misc
    "percent": "pct", "%": "pct",
    "volts": "v", "volt": "v", "amps": "a", "amp": "a",
    "°f": "f", "degf": "f", "fahrenheit": "f",
    "°c": "c", "degc": "c", "celsius": "c",
    "degrees": "deg", "degree": "deg", "°": "deg",
    "deg/s": "degps", "degree/s": "degps", "degrees/s": "degps", "°/s": "degps",
    "lbs": "lb", "pound": "lb", "pounds": "lb",
    "inches": "in", "inch": "in", '"': "in",
    "feet": "ft", "foot": "ft",
}


CANONICAL_TARGET_UNITS: Dict[str, str] = {
    "time_s": "s",
    "engine_rpm": "rpm",
    "driveshaft_rpm": "rpm",
    "clutch_rpm": "rpm",
    "speed_mph": "mph",
    "wheel_speed_mph": "mph",
    "longitudinal_g": "g",
    "lateral_g": "g",
    "vertical_g": "g",
    "gps_latitude_deg": "deg",
    "gps_longitude_deg": "deg",
    "heading_deg": "deg",
    "altitude_ft": "ft",
    "yaw_rate_degps": "degps",
    "battery_voltage": "v",
    "brake_pressure_psi": "psi",
    "steering_angle_deg": "deg",
    "throttle_pct": "pct",
    "boost_psi": "psi",
    "power_hp": "hp",
    "torque_lbft": "lbft",
    "ignition_timing_deg": "deg",
    "oil_pressure_psi": "psi",
    "fuel_pressure_psi": "psi",
    "coolant_temp_f": "f",
    "oil_temp_f": "f",
    "intake_air_temp_f": "f",
    "fuel_temp_f": "f",
    "injector_duty_pct": "pct",
}


def normalize_unit(unit: Optional[str]) -> str:
    if unit is None:
        return ""
    s = str(unit).strip().lower()
    if not s:
        return ""
    s = s.replace("−", "-").replace("–", "-")
    s = re.sub(r"\s+", " ", s)
    if s in UNITS:
        return s
    if s in ALIASES:
        return ALIASES[s]
    compact = s.replace(" ", "")
    compact_aliases = {k.replace(" ", ""): v for k, v in ALIASES.items()}
    if compact in compact_aliases:
        return compact_aliases[compact]
    return s


def dimension(unit: Optional[str]) -> str:
    key = normalize_unit(unit)
    return UNITS.get(key, UnitSpec(key, "unknown", str(unit or ""))).dimension


def compatible(unit_a: Optional[str], unit_b: Optional[str]) -> bool:
    da, db = dimension(unit_a), dimension(unit_b)
    return da != "unknown" and da == db


def convert_value(value, from_unit: Optional[str], to_unit: Optional[str]):
    """Convert a scalar/NumPy/Pandas value between supported engineering units."""
    f = normalize_unit(from_unit)
    t = normalize_unit(to_unit)
    if f == t or not f or not t:
        return value
    if f not in UNITS or t not in UNITS:
        raise ValueError(f"Unsupported unit conversion: {from_unit!r} -> {to_unit!r}")
    if UNITS[f].dimension != UNITS[t].dimension:
        raise ValueError(f"Incompatible units: {from_unit!r} ({UNITS[f].dimension}) -> {to_unit!r} ({UNITS[t].dimension})")
    if UNITS[f].dimension == "temperature":
        # convert source to °F, then to target
        if f == "c":
            base = value * 9.0 / 5.0 + 32.0
        else:
            base = value
        if t == "c":
            return (base - 32.0) * 5.0 / 9.0
        return base
    base = value * UNITS[f].scale + UNITS[f].offset
    return (base - UNITS[t].offset) / UNITS[t].scale


def display_label(unit: Optional[str]) -> str:
    key = normalize_unit(unit)
    return UNITS[key].label if key in UNITS else str(unit or "")


def extract_unit_from_label(label: str) -> Optional[str]:
    """Extract a likely engineering unit from a channel label.

    Prefer explicit bracket/parenthesis text and only then use conservative
    token matching.  It intentionally does not infer plain 's' from arbitrary
    labels because that created dangerous false time-unit matches.
    """
    raw = str(label or "")
    candidates = re.findall(r"\[([^\]]+)\]|\(([^)]+)\)", raw)
    for pair in candidates:
        token = next((x for x in pair if x), "")
        key = normalize_unit(token)
        if key in UNITS and key:
            return key
    s = raw.lower()
    patterns = [
        (r"\bkm\s*/\s*h\b|\bkph\b|\bkmh\b", "kmh"),
        (r"\bmph\b|\bmi\s*/\s*h\b", "mph"),
        (r"\bm\s*/\s*s(?:\^?2|²)\b", "mps2"),
        (r"\bft\s*/\s*s(?:\^?2|²)\b", "fps2"),
        (r"\bm\s*/\s*s\b", "mps"),
        (r"\bft\s*/\s*s\b", "fps"),
        (r"\brpm\b", "rpm"),
        (r"\bhorsepower\b|\bbhp\b|\bhp\b", "hp"),
        (r"\bkw\b|\bkilowatts?\b", "kw"),
        (r"\bwatts?\b|(?<!k)\bw\b", "w"),
        (r"\blb\s*[- ]?ft\b|\bft\s*[- ]?lb\b", "lbft"),
        (r"\bn\s*[· -]?m\b", "nm"),
        (r"\bkpa\b", "kpa"),
        (r"\bpsi[ag]?\b", "psi"),
        (r"\bbar\b", "bar"),
        (r"\bmilliseconds?\b|\bmsec\b|\bms\b", "ms"),
        (r"\bmicroseconds?\b|\busec\b|µs|μs", "us"),
        (r"\bseconds?\b|\bsec\b", "s"),
        (r"\bdeg(?:rees?)?\s*/\s*s\b|°/s", "degps"),
        (r"\bpercent\b|%", "pct"),
        (r"\bvolts?\b|\[v\]|\(v\)", "v"),
    ]
    for pattern, key in patterns:
        if re.search(pattern, s):
            return key
    return None


def canonical_target(canonical: str) -> Optional[str]:
    return CANONICAL_TARGET_UNITS.get(canonical)


def convert_canonical(values, canonical: str, source_unit: Optional[str]):
    target = canonical_target(canonical)
    if not target or not source_unit:
        return values, target or normalize_unit(source_unit)
    return convert_value(values, source_unit, target), target


# Broad plausibility bands.  These are guards against catastrophic unit/channel
# mistakes, not racing rules or hard physical limits.
PLAUSIBLE = {
    "time_s": (-1e3, 24 * 3600),
    "engine_rpm": (-100, 30000),
    "driveshaft_rpm": (-100, 25000),
    "clutch_rpm": (-100, 30000),
    "speed_mph": (-50, 500),
    "wheel_speed_mph": (-50, 700),
    "longitudinal_g": (-20, 20),
    "lateral_g": (-20, 20),
    "vertical_g": (-20, 20),
    "gps_latitude_deg": (-90, 90),
    "gps_longitude_deg": (-180, 180),
    "heading_deg": (-720, 720),
    "altitude_ft": (-2000, 100000),
    "yaw_rate_degps": (-5000, 5000),
    "battery_voltage": (-5, 100),
    "brake_pressure_psi": (-100, 5000),
    "steering_angle_deg": (-2000, 2000),
    "throttle_pct": (-20, 120),
    "boost_psi": (-30, 250),
    "power_hp": (-10000, 50000),
    "torque_lbft": (-50000, 100000),
    "ignition_timing_deg": (-180, 180),
    "oil_pressure_psi": (-20, 500),
    "fuel_pressure_psi": (-20, 5000),
    "coolant_temp_f": (-100, 500),
    "oil_temp_f": (-100, 600),
    "intake_air_temp_f": (-150, 500),
    "fuel_temp_f": (-150, 500),
    "injector_duty_pct": (-20, 150),
}


def plausible_range(canonical: str) -> Optional[Tuple[float, float]]:
    return PLAUSIBLE.get(canonical)
