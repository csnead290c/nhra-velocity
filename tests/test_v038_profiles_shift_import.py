from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from runlab.models import TelemetryRun, TimingData
from runlab.import_registry import spec_for_path
from runlab.importers import load_telemetry
from runlab.run_profiles import profile, infer_profile, resolve_profile_channels, apply_profile_rsa_defaults
from runlab.shift_report import detect_shifts, build_shift_report, compare_shift_reports


def _shift_run():
    dt = 0.01
    t = np.arange(-0.5, 7.2, dt)
    # Five-speed Pro Stock-ish trace: ramps with four sharp drops.
    rpm = np.full_like(t, 7000.0)
    rpm[t < 0] = 3500
    shift_times = [1.10, 2.05, 3.00, 4.05]
    rpm = np.full_like(t, 3500.0)
    segment_starts = [0.0] + [x + 0.12 for x in shift_times]
    segment_ends = shift_times + [6.4]
    for start, end in zip(segment_starts, segment_ends):
        seg=(t >= start) & (t < end)
        rpm[seg] = 7600 + (9400-7600) * (t[seg]-start) / max(end-start, 1e-6)
    # Explicitly shape the four shift RPM drops.
    for st in shift_times:
        drop = (t >= st) & (t < st + .12)
        rpm[drop] = np.linspace(9400, 7600, drop.sum())
    rpm[t >= 6.4] = 9000
    ds = np.clip((t + .05) * 1600, 0, 11000)
    clutch = rpm * 0.98
    data = pd.DataFrame({'Time': t, 'Engine RPM': rpm, 'DS RPM': ds, 'Clutch RPM': clutch})
    run = TelemetryRun('Pro Stock test', data, {'time_s':'Time','engine_rpm':'Engine RPM','driveshaft_rpm':'DS RPM','clutch_rpm':'Clutch RPM'},
                       units={'Time':'s','Engine RPM':'rpm','DS RPM':'rpm','Clutch RPM':'rpm'})
    run.metadata['original_channel_map'] = dict(run.channel_map)
    run.timing = TimingData(quarter_mile_s=6.55)
    return run


def test_registry_direct_extension_wins_over_coincidental_motec_header(tmp_path, monkeypatch):
    p = tmp_path / 'DKCHI26Q3.rpk'
    p.write_bytes((64).to_bytes(4, 'little') + b'X' * 3000)
    called = []
    import runlab.racepak as racepak
    import runlab.motec_ld as motec
    def fake_racepak(path):
        called.append('racepak')
        t=np.arange(5,dtype=float)
        run=TelemetryRun('rpk',pd.DataFrame({'Time':t,'RPM':np.arange(5.)}),{'time_s':'Time','engine_rpm':'RPM'},units={'Time':'s','RPM':'rpm'})
        run.metadata['original_channel_map']=dict(run.channel_map)
        return run
    def fake_motec(path):
        called.append('motec')
        raise AssertionError('MoTeC parser must not receive a .rpk file')
    monkeypatch.setattr(racepak,'parse_racepak_rpk',fake_racepak)
    monkeypatch.setattr(motec,'parse_motec_ld',fake_motec)
    run=load_telemetry(p)
    assert called == ['racepak']
    assert run.metadata['import_decoder'] == 'RacePak'
    assert 'registry extension match' in run.metadata['import_probe_reason']


def test_bigstuff_calibration_is_recognized_but_not_claimed_as_telemetry(tmp_path):
    p=tmp_path/'norwalk q1.bigTune'
    p.write_bytes(b'\x00binary')
    spec=spec_for_path(p)
    assert spec is not None and spec.key == 'bigstuff_tune'
    with pytest.raises(ValueError, match='calibration/support'):
        load_telemetry(p)


def test_pro_stock_profile_channels_and_rsa_defaults():
    run=_shift_run()
    p=infer_profile(run)
    assert p.key == 'pro_stock'
    chans=resolve_profile_channels(run,'pro_stock',group='Shift / Driveline')
    assert chans[:3] == ['Engine RPM','DS RPM','Clutch RPM']
    applied=apply_profile_rsa_defaults(run,'pro_stock')
    assert applied['weight_lb'] == pytest.approx(2355)
    assert applied['rollout_in'] == pytest.approx(9)
    assert applied['front_overhang_in'] == pytest.approx(40)
    assert run.metadata['rsa_profile_defaults']['profile'] == 'pro_stock'


def test_pro_stock_shift_report_detects_and_compares():
    run=_shift_run()
    events=detect_shifts(run)
    assert 3 <= len(events) <= 5
    assert all(e.engine_rpm > 8500 for e in events)
    report=build_shift_report(run)
    assert report['report_type'] == 'pro_stock_shift'
    assert report['fingerprint_sha256']
    changed={**report, 'events':[dict(x) for x in report['events']]}
    changed['events'][0]['engine_rpm'] += 250
    rows=compare_shift_reports(changed,report,rpm_alert=150)
    assert rows[0]['alert'] is True
    assert rows[0]['delta_rpm'] == pytest.approx(250)

from runlab.run_window import fit_window


def test_fit_window_uses_official_or_detected_run_not_entire_log():
    run=_shift_run()
    win=fit_window(run,'Time from Launch',finish_distance_ft=1320)
    assert win.x_min == pytest.approx(-0.5)
    assert win.x_max == pytest.approx(7.30)
    d=fit_window(run,'Distance from Launch',finish_distance_ft=1000)
    assert d.x_min == -25 and d.x_max == 1050
