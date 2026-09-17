from __future__ import annotations

from pathlib import Path
import numpy as np

from runlab.importers import load_telemetry
from runlab.racepak_channel_library import build_channel_id_census, install_census, lookup_verified_channel


def _lp(text: str) -> bytes:
    raw = text.encode('latin1'); assert len(raw) < 256
    return bytes([len(raw)]) + raw


def _channel(cid: int, name: str, unit: str = 'RPM', rate: int = 100) -> bytes:
    desc = f'ScaledBuffer: (0=>0,1=>1) [(0,12000),%-5.0lf,{unit}] _CONNECT4_COMMAND="{cid}"'
    return b'\x43\x09\x02\x00' + _lp('RPM') + _lp(name) + _lp(desc) + _lp('0.0') + _lp(f'Timer_{rate}sps') + b'\x00' * 12


def _config(cid: int = 2, name: str = 'ENGINE RPM', unit: str = 'RPM') -> bytes:
    return b'\x00' * 64 + _channel(cid, name, unit) + b'\x00' * 32


def _descriptor(flag: int, channel_id: int, rate: int, config_rate: int) -> bytes:
    return bytes([0x33, flag]) + int(channel_id).to_bytes(4, 'little') + int(rate).to_bytes(4, 'little') + int(config_rate).to_bytes(4, 'little') + b'\x00' * 8


def _ddf(cid: int = 2) -> bytes:
    header = bytearray(14); header[12:14] = (1).to_bytes(2, 'little')
    return bytes(header) + _descriptor(0x00, cid, 2, 2) + np.asarray([1000, 1100, 1200, 1300], dtype='<i2').tobytes()


def test_consensus_counts_distinct_configs_not_repeated_files(tmp_path: Path):
    # Three genuinely distinct configs agree on channel 2. One of the configs
    # appears in two files, but that duplicate may not manufacture extra votes.
    for i, extra in enumerate((101, 102, 103)):
        blob = _config(2, 'ENGINE RPM') + _channel(extra, f'OTHER {extra}', 'PSI', 10)
        (tmp_path / f'cfg{i}.rcg').write_bytes(blob)
    (tmp_path / 'duplicate.rcg').write_bytes((tmp_path / 'cfg0.rcg').read_bytes())

    payload = build_channel_id_census([tmp_path], rpk_mode='none')
    row = next(x for x in payload['channels'] if x['channel_id'] == 2)
    assert row['distinct_configurations'] == 3
    assert row['file_occurrences'] == 4
    assert row['confidence'] == 'verified'
    assert row['safe_for_fallback'] is True
    assert row['consensus_name'] == 'ENGINE RPM'


def test_conflicting_global_id_fails_closed(tmp_path: Path):
    (tmp_path / 'a.rcg').write_bytes(_config(2, 'ENGINE RPM'))
    (tmp_path / 'b.rcg').write_bytes(_config(2, 'DRIVE SHAFT'))
    (tmp_path / 'c.rcg').write_bytes(_config(2, 'ENGINE RPM'))
    payload = build_channel_id_census([tmp_path], rpk_mode='none')
    row = next(x for x in payload['channels'] if x['channel_id'] == 2)
    assert row['confidence'] == 'conflict'
    assert row['safe_for_fallback'] is False


def test_verified_census_can_name_configless_ddf_without_common_channel_guess(tmp_path: Path, monkeypatch):
    monkeypatch.setenv('NHRA_VELOCITY_HOME', str(tmp_path / 'home'))
    defs = tmp_path / 'defs'; defs.mkdir()
    for i, extra in enumerate((201, 202, 203)):
        (defs / f'cfg{i}.rcg').write_bytes(_config(2, 'ENGINE RPM') + _channel(extra, f'EXTRA {extra}', 'PSI', 10))
    payload = build_channel_id_census([defs], rpk_mode='none')
    install_census(payload)
    assert lookup_verified_channel(2)['consensus_name'] == 'ENGINE RPM'

    p = tmp_path / 'orphan.ddf'; p.write_bytes(_ddf(2))
    run = load_telemetry(p)
    assert 'ENGINE RPM' in run.native_channels
    assert run.units['ENGINE RPM'] == 'rpm'
    # Corpus knowledge improves the source label but never decides the Common
    # Channel role on the engineer's behalf.
    assert set(run.channel_map) == {'time_s'}
    assert run.native_channels['ENGINE RPM'].metadata['racepak_definition_source'] == 'global_corpus_consensus'
    assert run.metadata['ddf_global_definition_bound_channels'] == 1
