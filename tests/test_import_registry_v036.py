from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from runlab.compare_sets import CompareSet, CompareSetLibrary
from runlab.import_registry import spec_for_path, telemetry_candidate
from runlab.importers import load_telemetry
from runlab.qualification import qualify_file


def test_registry_recognizes_direct_and_pending_families(tmp_path):
    assert spec_for_path(tmp_path / 'run.vbo').key == 'vbox_vbo'
    assert spec_for_path(tmp_path / 'run.MaxxECU-Zip-log').key == 'maxxecu'
    assert spec_for_path(tmp_path / 'run.mf4').key == 'asam_mdf'
    assert spec_for_path(tmp_path / 'run.xrk').key == 'aim'
    assert spec_for_path(tmp_path / 'run.dlz').key == 'holley'
    assert telemetry_candidate(tmp_path / 'run.hpl')
    assert telemetry_candidate(tmp_path / 'trace.asc')
    assert not telemetry_candidate(tmp_path / 'firmware.bin')


def test_pending_proprietary_binary_fails_closed_with_specific_message(tmp_path):
    p = tmp_path / 'run.mf4'
    p.write_bytes(b'MDF     4.20' + b'\x00' * 256)
    with pytest.raises(ValueError) as exc:
        load_telemetry(p)
    text = str(exc.value)
    assert 'ASAM MDF' in text
    assert 'generic text parser' in text
    assert 'Recognition does not imply native qualification' in text


def test_vbox_vbo_direct_import_preserves_raw_and_adds_elapsed_gps(tmp_path):
    p = tmp_path / 'pass.vbo'
    p.write_text(
        '[header]\n'
        'File created by VBOX\n'
        '[column names]\n'
        'time lat long velocity heading height\n'
        '[data]\n'
        '123000.000 3512.0000 -08015.0000 0.0 10.0 250.0\n'
        '123000.100 3512.0006 -08014.9994 100.0 10.5 250.2\n'
        '123000.200 3512.0012 -08014.9988 200.0 11.0 250.4\n'
    )
    run = load_telemetry(p)
    assert run.vendor == 'Racelogic VBOX'
    assert run.metadata['import_decoder'] == 'VBOX'
    assert 'time' in run.data.columns  # raw source retained
    assert 'VBOX Elapsed Time' in run.data.columns
    assert 'GPS Latitude Decimal' in run.data.columns
    assert run.channel_map['time_s'] == '__time_s'
    assert run.channel_map['speed_mph'] == '__speed_mph'
    assert run.channel_map['gps_latitude_deg'] == '__gps_latitude_deg'
    assert np.isclose(float(run.data['__time_s'].iloc[-1]), 0.2, atol=1e-6)
    assert np.isclose(float(run.data['__speed_mph'].iloc[-1]), 124.274238, rtol=1e-5)
    assert 35.19 < float(run.data['__gps_latitude_deg'].iloc[0]) < 35.21
    assert -80.26 < float(run.data['__gps_longitude_deg'].iloc[0]) < -80.24


def test_tunerstudio_msl_text_import_and_binary_mlg_rejection(tmp_path):
    p = tmp_path / 'run.msl'
    p.write_text(
        'MegaSquirt Compatible DataLog\n'
        'Time\tRPM\tTPS\tMAP\n'
        's\trpm\t%\tkPa\n'
        '0.0\t1000\t0\t101\n'
        '0.1\t3000\t100\t110\n'
        '0.2\t5000\t100\t120\n'
    )
    run = load_telemetry(p)
    assert run.vendor == 'TunerStudio/MegaSquirt'
    assert 'engine_rpm' in run.channel_map
    assert 'time_s' in run.channel_map

    binary = tmp_path / 'run.mlg'
    binary.write_bytes(b'\x00MLG' + b'\x00' * 100)
    with pytest.raises(ValueError) as exc:
        load_telemetry(binary)
    assert 'Binary TunerStudio/MegaSquirt' in str(exc.value)


def test_excel_telemetry_import_selects_data_sheet_and_maps_channels(tmp_path):
    p = tmp_path / 'telemetry.xlsx'
    with pd.ExcelWriter(p, engine='openpyxl') as writer:
        pd.DataFrame({'notes': ['setup notes', 'not telemetry']}).to_excel(writer, sheet_name='Notes', index=False)
        pd.DataFrame({
            'Time [s]': [0.0, 0.1, 0.2, 0.3],
            'Engine RPM': [1000, 2500, 4200, 6000],
            'Vehicle Speed [mph]': [0, 20, 50, 90],
            'Battery Voltage [V]': [13.8, 13.7, 13.6, 13.5],
        }).to_excel(writer, sheet_name='Run 1', index=False)
    run = load_telemetry(p)
    assert run.vendor == 'Excel'
    assert run.metadata['workbook_sheet'] == 'Run 1'
    assert 'engine_rpm' in run.channel_map
    assert 'speed_mph' in run.channel_map
    assert 'battery_voltage' in run.channel_map



def test_maxxecu_package_uses_logmetadata_rate_as_physical_clock(tmp_path):
    import zipfile
    p = tmp_path / 'run.MaxxECU-Zip-log'
    log = (
        'RPM [61]\tTime after launch [260]\tVSS Speed [89]\n'
        '1000\t0\t0\n'
        '2000\t0\t10\n'
        '3000\t0.01\t20\n'
        '4000\t0.02\t30\n'
    )
    with zipfile.ZipFile(p, 'w') as zf:
        zf.writestr('sample.MaxxECU-Log', log)
        zf.writestr('fileinfo01.LogMetaData', 'LogRate=0.01\n')
    run = load_telemetry(p)
    assert run.vendor == 'MaxxECU'
    assert run.metadata['maxxecu_log_rate_s'] == 0.01
    assert run.channel_map['time_s'] == '__time_s'
    assert np.allclose(run.data['__time_s'].to_numpy(float), [0.0, 0.01, 0.02, 0.03])
    assert run.metadata.get('data_warnings', []) == []

def test_qualification_record_reports_registry_and_probe_metadata(tmp_path):
    p = tmp_path / 'simple.csv'
    p.write_text('Time [s],Engine RPM,Speed [mph]\n0,1000,0\n0.1,2000,10\n0.2,3000,25\n')
    rec = qualify_file(p)
    assert rec.status == 'pass'
    assert rec.format_key == 'delimited'
    assert rec.format_status == 'interchange'
    assert rec.decoder
    assert rec.probe_reason


def test_compare_set_reference_step_display_selection_alignment_and_roundtrip():
    cs = CompareSet('PSM test')
    cs.add_run('A', label='A run', role='reference')
    cs.add_run('B', label='B run')
    cs.add_run('C', label='C run')
    assert cs.reference_run_key == 'A'
    assert cs.step_reference(1) == 'B'
    assert cs.reference_run_key == 'B'
    cs.set_display_runs('waveform-1', ['A', 'C'])
    assert [r.run_key for r in cs.runs_for_display('waveform-1')] == ['A', 'C']
    cs.set_alignment('C', 0.125)
    cs.set_alignment('C', 0.250, display_id='waveform-1')
    assert np.isclose(cs.alignment_for('C'), 0.125)
    assert np.isclose(cs.alignment_for('C', display_id='waveform-1'), 0.250)
    rebuilt = CompareSet.from_dict(cs.to_dict())
    assert rebuilt.reference_run_key == 'B'
    assert [r.run_key for r in rebuilt.runs_for_display('waveform-1')] == ['A', 'C']
    assert np.isclose(rebuilt.alignment_for('C', display_id='waveform-1'), 0.250)

    lib = CompareSetLibrary()
    first = lib.create('One', ['A', 'B'])
    second = lib.create('Two', ['C'])
    assert lib.active is second
    lib.set_active(first.id)
    roundtrip = CompareSetLibrary.from_dict(lib.to_dict())
    assert roundtrip.active is not None
    assert roundtrip.active.name == 'One'
