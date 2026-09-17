from __future__ import annotations

from pathlib import Path
import numpy as np

from runlab.importers import load_telemetry
from runlab.racepak_config_profiles import (
    save_profile,
    matching_profile,
    config_path_from_profile,
    exact_binding_record,
    resolve_config_path,
)


def _lp(text: str) -> bytes:
    raw=text.encode('latin1'); assert len(raw)<256
    return bytes([len(raw)])+raw


def _config_channel(storage: str, name: str, desc: str, timer: str) -> bytes:
    return b'\x43\x09\x02\x00'+_lp(storage)+_lp(name)+_lp(desc)+_lp('0.0')+_lp(timer)+b'\x00'*12


def _config_blob(engine_name: str = 'ENGINE RPM') -> bytes:
    a=_config_channel('RPM',engine_name,'ScaledBuffer: (0=>0,1=>1) [(0,12000),%-5.0lf,RPM] _CONNECT4_COMMAND="2"','Timer_2sps')
    b=_config_channel('RPM','DRIVE SHAFT','ScaledBuffer: (0=>0,1=>1) [(0,12000),%-5.0lf,RPM] _CONNECT4_COMMAND="100"','Timer_1sps')
    return b'\x00'*128+a+b+b'\x00'*32


def _descriptor(flag: int, channel_id: int, rate: int, config_rate: int) -> bytes:
    return bytes([0x33,flag])+int(channel_id).to_bytes(4,'little')+int(rate).to_bytes(4,'little')+int(config_rate).to_bytes(4,'little')+b'\x00'*8


def _ddf_blob() -> bytes:
    desc=[_descriptor(0x00,2,2,2),_descriptor(0x00,100,1,1)]
    header=bytearray(14);header[12:14]=len(desc).to_bytes(2,'little')
    vals=np.asarray([1000,1100,100,1200,1300,110],dtype='<i2').tobytes()
    return bytes(header)+b''.join(desc)+vals


def _record(driver='Angie Smith', driver_id='drv-angie', vehicle_id='veh-8'):
    return {
        'driver_id':driver_id,'driver_name':driver,'vehicle_id':vehicle_id,'vehicle_name':'PSM 8',
        'category':'PRO STOCK MOTORCYCLE','car_number':'8',
    }


def test_ddf_accepts_explicit_racepak_config_path(tmp_path: Path):
    ddf=tmp_path/'run.ddf';ddf.write_bytes(_ddf_blob())
    cfg=tmp_path/'Angie.rcg';cfg.write_bytes(_config_blob())
    run=load_telemetry(ddf,racepak_config_path=cfg)
    assert 'ENGINE RPM' in run.native_channels
    assert 'DRIVE SHAFT' in run.native_channels
    assert run.metadata['ddf_config_file']=='Angie.rcg'
    assert run.metadata['ddf_config_sha256']
    assert run.units['ENGINE RPM']=='rpm'


def test_driver_category_profile_is_context_scoped_and_managed(tmp_path: Path, monkeypatch):
    home=tmp_path/'home';monkeypatch.setenv('NHRA_VELOCITY_HOME',str(home))
    cfg=tmp_path/'Angie.rcg';cfg.write_bytes(_config_blob())
    saved=save_profile(_record(),cfg,scope='driver_category')
    managed=Path(config_path_from_profile(saved));assert managed.is_file()
    cfg.unlink()
    matched=matching_profile(_record())
    assert Path(config_path_from_profile(matched)).is_file()
    assert matched['scope']=='driver_category'
    # Same category + logger family is not enough. Different driver must not
    # inherit Angie's DDF definition.
    assert matching_profile(_record(driver='Other Rider',driver_id='drv-other'))=={}


def test_vehicle_profile_wins_over_driver_profile(tmp_path: Path, monkeypatch):
    monkeypatch.setenv('NHRA_VELOCITY_HOME',str(tmp_path/'home'))
    driver_cfg=tmp_path/'driver.rcg';driver_cfg.write_bytes(_config_blob('DRIVER ENGINE'))
    vehicle_cfg=tmp_path/'vehicle.rcg';vehicle_cfg.write_bytes(_config_blob('VEHICLE ENGINE'))
    rec=_record()
    save_profile(rec,driver_cfg,scope='driver_category')
    save_profile(rec,vehicle_cfg,scope='vehicle_category')
    matched=matching_profile(rec)
    assert matched['scope']=='vehicle_category'
    assert matched['config']['filename']=='vehicle.rcg'


def test_exact_data_log_binding_wins_over_context_profile(tmp_path: Path, monkeypatch):
    monkeypatch.setenv('NHRA_VELOCITY_HOME',str(tmp_path/'home'))
    profile_cfg=tmp_path/'profile.rcg';profile_cfg.write_bytes(_config_blob('PROFILE ENGINE'))
    exact_cfg=tmp_path/'exact.rcg';exact_cfg.write_bytes(_config_blob('EXACT ENGINE'))
    rec=_record()
    save_profile(rec,profile_cfg,scope='driver_category')
    exact=exact_binding_record(exact_cfg,source='explicit_exact')
    path,source,_=resolve_config_path(rec,session_settings={'racepak_ddf_config':exact})
    assert source=='exact_data_log'
    assert Path(path).name.endswith('.rcg')
    assert exact['config']['sha256'] in Path(path).name


def test_context_profile_is_used_when_no_exact_binding(tmp_path: Path, monkeypatch):
    monkeypatch.setenv('NHRA_VELOCITY_HOME',str(tmp_path/'home'))
    cfg=tmp_path/'profile.rcg';cfg.write_bytes(_config_blob())
    rec=_record();save_profile(rec,cfg,scope='driver_category')
    path,source,profile=resolve_config_path(rec,session_settings={})
    assert source=='context_profile'
    assert Path(path).is_file()
    assert profile['scope']=='driver_category'


def test_profile_manager_lists_and_deletes_by_persisted_key(tmp_path: Path, monkeypatch):
    from runlab.racepak_config_profiles import list_profiles, delete_profile_key
    monkeypatch.setenv('NHRA_VELOCITY_HOME',str(tmp_path/'home'))
    cfg=tmp_path/'profile.rcg';cfg.write_bytes(_config_blob())
    saved=save_profile(_record(),cfg,scope='driver_category')
    rows=list_profiles()
    assert len(rows)==1
    assert rows[0]['profile_key']==saved['profile_key']
    assert rows[0]['valid'] is True
    assert delete_profile_key(saved['profile_key']) is True
    assert list_profiles()==[]


def test_profile_manager_surfaces_stale_managed_config(tmp_path: Path, monkeypatch):
    from runlab.racepak_config_profiles import list_profiles
    monkeypatch.setenv('NHRA_VELOCITY_HOME',str(tmp_path/'home'))
    cfg=tmp_path/'profile.rcg';cfg.write_bytes(_config_blob())
    saved=save_profile(_record(),cfg,scope='driver_category')
    Path(saved['config']['managed_path']).unlink()
    rows=list_profiles()
    assert len(rows)==1
    assert rows[0]['valid'] is False
