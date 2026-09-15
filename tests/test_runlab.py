from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from runlab.importers import load_telemetry
from runlab.inverse import FitRun, fit_vehicle
from runlab.models import VehicleConfig
from runlab.physics import SolverOptions, simulate
from runlab.quarterpro import parse_quarter_pro_dat
from runlab.weather import quarterpro_weather

ROOT = Path(__file__).resolve().parents[1]


def test_qpro_parser():
    v, env, meta = parse_quarter_pro_dat(ROOT / "examples" / "PROSTOCK.dat")
    assert abs(v.weight_lb - 2355) < 1e-9
    assert abs(v.final_drive_ratio - 4.86) < 1e-9
    assert len(v.dyno.rpm) == 11
    assert len(v.gear_ratios) == 5
    assert meta["source_format"] == "Quarter Pro DAT"


def test_weather_port():
    _, env, _ = parse_quarter_pro_dat(ROOT / "examples" / "PROSTOCK.dat")
    wx = quarterpro_weather(env)
    assert 0.06 < wx.density_lbm_ft3 < 0.09
    assert 0.8 < wx.horsepower_correction < 1.3


def test_forward_simulation_finishes():
    v, env, _ = parse_quarter_pro_dat(ROOT / "examples" / "PROSTOCK.dat")
    result = simulate(v, env, options=SolverOptions(dt_s=0.01))
    assert result.timing.sixty_ft_s is not None
    assert result.timing.quarter_mile_s is not None
    assert 5.0 < result.timing.quarter_mile_s < 10.0
    assert 140 < result.timing.quarter_mile_mph < 250


def test_generic_importer_maps_channels():
    run = load_telemetry(ROOT / "examples" / "demo_run_1.csv")
    assert "time_s" in run.channel_map
    assert "engine_rpm" in run.channel_map
    assert "driveshaft_rpm" in run.channel_map
    assert "speed_mph" in run.channel_map


def test_inverse_recovers_power_scale_from_synthetic_timing():
    v, env, _ = parse_quarter_pro_dat(ROOT / "examples" / "PROSTOCK.dat")
    truth = simulate(v, env, power_scale=1.06, options=SolverOptions(dt_s=0.01))
    fitted = fit_vehicle(
        v,
        [FitRun(name="synthetic", environment=env, timing=truth.timing)],
        ["power_scale"],
        max_nfev=80,
        fit_dt_s=0.01,
        final_dt_s=0.01,
    )
    estimate = float(fitted.estimates.loc[0, "estimate"])
    assert abs(estimate - 1.06) < 0.05


def test_reconstruction_produces_dyno_and_ratio_summary():
    from runlab.reconstruction import reconstruct_delivered_power
    v, env, _ = parse_quarter_pro_dat(ROOT / "examples" / "PROSTOCK.dat")
    run = load_telemetry(ROOT / "examples" / "demo_run_1.csv")
    rec = reconstruct_delivered_power(run, v, env)
    assert len(rec.dyno_curve) >= 5
    assert len(rec.gear_summary) >= 4
    # Top gears in the synthetic log should recover the configured trans ratio/slip closely.
    high = rec.gear_summary[rec.gear_summary["gear"] >= 2]
    assert np.nanmedian(np.abs(high["implied_slippage_vs_config"] - v.slippage)) < 0.03


def test_reference_suite_converges_without_hard_failure():
    from runlab.validation import qpro_convergence_report, qpro_validation_summary
    paths = sorted((ROOT / "examples" / "qpro_reference").glob("*.[dD][aA][tT]"))
    assert len(paths) == 6
    report = qpro_convergence_report(paths, dts=(0.01, 0.005, 0.0025))
    summary = qpro_validation_summary(report)
    assert len(summary) == 6
    assert not (summary["stability"] == "Needs solver attention").any()


def test_observability_flags_power_weight_conflict():
    from runlab.observability import assess_observability
    v, env, _ = parse_quarter_pro_dat(ROOT / "examples" / "PROSTOCK.dat")
    truth = simulate(v, env, options=SolverOptions(dt_s=0.01))
    table = assess_observability(
        v,
        [FitRun(name="timing only", environment=env, timing=truth.timing)],
        ["power_scale", "weight_lb"],
    )
    weight = table.loc[table["parameter"] == "weight_lb"].iloc[0]
    assert weight["preflight"] in {"Weak", "Not observable"}
    assert "confounded" in weight["important_confounds"]


def test_inverse_recovers_final_drive_ratio_when_it_is_only_unknown():
    v, env, _ = parse_quarter_pro_dat(ROOT / "examples" / "PROSTOCK.dat")
    truth_vehicle = VehicleConfig.from_dict(v.to_dict())
    truth_vehicle.final_drive_ratio = v.final_drive_ratio * 1.035
    truth = simulate(truth_vehicle, env, options=SolverOptions(dt_s=0.01))
    fitted = fit_vehicle(
        v,
        [FitRun(name="ratio synthetic", environment=env, timing=truth.timing)],
        ["final_drive_ratio"],
        max_nfev=80,
        fit_dt_s=0.01,
        final_dt_s=0.01,
    )
    estimate = float(fitted.estimates.loc[0, "estimate"])
    assert abs(estimate - truth_vehicle.final_drive_ratio) / truth_vehicle.final_drive_ratio < 0.03


def test_explicit_static_front_weight_is_preserved_as_baseline():
    v, env, _ = parse_quarter_pro_dat(ROOT / "examples" / "PROSTOCK.dat")
    v.static_front_weight_lb = 1000.0
    result = simulate(v, env, options=SolverOptions(dt_s=0.01))
    assert abs(result.diagnostics["static_front_weight_lb"] - 1000.0) < 1e-9


def test_run_specific_power_nuisance_protects_shared_model():
    v, env, _ = parse_quarter_pro_dat(ROOT / "examples" / "PROSTOCK.dat")
    low = simulate(v, env, power_scale=0.97, options=SolverOptions(dt_s=0.01))
    high = simulate(v, env, power_scale=1.03, options=SolverOptions(dt_s=0.01))
    fitted = fit_vehicle(
        v,
        [FitRun(name="low", environment=env, timing=low.timing), FitRun(name="high", environment=env, timing=high.timing)],
        ["power_scale"],
        nuisance_terms=["power_scale"],
        max_nfev=120,
        fit_dt_s=0.01,
        final_dt_s=0.01,
    )
    est = fitted.estimates.set_index("internal_name")["estimate"]
    assert abs(float(est["power_scale"]) - 1.0) < 0.03
    assert float(est["run__0__power_scale"]) < 1.0
    assert float(est["run__1__power_scale"]) > 1.0


def test_manual_channel_and_unit_overrides(tmp_path):
    p = tmp_path / "odd_logger.csv"
    p.write_text(
        "ClockTicks,EngSpd,GPS_V,AccelX,PedalRaw\n"
        "0,7000,0,0,0\n"
        "500000,8000,100,9.80665,0.5\n"
        "1000000,8500,160,4.903325,1.0\n"
    )
    run = load_telemetry(
        p,
        channel_overrides={
            "time_s": "ClockTicks",
            "engine_rpm": "EngSpd",
            "speed_mph": "GPS_V",
            "longitudinal_g": "AccelX",
            "throttle_pct": "PedalRaw",
        },
        unit_overrides={
            "time_s": "us",
            "speed_mph": "kmh",
            "longitudinal_g": "mps2",
            "throttle_pct": "fraction",
        },
    )
    df = run.data
    assert abs(float(df[run.channel_map["time_s"]].iloc[-1]) - 1.0) < 1e-9
    assert abs(float(df[run.channel_map["speed_mph"]].iloc[1]) - 62.1371192) < 1e-5
    assert abs(float(df[run.channel_map["longitudinal_g"]].iloc[1]) - 1.0) < 1e-6
    assert abs(float(df[run.channel_map["throttle_pct"]].iloc[1]) - 50.0) < 1e-9


def test_drag_pass_detection_ignores_early_movement_artifact():
    import pandas as pd
    from runlab.models import TelemetryRun
    from runlab.telemetry import detect_drag_pass_window

    t = np.arange(0.0, 20.0, 0.05)
    speed = np.zeros_like(t)
    speed[:12] = np.linspace(6.0, 0.0, 12)  # staging/rolling artifact at file start
    launch_i = int(5.0 / 0.05)
    peak_i = int(11.0 / 0.05)
    speed[launch_i:peak_i + 1] = np.linspace(0.0, 190.0, peak_i - launch_i + 1)
    speed[peak_i:] = np.maximum(0.0, 190.0 - 20.0 * (t[peak_i:] - t[peak_i]))
    df = pd.DataFrame({"Time": t, "Speed": speed})
    run = TelemetryRun(
        name="artifact",
        data=df,
        channel_map={"time_s": "Time", "speed_mph": "Speed"},
        units={"Time": "s", "Speed": "mph"},
        vendor="synthetic",
        metadata={},
    )
    window = detect_drag_pass_window(run)
    assert 4.8 <= window.launch_time_s <= 5.1
    assert window.peak_speed_mph is not None and window.peak_speed_mph > 185
    assert window.confidence == "High"


def test_native_racepak_legacy_float_buffer_parser(tmp_path):
    import struct
    from runlab.importers import load_telemetry

    def lp(text: str) -> bytes:
        raw = text.encode("latin1")
        assert len(raw) < 256
        return bytes([len(raw)]) + raw

    def channel(st: str, name: str, desc: str, timer: str = "Timer_20sps") -> bytes:
        return b"\x43\x09\x02\x00" + lp(st) + lp(name) + lp(desc) + lp("0.0") + lp(timer) + b"\x00" * 12

    def calc(name: str, expr: str) -> bytes:
        return b"\x03\x03\x02\x00" + lp("EXPR") + lp(name) + lp("Calculation: [(0,300),%-6.1lf,]") + lp(expr) + lp("") + b"\x00" * 12

    def buffer(values) -> bytes:
        values = list(map(float, values))
        n = len(values)
        return bytes([12]) + b"ScaledBuffer" + struct.pack("<4I", n, 0, n, 1) + struct.pack("<" + "f" * n, *values)

    data = b"\x00" * 256
    data += channel("RPM", "ENGINE RPM", "ScaledBuffer: (0=>0,1=>1) [(0,10000),%-5.0lf,RPM]")
    data += channel("RPM", "DRIVE SHAFT", "ScaledBuffer: (0=>0,1=>1) [(0,10000),%-5.0lf,RPM]")
    data += channel("VOLTAGE", "G_METER", "ScaledBuffer: (2=>0,5=>3) [(-2,3),%-5.2lf,G]")
    data += calc("MPH", "'DRIVE SHAFT'*.1")
    data += b"\x00" * 64
    data += buffer([0, 2000, 5000, 7000, 8000])
    data += buffer([0, 100, 300, 600, 1000])
    data += buffer([2.0, 2.5, 3.0, 3.5, 4.0])

    path = tmp_path / "legacy_demo.rpk"
    path.write_bytes(data)
    run = load_telemetry(path)
    assert run.vendor == "RacePak"
    assert run.channel_map["engine_rpm"] == "__engine_rpm"
    assert run.channel_map["driveshaft_rpm"] == "__driveshaft_rpm"
    assert "speed_mph" in run.channel_map
    assert "longitudinal_g" in run.channel_map
    assert abs(float(run.data[run.channel_map["speed_mph"]].iloc[-1]) - 100.0) < 1e-6
    assert abs(float(run.data[run.channel_map["longitudinal_g"]].iloc[-1]) - 2.0) < 1e-6


def test_source_faithful_reference_solver_runs_all_qpro_examples():
    from runlab.legacy_reference import simulate_legacy_reference
    paths = sorted((ROOT / "examples" / "qpro_reference").glob("*.[dD][aA][tT]"))
    for path in paths:
        v, env, _ = parse_quarter_pro_dat(path)
        result = simulate_legacy_reference(v, env)
        assert result.timing.quarter_mile_s is not None
        assert result.timing.quarter_mile_mph is not None
        assert result.diagnostics["states"] > 50


def test_qpro_parser_uses_exact_source_body_and_trans_rules():
    moto, _, _ = parse_quarter_pro_dat(ROOT / "examples" / "qpro_reference" / "MOTORCYC.DAT")
    sc, _, _ = parse_quarter_pro_dat(ROOT / "examples" / "qpro_reference" / "SUPERCMP.DAT")
    ps, _, _ = parse_quarter_pro_dat(ROOT / "examples" / "qpro_reference" / "PROSTOCK.dat")
    assert moto.body_style == 8
    assert sc.body_style == 1
    assert sc.transmission_type == "converter"
    assert ps.transmission_type == "clutch"


def test_parity_report_separates_convergence_from_source_agreement():
    from runlab.validation import qpro_parity_report
    paths = [ROOT / "examples" / "qpro_reference" / "FUNNYCAR.DAT", ROOT / "examples" / "qpro_reference" / "PROSTOCK.dat"]
    report = qpro_parity_report(paths, modern_dt_s=0.0025)
    assert len(report) == 2
    assert "legacy_1320ft_s" in report.columns
    assert "delta_1320ft_s" in report.columns
    assert set(report["parity_status"]).issubset({"Parity target", "Close / refine", "Material gap", "Priority physics gap"})


def test_legacy_reference_snapshot_does_not_drift():
    from runlab.legacy_reference import simulate_legacy_reference
    snapshot = pd.read_csv(ROOT / "examples" / "qpro_reference" / "legacy_source_reference_snapshot.csv")
    for _, row in snapshot.iterrows():
        matches = list((ROOT / "examples" / "qpro_reference").glob(f"{row['vehicle']}.[dD][aA][tT]"))
        assert matches, f"Missing Quarter Pro sample for {row['vehicle']}"
        v, env, _ = parse_quarter_pro_dat(matches[0])
        t = simulate_legacy_reference(v, env).timing
        assert abs(float(t.sixty_ft_s) - float(row["60ft_s"])) < 1e-7
        assert abs(float(t.three_thirty_ft_s) - float(row["330ft_s"])) < 1e-7
        assert abs(float(t.eighth_mile_s) - float(row["660ft_s"])) < 1e-7
        assert abs(float(t.eighth_mile_mph) - float(row["660ft_mph"])) < 1e-6
        assert abs(float(t.thousand_ft_s) - float(row["1000ft_s"])) < 1e-7
        assert abs(float(t.quarter_mile_s) - float(row["1320ft_s"])) < 1e-7
        assert abs(float(t.quarter_mile_mph) - float(row["1320ft_mph"])) < 1e-6


def test_inverse_fit_runs_high_fidelity_second_opinion():
    v, env, _ = parse_quarter_pro_dat(ROOT / "examples" / "PROSTOCK.dat")
    truth = simulate(v, env, power_scale=1.02, options=SolverOptions(dt_s=0.01))
    fitted = fit_vehicle(
        v,
        [FitRun(name="verification", environment=env, timing=truth.timing)],
        ["power_scale"],
        max_nfev=60,
        fit_dt_s=0.01,
        final_dt_s=0.005,
    )
    assert "verification" in fitted.reference_predictions
    assert fitted.reference_residuals is not None
    assert not fitted.reference_residuals.empty
    assert "engine" in fitted.reference_residuals.columns


def test_smooth_surrogate_stays_within_reference_acceptance_band():
    from runlab.validation import qpro_parity_report
    paths = sorted((ROOT / "examples" / "qpro_reference").glob("*.[dD][aA][tT]"))
    report = qpro_parity_report(paths, modern_dt_s=0.0025)
    assert not report.empty
    assert not report["parity_status"].isin({"Material gap", "Priority physics gap"}).any()
    assert report["delta_1320ft_s"].abs().max() < 0.030
    assert report["delta_1320ft_mph"].abs().max() < 1.0


def _write_synthetic_motec_ld(path: Path):
    """Write a structurally realistic M1-family LD fixture.

    The header count is intentionally wrong so the test proves the parser walks
    the channel linked list.  The fixture also exercises integer scaling,
    short-name unit fallback, float16 and float64 support.
    """
    import struct

    channels = [
        # name, short_name, unit, rate, dtype_a, dtype_size, shift, mul, scale, dec, raw
        ("Engine Speed", "RPM", "rpm", 100, 0x07, 4, 0, 1, 1, 0,
         np.array([3000, 3500, 4000, 4500, 5000], dtype='<f4')),
        ("Ground Speed", "", "km/h", 100, 0x07, 4, 0, 1, 1, 0,
         np.array([0, 50, 100, 150, 200], dtype='<f4')),
        ("Engine Power", "", "kW", 100, 0x07, 4, 0, 1, 1, 0,
         np.array([100, 150, 200, 250, 300], dtype='<f4')),
        # Unit deliberately stored in short_name and nontrivial scaling:
        # converted = raw * .001 * 2 + 50 => 0..100 %
        ("Throttle Pos", "%", "", 100, 0x03, 2, 50, 2, 1, 3,
         np.array([-25000, -12500, 0, 12500, 25000], dtype='<i2')),
        # Half precision is seen in some LD-family files.
        ("Damper Pos", "", "mm", 50, 0x07, 2, 0, 1, 1, 0,
         np.array([1, 2, 3, 4, 5], dtype='<f2')),
        # Float64 is used by M1 logs for GPS coordinates.
        ("GPS Latitude", "", "deg", 10, 0x08, 8, 0, 1, 1, 0,
         np.array([36.56, 36.5601, 36.5602], dtype='<f8')),
    ]
    header_size = 1800
    chan_size = 212
    # Add a zero-data terminator record after the real channels.
    first_meta = header_size
    record_count = len(channels) + 1
    data_start = first_meta + chan_size * record_count
    blob = bytearray(data_start + sum(c[-1].nbytes for c in channels) + 64)
    struct.pack_into('<I', blob, 0, 64)
    struct.pack_into('<I', blob, 8, first_meta)
    struct.pack_into('<I', blob, 12, data_start)
    struct.pack_into('<I', blob, 36, 0)
    struct.pack_into('<I', blob, 70, 12345)
    blob[74:74+8] = b'M1TEST\x00\x00'
    struct.pack_into('<H', blob, 82, 123)
    # Intentionally not equal to parsed channel count.
    struct.pack_into('<I', blob, 86, 99)

    def putstr(off, n, txt):
        b = txt.encode('latin1')[:n]
        blob[off:off+len(b)] = b
        if len(b) < n:
            blob[off+len(b)] = 0

    putstr(94, 16, '01/02/2026')
    putstr(126, 16, '12:34:56')
    putstr(158, 64, 'Test Driver')
    putstr(222, 64, 'Test Car')
    putstr(350, 64, 'Test Track')
    putstr(1572, 64, 'Synthetic M1 Session')

    pos = data_start
    for i, (name, short_name, unit, rate, dtype_a, dtype_size, shift, mul, scale, dec, vals) in enumerate(channels):
        addr = first_meta + i * chan_size
        next_addr = first_meta + (i + 1) * chan_size
        prev_addr = first_meta + (i - 1) * chan_size if i else 0
        struct.pack_into(
            '<IIIIHHHHhhhh', blob, addr,
            prev_addr, next_addr, pos, len(vals), 0x2EE1 + i,
            dtype_a, dtype_size, rate, shift, mul, scale, dec,
        )
        putstr(addr + 32, 32, name)
        putstr(addr + 64, 8, short_name)
        putstr(addr + 72, 12, unit)
        raw = vals.tobytes()
        blob[pos:pos+len(raw)] = raw
        pos += len(raw)

    term = first_meta + len(channels) * chan_size
    prev = first_meta + (len(channels)-1) * chan_size
    struct.pack_into('<IIIIHHHHhhhh', blob, term, prev, 0, 0, 0, 0, 0x03, 2, 0, 0, 1, 1, 0)
    path.write_bytes(blob)


def test_native_motec_ld_import_and_units(tmp_path):
    p = tmp_path / 'native.ld'
    _write_synthetic_motec_ld(p)
    run = load_telemetry(p)
    assert run.vendor == 'MoTeC'
    assert 'engine_rpm' in run.channel_map
    assert 'speed_mph' in run.channel_map
    assert 'power_hp' in run.channel_map
    assert len(run.native_channels) == 6
    assert run.metadata['header_channel_count'] == 99
    assert run.metadata['parsed_channel_count'] == 6
    assert any('header declares 99' in w for w in run.metadata.get('data_warnings', []))
    assert run.units['Throttle Pos'] == 'pct'
    assert np.allclose(run.native_channels['Throttle Pos'].values, [0, 25, 50, 75, 100])
    assert np.allclose(run.native_channels['Damper Pos'].values, [1, 2, 3, 4, 5])
    assert abs(run.native_channels['GPS Latitude'].values[-1] - 36.5602) < 1e-9
    # 200 km/h = ~124.274 mph
    assert abs(float(run.data[run.channel_map['speed_mph']].dropna().iloc[-1]) - 124.2742384) < 1e-4
    # 300 kW = ~402.3066 hp. This directly guards the reported million-HP unit failure.
    hp = float(run.data[run.channel_map['power_hp']].dropna().iloc[-1])
    assert 400 < hp < 405
    assert run.units[run.channel_map['power_hp']] == 'hp'
    assert run.metadata['unit_provenance']['Engine Power'] == 'native MoTeC LD channel metadata'


def test_power_unit_conversion_watts_to_hp(tmp_path):
    p = tmp_path / 'power.csv'
    p.write_text(
        'Time (s),Vehicle Speed (mph),Engine RPM,Power (W)\n'
        '0,0,3000,0\n'
        '0.1,20,3500,149139\n'
        '0.2,40,4000,223708.5\n'
        '0.3,60,4500,298278\n'
    )
    run = load_telemetry(p)
    assert 'power_hp' in run.channel_map
    hp = pd.to_numeric(run.data[run.channel_map['power_hp']], errors='coerce')
    assert 399 < float(hp.iloc[-1]) < 401


def test_suspicious_speed_mapping_is_rejected_instead_of_poisoning_power(tmp_path):
    p = tmp_path / 'badmap.csv'
    p.write_text(
        'Time (s),Speed,Engine RPM\n'
        '0,0,3000\n'
        '0.1,3000,4000\n'
        '0.2,6000,5000\n'
        '0.3,9000,6000\n'
    )
    run = load_telemetry(p)
    assert 'speed_mph' not in run.channel_map
    assert any('Rejected automatic speed_mph mapping' in w for w in run.metadata.get('data_warnings', []))


def test_derivative_power_pipeline_blocks_physically_impossible_time_speed_combo(tmp_path):
    """Catastrophic derivative inputs must fail closed instead of returning huge HP."""
    from runlab.reconstruction import reconstruct_delivered_power
    from runlab.models import VehicleConfig
    p = tmp_path / 'catastrophic.csv'
    p.write_text(
        'Time (s),Vehicle Speed (mph),Engine RPM\n'
        '0.000,0,3000\n'
        '0.001,100,3500\n'
        '0.002,200,4000\n'
        '0.003,300,4500\n'
        '0.004,320,5000\n'
        '0.005,330,5500\n'
    )
    run = load_telemetry(p)
    import pytest
    with pytest.raises(ValueError, match='telemetry audit'):
        reconstruct_delivered_power(run, VehicleConfig())


def test_run_alignment_recovers_compare_offset():
    from runlab.alignment import estimate_time_alignment
    from runlab.models import TelemetryRun
    t = np.arange(0.0, 8.0, 0.01)
    # Keep vehicle-speed launch identical so pass detection does not absorb the
    # deliberate residual offset in the comparison signal.
    speed = np.where(t < 1.0, 0.0, np.minimum((t - 1.0) * 42.0, 190.0))
    rel = t - 1.0
    g_main = (
        1.7*np.exp(-((rel-0.15)/0.10)**2)
        + 0.8*np.exp(-((rel-0.95)/0.08)**2)
        - 0.45*np.exp(-((rel-1.15)/0.05)**2)
        + 0.55*np.exp(-((rel-2.2)/0.12)**2)
    )
    delay = 0.12
    g_compare = np.interp(t-delay, t, g_main, left=0.0, right=0.0)
    def make(name, g):
        df = pd.DataFrame({'Time': t, 'Speed': speed, 'G': g})
        return TelemetryRun(
            name=name, data=df,
            channel_map={'time_s':'Time','speed_mph':'Speed','longitudinal_g':'G'},
            units={'Time':'s','Speed':'mph','G':'g'},
        )
    result = estimate_time_alignment(make('main', g_main), make('compare', g_compare), max_offset_s=0.4)
    assert result.canonical == 'longitudinal_g'
    assert result.score > 0.95
    assert abs(result.offset_s + delay) <= 0.015


def test_math_channel_is_safe_persistent_and_unit_tagged():
    from runlab.math_channels import add_math_channel, reapply_math_channels, evaluate_expression
    from runlab.models import TelemetryRun
    df = pd.DataFrame({
        'Time': [0.0, 0.1, 0.2],
        'Engine RPM': [6000.0, 7000.0, 8000.0],
        'Clutch RPM': [3000.0, 5000.0, 8000.0],
    })
    run = TelemetryRun('math', df.copy(), {'time_s':'Time'}, units={'Time':'s','Engine RPM':'rpm','Clutch RPM':'rpm'})
    add_math_channel(run, 'Clutch Ratio', '`Engine RPM` / `Clutch RPM`', 'ratio')
    np.testing.assert_allclose(run.data['Clutch Ratio'], [2.0, 1.4, 1.0])
    assert run.units['Clutch Ratio'] == 'ratio'
    defs = list(run.metadata['math_channels'])
    run2 = TelemetryRun('math2', df.copy(), {'time_s':'Time'}, units={'Time':'s','Engine RPM':'rpm','Clutch RPM':'rpm'})
    reapply_math_channels(run2, defs)
    np.testing.assert_allclose(run2.data['Clutch Ratio'], run.data['Clutch Ratio'])
    with pytest.raises(ValueError):
        evaluate_expression(df, '__import__("os").system("echo no")')
    with pytest.raises(ValueError):
        evaluate_expression(df, '`Missing Channel` + 1')


def test_plotability_selects_useful_default_channels_for_racepak_fixture(tmp_path):
    import struct
    from runlab.importers import load_telemetry
    from runlab.plotability import assess_plotability

    def lp(text: str) -> bytes:
        raw = text.encode('latin1'); return bytes([len(raw)]) + raw
    def channel(st: str, name: str, desc: str, timer: str = 'Timer_20sps') -> bytes:
        return b'\x43\x09\x02\x00' + lp(st) + lp(name) + lp(desc) + lp('0.0') + lp(timer) + b'\x00' * 12
    def buffer(values) -> bytes:
        values = list(map(float, values)); n = len(values)
        return bytes([12]) + b'ScaledBuffer' + struct.pack('<4I', n, 0, n, 1) + struct.pack('<' + 'f' * n, *values)

    data = b'\\\x07' + b'\x00' * 254
    data += channel('RPM', 'ENGINE RPM', 'ScaledBuffer: (0=>0,1=>1) [(0,10000),%-5.0lf,RPM]')
    data += channel('RPM', 'DRIVE SHAFT', 'ScaledBuffer: (0=>0,1=>1) [(0,10000),%-5.0lf,RPM]')
    data += b'\x00' * 64
    data += buffer([0, 2000, 5000, 7000, 8000])
    data += buffer([0, 100, 300, 600, 1000])
    path = tmp_path / 'renamed_capture.rpk.bin'
    path.write_bytes(data)

    run = load_telemetry(path)
    report = assess_plotability(run)
    assert run.vendor == 'RacePak'
    assert report.plotable
    assert 'ENGINE RPM' in report.default_channels
    assert 'DRIVE SHAFT' in report.default_channels


def test_text_log_without_time_still_plotable_by_sample_index(tmp_path):
    from runlab.importers import load_telemetry
    from runlab.plotability import assess_plotability
    p = tmp_path / 'sensor_export.csv'
    p.write_text('RPM,Oil PSI\n7000,80\n7200,82\n7400,81\n7600,79\n')
    run = load_telemetry(p)
    report = assess_plotability(run)
    assert report.plotable
    assert report.timebase == 'sample_index'
    assert report.default_channels


def test_unknown_binary_fails_before_csv_parser(tmp_path):
    from runlab.importers import load_telemetry
    p = tmp_path / 'mystery.bin'
    p.write_bytes(bytes(range(256)) * 8)
    try:
        load_telemetry(p)
    except ValueError as exc:
        text = str(exc).lower()
        assert 'unsupported or unrecognized telemetry format' in text
        assert 'csv parser' in text
    else:
        raise AssertionError('unknown binary should be rejected')


def test_generic_telemetry_zip_dispatches_member(tmp_path):
    import zipfile
    from runlab.importers import load_telemetry
    p = tmp_path / 'event_logs.zip'
    with zipfile.ZipFile(p, 'w') as zf:
        zf.writestr('run_01.csv', 'Time (s),Engine RPM,Speed mph\n0,7000,0\n0.1,7500,20\n0.2,8000,45\n0.3,8200,70\n')
    run = load_telemetry(p)
    assert run.metadata['archive_member'] == 'run_01.csv'
    assert run.metadata['source_file'] == 'event_logs.zip'
    assert run.metadata['plotability']['plotable'] is True


def test_racepak_gs_unit_alias_is_recognized():
    from runlab.units import normalize_unit, compatible
    assert normalize_unit("g's") == 'g'
    assert normalize_unit('Gs') == 'g'
    assert compatible("g's", 'g')


def test_native_racepak_current_can_device_parser_and_extended_strings(tmp_path):
    import struct
    from runlab.importers import load_telemetry

    def lp(text: str) -> bytes:
        raw = text.encode('latin1')
        if len(raw) < 0xFF:
            return bytes([len(raw)]) + raw
        assert len(raw) < 0xFFFF
        return b'\xff' + struct.pack('<H', len(raw)) + raw

    def modern_channel(st: str, name: str, desc: str, timer: str = '') -> bytes:
        return b'\x43\x09\x02\x00' + lp(st) + lp(name) + lp(desc) + lp('0.0') + lp(timer) + b'\x00' * 8

    def modern_buffer(values) -> bytes:
        vals = list(map(float, values))
        if not vals:
            return lp('CAN_Device') + struct.pack('<4I', 0, 0, 0, 0)
        # Capacity may exceed used samples in real DataLink files.  Keep one
        # spare slot to exercise used-count handling.
        cap = len(vals) + 1
        padded = vals + [vals[-1]]
        return lp('CAN_Device') + struct.pack('<4I', cap, len(vals), len(vals), 0) + struct.pack('<' + 'f' * cap, *padded)

    filler = 'X' * 400  # forces the current extended-length LP string encoding
    engine_desc = (
        'CAN_Device: CHANNEL_MODE="2", Logger_Sample_Rate="100", '
        '_HW_A="1", _HW_B="0", _UNIT="RPM", _X_MIN="0", _X_MAX="1", '
        '_Y_MIN="0", _Y_MAX="1", NOTE="' + filler + '"'
    )
    wheel_desc = (
        'CAN_Device: Logger_Sample_Rate="100", _HW_A="1", _HW_B="0", '
        '_UNIT="MPH", _X_MIN="0", _X_MAX="1", _Y_MIN="0", _Y_MAX="0.1"'
    )
    accel_desc = (
        'CAN_Device: Logger_Sample_Rate="50", _HW_A="0.005", _HW_B="0", '
        '_UNIT="G\'s", _X_MIN="2.5", _X_MAX="3.0", _Y_MIN="0", _Y_MAX="-1"'
    )
    unused_desc = 'CAN_Device: Logger_Sample_Rate="0", _UNIT="Voltage", _X_MIN="0", _X_MAX="1", _Y_MIN="0", _Y_MAX="1"'

    data = b'\x00' * 512
    data += modern_channel('V300SD_TACH', 'Engine RPM', engine_desc, 'Timer_100sps')
    data += modern_channel('V300SD_RPM', 'Front Wheel', wheel_desc, 'Timer_100sps')
    data += modern_channel('LOGGER_ANALOG', 'Accel G', accel_desc, 'Timer_50sps')
    data += modern_channel('LOGGER_ANALOG', 'Unused Input', unused_desc, '')
    data += b'\x00' * 64
    data += modern_buffer([3000, 5000, 7000, 8000])
    data += modern_buffer([0, 500, 1000, 2000])       # 0..200 mph after X/Y scaling
    data += modern_buffer([500, 520])                 # 2.5..2.6 V -> 0..-0.2 g
    data += modern_buffer([])

    path = tmp_path / 'current.rpk'
    path.write_bytes(data)
    run = load_telemetry(path)
    assert run.vendor == 'RacePak'
    assert run.metadata['rpk_buffer_family'] == 'CAN_Device'
    assert len(run.metadata['rpk_recorded_channels']) == 3
    assert run.metadata['original_channel_map']['engine_rpm'] == 'Engine RPM'
    assert run.metadata['original_channel_map']['wheel_speed_mph'] == 'Front Wheel'
    assert np.isclose(float(run.data['Front Wheel'].dropna().max()), 200.0)
    assert np.isclose(float(run.data['Accel G'].dropna().iloc[-1]), -0.2, atol=1e-5)
    assert run.units['Engine RPM'] == 'rpm'
    assert run.units['Front Wheel'] == 'mph'
    assert run.units['Accel G'] == 'g'


def test_auto_mapper_prefers_measurement_over_limit_state():
    from runlab.importers import auto_map_channels

    cols = ['Engine.Speed.Limit.State', 'Engine.Speed', 'DS RPM', 'Clutch RPM']
    units = {
        'Engine.Speed.Limit.State': '',
        'Engine.Speed': 'rpm',
        'DS RPM': 'rpm',
        'Clutch RPM': 'rpm',
    }
    mapping = auto_map_channels(cols, units=units)
    assert mapping['engine_rpm'] == 'Engine.Speed'
    assert mapping['driveshaft_rpm'] == 'DS RPM'
    assert mapping['clutch_rpm'] == 'Clutch RPM'
