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
