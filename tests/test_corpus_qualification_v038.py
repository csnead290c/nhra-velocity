from pathlib import Path

from runlab.qualification import extension_inventory, expand_candidates, qualify_corpus


def test_corpus_scan_skips_support_assets_and_unrelated_files(tmp_path):
    (tmp_path / 'map.ftm').write_bytes(b'x')
    (tmp_path / 'setup.hefi').write_bytes(b'x')
    (tmp_path / 'notes.json').write_text('{}')
    log = tmp_path / 'run.csv'
    log.write_text('Time,RPM,TPS\n0,1000,0\n0.1,5000,100\n0.2,7000,100\n')
    candidates = expand_candidates([tmp_path], recursive=True)
    assert candidates == [log.resolve()]
    assert expand_candidates([tmp_path / 'map.ftm']) == []


def test_extension_inventory_surfaces_unrecognized_and_support_families(tmp_path):
    (tmp_path / 'run.csv').write_text('Time,RPM\n0,1000\n1,2000\n')
    (tmp_path / 'setup.hefi').write_bytes(b'x')
    (tmp_path / 'mystery.xyz123').write_bytes(b'x')
    rows = extension_inventory([tmp_path], recursive=True)
    by_ext = {row['extension']: row for row in rows}
    assert by_ext['.csv']['format_status'] == 'interchange'
    assert by_ext['.hefi']['format_status'] == 'support'
    assert by_ext['.hefi']['data_log_candidate'] is False
    assert by_ext['.xyz123']['format_status'] == 'unrecognized'


def test_qualification_adds_integrity_flags_and_sampling(tmp_path):
    for index in range(5):
        p = tmp_path / f'run{index}.csv'
        p.write_text('Time,RPM,Flat\n0,1000,5\n0.1,2000,5\n0.2,3000,5\n')
    rows = qualify_corpus([tmp_path], recursive=True, sample_per_format=2)
    assert len(rows) == 2
    assert all(row.status == 'pass' for row in rows)
    assert all(row.constant_numeric_channels >= 1 for row in rows)
    assert all('constant' not in row.integrity_flags for row in rows)


def test_cloud_unavailable_source_is_not_misreported_as_decoder_failure(tmp_path, monkeypatch):
    from runlab import qualification
    p = tmp_path / 'cloud.ld'
    p.write_bytes(b'placeholder')
    monkeypatch.setattr(
        qualification,
        '_source_probe',
        lambda path: {'state': 'cloud-unavailable', 'error': '[WinError 388] The cloud sync provider failed to perform the operation', 'size': 123, 'head': b''},
    )
    rec = qualification.qualify_file(p)
    assert rec.status == 'source-unavailable'
    assert rec.source_state == 'cloud-unavailable'
    assert 'cloud sync provider' in rec.error.lower()
    assert rec.numeric_channels == 0


def test_maxxecu_zip_named_nonzip_is_reported_as_format_variant(tmp_path):
    from runlab.qualification import qualify_file
    p = tmp_path / 'run.MaxxECU-Zip-log'
    p.write_bytes(b'MAXX-NATIVE-VARIANT\x00\x01\x02\x03')
    rec = qualify_file(p, compute_sha=False)
    assert rec.status == 'format-variant'
    assert rec.source_state == 'local-readable'
    assert 'does not contain a standard zip signature' in rec.error.lower()
    assert rec.header_hex
