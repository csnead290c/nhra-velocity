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
        obj={'version':1,'channels':{}}
    else:
        try:
            obj=read_project_json(p)
            if not isinstance(obj.get('channels',{}),dict): obj['channels']={}
        except Exception:
            obj={'version':1,'channels':{}}
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
