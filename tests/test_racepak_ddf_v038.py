from __future__ import annotations

from pathlib import Path

import numpy as np

from runlab.import_registry import spec_for_path
from runlab.importers import load_telemetry
from runlab.racepak_ddf import parse_ddf_structure


def _descriptor(flag: int, channel_id: int, rate: int, config_rate: int) -> bytes:
    return (
        bytes([0x33, flag])
        + int(channel_id).to_bytes(4, 'little')
        + int(rate).to_bytes(4, 'little')
        + int(config_rate).to_bytes(4, 'little')
        + b'\x00' * 8
    )


def _make_ddf() -> bytes:
    # Two recorded channels plus one descriptor intentionally disabled from the
    # payload. Values are laid out as one-second frames in descriptor order.
    desc = [
        _descriptor(0x00, 2, 2, 2),      # integer, 2 Hz
        _descriptor(0xFE, 100, 1, 3),    # /100 fixed point, 1 Hz
        _descriptor(0xFF, 200, 5, 0),    # configured but not recorded
    ]
    header = bytearray(14)
    header[12:14] = len(desc).to_bytes(2, 'little')
    # second 0: channel 2 -> 100,101 ; channel 100 -> -1.23
    # second 1: channel 2 -> 102,103 ; channel 100 -> 4.56
    values = np.asarray([100, 101, -123, 102, 103, 456], dtype='<i2').tobytes()
    return bytes(header) + b''.join(desc) + values


def test_ddf_structure_and_fixed_point_frame_decode(tmp_path: Path, monkeypatch):
    monkeypatch.setenv('NHRA_VELOCITY_HOME', str(tmp_path / 'home'))
    p = tmp_path / 'run.DDF'
    p.write_bytes(_make_ddf())

    spec = spec_for_path(p)
    assert spec is not None and spec.key == 'racepak_ddf' and spec.status == 'direct'

    structure = parse_ddf_structure(p)
    assert len(structure.descriptors) == 3
    assert [d.channel_id for d in structure.recorded_descriptors] == [2, 100]
    assert structure.frame_words == 3
    assert structure.full_frames == 2
    assert structure.partial_frame_words == 0

    run = load_telemetry(p)
    assert run.vendor == 'RacePak'
    assert run.metadata['import_decoder'] == 'RacePak DDF'
    assert run.metadata['ddf_recorded_channel_count'] == 2
    assert set(run.native_channels) == {'RacePak Channel 2', 'RacePak Channel 100'}
    assert np.allclose(run.native_channels['RacePak Channel 2'].values, [100, 101, 102, 103])
    assert np.allclose(run.native_channels['RacePak Channel 100'].values, [-1.23, 4.56])
    # Without an RCG/RPK definition, the importer does not invent engine/DS roles.
    assert set(run.channel_map) == {'time_s'}
    assert any('did not guess channel names' in x for x in run.metadata['data_warnings'])


def test_ddf_partial_final_frame_is_preserved(tmp_path: Path, monkeypatch):
    monkeypatch.setenv('NHRA_VELOCITY_HOME', str(tmp_path / 'home'))
    blob = _make_ddf()
    # Remove the last 16-bit sample: second frame still has both channel-2
    # samples but no channel-100 sample.
    p = tmp_path / 'partial.ddf'
    p.write_bytes(blob[:-2])
    structure = parse_ddf_structure(p)
    assert structure.full_frames == 1
    assert structure.partial_frame_words == 2
    run = load_telemetry(p)
    assert np.allclose(run.native_channels['RacePak Channel 2'].values, [100, 101, 102, 103])
    assert np.allclose(run.native_channels['RacePak Channel 100'].values, [-1.23])


def test_ddf_unknown_scale_flag_fails_closed(tmp_path: Path, monkeypatch):
    monkeypatch.setenv('NHRA_VELOCITY_HOME', str(tmp_path / 'home'))
    header = bytearray(14)
    header[12:14] = (1).to_bytes(2, 'little')
    p = tmp_path / 'unknown.ddf'
    p.write_bytes(bytes(header) + _descriptor(0xFB, 2, 100, 100) + b'\x00\x00')
    try:
        parse_ddf_structure(p)
    except ValueError as exc:
        assert 'unsupported fixed-point flag' in str(exc)
    else:
        raise AssertionError('unknown DDF fixed-point flag should fail closed')
