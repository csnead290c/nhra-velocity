from pathlib import Path

import pytest

from runlab.import_registry import (
    FORMAT_SPECS,
    OPENABLE_STATUSES,
    openable_specs,
    qt_file_dialog_filter,
    recognized_unavailable_specs,
    spec_for_path,
    support_specs,
    telemetry_candidate,
)
from runlab.importers import load_telemetry


def test_openable_picker_is_derived_from_import_registry():
    text = qt_file_dialog_filter()
    first_group = text.split(';;', 1)[0]
    for spec in FORMAT_SPECS:
        if spec.status not in OPENABLE_STATUSES:
            continue
        for ext in spec.extensions:
            assert f'*{ext}' in first_group, (spec.key, ext, first_group)


def test_maxxecu_zip_log_is_visible_without_all_files_workaround():
    text = qt_file_dialog_filter()
    first_group = text.split(';;', 1)[0]
    assert '*.maxxecu-zip-log' in first_group
    assert '*.maxxecu-log' in first_group
    assert '*.maxxlog' in first_group


def test_compound_native_suffixes_are_explicit_not_generic_bin():
    text = qt_file_dialog_filter()
    first_group = text.split(';;', 1)[0]
    assert '*.rpk.bin' in first_group
    assert '*.ld.bin' in first_group
    assert '*.bin' not in first_group.split()


def test_pending_and_bridge_formats_have_explicit_recognized_group():
    text = qt_file_dialog_filter()
    groups = text.split(';;')
    recognized = next(group for group in groups if group.startswith('Recognized data logs'))
    for spec in recognized_unavailable_specs():
        for ext in spec.extensions:
            assert f'*{ext}' in recognized


def test_support_assets_are_separate_from_data_log_candidates():
    text = qt_file_dialog_filter()
    groups = text.split(';;')
    support = next(group for group in groups if group.startswith('Calibration / support files'))
    for spec in support_specs():
        for ext in spec.extensions:
            assert f'*{ext}' in support
            assert f'*{ext}' not in groups[0]
    assert spec_for_path('map.ftm').status == 'support'
    assert spec_for_path('config.hefi').status == 'support'
    assert spec_for_path('session.ldx').status == 'support'
    assert spec_for_path('grid.mff').status == 'support'
    assert spec_for_path('logger.rcg').status == 'support'
    assert not telemetry_candidate('map.ftm')
    assert not telemetry_candidate('config.hefi')
    assert not telemetry_candidate('session.ldx')
    assert not telemetry_candidate('grid.mff')
    assert not telemetry_candidate('logger.rcg')


def test_box_power_grid_daq_family_is_not_mislabeled_as_aem_only():
    spec = spec_for_path('7730_9201_0000.daq')
    assert spec is not None
    assert spec.key == 'daq_binary'
    assert 'Power Grid' in spec.message
    assert spec_for_path('run.itlog').key == 'aem'
    assert spec_for_path('7730_10357_0007.dqi').key == 'msd_power_grid_dqi'


def test_support_assets_fail_closed_with_clear_message(tmp_path):
    hefi = tmp_path / 'setup.hefi'
    hefi.write_bytes(b'not-a-log')
    with pytest.raises(ValueError, match='configuration files rather than data logs'):
        load_telemetry(hefi)
    ftm = tmp_path / 'map.ftm'
    ftm.write_bytes(b'not-a-log')
    with pytest.raises(ValueError, match='map/calibration files rather than data logs'):
        load_telemetry(ftm)


def test_desktop_data_log_dialogs_use_registry_filter():
    source = Path('desktop.py').read_text(encoding='utf-8')
    assert source.count('qt_file_dialog_filter()') >= 2
    assert 'Supported data logs (*.ld *.rpk *.ddf' not in source
