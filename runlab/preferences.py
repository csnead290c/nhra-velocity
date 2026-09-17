from __future__ import annotations

"""Cross-project channel/display preferences.

Preferences are intentionally separate from telemetry and project files. A
preference can target a canonical engineering role (preferred) or an exact
source-channel name. Project-local trace styling still overrides these values.
"""

from pathlib import Path
from typing import Any, Dict, Optional
import re
import uuid

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
        obj={'version':4,'channels':{},'common_channel_mappings':{},'common_channel_profiles':{},'math_templates':{},'worksheet_templates':{}}
    else:
        try:
            obj=read_project_json(p)
            if not isinstance(obj.get('channels',{}),dict): obj['channels']={}
            if not isinstance(obj.get('common_channel_mappings',{}),dict): obj['common_channel_mappings']={}
            if not isinstance(obj.get('common_channel_profiles',{}),dict): obj['common_channel_profiles']={}
            if not isinstance(obj.get('math_templates',{}),dict): obj['math_templates']={}
            if not isinstance(obj.get('worksheet_templates',{}),dict): obj['worksheet_templates']={}
            obj['version']=max(4,int(obj.get('version',1) or 1))
        except Exception:
            obj={'version':4,'channels':{},'common_channel_mappings':{},'common_channel_profiles':{},'math_templates':{},'worksheet_templates':{}}
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


# ---- Context-scoped common-channel mapping profiles ------------------------

# A source-channel name is not a universal engineering truth.  The same logger
# may expose several plausible RPM/speed channels, and which one Velocity should
# treat as the canonical engineering signal can legitimately differ between
# drivers, vehicles, categories, or logger configurations.  Learned mappings are
# therefore stored only in explicit, narrow context profiles.  Run/data-log
# specific overrides remain higher authority than every reusable profile.

_COMMON_PROFILE_SCOPES = ("vehicle_category", "driver_category")


def _vendor_key(run_or_vendor) -> str:
    vendor = getattr(run_or_vendor, 'vendor', run_or_vendor)
    text = re.sub(r'\s+', ' ', str(vendor or 'unknown').strip().lower())
    return text or 'unknown'


def _source_key(source: str) -> str:
    return re.sub(r'\s+', ' ', str(source or '').strip().lower())


def _context_token(value: Any) -> str:
    return re.sub(r'\s+', ' ', str(value or '').strip().lower())


def common_channel_profile_context(run: TelemetryRun) -> Dict[str,str]:
    """Return the narrow identity context available for mapping profiles.

    Stable catalog ids win.  Human-readable names are retained as a fallback so
    imported/scratch runs can still describe their context, but Velocity never
    invents a driver/category profile when that context is absent.
    """
    md = run.metadata if isinstance(run.metadata, dict) else {}
    return {
        'vendor': _vendor_key(run),
        'category': _context_token(md.get('catalog_category') or md.get('official_category') or md.get('category')),
        'driver_id': _context_token(md.get('catalog_driver_id')),
        'driver_name': _context_token(md.get('catalog_driver_name') or md.get('driver_name')),
        'vehicle_id': _context_token(md.get('catalog_vehicle_id')),
        'vehicle_name': _context_token(md.get('catalog_vehicle_name') or md.get('vehicle_name')),
        'car_number': _context_token(md.get('catalog_car_number') or md.get('car_number')),
    }


def common_channel_profile_scope_options(run: TelemetryRun) -> list[tuple[str,str]]:
    """Return safe reusable mapping scopes supported by the active run.

    Deliberately no vendor-global option is offered.  A broad logger-vendor rule
    is exactly the kind of "smart" behavior that can choose the wrong physical
    signal on another car or team.
    """
    c = common_channel_profile_context(run)
    out: list[tuple[str,str]] = []
    if c['category'] and (c['driver_id'] or c['driver_name']):
        driver = str(run.metadata.get('catalog_driver_name') or run.metadata.get('driver_name') or 'this driver')
        category = str(run.metadata.get('catalog_category') or run.metadata.get('official_category') or run.metadata.get('category') or 'this category')
        out.append(('driver_category', f'Driver + Category + Logger — {driver} / {category} / {run.vendor or "logger"}'))
    if c['category'] and (c['vehicle_id'] or c['car_number'] or c['vehicle_name']):
        vehicle = str(run.metadata.get('catalog_vehicle_name') or run.metadata.get('vehicle_name') or run.metadata.get('catalog_car_number') or run.metadata.get('car_number') or 'this vehicle')
        category = str(run.metadata.get('catalog_category') or run.metadata.get('official_category') or run.metadata.get('category') or 'this category')
        out.append(('vehicle_category', f'Vehicle + Category + Logger — {vehicle} / {category} / {run.vendor or "logger"}'))
    return out


def _profile_identity(run: TelemetryRun, scope: str) -> tuple[str, Dict[str,str]]:
    scope = str(scope or '').strip()
    if scope not in _COMMON_PROFILE_SCOPES:
        raise ValueError(f'Unsupported Common Channel profile scope: {scope!r}')
    c = common_channel_profile_context(run)
    if not c['category']:
        raise ValueError('A reusable Common Channel profile requires an authoritative category. Use this data log only.')
    if scope == 'driver_category':
        identity = c['driver_id'] or c['driver_name']
        if not identity:
            raise ValueError('Driver + Category mapping requires an authoritative driver. Use this data log only.')
        key = f"driver_category|{c['vendor']}|{c['category']}|{identity}"
    else:
        identity = c['vehicle_id'] or c['car_number'] or c['vehicle_name']
        if not identity:
            raise ValueError('Vehicle + Category mapping requires an authoritative vehicle/car identity. Use this data log only.')
        key = f"vehicle_category|{c['vendor']}|{c['category']}|{identity}"
    return key, c


def _profile_label(run: TelemetryRun, scope: str) -> str:
    options = dict(common_channel_profile_scope_options(run))
    return options.get(scope, scope.replace('_',' ').title())


def save_common_channel_profile(
    run: TelemetryRun,
    mappings: Dict[str,str],
    *,
    scope: str = 'driver_category',
    path: Optional[Path] = None,
) -> Path:
    """Save one coherent Common Channel profile for an explicit run context.

    The profile is intentionally all-or-none at application time.  If a future
    data log does not contain every mapped source with compatible dimensions,
    Velocity applies none of the profile rather than silently mixing a partial
    old profile with new importer guesses.
    """
    key, context = _profile_identity(run, scope)
    clean: Dict[str,str] = {}
    for canonical, source in dict(mappings or {}).items():
        canonical = str(canonical or '').strip(); source = str(source or '').strip()
        if not source:
            continue
        if canonical not in CANONICAL_CHANNELS:
            raise ValueError(f'Unknown common channel: {canonical!r}')
        if source not in run.data.columns:
            raise ValueError(f'Profile source channel is not present in this data log: {source!r}')
        target = CANONICAL_TARGET_UNITS.get(canonical,'')
        source_unit = normalize_unit(run.units.get(source,''))
        if target and source_unit and not compatible(source_unit,target):
            raise ValueError(f'{source} is dimensionally incompatible with {canonical}.')
        clean[canonical] = source
    if not clean:
        raise ValueError('A reusable Common Channel profile needs at least one assigned channel.')
    p = path or preferences_path(); obj = _safe_load(p)
    obj.setdefault('common_channel_profiles',{})[key] = {
        'scope': scope,
        'context': context,
        'label': _profile_label(run, scope),
        'mappings': clean,
    }
    obj['version'] = max(4, int(obj.get('version',1) or 1))
    atomic_write_json(p,obj); _invalidate_cache(); return p


def delete_common_channel_profile(run: TelemetryRun, scope: str, *, path: Optional[Path]=None) -> bool:
    key, _ = _profile_identity(run, scope)
    p=path or preferences_path(); obj=_safe_load(p); profiles=obj.get('common_channel_profiles',{})
    if not isinstance(profiles,dict) or key not in profiles:return False
    del profiles[key]; atomic_write_json(p,obj); _invalidate_cache(); return True


def matching_common_channel_profile(run: TelemetryRun, *, path: Optional[Path]=None) -> Dict[str,Any]:
    """Return the single most-specific exact reusable profile for ``run``."""
    obj=_safe_load(path); profiles=obj.get('common_channel_profiles',{})
    if not isinstance(profiles,dict):return {}
    # Vehicle is narrower than driver/category when both exist.
    for scope in ('vehicle_category','driver_category'):
        try:key,_=_profile_identity(run,scope)
        except ValueError:continue
        rec=profiles.get(key,{})
        if isinstance(rec,dict) and isinstance(rec.get('mappings'),dict):
            out=dict(rec);out['profile_key']=key;return out
    return {}


def remember_common_channel_mapping(
    run: TelemetryRun, source: str, canonical: str, *, scope: str = 'driver_category', path: Optional[Path]=None
) -> Path:
    """Merge one assignment into an explicit context-scoped mapping profile."""
    key, _ = _profile_identity(run, scope)
    obj=_safe_load(path); rec=obj.get('common_channel_profiles',{}).get(key,{}) if isinstance(obj.get('common_channel_profiles',{}),dict) else {}
    mappings=dict(rec.get('mappings',{})) if isinstance(rec,dict) and isinstance(rec.get('mappings'),dict) else {}
    mappings[str(canonical or '').strip()] = str(source or '').strip()
    return save_common_channel_profile(run,mappings,scope=scope,path=path)


def forget_common_channel_mapping(
    run: TelemetryRun, source: str, *, scope: str = 'driver_category', path: Optional[Path]=None
) -> bool:
    key, _ = _profile_identity(run, scope)
    p=path or preferences_path();obj=_safe_load(p);profiles=obj.get('common_channel_profiles',{})
    if not isinstance(profiles,dict):return False
    rec=profiles.get(key,{})
    if not isinstance(rec,dict) or not isinstance(rec.get('mappings'),dict):return False
    mappings=dict(rec['mappings']);source_key=_source_key(source)
    changed=False
    for canonical,mapped in list(mappings.items()):
        if _source_key(mapped)==source_key:
            del mappings[canonical];changed=True
    if not changed:return False
    if mappings:
        rec=dict(rec);rec['mappings']=mappings;profiles[key]=rec
    else:
        profiles.pop(key,None)
    atomic_write_json(p,obj);_invalidate_cache();return True


def learned_common_channel_overrides(run: TelemetryRun, *, path: Optional[Path]=None) -> Dict[str,str]:
    """Return one exact, all-or-none context profile available in ``run``.

    This function intentionally ignores the old vendor-global v0.38-dev.15
    ``common_channel_mappings`` records.  Those broad mappings are retained in
    preferences for audit/migration but are never auto-applied.
    """
    rec=matching_common_channel_profile(run,path=path)
    mappings=dict(rec.get('mappings',{})) if isinstance(rec.get('mappings',{}),dict) else {}
    if not mappings:return {}
    names={_source_key(str(n)):str(n) for n in run.data.columns if not str(n).startswith('__')}
    resolved: Dict[str,str]={}
    for canonical, stored_source in mappings.items():
        source=names.get(_source_key(stored_source))
        if not source:
            return {}  # all-or-none safety: configuration changed
        target=CANONICAL_TARGET_UNITS.get(canonical,'')
        source_unit=normalize_unit(run.units.get(source,''))
        if target and source_unit and not compatible(source_unit,target):
            return {}
        resolved[str(canonical)]=source
    return resolved


def learned_mapping_for_source(run: TelemetryRun, source: str, *, path: Optional[Path]=None) -> str:
    rec=matching_common_channel_profile(run,path=path)
    mappings=rec.get('mappings',{}) if isinstance(rec,dict) else {}
    if not isinstance(mappings,dict):return ''
    needle=_source_key(source)
    for canonical,mapped in mappings.items():
        if _source_key(mapped)==needle:return str(canonical)
    return ''


def learned_common_channel_profile_scope(run: TelemetryRun, *, path: Optional[Path]=None) -> str:
    rec=matching_common_channel_profile(run,path=path)
    return str(rec.get('scope') or '') if rec else ''


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


# ---- Portable worksheet templates ----------------------------------------

def _worksheet_template_context(run: Optional[TelemetryRun]) -> Dict[str,str]:
    if run is None:
        return {'category':'','vehicle_id':'','vehicle_name':'','car_number':''}
    md=run.metadata if isinstance(run.metadata,dict) else {}
    return {
        'category': _context_token(md.get('catalog_category') or md.get('official_category') or md.get('category')),
        'vehicle_id': _context_token(md.get('catalog_vehicle_id')),
        'vehicle_name': _context_token(md.get('catalog_vehicle_name') or md.get('vehicle_name')),
        'car_number': _context_token(md.get('catalog_car_number') or md.get('car_number')),
    }


def worksheet_template_scope_options(run: Optional[TelemetryRun]) -> list[tuple[str,str]]:
    out=[('global','All vehicles / categories')]
    c=_worksheet_template_context(run)
    if c['category']:
        out.append(('category',f"Category — {c['category']}"))
        if c['vehicle_id'] or c['car_number'] or c['vehicle_name']:
            vehicle=c['vehicle_name'] or (f"#{c['car_number']}" if c['car_number'] else c['vehicle_id'])
            out.append(('vehicle_category',f"Vehicle + Category — {vehicle} / {c['category']}"))
    return out


def _worksheet_template_matches(rec: Dict[str,Any], run: Optional[TelemetryRun]) -> bool:
    scope=str(rec.get('scope') or 'global')
    if scope=='global': return True
    c=_worksheet_template_context(run); saved=rec.get('context',{}) if isinstance(rec.get('context',{}),dict) else {}
    if not c['category'] or _context_token(saved.get('category'))!=c['category']:
        return False
    if scope=='category': return True
    if scope!='vehicle_category': return False
    saved_identity=_context_token(saved.get('vehicle_id') or saved.get('car_number') or saved.get('vehicle_name'))
    current_identity=c['vehicle_id'] or c['car_number'] or c['vehicle_name']
    return bool(saved_identity and current_identity and saved_identity==current_identity)


def worksheet_templates(*, run: Optional[TelemetryRun]=None, compatible_only: bool=False, path: Optional[Path]=None) -> list[Dict[str,Any]]:
    obj=_safe_load(path); raw=obj.get('worksheet_templates',{})
    if not isinstance(raw,dict): return []
    out=[]
    for key,rec in raw.items():
        if not isinstance(rec,dict): continue
        row=dict(rec); row['id']=str(key)
        row['compatible']=_worksheet_template_matches(row,run)
        if compatible_only and not row['compatible']: continue
        out.append(row)
    rank={'vehicle_category':0,'category':1,'global':2}
    out.sort(key=lambda r:(rank.get(str(r.get('scope')),9),str(r.get('name','')).casefold()))
    return out


def save_worksheet_template(name: str, payload: Dict[str,Any], *, run: Optional[TelemetryRun]=None, scope: str='global', path: Optional[Path]=None) -> str:
    name=str(name or '').strip(); scope=str(scope or 'global')
    if not name: raise ValueError('Worksheet template name is required.')
    if scope not in ('global','category','vehicle_category'): raise ValueError(f'Unsupported worksheet template scope: {scope!r}')
    context=_worksheet_template_context(run)
    if scope in ('category','vehicle_category') and not context['category']:
        raise ValueError('A category-scoped worksheet template requires authoritative category context.')
    if scope=='vehicle_category' and not (context['vehicle_id'] or context['car_number'] or context['vehicle_name']):
        raise ValueError('Vehicle + Category worksheet template requires authoritative vehicle identity.')
    p=path or preferences_path(); obj=_safe_load(p); raw=obj.setdefault('worksheet_templates',{})
    existing=''
    for key,rec in raw.items():
        if not isinstance(rec,dict): continue
        if str(rec.get('name','')).casefold()!=name.casefold() or str(rec.get('scope','global'))!=scope: continue
        saved=rec.get('context',{}) if isinstance(rec.get('context',{}),dict) else {}
        if scope=='global' or saved==context:
            existing=str(key); break
    ident=existing or str(uuid.uuid4())
    raw[ident]={'name':name,'scope':scope,'context':context,'payload':dict(payload or {})}
    obj['version']=max(4,int(obj.get('version',1) or 1)); atomic_write_json(p,obj); _invalidate_cache(); return ident


def delete_worksheet_template(template_id: str, *, path: Optional[Path]=None) -> bool:
    p=path or preferences_path(); obj=_safe_load(p); raw=obj.get('worksheet_templates',{})
    key=str(template_id or '')
    if not isinstance(raw,dict) or key not in raw: return False
    del raw[key]; atomic_write_json(p,obj); _invalidate_cache(); return True
