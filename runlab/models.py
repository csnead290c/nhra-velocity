from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
import copy
import numpy as np


@dataclass
class Environment:
    elevation_ft: float = 0.0
    temperature_f: float = 75.0
    barometer_inhg: float = 29.92
    humidity_pct: float = 50.0
    wind_mph: float = 0.0
    wind_angle_deg: float = 0.0
    track_temperature_f: float = 100.0
    fuel_system: int = 9

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Environment":
        aliases = {
            "temp_f": "temperature_f",
            "temperature": "temperature_f",
            "baro": "barometer_inhg",
            "barometer": "barometer_inhg",
            "humidity": "humidity_pct",
            "elevation": "elevation_ft",
            "track_temp_f": "track_temperature_f",
            "track_temp": "track_temperature_f",
            "wind_speed_mph": "wind_mph",
            "wind_angle": "wind_angle_deg",
        }
        normalized = dict(data or {})
        for old, new in aliases.items():
            if old in normalized and new not in normalized:
                normalized[new] = normalized.pop(old)
        fields = cls.__dataclass_fields__
        return cls(**{k: v for k, v in normalized.items() if k in fields})

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DynoCurve:
    rpm: List[float] = field(default_factory=lambda: [5000, 6000, 7000, 8000, 9000])
    hp: List[float] = field(default_factory=lambda: [500, 700, 900, 1000, 950])

    def __post_init__(self) -> None:
        pairs = sorted((float(r), float(h)) for r, h in zip(self.rpm, self.hp) if float(r) > 0)
        if len(pairs) < 2:
            raise ValueError("Dyno curve needs at least two RPM/HP points.")
        self.rpm = [p[0] for p in pairs]
        self.hp = [p[1] for p in pairs]

    @property
    def torque_lbft(self) -> List[float]:
        return [5252.113 * h / r for r, h in zip(self.rpm, self.hp)]

    def hp_at(self, rpm: float, multipliers: Optional[List[float]] = None) -> float:
        x = np.asarray(self.rpm, dtype=float)
        y = np.asarray(self.hp, dtype=float)
        if multipliers is not None and len(multipliers):
            m = np.asarray(multipliers, dtype=float)
            if len(m) != len(x):
                node_x = np.linspace(x[0], x[-1], len(m))
                m = np.interp(x, node_x, m)
            y = y * m
        # Quarter Pro extrapolates/interpolates through the supplied curve.  We
        # clamp here because uncontrolled extrapolation is dangerous during fitting.
        return float(np.interp(float(rpm), x, y, left=y[0], right=y[-1]))

    def to_dict(self) -> Dict[str, Any]:
        return {"rpm": list(self.rpm), "hp": list(self.hp)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DynoCurve":
        return cls(rpm=list(data.get("rpm", [])), hp=list(data.get("hp", [])))


@dataclass
class VehicleConfig:
    name: str = "Vehicle"
    weight_lb: float = 2355.0
    wheelbase_in: float = 107.0
    rollout_in: float = 9.0
    front_overhang_in: float = 40.0

    frontal_area_ft2: float = 18.2
    drag_coefficient: float = 0.24
    lift_coefficient: float = 0.10

    body_style: int = 5  # legacy Quarter Pro convention: 8 = motorcycle
    traction_index: float = 3.0

    transmission_type: str = "clutch"  # clutch | converter
    launch_rpm: float = 7200.0
    stall_rpm: float = 7600.0
    slippage: float = 1.004
    torque_multiplication: float = 1.0
    lockup_after_first: bool = False
    shift_duration_s: float = 0.20

    final_drive_ratio: float = 4.86
    final_drive_efficiency: float = 0.975
    tire_diameter_in: float = 102.5 / np.pi
    tire_width_in: float = 17.0
    tire_growth_scale: float = 1.0

    gear_ratios: List[float] = field(default_factory=lambda: [2.6, 1.9, 1.5, 1.2, 1.0])
    gear_efficiencies: List[float] = field(default_factory=lambda: [0.99, 0.991, 0.992, 0.993, 0.994])
    shift_rpms: List[float] = field(default_factory=lambda: [9400, 9400, 9400, 9400, 0])

    hp_multiplier: float = 1.0
    engine_pmi: float = 3.42
    transmission_pmi: float = 0.247
    tires_pmi: float = 50.8

    # Quarter Pro internally estimated these. Exposing them is useful for inverse work.
    cg_height_in: Optional[float] = None
    static_front_weight_lb: Optional[float] = None

    dyno: DynoCurve = field(default_factory=DynoCurve)

    @property
    def cda_ft2(self) -> float:
        return self.drag_coefficient * self.frontal_area_ft2

    @property
    def n_gears(self) -> int:
        return min(len([x for x in self.gear_ratios if x > 0]), 6)

    def normalized(self) -> "VehicleConfig":
        v = copy.deepcopy(self)
        n = v.n_gears
        if n < 1:
            raise ValueError("At least one transmission gear is required.")
        v.gear_ratios = [float(x) for x in v.gear_ratios[:n]]
        eff = list(v.gear_efficiencies[:n])
        while len(eff) < n:
            eff.append(eff[-1] if eff else 0.98)
        v.gear_efficiencies = [max(0.5, min(1.0, float(x))) for x in eff]
        shifts = list(v.shift_rpms[:n])
        while len(shifts) < n:
            shifts.append(0.0)
        v.shift_rpms = [float(x) for x in shifts]
        v.transmission_type = str(v.transmission_type).lower().strip()
        if v.transmission_type not in {"clutch", "converter"}:
            raise ValueError("transmission_type must be 'clutch' or 'converter'.")
        return v

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["dyno"] = self.dyno.to_dict()
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VehicleConfig":
        data = copy.deepcopy(data or {})
        aliases = {
            "weight": "weight_lb",
            "wheelbase": "wheelbase_in",
            "rollout": "rollout_in",
            "overhang": "front_overhang_in",
            "ref_area": "frontal_area_ft2",
            "cd": "drag_coefficient",
            "cl": "lift_coefficient",
            "final_ratio": "final_drive_ratio",
            "final_efficiency": "final_drive_efficiency",
            "tire_dia": "tire_diameter_in",
            "tire_width": "tire_width_in",
            "torque_mult": "torque_multiplication",
            "hptq_multiplier": "hp_multiplier",
        }
        for old, new in aliases.items():
            if old in data and new not in data:
                data[new] = data.pop(old)
        if isinstance(data.get("dyno"), dict):
            data["dyno"] = DynoCurve.from_dict(data["dyno"])
        fields = cls.__dataclass_fields__
        return cls(**{k: v for k, v in data.items() if k in fields}).normalized()


@dataclass
class TimingData:
    sixty_ft_s: Optional[float] = None
    three_thirty_ft_s: Optional[float] = None
    eighth_mile_s: Optional[float] = None
    eighth_mile_mph: Optional[float] = None
    thousand_ft_s: Optional[float] = None
    thousand_ft_mph: Optional[float] = None
    quarter_mile_s: Optional[float] = None
    quarter_mile_mph: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimingData":
        aliases = {
            "60": "sixty_ft_s", "60ft": "sixty_ft_s", "60ft_s": "sixty_ft_s",
            "330": "three_thirty_ft_s", "330ft": "three_thirty_ft_s", "330ft_s": "three_thirty_ft_s",
            "660": "eighth_mile_s", "660ft": "eighth_mile_s", "660ft_s": "eighth_mile_s", "eighth_s": "eighth_mile_s",
            "660_mph": "eighth_mile_mph", "660ft_mph": "eighth_mile_mph", "eighth_mph": "eighth_mile_mph",
            "1000": "thousand_ft_s", "1000ft": "thousand_ft_s", "1000ft_s": "thousand_ft_s",
            "1000_mph": "thousand_ft_mph", "1000ft_mph": "thousand_ft_mph", "thousand_mph": "thousand_ft_mph",
            "1320": "quarter_mile_s", "1320ft": "quarter_mile_s", "1320ft_s": "quarter_mile_s", "et": "quarter_mile_s",
            "1320_mph": "quarter_mile_mph", "1320ft_mph": "quarter_mile_mph", "mph": "quarter_mile_mph",
        }
        normalized: Dict[str, Any] = {}
        for k, v in (data or {}).items():
            key = str(k).strip().lower().replace(" ", "_")
            key = aliases.get(key, key)
            if key in cls.__dataclass_fields__:
                normalized[key] = None if v in (None, "") else float(v)
        return cls(**normalized)

    def to_dict(self) -> Dict[str, Optional[float]]:
        return asdict(self)

    def count(self) -> int:
        return sum(v is not None for v in asdict(self).values())


@dataclass
class ChannelSeries:
    """A telemetry channel on its native timebase.

    Desktop displays should prefer this representation so mixed-rate files do
    not have to be expanded to one giant rectangular table.  The legacy
    DataFrame representation remains available for the physics/inverse code.
    """
    name: str
    time_s: Any
    values: Any
    unit: str = ""
    sample_rate_hz: Optional[float] = None
    decimals: int = 3
    interpolate: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)



@dataclass
class TelemetryRun:
    name: str
    data: Any  # pandas.DataFrame, kept Any to keep model module lightweight
    channel_map: Dict[str, str]
    units: Dict[str, str] = field(default_factory=dict)
    vendor: str = "generic"
    metadata: Dict[str, Any] = field(default_factory=dict)
    environment: Environment = field(default_factory=Environment)
    timing: TimingData = field(default_factory=TimingData)
    native_channels: Dict[str, ChannelSeries] = field(default_factory=dict)

    def channel_series(self, channel: str) -> Optional[ChannelSeries]:
        """Return a channel on its native timebase when available."""
        if channel in self.native_channels:
            return self.native_channels[channel]
        # Canonical private columns may originate from a source channel.
        prov = str(self.metadata.get("unit_provenance", {}).get(channel, ""))
        if " from " in prov:
            src = prov.split(" from ", 1)[1].split(" [", 1)[0]
            if src in self.native_channels:
                return self.native_channels[src]
        return None


@dataclass
class SimulationResult:
    trace: Any
    timing: TimingData
    diagnostics: Dict[str, Any] = field(default_factory=dict)


DEFAULT_PRO_STOCK = VehicleConfig(
    name="Pro Stock example",
    weight_lb=2355,
    wheelbase_in=107,
    rollout_in=9,
    front_overhang_in=40,
    frontal_area_ft2=18.2,
    drag_coefficient=0.24,
    lift_coefficient=0.10,
    body_style=5,
    traction_index=3,
    transmission_type="clutch",
    launch_rpm=7200,
    stall_rpm=7600,
    torque_multiplication=1.0,
    slippage=1.004,
    lockup_after_first=False,
    final_drive_ratio=4.86,
    final_drive_efficiency=0.975,
    tire_diameter_in=102.5 / np.pi,
    tire_width_in=17,
    gear_ratios=[2.6, 1.9, 1.5, 1.2, 1.0],
    gear_efficiencies=[0.99, 0.991, 0.992, 0.993, 0.994],
    shift_rpms=[9400, 9400, 9400, 9400, 0],
    hp_multiplier=1.0,
    engine_pmi=3.42,
    transmission_pmi=0.247,
    tires_pmi=50.8,
    dyno=DynoCurve(
        rpm=[7000, 7250, 7500, 7750, 8000, 8250, 8500, 8750, 9000, 9250, 9500],
        hp=[1078, 1131, 1177, 1216, 1251, 1274, 1288, 1300, 1297, 1269, 1222],
    ),
)
