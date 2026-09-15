from __future__ import annotations

"""Run-centric domain records used by the local NHRA technical data catalog.

The desktop workstation deliberately separates *evidence and engineering state*
from workbook/layout state.  These lightweight records are UI-independent and
map cleanly to the authoritative Tech Services mirror/API.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4


def new_id(prefix: str = "") -> str:
    token = uuid4().hex
    return f"{prefix}_{token}" if prefix else token


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class EventRecord:
    id: str
    name: str
    season: Optional[int] = None
    event_code: str = ""
    start_date: str = ""
    end_date: str = ""
    track_name: str = ""
    track_id: str = ""
    location: str = ""
    remote_id: str = ""
    sync_state: str = "local"


@dataclass
class DriverRecord:
    id: str
    name: str
    nhra_member_id: str = ""
    remote_id: str = ""


@dataclass
class VehicleRecord:
    id: str
    name: str
    category: str = ""
    car_number: str = ""
    make: str = ""
    model: str = ""
    year: Optional[int] = None
    remote_id: str = ""


@dataclass
class RunRecord:
    id: str
    event_id: Optional[str] = None
    entry_id: Optional[str] = None
    driver_id: Optional[str] = None
    vehicle_id: Optional[str] = None
    run_key: str = ""
    round: str = ""
    run_number: str = ""
    lane: str = ""
    category: str = ""
    car_number: str = ""
    run_datetime: str = ""
    notes: str = ""
    remote_id: str = ""
    sync_state: str = "local"


@dataclass
class AssetRecord:
    id: str
    run_id: str
    asset_type: str
    filename: str
    remote_id: str = ""
    revision: str = ""
    source_kind: str = "local_dev"  # tech_services | local_dev
    original_path: str = ""
    local_path: str = ""
    sha256: str = ""
    size_bytes: int = 0
    mime_type: str = ""
    vendor: str = ""
    storage_mode: str = "external"  # external | managed | remote
    sync_state: str = "local"
    remote_uri: str = ""  # stable non-capability reference only; never persist signed URLs
    uploaded_at: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TimeMappingRecord:
    id: str
    run_id: str
    asset_id: str
    scale: float = 1.0
    offset_s: float = 0.0
    method: str = "manual"
    confidence: Optional[float] = None
    uncertainty_s: Optional[float] = None
    anchors: List[Dict[str, float]] = field(default_factory=list)


@dataclass
class ModelSnapshotRecord:
    id: str
    name: str
    run_id: Optional[str] = None
    analysis_case_id: Optional[str] = None
    model_type: str = "vehicle_performance"
    model_version: str = ""
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    quality: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)


@dataclass
class AnalysisCaseRecord:
    id: str
    title: str
    case_type: str = "engineering"
    status: str = "open"
    summary: str = ""
    primary_run_id: Optional[str] = None
    remote_id: str = ""
    revision: str = ""
    sync_state: str = "local"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass
class AnalysisCaseRunRecord:
    case_id: str
    run_id: str
    role: str = "reference"
    sort_order: int = 0
    notes: str = ""
    time_scale: float = 1.0
    time_offset_s: float = 0.0
    alignment_method: str = "run_time"
    alignment_confidence: Optional[float] = None
    alignment_uncertainty_s: Optional[float] = None
    alignment_anchors: List[Dict[str, float]] = field(default_factory=list)
    added_at: str = field(default_factory=utc_now)


@dataclass
class AnalysisCaseEvidenceRecord:
    id: str
    case_id: str
    evidence_type: str = "other"
    asset_id: Optional[str] = None
    label: str = ""
    filename: str = ""
    sha256: str = ""
    size_bytes: int = 0
    mime_type: str = ""
    storage_mode: str = "external"
    source_kind: str = "local_case"
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass
class AnalysisCaseMarkerRecord:
    id: str
    case_id: str
    label: str
    kind: str = "marker"
    time_domain: str = "case"
    source_start_s: float = 0.0
    source_end_s: Optional[float] = None
    source_run_id: Optional[str] = None
    source_asset_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass
class IncidentCaseRecord:
    """Deprecated compatibility shape for pre-v0.18 callers."""
    id: str
    run_id: str
    title: str
    status: str = "open"
    summary: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


def record_dict(record: Any) -> Dict[str, Any]:
    return asdict(record)
