from __future__ import annotations

"""Cross-project channel/display preferences.

Preferences are intentionally separate from telemetry and project files. A
preference can target a canonical engineering role (preferred) or an exact
source-channel name. Project-local trace styling still overrides these values.
"""

from pathlib import Path
from typing import Any, Dict, Optional
import re

from .diagnostics import app_data_root
from .project_io import atomic_write_json, read_project_json
from .models import TelemetryRun
from .importers import CANONICAL_CHANNELS
from .units import CANONICAL_TARGET_UNITS, compatible, normalize_unit

_CACHE_PATH: Optional[Path] = None
_CACHE_MTIME_NS: Optional[int] = None
_CACHE_OBJECT: Optional[dict] = None


def preferences_path() -> Path:
    p=app_data_root()/'preferences.json'; p.parent.mkdir(parents=True,exist_ok=True); return p


def _safe_load(path: Optional[Path]=None) -> dict:
    global _CACHE_PATH, _CACHE_MTIME_NS, _CACHE_OBJECT
    p=(path or preferences_path()).resolve()
    mtime=p.stat().st_mtime_ns if p.exists() else None
    if _CACHE_PATH==p and _CACHE_MTIME_NS==mtime and _CACHE_OBJECT is not None:
        return dict(_CACHE_OBJECT)
    if not p.exists():
        obj={'version':2,'channels':{},'common_channel_mappings':{},'math_templates':{}}
    else:
        try:
            obj=read_project_json(p)
            if not isinstance(obj.get('channels',{}),dict): obj['channels']={}
            if not isinstance(obj.get('common_channel_mappings',{}),dict): obj['common_channel_mappings']={}
            if not isinstance(obj.get('math_templates',{}),dict): obj['math_templates']={}
            obj['version']=max(2,int(obj.get('version',1) or 1))
        except Exception:
            obj={'version':2,'channels':{},'common_channel_mappings':{},'math_templates':{}}
    _CACHE_PATH=p; _CACHE_MTIME_NS=mtime; _CACHE_OBJECT=dict(obj)
    return dict(obj)


def _invalidate_cache():
    global _CACHE_PATH, _CACHE_MTIME_NS, _CACHE_OBJECT
    _CACHE_PATH=None; _CACHE_MTIME_NS=None; _CACHE_OBJECT=None


def canonical_for_channel(run: TelemetryRun, channel: str) -> Optional[str]:
    originals=run.metadata.get('original_channel_map',{}) or {}
    for canonical,source in originals.items():
        if str(source)==str(channel) and canonical in run.channel_map:
            return str(canonical)
    for canonical,mapped in run.channel_map.items():
        if str(mapped)==str(channel): return str(canonical)
    return None


def preference_key(run: TelemetryRun, channel: str) -> str:
    canonical=canonical_for_channel(run,channel)
    if canonical: return f'canonical:{canonical}'
    normalized=re.sub(r'\s+',' ',str(channel).strip().lower())
    return f'source:{normalized}'


def get_channel_preference(run: TelemetryRun, channel: str, *, path: Optional[Path]=None) -> Dict[str,Any]:
    obj=_safe_load(path)
    rec=obj.get('channels',{}).get(preference_key(run,channel),{})
    return dict(rec) if isinstance(rec,dict) else {}


def set_channel_preference(run: TelemetryRun, channel: str, preference: Dict[str,Any], *, path: Optional[Path]=None) -> Path:
    p=path or preferences_path(); obj=_safe_load(p)
    obj.setdefault('channels',{})[preference_key(run,channel)]=dict(preference)
    atomic_write_json(p,obj); _invalidate_cache()
    return p


def clear_channel_preference(run: TelemetryRun, channel: str, *, path: Optional[Path]=None) -> bool:
    p=path or preferences_path(); obj=_safe_load(p); key=preference_key(run,channel)
    if key not in obj.get('channels',{}): return False
    del obj['channels'][key]; atomic_write_json(p,obj); _invalidate_cache(); return True


# ---- Learned common-channel mappings --------------------------------------

def _vendor_key(run_or_vendor) -> str:
    vendor = getattr(run_or_vendor, 'vendor', run_or_vendor)
    text = re.sub(r'\s+', ' ', str(vendor or 'unknown').strip().lower())
    return text or 'unknown'


def _source_key(source: str) -> str:
    return re.sub(r'\s+', ' ', str(source or '').strip().lower())


def remember_common_channel_mapping(
    run: TelemetryRun, source: str, canonical: str, *, path: Optional[Path]=None
) -> Path:
    """Remember one vendor/source-name -> common engineering role mapping.

    Mappings are vendor-scoped on purpose.  A channel called ``RPM`` on one
    logger family must not silently redefine an unrelated channel on another.
    """
    source = str(source or '').strip(); canonical = str(canonical or '').strip()
    if not source:
        raise ValueError('Source channel is required.')
    if canonical not in CANONICAL_CHANNELS:
        raise ValueError(f'Unknown common channel: {canonical!r}')
    p=path or preferences_path(); obj=_safe_load(p)
    vendor=_vendor_key(run); key=_source_key(source)
    obj.setdefault('common_channel_mappings',{}).setdefault(vendor,{})[key]={
        'source':source,'canonical':canonical
    }
    atomic_write_json(p,obj); _invalidate_cache(); return p


def forget_common_channel_mapping(
    run: TelemetryRun, source: str, *, path: Optional[Path]=None
) -> bool:
    p=path or preferences_path(); obj=_safe_load(p); vendor=_vendor_key(run); key=_source_key(source)
    group=obj.get('common_channel_mappings',{}).get(vendor,{})
    if key not in group:return False
    del group[key]
    if not group: obj.get('common_channel_mappings',{}).pop(vendor,None)
    atomic_write_json(p,obj); _invalidate_cache(); return True


def learned_common_channel_overrides(run: TelemetryRun, *, path: Optional[Path]=None) -> Dict[str,str]:
    """Return safe learned canonical->source mappings available in ``run``."""
    obj=_safe_load(path); group=obj.get('common_channel_mappings',{}).get(_vendor_key(run),{})
    if not isinstance(group,dict) or not group:return {}
    # Common-role normalization currently operates on the rectangular data
    # frame. Native-only mixed-rate channels remain visible to the workstation
    # but are not silently promoted into the canonical physics layer.
    names=[]
    for n in run.data.columns:
        text=str(n)
        if not text.startswith('__') and text not in names:names.append(text)
    by_key={_source_key(n):n for n in names}
    out: Dict[str,str]={}
    for source_key,rec in group.items():
        if not isinstance(rec,dict):continue
        source=by_key.get(str(source_key))
        canonical=str(rec.get('canonical','') or '')
        if not source or not canonical:continue
        target=CANONICAL_TARGET_UNITS.get(canonical,'')
        source_unit=normalize_unit(run.units.get(source,''))
        if target and source_unit and not compatible(source_unit,target):
            # A stale preference is never allowed to overrule dimensional safety.
            continue
        out[canonical]=source
    return out


def learned_mapping_for_source(run: TelemetryRun, source: str, *, path: Optional[Path]=None) -> str:
    obj=_safe_load(path); group=obj.get('common_channel_mappings',{}).get(_vendor_key(run),{})
    rec=group.get(_source_key(source),{}) if isinstance(group,dict) else {}
    return str(rec.get('canonical','') or '') if isinstance(rec,dict) else ''


# ---- Reusable calculated-channel templates -------------------------------

_BUILTIN_MATH_TEMPLATES: Dict[str,Dict[str,str]] = {
    'Engine / Driveshaft Ratio': {'expression':'@engine_rpm / @driveshaft_rpm','unit':'ratio'},
    'Engine / Clutch Ratio': {'expression':'@engine_rpm / @clutch_rpm','unit':'ratio'},
    'Speed Smoothed 0.10 s': {'expression':'smooth(@speed_mph, 0.10)','unit':'mph'},
}


def math_channel_templates(*, path: Optional[Path]=None, include_builtin: bool=True) -> Dict[str,Dict[str,str]]:
    obj=_safe_load(path); out={}
    if include_builtin:out.update({k:dict(v) for k,v in _BUILTIN_MATH_TEMPLATES.items()})
    raw=obj.get('math_templates',{})
    if isinstance(raw,dict):
        for name,rec in raw.items():
            if isinstance(rec,dict) and str(rec.get('expression','')).strip():
                out[str(name)]={'expression':str(rec.get('expression','')),'unit':str(rec.get('unit',''))}
    return out


def save_math_channel_template(name: str, expression: str, unit: str='', *, path: Optional[Path]=None) -> Path:
    name=str(name or '').strip(); expression=str(expression or '').strip()
    if not name:raise ValueError('Template name is required.')
    if not expression:raise ValueError('Template expression is required.')
    p=path or preferences_path(); obj=_safe_load(p)
    obj.setdefault('math_templates',{})[name]={'expression':expression,'unit':str(unit or '')}
    atomic_write_json(p,obj); _invalidate_cache(); return p


def delete_math_channel_template(name: str, *, path: Optional[Path]=None) -> bool:
    p=path or preferences_path(); obj=_safe_load(p); raw=obj.get('math_templates',{})
    if not isinstance(raw,dict) or name not in raw:return False
    del raw[name]; atomic_write_json(p,obj); _invalidate_cache(); return True
