from __future__ import annotations

"""Portable worksheet/display templates.

Templates capture display intent rather than logger-vendor channel spelling.  A
channel that is currently assigned to a Common Channel is persisted as that
canonical engineering role; otherwise the exact source name is retained and
must exist verbatim when the template is applied.

This deliberately never performs fuzzy channel-name matching.  Missing inputs
are reported to the caller so the desktop can fail visibly instead of quietly
plotting the wrong signal.
"""

from copy import deepcopy
from typing import Any, Dict, Iterable, Tuple

from .models import TelemetryRun
from .preferences import canonical_for_channel


_CHANNEL_FIELDS = {"channel", "x", "y", "z", "engine"}


def visible_channels(run: TelemetryRun) -> list[str]:
    names: list[str] = []
    for raw in list(run.native_channels) + [str(x) for x in run.data.columns]:
        name = str(raw)
        if name.startswith("__") or name in names:
            continue
        names.append(name)
    return names


def channel_reference(run: TelemetryRun, channel: str) -> Dict[str, str]:
    """Return an explicit portable reference for one visible source channel."""
    name = str(channel or "")
    canonical = canonical_for_channel(run, name)
    if canonical:
        return {"kind": "common", "key": canonical, "label": name}
    return {"kind": "source", "key": name, "label": name}


def resolve_channel_reference(run: TelemetryRun, reference: Any) -> str:
    """Resolve a template reference without fuzzy guessing.

    Common Channel references resolve only through the run's explicit
    ``channel_map`` / ``original_channel_map``.  Source references require an
    exact source-channel name.
    """
    if isinstance(reference, str):
        # Backward-compatible exact source reference for hand-authored records.
        return reference if reference in visible_channels(run) else ""
    if not isinstance(reference, dict):
        return ""
    kind = str(reference.get("kind") or "")
    key = str(reference.get("key") or "")
    if not key:
        return ""
    if kind == "source":
        return key if key in visible_channels(run) else ""
    if kind != "common":
        return ""
    originals = run.metadata.get("original_channel_map", {}) if isinstance(run.metadata, dict) else {}
    source = str(originals.get(key) or "") if isinstance(originals, dict) else ""
    if source and source in visible_channels(run):
        return source
    mapped = str(run.channel_map.get(key) or "")
    if mapped and mapped in visible_channels(run):
        return mapped
    return ""


def _portable_channel_value(run: TelemetryRun, value: Any) -> Any:
    if isinstance(value, str) and value in visible_channels(run):
        return {"__velocity_channel_ref__": channel_reference(run, value)}
    return deepcopy(value)


def _resolved_channel_value(run: TelemetryRun, value: Any, missing: list[str]) -> Any:
    if isinstance(value, dict) and "__velocity_channel_ref__" in value:
        ref = value.get("__velocity_channel_ref__")
        resolved = resolve_channel_reference(run, ref)
        if not resolved:
            if isinstance(ref, dict):
                missing.append(str(ref.get("label") or ref.get("key") or "channel"))
            else:
                missing.append(str(ref))
            return ""
        return resolved
    return deepcopy(value)


def capture_display_specs(run: TelemetryRun, specs: Iterable[dict]) -> list[dict]:
    """Convert worksheet display specs into vendor-portable JSON data."""
    result: list[dict] = []
    for raw_spec in specs:
        spec = deepcopy(dict(raw_spec or {}))
        cfg = dict(spec.get("config") or {})
        dtype = str(spec.get("type") or "")
        if dtype == "waveform":
            refs = [channel_reference(run, c) for c in cfg.get("channels", []) if str(c)]
            cfg["channel_refs"] = refs
            cfg.pop("channels", None)
            portable_styles: Dict[str, dict] = {}
            for channel, style in dict(cfg.get("channel_styles") or {}).items():
                ref = channel_reference(run, str(channel))
                token = f"{ref['kind']}:{ref['key']}"
                portable_styles[token] = {"ref": ref, "style": deepcopy(dict(style or {}))}
            cfg["channel_style_refs"] = portable_styles
            cfg.pop("channel_styles", None)
        for field in _CHANNEL_FIELDS:
            if field in cfg:
                cfg[field] = _portable_channel_value(run, cfg[field])
        spec["config"] = cfg
        result.append(spec)
    return result


def resolve_display_specs(run: TelemetryRun, specs: Iterable[dict]) -> Tuple[list[dict], list[str]]:
    """Resolve portable specs for ``run`` and return (specs, missing labels)."""
    result: list[dict] = []
    missing: list[str] = []
    for raw_spec in specs:
        spec = deepcopy(dict(raw_spec or {}))
        cfg = dict(spec.get("config") or {})
        dtype = str(spec.get("type") or "")
        if dtype == "waveform" and "channel_refs" in cfg:
            channels: list[str] = []
            for ref in list(cfg.get("channel_refs") or []):
                resolved = resolve_channel_reference(run, ref)
                if resolved and resolved not in channels:
                    channels.append(resolved)
                elif not resolved:
                    missing.append(str(ref.get("label") or ref.get("key") or "channel") if isinstance(ref, dict) else str(ref))
            cfg["channels"] = channels
            cfg.pop("channel_refs", None)
            styles: Dict[str, dict] = {}
            for rec in dict(cfg.get("channel_style_refs") or {}).values():
                if not isinstance(rec, dict):
                    continue
                ref = rec.get("ref")
                resolved = resolve_channel_reference(run, ref)
                if resolved:
                    styles[resolved] = deepcopy(dict(rec.get("style") or {}))
            cfg["channel_styles"] = styles
            cfg.pop("channel_style_refs", None)
        for field in _CHANNEL_FIELDS:
            if field in cfg:
                cfg[field] = _resolved_channel_value(run, cfg[field], missing)
        spec["config"] = cfg
        result.append(spec)
    # Stable, de-duplicated warning order.
    unique: list[str] = []
    for item in missing:
        if item and item not in unique:
            unique.append(item)
    return result, unique
