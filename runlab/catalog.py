from __future__ import annotations

"""SQLite-backed run-centric catalog for NHRA Velocity.

The catalog is the local mirror of authoritative Tech Services Events/Runs/Assets
plus local analysis state such as time mappings, engineering values and model
snapshots. Workbooks remain separate and only remember how an engineer chose
to view data.
"""

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional
from datetime import datetime, timezone
import json
import mimetypes
import os
import sqlite3

from .diagnostics import app_data_root
from .domain import new_id, utc_now
from .local_store import LocalObjectStore, sha256_file

from .product_manifest import CATALOG_SCHEMA_VERSION

SCHEMA_VERSION = CATALOG_SCHEMA_VERSION
UNASSIGNED_EVENT_CODE = "LOCAL-UNASSIGNED"


def default_catalog_path() -> Path:
    path = app_data_root() / "catalog" / "nhra-velocity.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, separators=(",", ":"), ensure_ascii=False)


def _unjson(value: Any, fallback: Any = None) -> Any:
    if value in (None, ""):
        return {} if fallback is None else fallback
    try:
        return json.loads(value)
    except Exception:
        return {} if fallback is None else fallback


class LocalCatalog:
    def __init__(self, path: str | os.PathLike[str] | None = None, *, object_store: LocalObjectStore | None = None):
        self.path = Path(path) if path is not None else default_catalog_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.object_store = object_store or LocalObjectStore()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self.transaction() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS catalog_meta(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events(
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    season INTEGER,
                    event_code TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    track_name TEXT,
                    track_id TEXT,
                    location TEXT,
                    remote_id TEXT,
                    sync_state TEXT NOT NULL DEFAULT 'local',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_events_code ON events(event_code) WHERE event_code IS NOT NULL AND event_code <> '';

                CREATE TABLE IF NOT EXISTS drivers(
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    nhra_member_id TEXT,
                    remote_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS vehicles(
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    category TEXT,
                    car_number TEXT,
                    make TEXT,
                    model TEXT,
                    year INTEGER,
                    remote_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS entries(
                    id TEXT PRIMARY KEY,
                    event_id TEXT REFERENCES events(id) ON DELETE CASCADE,
                    driver_id TEXT REFERENCES drivers(id) ON DELETE SET NULL,
                    vehicle_id TEXT REFERENCES vehicles(id) ON DELETE SET NULL,
                    category TEXT,
                    car_number TEXT,
                    remote_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs(
                    id TEXT PRIMARY KEY,
                    event_id TEXT REFERENCES events(id) ON DELETE SET NULL,
                    entry_id TEXT REFERENCES entries(id) ON DELETE SET NULL,
                    driver_id TEXT REFERENCES drivers(id) ON DELETE SET NULL,
                    vehicle_id TEXT REFERENCES vehicles(id) ON DELETE SET NULL,
                    run_key TEXT,
                    round TEXT,
                    run_number TEXT,
                    lane TEXT,
                    category TEXT,
                    car_number TEXT,
                    run_datetime TEXT,
                    official_timing_json TEXT NOT NULL DEFAULT '{}',
                    weather_json TEXT NOT NULL DEFAULT '{}',
                    timing_provenance TEXT NOT NULL DEFAULT 'unknown',
                    weather_provenance TEXT NOT NULL DEFAULT 'unknown',
                    official_source_json TEXT NOT NULL DEFAULT '{}',
                    notes TEXT,
                    remote_id TEXT,
                    sync_state TEXT NOT NULL DEFAULT 'local',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_key ON runs(run_key) WHERE run_key IS NOT NULL AND run_key <> '';
                CREATE INDEX IF NOT EXISTS idx_runs_event ON runs(event_id);
                CREATE INDEX IF NOT EXISTS idx_runs_driver ON runs(driver_id);
                CREATE INDEX IF NOT EXISTS idx_runs_datetime ON runs(run_datetime);

                CREATE TABLE IF NOT EXISTS assets(
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    remote_id TEXT,
                    revision TEXT,
                    source_kind TEXT NOT NULL DEFAULT 'local_dev',
                    asset_type TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    original_path TEXT,
                    local_path TEXT,
                    sha256 TEXT,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    mime_type TEXT,
                    vendor TEXT,
                    storage_mode TEXT NOT NULL DEFAULT 'external',
                    sync_state TEXT NOT NULL DEFAULT 'local',
                    remote_uri TEXT,
                    uploaded_at TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_assets_run_hash ON assets(run_id, sha256) WHERE sha256 IS NOT NULL AND sha256 <> '';
                CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_remote_id ON assets(remote_id) WHERE remote_id IS NOT NULL AND remote_id <> '';
                CREATE INDEX IF NOT EXISTS idx_assets_hash ON assets(sha256);
                CREATE INDEX IF NOT EXISTS idx_assets_run ON assets(run_id);

                CREATE TABLE IF NOT EXISTS telemetry_sessions(
                    id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    display_name TEXT,
                    vendor TEXT,
                    channel_summary_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_tel_asset ON telemetry_sessions(asset_id);

                CREATE TABLE IF NOT EXISTS time_mappings(
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
                    scale REAL NOT NULL DEFAULT 1.0,
                    offset_s REAL NOT NULL DEFAULT 0.0,
                    method TEXT,
                    confidence REAL,
                    uncertainty_s REAL,
                    anchors_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_time_mapping_asset ON time_mappings(asset_id);

                CREATE TABLE IF NOT EXISTS engineering_values(
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    unit TEXT,
                    provenance TEXT,
                    confidence REAL,
                    lower_value REAL,
                    upper_value REAL,
                    method TEXT,
                    notes TEXT,
                    model_snapshot_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_eng_run_key ON engineering_values(run_id, key);
                CREATE INDEX IF NOT EXISTS idx_eng_key ON engineering_values(key);

                CREATE TABLE IF NOT EXISTS run_reports(
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    source_asset_id TEXT REFERENCES assets(id) ON DELETE SET NULL,
                    report_type TEXT NOT NULL,
                    report_version INTEGER NOT NULL DEFAULT 1,
                    profile TEXT,
                    label TEXT,
                    fingerprint_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    generated_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_run_reports_fingerprint ON run_reports(run_id,report_type,fingerprint_sha256);
                CREATE INDEX IF NOT EXISTS idx_run_reports_run_type ON run_reports(run_id,report_type,created_at);

                CREATE TABLE IF NOT EXISTS analysis_cases(
                    id TEXT PRIMARY KEY,
                    case_type TEXT NOT NULL DEFAULT 'engineering',
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    summary TEXT,
                    primary_run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
                    remote_id TEXT,
                    revision TEXT,
                    sync_state TEXT NOT NULL DEFAULT 'local',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_cases_type ON analysis_cases(case_type,status,updated_at);
                CREATE INDEX IF NOT EXISTS idx_analysis_cases_primary_run ON analysis_cases(primary_run_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_analysis_cases_remote_id ON analysis_cases(remote_id) WHERE remote_id IS NOT NULL AND remote_id <> '';

                CREATE TABLE IF NOT EXISTS analysis_case_runs(
                    case_id TEXT NOT NULL REFERENCES analysis_cases(id) ON DELETE CASCADE,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    role TEXT NOT NULL DEFAULT 'reference',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    notes TEXT,
                    time_scale REAL NOT NULL DEFAULT 1.0,
                    time_offset_s REAL NOT NULL DEFAULT 0.0,
                    alignment_method TEXT NOT NULL DEFAULT 'run_time',
                    alignment_confidence REAL,
                    alignment_uncertainty_s REAL,
                    alignment_anchors_json TEXT NOT NULL DEFAULT '[]',
                    alignment_updated_at TEXT,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY(case_id,run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_case_runs_run ON analysis_case_runs(run_id,case_id);

                CREATE TABLE IF NOT EXISTS analysis_case_markers(
                    id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL REFERENCES analysis_cases(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL DEFAULT 'marker',
                    label TEXT,
                    time_domain TEXT NOT NULL DEFAULT 'case',
                    source_run_id TEXT REFERENCES runs(id) ON DELETE CASCADE,
                    source_asset_id TEXT REFERENCES assets(id) ON DELETE CASCADE,
                    source_start_s REAL NOT NULL,
                    source_end_s REAL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK(time_domain IN ('case','run','asset'))
                );
                CREATE INDEX IF NOT EXISTS idx_case_markers_case ON analysis_case_markers(case_id,created_at);

                CREATE TABLE IF NOT EXISTS analysis_case_evidence(
                    id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL REFERENCES analysis_cases(id) ON DELETE CASCADE,
                    asset_id TEXT REFERENCES assets(id) ON DELETE CASCADE,
                    evidence_type TEXT NOT NULL DEFAULT 'other',
                    label TEXT,
                    filename TEXT,
                    original_path TEXT,
                    local_path TEXT,
                    sha256 TEXT,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    mime_type TEXT,
                    source_kind TEXT NOT NULL DEFAULT 'local_case',
                    storage_mode TEXT NOT NULL DEFAULT 'external',
                    remote_id TEXT,
                    revision TEXT,
                    remote_uri TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK(asset_id IS NOT NULL OR COALESCE(filename,'') <> '')
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_case_evidence_asset ON analysis_case_evidence(case_id,asset_id) WHERE asset_id IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_case_evidence_case ON analysis_case_evidence(case_id,created_at);
                CREATE INDEX IF NOT EXISTS idx_case_evidence_hash ON analysis_case_evidence(sha256) WHERE sha256 IS NOT NULL AND sha256 <> '';

                CREATE TABLE IF NOT EXISTS model_snapshots(
                    id TEXT PRIMARY KEY,
                    run_id TEXT REFERENCES runs(id) ON DELETE CASCADE,
                    analysis_case_id TEXT REFERENCES analysis_cases(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    model_type TEXT NOT NULL,
                    model_version TEXT,
                    inputs_json TEXT NOT NULL DEFAULT '{}',
                    outputs_json TEXT NOT NULL DEFAULT '{}',
                    quality_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    CHECK(run_id IS NOT NULL OR analysis_case_id IS NOT NULL)
                );
                CREATE INDEX IF NOT EXISTS idx_model_run ON model_snapshots(run_id, created_at);

                CREATE TABLE IF NOT EXISTS annotations(
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    asset_id TEXT REFERENCES assets(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    label TEXT,
                    start_s REAL,
                    end_s REAL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_annotations_run ON annotations(run_id);

                CREATE TABLE IF NOT EXISTS incident_cases(
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    summary TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_incident_run ON incident_cases(run_id);

                CREATE TABLE IF NOT EXISTS sync_journal(
                    id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    state TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sync_state ON sync_journal(state, created_at);

                CREATE TABLE IF NOT EXISTS remote_entities(
                    provider TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    remote_id TEXT NOT NULL,
                    local_id TEXT NOT NULL,
                    revision TEXT,
                    payload_hash TEXT,
                    last_synced_at TEXT NOT NULL,
                    PRIMARY KEY(provider, entity_type, remote_id)
                );
                CREATE INDEX IF NOT EXISTS idx_remote_entities_local ON remote_entities(entity_type,local_id);

                CREATE TABLE IF NOT EXISTS sync_cursors(
                    provider TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    cursor TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(provider, scope)
                );

                """
            )
            # v0.14 schema migration. Existing v0.13 catalogs are upgraded in-place;
            # no user data is rewritten. SQLite only permits ADD COLUMN for this
            # lightweight migration, which is exactly what we need here.
            run_columns = {str(row[1]) for row in c.execute("PRAGMA table_info(runs)").fetchall()}
            if "timing_provenance" not in run_columns:
                c.execute("ALTER TABLE runs ADD COLUMN timing_provenance TEXT NOT NULL DEFAULT 'unknown'")
            if "weather_provenance" not in run_columns:
                c.execute("ALTER TABLE runs ADD COLUMN weather_provenance TEXT NOT NULL DEFAULT 'unknown'")
            if "official_source_json" not in run_columns:
                c.execute("ALTER TABLE runs ADD COLUMN official_source_json TEXT NOT NULL DEFAULT '{}'")
            asset_columns = {str(row[1]) for row in c.execute("PRAGMA table_info(assets)").fetchall()}
            if "remote_id" not in asset_columns:
                c.execute("ALTER TABLE assets ADD COLUMN remote_id TEXT")
            if "revision" not in asset_columns:
                c.execute("ALTER TABLE assets ADD COLUMN revision TEXT")
            if "source_kind" not in asset_columns:
                c.execute("ALTER TABLE assets ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'local_dev'")
            if "uploaded_at" not in asset_columns:
                c.execute("ALTER TABLE assets ADD COLUMN uploaded_at TEXT")
            c.execute("DROP INDEX IF EXISTS idx_assets_run_hash")
            c.execute("CREATE INDEX IF NOT EXISTS idx_assets_run_hash ON assets(run_id,sha256) WHERE sha256 IS NOT NULL AND sha256 <> ''")
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_remote_id ON assets(remote_id) WHERE remote_id IS NOT NULL AND remote_id <> ''")

            # v0.18 schema migration: AnalysisCase becomes the reusable multi-run
            # engineering workspace. Existing v0.17 IncidentCase rows are copied
            # forward without deleting the legacy table, and old run-only model
            # snapshots are rebuilt into the nullable run/case ownership shape.
            model_columns = {str(row[1]) for row in c.execute("PRAGMA table_info(model_snapshots)").fetchall()}
            if "analysis_case_id" not in model_columns:
                c.execute("DROP INDEX IF EXISTS idx_model_run")
                c.executescript(
                    """
                    CREATE TABLE model_snapshots_v6(
                        id TEXT PRIMARY KEY,
                        run_id TEXT REFERENCES runs(id) ON DELETE CASCADE,
                        analysis_case_id TEXT REFERENCES analysis_cases(id) ON DELETE CASCADE,
                        name TEXT NOT NULL,
                        model_type TEXT NOT NULL,
                        model_version TEXT,
                        inputs_json TEXT NOT NULL DEFAULT '{}',
                        outputs_json TEXT NOT NULL DEFAULT '{}',
                        quality_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        CHECK(run_id IS NOT NULL OR analysis_case_id IS NOT NULL)
                    );
                    INSERT INTO model_snapshots_v6(id,run_id,analysis_case_id,name,model_type,model_version,inputs_json,outputs_json,quality_json,created_at)
                    SELECT id,run_id,NULL,name,model_type,model_version,inputs_json,outputs_json,quality_json,created_at FROM model_snapshots;
                    DROP TABLE model_snapshots;
                    ALTER TABLE model_snapshots_v6 RENAME TO model_snapshots;
                    CREATE INDEX idx_model_run ON model_snapshots(run_id,created_at);
                    CREATE INDEX idx_model_case ON model_snapshots(analysis_case_id,created_at);
                    """
                )

            c.execute("CREATE INDEX IF NOT EXISTS idx_model_case ON model_snapshots(analysis_case_id,created_at)")

            # v0.19 schema migration: each member Run can be mapped onto a
            # shared AnalysisCase time axis. Asset→Run mappings remain separate.
            case_run_columns = {str(row[1]) for row in c.execute("PRAGMA table_info(analysis_case_runs)").fetchall()}
            for col,decl in (
                ("time_scale","REAL NOT NULL DEFAULT 1.0"),
                ("time_offset_s","REAL NOT NULL DEFAULT 0.0"),
                ("alignment_method","TEXT NOT NULL DEFAULT 'run_time'"),
                ("alignment_confidence","REAL"),
                ("alignment_uncertainty_s","REAL"),
                ("alignment_anchors_json","TEXT NOT NULL DEFAULT '[]'"),
                ("alignment_updated_at","TEXT"),
            ):
                if col not in case_run_columns:
                    c.execute(f"ALTER TABLE analysis_case_runs ADD COLUMN {col} {decl}")

            legacy_incidents = c.execute("SELECT id,run_id,title,status,summary,created_at,updated_at FROM incident_cases").fetchall()
            for row in legacy_incidents:
                c.execute(
                    "INSERT OR IGNORE INTO analysis_cases(id,case_type,title,status,summary,primary_run_id,sync_state,created_at,updated_at) VALUES(?,?,?,?,?,?,'local',?,?)",
                    (row[0],'incident',row[2],row[3],row[4],row[1],row[5],row[6]),
                )
                c.execute(
                    "INSERT OR IGNORE INTO analysis_case_runs(case_id,run_id,role,sort_order,notes,added_at) VALUES(?,?,'primary',0,'Migrated from v0.17 IncidentCase',?)",
                    (row[0],row[1],row[5]),
                )

            c.execute("INSERT OR REPLACE INTO catalog_meta(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))

    @property
    def schema_version(self) -> int:
        with self._connect() as c:
            row = c.execute("SELECT value FROM catalog_meta WHERE key='schema_version'").fetchone()
            return int(row[0]) if row else 0

    def ensure_unassigned_event(self) -> str:
        with self.transaction() as c:
            row = c.execute("SELECT id FROM events WHERE event_code=?", (UNASSIGNED_EVENT_CODE,)).fetchone()
            if row:
                return str(row[0])
            now = utc_now(); event_id = new_id("evt")
            c.execute(
                "INSERT INTO events(id,name,event_code,sync_state,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (event_id, "Unassigned Local Imports", UNASSIGNED_EVENT_CODE, "local", now, now),
            )
            return event_id

    def create_event(self, name: str, *, season: int | None = None, event_code: str = "", start_date: str = "", end_date: str = "", track_name: str = "", track_id: str = "", location: str = "", remote_id: str = "", sync_state: str = "local") -> str:
        now = utc_now(); event_id = new_id("evt")
        with self.transaction() as c:
            c.execute(
                "INSERT INTO events(id,name,season,event_code,start_date,end_date,track_name,track_id,location,remote_id,sync_state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (event_id, name, season, event_code, start_date, end_date, track_name, track_id, location, remote_id, sync_state, now, now),
            )
        return event_id

    def find_event_by_code(self, event_code: str) -> Dict[str, Any] | None:
        with self._connect() as c:
            row=c.execute("SELECT * FROM events WHERE event_code=?",(str(event_code or "").strip(),)).fetchone()
        return dict(row) if row else None

    def find_event(self, *, event_code: str = "", remote_id: str = "") -> Dict[str, Any] | None:
        code=str(event_code or "").strip(); remote=str(remote_id or "").strip()
        with self._connect() as c:
            row=None
            if remote:
                row=c.execute("SELECT * FROM events WHERE remote_id=? ORDER BY created_at LIMIT 1",(remote,)).fetchone()
            if row is None and code:
                row=c.execute("SELECT * FROM events WHERE event_code=? ORDER BY created_at LIMIT 1",(code,)).fetchone()
        return dict(row) if row else None

    def upsert_event(self, name: str, *, season: int | None = None, event_code: str = "", start_date: str = "", end_date: str = "", track_name: str = "", track_id: str = "", location: str = "", remote_id: str = "", sync_state: str = "local") -> str:
        code=str(event_code or "").strip()
        existing=self.find_event(event_code=code, remote_id=remote_id) if (code or remote_id) else None
        if existing is None:
            return self.create_event(name,season=season,event_code=code,start_date=start_date,end_date=end_date,track_name=track_name,track_id=track_id,location=location,remote_id=remote_id,sync_state=sync_state)
        fields={"name":name,"season":season,"start_date":start_date,"end_date":end_date,"track_name":track_name,"track_id":track_id,"location":location,"remote_id":remote_id,"sync_state":sync_state}
        sets=[];vals=[]
        for key,value in fields.items():
            if value not in (None, ""):
                sets.append(f"{key}=?");vals.append(value)
        if sets:
            sets.append("updated_at=?");vals.append(utc_now());vals.append(existing["id"])
            with self.transaction() as c:c.execute(f"UPDATE events SET {','.join(sets)} WHERE id=?",vals)
        return str(existing["id"])

    def list_drivers(self) -> List[Dict[str, Any]]:
        with self._connect() as c:rows=c.execute("SELECT * FROM drivers ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def create_driver(self, name: str, *, nhra_member_id: str = "", remote_id: str = "") -> str:
        now=utc_now(); driver_id=new_id("drv")
        with self.transaction() as c:
            c.execute("INSERT INTO drivers(id,name,nhra_member_id,remote_id,created_at,updated_at) VALUES(?,?,?,?,?,?)",(driver_id,name,nhra_member_id,remote_id,now,now))
        return driver_id

    def find_or_create_driver(self, name: str, *, nhra_member_id: str = "", remote_id: str = "") -> str:
        clean=str(name or "").strip()
        if not clean: raise ValueError("Driver name is required")
        with self._connect() as c:
            row=c.execute("SELECT id,remote_id FROM drivers WHERE lower(name)=lower(?) ORDER BY created_at LIMIT 1",(clean,)).fetchone()
        if row:
            if remote_id and not str(row[1] or ""):
                with self.transaction() as c:c.execute("UPDATE drivers SET remote_id=?,updated_at=? WHERE id=?",(remote_id,utc_now(),row[0]))
            return str(row[0])
        return self.create_driver(clean,nhra_member_id=nhra_member_id,remote_id=remote_id)

    def create_vehicle(self, name: str, *, category: str = "", car_number: str = "", make: str = "", model: str = "", year: int | None = None, remote_id: str = "") -> str:
        now=utc_now(); vehicle_id=new_id("veh")
        with self.transaction() as c:
            c.execute("INSERT INTO vehicles(id,name,category,car_number,make,model,year,remote_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(vehicle_id,name,category,car_number,make,model,year,remote_id,now,now))
        return vehicle_id

    def find_or_create_vehicle(self, *, name: str = "", category: str = "", car_number: str = "", make: str = "", model: str = "", remote_id: str = "") -> str:
        label=str(name or "").strip() or (f"{category} #{car_number}".strip() if category or car_number else "Vehicle")
        with self._connect() as c:
            row=c.execute("SELECT id,remote_id FROM vehicles WHERE lower(name)=lower(?) AND COALESCE(category,'')=? AND COALESCE(car_number,'')=? ORDER BY created_at LIMIT 1",(label,category,car_number)).fetchone()
        if row:
            if remote_id and not str(row[1] or ""):
                with self.transaction() as c:c.execute("UPDATE vehicles SET remote_id=?,updated_at=? WHERE id=?",(remote_id,utc_now(),row[0]))
            return str(row[0])
        return self.create_vehicle(label,category=category,car_number=car_number,make=make,model=model,remote_id=remote_id)

    def create_entry(self, event_id: str, *, driver_id: str | None = None, vehicle_id: str | None = None, category: str = "", car_number: str = "", remote_id: str = "") -> str:
        now=utc_now();entry_id=new_id("ent")
        with self.transaction() as c:
            c.execute("INSERT INTO entries(id,event_id,driver_id,vehicle_id,category,car_number,remote_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(entry_id,event_id,driver_id,vehicle_id,category,car_number,remote_id,now,now))
        return entry_id

    def list_entries(self, *, event_id: str | None = None) -> List[Dict[str, Any]]:
        sql="SELECT * FROM entries";args=[]
        if event_id:
            sql+=" WHERE event_id=?";args.append(event_id)
        sql+=" ORDER BY created_at"
        with self._connect() as c:rows=c.execute(sql,args).fetchall()
        return [dict(r) for r in rows]

    def find_or_create_entry(self, event_id: str, *, driver_id: str | None = None, vehicle_id: str | None = None, category: str = "", car_number: str = "", remote_id: str = "") -> str:
        remote=str(remote_id or "").strip()
        with self._connect() as c:
            row=None
            if remote:
                row=c.execute("SELECT id FROM entries WHERE remote_id=? ORDER BY created_at LIMIT 1",(remote,)).fetchone()
            if row is None:
                row=c.execute("""SELECT id,remote_id FROM entries WHERE event_id=? AND COALESCE(driver_id,'')=COALESCE(?, '') AND COALESCE(vehicle_id,'')=COALESCE(?, '') AND COALESCE(category,'')=? AND COALESCE(car_number,'')=? ORDER BY created_at LIMIT 1""",(event_id,driver_id,vehicle_id,category,car_number)).fetchone()
        if row:
            if remote and len(row)>1 and not str(row[1] or ""):
                with self.transaction() as c:c.execute("UPDATE entries SET remote_id=?,updated_at=? WHERE id=?",(remote,utc_now(),row[0]))
            return str(row[0])
        return self.create_entry(event_id,driver_id=driver_id,vehicle_id=vehicle_id,category=category,car_number=car_number,remote_id=remote)

    def create_run(self, *, event_id: str | None = None, entry_id: str | None = None, driver_id: str | None = None, vehicle_id: str | None = None, run_key: str = "", round: str = "", run_number: str = "", lane: str = "", category: str = "", car_number: str = "", run_datetime: str = "", timing: Mapping[str, Any] | None = None, weather: Mapping[str, Any] | None = None, timing_provenance: str = "unknown", weather_provenance: str = "unknown", source: Mapping[str, Any] | None = None, notes: str = "", remote_id: str = "", sync_state: str = "local") -> str:
        now=utc_now(); run_id=new_id("run")
        event_id = event_id or self.ensure_unassigned_event()
        with self.transaction() as c:
            c.execute(
                "INSERT INTO runs(id,event_id,entry_id,driver_id,vehicle_id,run_key,round,run_number,lane,category,car_number,run_datetime,official_timing_json,weather_json,timing_provenance,weather_provenance,official_source_json,notes,remote_id,sync_state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id,event_id,entry_id,driver_id,vehicle_id,run_key,round,run_number,lane,category,car_number,run_datetime,_json(dict(timing or {})),_json(dict(weather or {})),timing_provenance,weather_provenance,_json(dict(source or {})),notes,remote_id,sync_state,now,now),
            )
        return run_id

    def upsert_run(self, *, run_key: str, event_id: str | None = None, entry_id: str | None = None, driver_id: str | None = None, vehicle_id: str | None = None, round: str = "", run_number: str = "", lane: str = "", category: str = "", car_number: str = "", run_datetime: str = "", timing: Mapping[str, Any] | None = None, weather: Mapping[str, Any] | None = None, timing_provenance: str = "unknown", weather_provenance: str = "unknown", source: Mapping[str, Any] | None = None, notes: str | None = None, remote_id: str = "", sync_state: str = "local") -> tuple[str, bool]:
        """Create or update a stable run identity. Returns ``(run_id, created)``.

        Official imports use this so repeatedly downloading/importing the same
        event is idempotent rather than producing duplicate runs.
        """
        clean_key=str(run_key or "").strip()
        if not clean_key:
            raise ValueError("run_key is required for upsert_run")
        with self._connect() as c:
            row=c.execute("SELECT id FROM runs WHERE run_key=?",(clean_key,)).fetchone()
        if not row:
            return self.create_run(event_id=event_id,entry_id=entry_id,driver_id=driver_id,vehicle_id=vehicle_id,run_key=clean_key,round=round,run_number=run_number,lane=lane,category=category,car_number=car_number,run_datetime=run_datetime,timing=timing,weather=weather,timing_provenance=timing_provenance,weather_provenance=weather_provenance,source=source,notes=notes or "",remote_id=remote_id,sync_state=sync_state), True
        run_id=str(row[0]); now=utc_now()
        fields={
            "event_id":event_id,"entry_id":entry_id,"driver_id":driver_id,"vehicle_id":vehicle_id,
            "round":round,"run_number":run_number,"lane":lane,"category":category,"car_number":car_number,
            "run_datetime":run_datetime,"remote_id":remote_id,"sync_state":sync_state,
        }
        sets=[];vals=[]
        for key,value in fields.items():
            if value not in (None, ""):
                sets.append(f"{key}=?");vals.append(value)
        if timing is not None:
            sets.extend(["official_timing_json=?","timing_provenance=?"]);vals.extend([_json(dict(timing)),timing_provenance])
        if weather is not None:
            sets.extend(["weather_json=?","weather_provenance=?"]);vals.extend([_json(dict(weather)),weather_provenance])
        if source is not None:
            sets.append("official_source_json=?");vals.append(_json(dict(source)))
        if notes is not None:
            sets.append("notes=?");vals.append(str(notes))
        if sets:
            sets.append("updated_at=?");vals.append(now);vals.append(run_id)
            with self.transaction() as c:c.execute(f"UPDATE runs SET {','.join(sets)} WHERE id=?",vals)
        return run_id, False

    def _file_datetime(self, path: Path) -> str:
        try:
            return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
        except Exception:
            return ""

    def register_asset(self, run_id: str, path: str | os.PathLike[str], *, asset_type: str, vendor: str = "", metadata: Mapping[str, Any] | None = None, managed: bool = False, sync_state: str = "local") -> str:
        source = Path(path).expanduser().resolve()
        digest, size = sha256_file(source)
        with self._connect() as c:
            row = c.execute("SELECT id FROM assets WHERE run_id=? AND sha256=?", (run_id, digest)).fetchone()
            if row:
                return str(row[0])
        if managed:
            stored = self.object_store.ingest(source)
            local_path = str(stored.path); storage_mode = "managed"
        else:
            local_path = str(source); storage_mode = "external"
        mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        now=utc_now(); asset_id=new_id("ast")
        with self.transaction() as c:
            c.execute(
                "INSERT INTO assets(id,run_id,source_kind,asset_type,filename,original_path,local_path,sha256,size_bytes,mime_type,vendor,storage_mode,sync_state,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (asset_id,run_id,"local_dev",asset_type,source.name,str(source),local_path,digest,size,mime,vendor,storage_mode,sync_state,_json(dict(metadata or {})),now,now),
            )
        return asset_id

    def register_telemetry_file(self, path: str | os.PathLike[str], *, run_id: str | None = None, vendor: str = "", display_name: str = "", channel_summary: Mapping[str, Any] | None = None, metadata: Mapping[str, Any] | None = None, managed: bool = False, time_offset_s: float | None = None, time_method: str = "logger") -> tuple[str, str, str]:
        source=Path(path).expanduser().resolve(); digest,_=sha256_file(source)
        # A repeated import should resolve to the existing catalog run rather than
        # generating a new synthetic run every time the same evidence is opened.
        if run_id is None:
            with self._connect() as c:
                row=c.execute("SELECT run_id,id FROM assets WHERE sha256=? AND asset_type='telemetry' ORDER BY created_at LIMIT 1",(digest,)).fetchone()
                if row:
                    asset_id=str(row[1])
                    tel=c.execute("SELECT id FROM telemetry_sessions WHERE asset_id=?",(asset_id,)).fetchone()
                    return str(row[0]), asset_id, str(tel[0]) if tel else ""
            run_id=self.create_run(run_key=f"local:{digest[:20]}",run_datetime=self._file_datetime(source),notes=f"Imported from {source.name}")
        asset_id=self.register_asset(run_id,source,asset_type="telemetry",vendor=vendor,metadata=metadata,managed=managed)
        now=utc_now()
        with self.transaction() as c:
            row=c.execute("SELECT id FROM telemetry_sessions WHERE asset_id=?",(asset_id,)).fetchone()
            if row: session_id=str(row[0])
            else:
                session_id=new_id("tel")
                c.execute("INSERT INTO telemetry_sessions(id,asset_id,run_id,display_name,vendor,channel_summary_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",(session_id,asset_id,run_id,display_name or source.stem,vendor,_json(dict(channel_summary or {})),now,now))
            existing=c.execute("SELECT id FROM time_mappings WHERE asset_id=?",(asset_id,)).fetchone()
            if not existing:
                c.execute("INSERT INTO time_mappings(id,run_id,asset_id,scale,offset_s,method,anchors_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(new_id("tm"),run_id,asset_id,1.0,float(time_offset_s or 0.0),time_method,"[]",now,now))
        return run_id,asset_id,session_id

    def ensure_telemetry_session(self, asset_id: str, *, display_name: str = "", vendor: str = "", channel_summary: Mapping[str, Any] | None = None, time_offset_s: float = 0.0, time_method: str = "provisional identity") -> str:
        asset=self.get_asset(asset_id)
        if asset is None: raise KeyError(asset_id)
        run_id=str(asset['run_id']);now=utc_now()
        with self.transaction() as c:
            row=c.execute("SELECT id FROM telemetry_sessions WHERE asset_id=?",(asset_id,)).fetchone()
            if row:
                session_id=str(row[0])
                c.execute("UPDATE telemetry_sessions SET display_name=?,vendor=?,channel_summary_json=?,updated_at=? WHERE id=?",(display_name or asset.get('filename') or '',vendor or asset.get('vendor') or '',_json(dict(channel_summary or {})),now,session_id))
            else:
                session_id=new_id('tel')
                c.execute("INSERT INTO telemetry_sessions(id,asset_id,run_id,display_name,vendor,channel_summary_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",(session_id,asset_id,run_id,display_name or asset.get('filename') or '',vendor or asset.get('vendor') or '',_json(dict(channel_summary or {})),now,now))
            mapping=c.execute("SELECT id FROM time_mappings WHERE asset_id=?",(asset_id,)).fetchone()
            if not mapping:
                c.execute("INSERT INTO time_mappings(id,run_id,asset_id,scale,offset_s,method,anchors_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(new_id('tm'),run_id,asset_id,1.0,float(time_offset_s),time_method,'[]',now,now))
        return session_id

    def update_time_mapping(self, asset_id: str, *, scale: float, offset_s: float, method: str, confidence: float | None = None, uncertainty_s: float | None = None, anchors: Iterable[Mapping[str, float]] = ()) -> None:
        now=utc_now()
        with self.transaction() as c:
            asset=c.execute("SELECT run_id FROM assets WHERE id=?",(asset_id,)).fetchone()
            if not asset: raise KeyError(f"Unknown asset {asset_id}")
            row=c.execute("SELECT id FROM time_mappings WHERE asset_id=?",(asset_id,)).fetchone()
            if row:
                c.execute("UPDATE time_mappings SET scale=?,offset_s=?,method=?,confidence=?,uncertainty_s=?,anchors_json=?,updated_at=? WHERE id=?",(float(scale),float(offset_s),method,confidence,uncertainty_s,_json(list(anchors)),now,row[0]))
            else:
                c.execute("INSERT INTO time_mappings(id,run_id,asset_id,scale,offset_s,method,confidence,uncertainty_s,anchors_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(new_id("tm"),asset[0],asset_id,float(scale),float(offset_s),method,confidence,uncertainty_s,_json(list(anchors)),now,now))

    def set_run_conditions(self, run_id: str, *, timing: Mapping[str, Any] | None = None, weather: Mapping[str, Any] | None = None, notes: str | None = None, timing_provenance: str | None = None, weather_provenance: str | None = None, source: Mapping[str, Any] | None = None, overwrite_official: bool = False) -> None:
        with self._connect() as c:
            current=c.execute("SELECT timing_provenance,weather_provenance FROM runs WHERE id=?",(run_id,)).fetchone()
        if not current:
            raise KeyError(f"Unknown run {run_id}")
        sets=[]; vals=[]
        if timing is not None:
            incoming=str(timing_provenance or "unknown")
            if overwrite_official or str(current[0] or "") != "official" or incoming == "official":
                sets.extend(["official_timing_json=?","timing_provenance=?"]);vals.extend([_json(dict(timing)),incoming])
        if weather is not None:
            incoming=str(weather_provenance or "unknown")
            if overwrite_official or str(current[1] or "") != "official" or incoming == "official":
                sets.extend(["weather_json=?","weather_provenance=?"]);vals.extend([_json(dict(weather)),incoming])
        if source is not None:
            sets.append("official_source_json=?");vals.append(_json(dict(source)))
        if notes is not None: sets.append("notes=?"); vals.append(str(notes))
        if not sets:return
        sets.append("updated_at=?");vals.append(utc_now());vals.append(run_id)
        with self.transaction() as c:c.execute(f"UPDATE runs SET {','.join(sets)} WHERE id=?",vals)

    def set_engineering_value(self, run_id: str, key: str, value: Any, *, unit: str = "", provenance: str = "user", confidence: float | None = None, lower: float | None = None, upper: float | None = None, method: str = "", notes: str = "", model_snapshot_id: str | None = None) -> str:
        rec_id=new_id("eng")
        with self.transaction() as c:
            c.execute("INSERT INTO engineering_values(id,run_id,key,value_json,unit,provenance,confidence,lower_value,upper_value,method,notes,model_snapshot_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(rec_id,run_id,key,_json(value),unit,provenance,confidence,lower,upper,method,notes,model_snapshot_id,utc_now()))
        return rec_id

    def list_engineering_values(self, run_id: str, *, latest_only: bool = True) -> List[Dict[str, Any]]:
        """Return engineering inputs/derived values attached to one canonical Run.

        The catalog is append-only for engineering values so provenance history is
        retained.  ``latest_only`` gives the ordinary Run Workspace view without
        discarding the older records from the database.
        """
        with self._connect() as c:
            rows=c.execute("SELECT * FROM engineering_values WHERE run_id=? ORDER BY created_at DESC",(run_id,)).fetchall()
        out=[];seen=set()
        for r in rows:
            d=dict(r);d["value"]=_unjson(d.pop("value_json",None),None)
            key=str(d.get("key") or "")
            if latest_only and key in seen:continue
            seen.add(key);out.append(d)
        return out

    def save_run_report(self, run_id: str, report: Mapping[str, Any], *, source_asset_id: str | None = None, label: str = "") -> tuple[str, bool]:
        """Persist a standardized derived report as Run metadata.

        Reports are immutable evidence products keyed by their deterministic
        fingerprint. Re-running the same analysis is idempotent; changed source
        data or analysis logic creates a new report record rather than silently
        replacing history.
        """
        payload=dict(report or {})
        report_type=str(payload.get("report_type") or "").strip()
        fingerprint=str(payload.get("fingerprint_sha256") or "").strip().lower()
        if not report_type:raise ValueError("Run report requires report_type")
        if not fingerprint:raise ValueError("Run report requires fingerprint_sha256")
        with self._connect() as c:
            if not c.execute("SELECT 1 FROM runs WHERE id=?",(run_id,)).fetchone():raise KeyError(f"Unknown run {run_id}")
            if source_asset_id and not c.execute("SELECT 1 FROM assets WHERE id=? AND run_id=?",(source_asset_id,run_id)).fetchone():
                raise ValueError("source_asset_id must belong to the report Run")
            row=c.execute("SELECT id FROM run_reports WHERE run_id=? AND report_type=? AND fingerprint_sha256=?",(run_id,report_type,fingerprint)).fetchone()
        if row:return str(row[0]),False
        now=utc_now();report_id=new_id("rpt")
        generated=str(payload.get("generated_at_utc") or payload.get("generated_at") or "")
        with self.transaction() as c:
            c.execute("INSERT INTO run_reports(id,run_id,source_asset_id,report_type,report_version,profile,label,fingerprint_sha256,payload_json,generated_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(report_id,run_id,source_asset_id,report_type,int(payload.get("report_version") or 1),str(payload.get("profile") or ""),str(label or payload.get("label") or report_type),fingerprint,_json(payload),generated,now,now))
        return report_id,True

    def list_run_reports(self, run_id: str, *, report_type: str | None = None, limit: int = 500) -> List[Dict[str, Any]]:
        where=["run_id=?"];args=[run_id]
        if report_type:
            where.append("report_type=?");args.append(str(report_type))
        args.append(int(limit))
        with self._connect() as c:
            rows=c.execute("SELECT * FROM run_reports WHERE "+" AND ".join(where)+" ORDER BY COALESCE(generated_at,created_at) DESC LIMIT ?",args).fetchall()
        out=[]
        for r in rows:
            d=dict(r);d["payload"]=_unjson(d.pop("payload_json",None));out.append(d)
        return out

    def latest_run_report(self, run_id: str, report_type: str) -> Dict[str, Any] | None:
        rows=self.list_run_reports(run_id,report_type=report_type,limit=1)
        return rows[0] if rows else None

    def previous_run_report(self, run_id: str, report_type: str) -> Dict[str, Any] | None:
        """Return the nearest earlier report for the same driver/category.

        This is intended for standardized compliance/performance trend reports.
        If the canonical Run does not have a driver identity, no cross-Run guess is
        attempted.
        """
        current=self.get_run(run_id)
        if not current or not current.get("driver_id"):
            return None
        where=["rr.report_type=?","rr.run_id<>?","r.driver_id=?"]
        args=[str(report_type),str(run_id),str(current.get("driver_id"))]
        category=str(current.get("category") or "").strip()
        if category:
            where.append("COALESCE(r.category,'')=?");args.append(category)
        run_dt=str(current.get("run_datetime") or "").strip()
        if run_dt:
            where.append("COALESCE(r.run_datetime,rr.generated_at,rr.created_at) < ?");args.append(run_dt)
        sql="""SELECT rr.*,r.run_key,r.run_datetime,r.category,e.name AS event_name,d.name AS driver_name
            FROM run_reports rr JOIN runs r ON r.id=rr.run_id
            LEFT JOIN events e ON e.id=r.event_id LEFT JOIN drivers d ON d.id=r.driver_id
            WHERE """+" AND ".join(where)+" ORDER BY COALESCE(r.run_datetime,rr.generated_at,rr.created_at) DESC LIMIT 1"
        with self._connect() as c:row=c.execute(sql,args).fetchone()
        if not row:return None
        d=dict(row);d["payload"]=_unjson(d.pop("payload_json",None));return d

    def create_model_snapshot(self, run_id: str | None = None, *, analysis_case_id: str | None = None, name: str, model_type: str = "vehicle_performance", model_version: str = "", inputs: Mapping[str, Any] | None = None, outputs: Mapping[str, Any] | None = None, quality: Mapping[str, Any] | None = None) -> str:
        if not run_id and not analysis_case_id:
            raise ValueError("ModelSnapshot requires a Run or AnalysisCase owner")
        snapshot_id=new_id("mdl"); now=utc_now()
        with self.transaction() as c:
            if run_id and not c.execute("SELECT 1 FROM runs WHERE id=?",(run_id,)).fetchone():
                raise KeyError(f"Unknown run {run_id}")
            if analysis_case_id and not c.execute("SELECT 1 FROM analysis_cases WHERE id=?",(analysis_case_id,)).fetchone():
                raise KeyError(f"Unknown analysis case {analysis_case_id}")
            c.execute("INSERT INTO model_snapshots(id,run_id,analysis_case_id,name,model_type,model_version,inputs_json,outputs_json,quality_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(snapshot_id,run_id,analysis_case_id,name,model_type,model_version,_json(dict(inputs or {})),_json(dict(outputs or {})),_json(dict(quality or {})),now))
        return snapshot_id

    def create_analysis_case(self, title: str, *, case_type: str = "engineering", primary_run_id: str | None = None, status: str = "open", summary: str = "", remote_id: str = "", revision: str = "", sync_state: str = "local") -> str:
        case_id=new_id("case");now=utc_now();kind=(case_type or "engineering").strip().lower().replace(" ","_")
        with self.transaction() as c:
            if primary_run_id and not c.execute("SELECT 1 FROM runs WHERE id=?",(primary_run_id,)).fetchone():
                raise KeyError(f"Unknown run {primary_run_id}")
            c.execute("INSERT INTO analysis_cases(id,case_type,title,status,summary,primary_run_id,remote_id,revision,sync_state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(case_id,kind,title,status,summary,primary_run_id,remote_id,revision,sync_state,now,now))
            if primary_run_id:
                c.execute("INSERT INTO analysis_case_runs(case_id,run_id,role,sort_order,notes,added_at) VALUES(?,?,'primary',0,'',?)",(case_id,primary_run_id,now))
        return case_id

    def create_incident_case(self, run_id: str, title: str, *, status: str = "open", summary: str = "") -> str:
        """Compatibility wrapper: incidents are now AnalysisCases of type incident."""
        return self.create_analysis_case(title,case_type="incident",primary_run_id=run_id,status=status,summary=summary)

    def update_analysis_case(self, case_id: str, *, title: str | None = None, case_type: str | None = None, status: str | None = None, summary: str | None = None) -> None:
        sets=[];vals=[]
        for col,value in (("title",title),("status",status),("summary",summary)):
            if value is not None: sets.append(f"{col}=?");vals.append(str(value))
        if case_type is not None:
            sets.append("case_type=?");vals.append((case_type or "engineering").strip().lower().replace(" ","_"))
        if not sets:return
        sets.append("updated_at=?");vals.append(utc_now());vals.append(case_id)
        with self.transaction() as c:
            cur=c.execute(f"UPDATE analysis_cases SET {','.join(sets)} WHERE id=?",vals)
            if cur.rowcount==0: raise KeyError(f"Unknown analysis case {case_id}")

    def add_run_to_case(self, case_id: str, run_id: str, *, role: str = "reference", sort_order: int = 0, notes: str = "") -> None:
        now=utc_now();role=(role or "reference").strip().lower()
        with self.transaction() as c:
            if not c.execute("SELECT 1 FROM analysis_cases WHERE id=?",(case_id,)).fetchone():raise KeyError(f"Unknown analysis case {case_id}")
            if not c.execute("SELECT 1 FROM runs WHERE id=?",(run_id,)).fetchone():raise KeyError(f"Unknown run {run_id}")
            if role=="primary":
                c.execute("UPDATE analysis_case_runs SET role='reference' WHERE case_id=? AND role='primary'",(case_id,))
                c.execute("UPDATE analysis_cases SET primary_run_id=?,updated_at=? WHERE id=?",(run_id,now,case_id))
            c.execute("INSERT INTO analysis_case_runs(case_id,run_id,role,sort_order,notes,added_at) VALUES(?,?,?,?,?,?) ON CONFLICT(case_id,run_id) DO UPDATE SET role=excluded.role,sort_order=excluded.sort_order,notes=excluded.notes",(case_id,run_id,role,int(sort_order),notes,now))
            c.execute("UPDATE analysis_cases SET updated_at=? WHERE id=?",(now,case_id))

    def set_case_primary_run(self, case_id: str, run_id: str) -> None:
        self.add_run_to_case(case_id,run_id,role="primary")

    def remove_run_from_case(self, case_id: str, run_id: str) -> None:
        now=utc_now()
        with self.transaction() as c:
            case=c.execute("SELECT primary_run_id FROM analysis_cases WHERE id=?",(case_id,)).fetchone()
            if not case:raise KeyError(f"Unknown analysis case {case_id}")
            c.execute("DELETE FROM analysis_case_runs WHERE case_id=? AND run_id=?",(case_id,run_id))
            if case[0]==run_id:c.execute("UPDATE analysis_cases SET primary_run_id=NULL,updated_at=? WHERE id=?",(now,case_id))
            else:c.execute("UPDATE analysis_cases SET updated_at=? WHERE id=?",(now,case_id))

    def link_asset_to_case(self, case_id: str, asset_id: str, *, evidence_type: str = "run_asset", label: str = "", metadata: Mapping[str, Any] | None = None) -> str:
        now=utc_now()
        with self.transaction() as c:
            if not c.execute("SELECT 1 FROM analysis_cases WHERE id=?",(case_id,)).fetchone():raise KeyError(f"Unknown analysis case {case_id}")
            asset=c.execute("SELECT filename,run_id FROM assets WHERE id=?",(asset_id,)).fetchone()
            if not asset:raise KeyError(f"Unknown asset {asset_id}")
            linked_run_id=str(asset[1] or '')
            if linked_run_id and not c.execute("SELECT 1 FROM analysis_case_runs WHERE case_id=? AND run_id=?",(case_id,linked_run_id)).fetchone():
                # Evidence from a Run cannot be orphaned from the case context.
                # Preserve server Run ownership and add the owning Run only as a
                # case reference; never re-parent or duplicate the Asset.
                next_order=int(c.execute("SELECT COALESCE(MAX(sort_order),-1)+1 FROM analysis_case_runs WHERE case_id=?",(case_id,)).fetchone()[0])
                c.execute("INSERT INTO analysis_case_runs(case_id,run_id,role,sort_order,notes,added_at) VALUES(?,?,'reference',?,'Added automatically from linked Run Asset',?)",(case_id,linked_run_id,next_order,now))
            row=c.execute("SELECT id FROM analysis_case_evidence WHERE case_id=? AND asset_id=?",(case_id,asset_id)).fetchone()
            if row:return str(row[0])
            evidence_id=new_id("evd")
            c.execute("INSERT INTO analysis_case_evidence(id,case_id,asset_id,evidence_type,label,filename,source_kind,storage_mode,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?, 'run_asset','linked',?,?,?)",(evidence_id,case_id,asset_id,evidence_type,label,str(asset[0] or ''),_json(dict(metadata or {})),now,now))
            c.execute("UPDATE analysis_cases SET updated_at=? WHERE id=?",(now,case_id))
        return evidence_id

    def register_case_evidence(self, case_id: str, path: str | os.PathLike[str], *, evidence_type: str = "other", label: str = "", metadata: Mapping[str, Any] | None = None, managed: bool = True) -> str:
        source=Path(path).expanduser().resolve();digest,size=sha256_file(source);mime=mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        with self._connect() as c:
            if not c.execute("SELECT 1 FROM analysis_cases WHERE id=?",(case_id,)).fetchone():raise KeyError(f"Unknown analysis case {case_id}")
            row=c.execute("SELECT id FROM analysis_case_evidence WHERE case_id=? AND asset_id IS NULL AND sha256=?",(case_id,digest)).fetchone()
            if row:return str(row[0])
        if managed:
            stored=self.object_store.ingest(source);local_path=str(stored.path);storage_mode="managed"
        else:
            local_path=str(source);storage_mode="external"
        now=utc_now();evidence_id=new_id("evd")
        with self.transaction() as c:
            c.execute("INSERT INTO analysis_case_evidence(id,case_id,evidence_type,label,filename,original_path,local_path,sha256,size_bytes,mime_type,source_kind,storage_mode,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,'local_case',?,?,?,?)",(evidence_id,case_id,evidence_type,label,source.name,str(source),local_path,digest,size,mime,storage_mode,_json(dict(metadata or {})),now,now))
            c.execute("UPDATE analysis_cases SET updated_at=? WHERE id=?",(now,case_id))
        return evidence_id

    def mark_asset_managed(self, asset_id: str) -> str:
        with self._connect() as c:
            row=c.execute("SELECT * FROM assets WHERE id=?",(asset_id,)).fetchone()
        if not row: raise KeyError(f"Unknown asset {asset_id}")
        source=Path(row["local_path"] or row["original_path"])
        stored=self.object_store.ingest(source)
        with self.transaction() as c:c.execute("UPDATE assets SET local_path=?,storage_mode='managed',updated_at=? WHERE id=?",(str(stored.path),utc_now(),asset_id))
        return str(stored.path)

    def keep_run_offline(self, run_id: str) -> Dict[str, Any]:
        """Promote every locally available asset for a run into managed storage.

        The operation is intentionally implemented in the catalog rather than
        the desktop UI so the same semantics can later be used by the Tech
        Services synchronizer, event-prefetch jobs and CLI tooling.  Missing
        source files are reported and do not abort promotion of other assets.
        """
        result: Dict[str, Any] = {"run_id": run_id, "managed": 0, "already_managed": 0, "errors": []}
        if self.get_run(run_id) is None:
            raise KeyError(f"Unknown run {run_id}")
        for asset in self.list_assets(run_id):
            if asset.get("storage_mode") == "managed":
                result["already_managed"] += 1
                continue
            try:
                self.mark_asset_managed(str(asset["id"]))
                result["managed"] += 1
            except Exception as exc:
                result["errors"].append({"asset_id": str(asset.get("id", "")), "filename": str(asset.get("filename", "")), "error": str(exc)})
        result["complete"] = len(result["errors"]) == 0
        return result

    def keep_event_offline(self, event_id: str) -> Dict[str, Any]:
        """Promote all locally available evidence for an event into managed storage."""
        events = {str(e["id"]): e for e in self.list_events()}
        if event_id not in events:
            raise KeyError(f"Unknown event {event_id}")
        runs = self.list_runs(event_id=event_id, limit=100000)
        result: Dict[str, Any] = {
            "event_id": event_id,
            "run_count": len(runs),
            "managed": 0,
            "already_managed": 0,
            "errors": [],
        }
        for run in runs:
            item = self.keep_run_offline(str(run["id"]))
            result["managed"] += int(item["managed"])
            result["already_managed"] += int(item["already_managed"])
            result["errors"].extend(item["errors"])
        result["complete"] = len(result["errors"]) == 0
        return result

    def relink_asset_to_run(self, asset_id: str, run_id: str) -> None:
        asset=self.get_asset(asset_id)
        if not asset: raise KeyError(asset_id)
        if str(asset.get('source_kind') or '')=='tech_services':
            raise ValueError('Tech Services assets cannot be re-parented by the desktop; their Run relationship is authoritative on the server')
        now=utc_now()
        with self.transaction() as c:
            c.execute("UPDATE assets SET run_id=?,updated_at=? WHERE id=?",(run_id,now,asset_id))
            c.execute("UPDATE telemetry_sessions SET run_id=?,updated_at=? WHERE asset_id=?",(run_id,now,asset_id))
            c.execute("UPDATE time_mappings SET run_id=?,updated_at=? WHERE asset_id=?",(run_id,now,asset_id))

    def get_run_by_key(self, run_key: str) -> Dict[str, Any] | None:
        with self._connect() as c:
            row=c.execute("SELECT id FROM runs WHERE run_key=?",(str(run_key or "").strip(),)).fetchone()
        return self.get_run(str(row[0])) if row else None

    def get_asset_by_remote_id(self, remote_id: str) -> Dict[str, Any] | None:
        token=str(remote_id or '').strip()
        if not token:return None
        with self._connect() as c:
            row=c.execute("SELECT id FROM assets WHERE remote_id=?",(token,)).fetchone()
        return self.get_asset(str(row[0])) if row else None

    def upsert_server_asset(self, run_id: str, *, remote_id: str, filename: str, asset_type: str = "other", sha256: str = "", size_bytes: int = 0, mime_type: str = "", vendor: str = "", remote_uri: str = "", revision: str = "", uploaded_at: str = "", metadata: Mapping[str, Any] | None = None) -> tuple[str, bool]:
        """Mirror one permanent Tech Services asset already attached to a Run.

        The server relationship is authoritative. The desktop never guesses or
        re-parents these assets. A changed authoritative content hash invalidates
        any old local cache and decoded telemetry session.
        """
        if self.get_run(run_id) is None: raise KeyError(run_id)
        remote_id=str(remote_id or '').strip()
        if not remote_id: raise ValueError('remote_id is required for a Tech Services asset')
        now=utc_now();incoming_hash=str(sha256 or '').lower().strip()
        with self._connect() as c:
            row=c.execute("SELECT * FROM assets WHERE remote_id=?",(remote_id,)).fetchone()
        if row:
            asset_id=str(row['id']);old_hash=str(row['sha256'] or '').lower().strip();effective_hash=incoming_hash or old_hash
            hash_changed=bool(incoming_hash and old_hash and incoming_hash!=old_hash)
            local_path=None if hash_changed else row['local_path'];storage_mode='remote' if hash_changed else str(row['storage_mode'] or 'remote')
            effective_size=int(size_bytes or row['size_bytes'] or 0)
            with self.transaction() as c:
                c.execute("UPDATE assets SET run_id=?,revision=?,source_kind='tech_services',asset_type=?,filename=?,sha256=?,size_bytes=?,mime_type=?,vendor=?,storage_mode=?,sync_state='synced',remote_uri=?,uploaded_at=?,metadata_json=?,local_path=?,updated_at=? WHERE id=?",(run_id,revision,asset_type,filename,effective_hash,effective_size,mime_type or row['mime_type'],vendor or row['vendor'],storage_mode,remote_uri or row['remote_uri'],uploaded_at or row['uploaded_at'],_json(dict(metadata or {})),local_path,now,asset_id))
                if hash_changed:
                    c.execute("DELETE FROM telemetry_sessions WHERE asset_id=?",(asset_id,));c.execute("DELETE FROM time_mappings WHERE asset_id=?",(asset_id,))
            return asset_id,False
        asset_id=new_id('ast')
        with self.transaction() as c:
            c.execute("INSERT INTO assets(id,run_id,remote_id,revision,source_kind,asset_type,filename,sha256,size_bytes,mime_type,vendor,storage_mode,sync_state,remote_uri,uploaded_at,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(asset_id,run_id,remote_id,revision,'tech_services',asset_type,filename,incoming_hash,int(size_bytes or 0),mime_type,vendor,'remote','synced',remote_uri,uploaded_at,_json(dict(metadata or {})),now,now))
        return asset_id,True

    def cache_server_asset_bytes(self, asset_id: str, content: bytes) -> str:
        asset=self.get_asset(asset_id)
        if asset is None: raise KeyError(asset_id)
        if str(asset.get('source_kind') or '')!='tech_services':
            raise ValueError('cache_server_asset_bytes is only for Tech Services assets')
        stored=self.object_store.ingest_bytes(content,expected_sha256=str(asset.get('sha256') or ''))
        if int(asset.get('size_bytes') or 0) and stored.size_bytes!=int(asset['size_bytes']):
            raise IOError(f"Downloaded asset size mismatch: expected {asset['size_bytes']}, got {stored.size_bytes}")
        with self.transaction() as c:
            c.execute("UPDATE assets SET local_path=?,storage_mode='managed',sha256=?,updated_at=? WHERE id=?",(str(stored.path),stored.sha256,utc_now(),asset_id))
        return str(stored.path)

    def asset_cache_valid(self, asset_id: str) -> bool:
        asset=self.get_asset(asset_id)
        if not asset or str(asset.get('storage_mode') or '')!='managed':return False
        digest=str(asset.get('sha256') or '')
        path=str(asset.get('local_path') or '')
        if not digest or not path or not Path(path).is_file():return False
        return self.object_store.verify(digest)

    def upsert_remote_entity(self, provider: str, entity_type: str, remote_id: str, local_id: str, *, revision: str = "", payload_hash: str = "") -> None:
        now=utc_now()
        with self.transaction() as c:
            c.execute("INSERT INTO remote_entities(provider,entity_type,remote_id,local_id,revision,payload_hash,last_synced_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(provider,entity_type,remote_id) DO UPDATE SET local_id=excluded.local_id,revision=excluded.revision,payload_hash=excluded.payload_hash,last_synced_at=excluded.last_synced_at",(provider,entity_type,remote_id,local_id,revision,payload_hash,now))

    def set_sync_cursor(self, provider: str, scope: str, cursor: str) -> None:
        with self.transaction() as c:
            c.execute("INSERT INTO sync_cursors(provider,scope,cursor,updated_at) VALUES(?,?,?,?) ON CONFLICT(provider,scope) DO UPDATE SET cursor=excluded.cursor,updated_at=excluded.updated_at",(provider,scope,str(cursor),utc_now()))

    def get_sync_cursor(self, provider: str, scope: str) -> str:
        with self._connect() as c:
            row=c.execute("SELECT cursor FROM sync_cursors WHERE provider=? AND scope=?",(provider,scope)).fetchone()
        return str(row[0]) if row else ""

    def get_run(self, run_id: str) -> Dict[str, Any] | None:
        with self._connect() as c:
            row=c.execute("""SELECT r.*,e.name AS event_name,d.name AS driver_name,v.name AS vehicle_name
                FROM runs r LEFT JOIN events e ON e.id=r.event_id LEFT JOIN drivers d ON d.id=r.driver_id LEFT JOIN vehicles v ON v.id=r.vehicle_id
                WHERE r.id=?""",(run_id,)).fetchone()
        if not row:return None
        out=dict(row);out["timing"]=_unjson(out.pop("official_timing_json",None));out["weather"]=_unjson(out.pop("weather_json",None));out["source"]=_unjson(out.pop("official_source_json",None));return out

    def list_events(self) -> List[Dict[str, Any]]:
        with self._connect() as c:
            rows=c.execute("""SELECT e.*,COUNT(r.id) AS run_count FROM events e LEFT JOIN runs r ON r.event_id=e.id GROUP BY e.id ORDER BY COALESCE(e.season,0) DESC,e.start_date DESC,e.name""").fetchall()
        return [dict(r) for r in rows]

    def list_runs(self, *, event_id: str | None = None, search: str = "", limit: int = 1000) -> List[Dict[str, Any]]:
        where=[];args=[]
        if event_id: where.append("r.event_id=?");args.append(event_id)
        if search.strip():
            token=f"%{search.strip()}%";where.append("(r.run_key LIKE ? OR r.round LIKE ? OR r.category LIKE ? OR r.car_number LIKE ? OR d.name LIKE ? OR v.name LIKE ? OR e.name LIKE ?)");args.extend([token]*7)
        sql="""SELECT r.id,r.event_id,r.run_key,r.round,r.run_number,r.lane,r.category,r.car_number,r.run_datetime,r.sync_state,r.timing_provenance,r.weather_provenance,r.official_timing_json,
            e.name AS event_name,d.name AS driver_name,v.name AS vehicle_name,COUNT(DISTINCT a.id) AS asset_count,
            SUM(CASE WHEN a.storage_mode='managed' THEN 1 ELSE 0 END) AS offline_asset_count,
            SUM(CASE WHEN a.asset_type='telemetry' THEN 1 ELSE 0 END) AS data_log_count,
            SUM(CASE WHEN a.asset_type='telemetry' AND a.storage_mode='managed' THEN 1 ELSE 0 END) AS local_data_log_count
            FROM runs r LEFT JOIN events e ON e.id=r.event_id LEFT JOIN drivers d ON d.id=r.driver_id LEFT JOIN vehicles v ON v.id=r.vehicle_id LEFT JOIN assets a ON a.run_id=r.id"""
        if where: sql += " WHERE " + " AND ".join(where)
        sql += " GROUP BY r.id ORDER BY COALESCE(r.run_datetime,r.created_at) DESC LIMIT ?";args.append(int(limit))
        with self._connect() as c: rows=c.execute(sql,args).fetchall()
        out=[]
        for r in rows:
            d=dict(r); timing=_unjson(d.pop("official_timing_json",None));d["timing"]=timing
            d["et_s"]=timing.get("quarter_mile_s",timing.get("et")) if isinstance(timing,dict) else None
            d["mph"]=timing.get("quarter_mile_mph",timing.get("mph")) if isinstance(timing,dict) else None
            d["sixty_ft_s"]=timing.get("sixty_ft_s",timing.get("60ft")) if isinstance(timing,dict) else None
            out.append(d)
        return out

    def get_asset(self, asset_id: str) -> Dict[str, Any] | None:
        with self._connect() as c:
            row=c.execute("SELECT * FROM assets WHERE id=?",(asset_id,)).fetchone()
        if not row:return None
        d=dict(row);d["metadata"]=_unjson(d.pop("metadata_json",None));return d

    def get_time_mapping(self, asset_id: str) -> Dict[str, Any] | None:
        with self._connect() as c:
            row=c.execute("SELECT * FROM time_mappings WHERE asset_id=?",(asset_id,)).fetchone()
        if not row:return None
        d=dict(row);d["anchors"]=_unjson(d.pop("anchors_json",None),[]);return d

    def list_assets(self, run_id: str) -> List[Dict[str, Any]]:
        with self._connect() as c: rows=c.execute("SELECT * FROM assets WHERE run_id=? ORDER BY created_at",(run_id,)).fetchall()
        out=[]
        for r in rows:
            d=dict(r);d["metadata"]=_unjson(d.pop("metadata_json",None));out.append(d)
        return out

    def get_analysis_case(self, case_id: str) -> Dict[str, Any] | None:
        with self._connect() as c:
            row=c.execute("""SELECT ac.*,COUNT(DISTINCT acr.run_id) AS run_count,COUNT(DISTINCT ace.id) AS evidence_count,COUNT(DISTINCT ms.id) AS model_count
                FROM analysis_cases ac LEFT JOIN analysis_case_runs acr ON acr.case_id=ac.id LEFT JOIN analysis_case_evidence ace ON ace.case_id=ac.id LEFT JOIN model_snapshots ms ON ms.analysis_case_id=ac.id WHERE ac.id=? GROUP BY ac.id""",(case_id,)).fetchone()
        return dict(row) if row else None

    def list_analysis_cases(self, *, case_type: str | None = None, run_id: str | None = None, status: str | None = None, limit: int = 1000) -> List[Dict[str, Any]]:
        where=[];args=[]
        if case_type:where.append("ac.case_type=?");args.append(case_type.strip().lower().replace(" ","_"))
        if status:where.append("ac.status=?");args.append(status)
        if run_id:where.append("EXISTS(SELECT 1 FROM analysis_case_runs x WHERE x.case_id=ac.id AND x.run_id=?)");args.append(run_id)
        sql="""SELECT ac.*,COUNT(DISTINCT acr.run_id) AS run_count,COUNT(DISTINCT ace.id) AS evidence_count,COUNT(DISTINCT ms.id) AS model_count
            FROM analysis_cases ac LEFT JOIN analysis_case_runs acr ON acr.case_id=ac.id LEFT JOIN analysis_case_evidence ace ON ace.case_id=ac.id LEFT JOIN model_snapshots ms ON ms.analysis_case_id=ac.id"""
        if where:sql+=" WHERE "+" AND ".join(where)
        sql+=" GROUP BY ac.id ORDER BY ac.updated_at DESC LIMIT ?";args.append(int(limit))
        with self._connect() as c:rows=c.execute(sql,args).fetchall()
        return [dict(r) for r in rows]

    def list_case_runs(self, case_id: str) -> List[Dict[str, Any]]:
        with self._connect() as c:
            rows=c.execute("""SELECT acr.role,acr.sort_order,acr.notes AS case_notes,acr.time_scale,acr.time_offset_s,acr.alignment_method,acr.alignment_confidence,acr.alignment_uncertainty_s,acr.alignment_anchors_json,acr.alignment_updated_at,r.*,e.name AS event_name,d.name AS driver_name,v.name AS vehicle_name
                FROM analysis_case_runs acr JOIN runs r ON r.id=acr.run_id LEFT JOIN events e ON e.id=r.event_id LEFT JOIN drivers d ON d.id=r.driver_id LEFT JOIN vehicles v ON v.id=r.vehicle_id
                WHERE acr.case_id=? ORDER BY CASE acr.role WHEN 'primary' THEN 0 WHEN 'baseline' THEN 1 WHEN 'comparison' THEN 2 ELSE 3 END,acr.sort_order,COALESCE(r.run_datetime,r.created_at)""",(case_id,)).fetchall()
        out=[]
        for r in rows:
            d=dict(r);d["timing"]=_unjson(d.pop("official_timing_json",None));d["weather"]=_unjson(d.pop("weather_json",None));d["source"]=_unjson(d.pop("official_source_json",None));d["alignment_anchors"]=_unjson(d.pop("alignment_anchors_json",None),[]);out.append(d)
        return out

    def get_case_run_alignment(self, case_id: str, run_id: str) -> Dict[str, Any] | None:
        with self._connect() as c:
            row=c.execute("SELECT case_id,run_id,time_scale,time_offset_s,alignment_method,alignment_confidence,alignment_uncertainty_s,alignment_anchors_json,alignment_updated_at FROM analysis_case_runs WHERE case_id=? AND run_id=?",(case_id,run_id)).fetchone()
        if not row:return None
        d=dict(row);d["anchors"]=_unjson(d.pop("alignment_anchors_json",None),[]);return d

    def update_case_run_alignment(self, case_id: str, run_id: str, *, scale: float = 1.0, offset_s: float = 0.0, method: str = "manual", confidence: float | None = None, uncertainty_s: float | None = None, anchors: Iterable[Mapping[str, float]] = ()) -> None:
        scale=float(scale);offset_s=float(offset_s)
        if abs(scale-1.0)>1e-9:raise ValueError("Run→Case alignment preserves physical seconds; scale must be 1.0")
        now=utc_now();anchor_rows=list(anchors)
        with self.transaction() as c:
            cur=c.execute("UPDATE analysis_case_runs SET time_scale=?,time_offset_s=?,alignment_method=?,alignment_confidence=?,alignment_uncertainty_s=?,alignment_anchors_json=?,alignment_updated_at=? WHERE case_id=? AND run_id=?",(scale,offset_s,method,confidence,uncertainty_s,_json(anchor_rows),now,case_id,run_id))
            if cur.rowcount==0:raise KeyError(f"Run {run_id} is not a member of analysis case {case_id}")
            c.execute("UPDATE analysis_cases SET updated_at=? WHERE id=?",(now,case_id))

    def map_run_time_to_case(self, case_id: str, run_id: str, run_time_s: float) -> float:
        m=self.get_case_run_alignment(case_id,run_id)
        if m is None:raise KeyError(f"Run {run_id} is not a member of analysis case {case_id}")
        return float(run_time_s)*float(m['time_scale'])+float(m['time_offset_s'])

    def map_case_time_to_run(self, case_id: str, run_id: str, case_time_s: float) -> float:
        m=self.get_case_run_alignment(case_id,run_id)
        if m is None:raise KeyError(f"Run {run_id} is not a member of analysis case {case_id}")
        scale=float(m['time_scale'])
        if abs(scale)<1e-12:raise ValueError('Case alignment scale cannot be zero')
        return (float(case_time_s)-float(m['time_offset_s']))/scale

    def map_asset_time_to_case(self, case_id: str, asset_id: str, asset_time_s: float) -> float:
        asset=self.get_asset(asset_id)
        if asset is None:raise KeyError(asset_id)
        mapping=self.get_time_mapping(asset_id)
        if mapping is None:raise KeyError(f"Asset {asset_id} has no Asset→Run time mapping")
        run_time=float(asset_time_s)*float(mapping['scale'])+float(mapping['offset_s'])
        return self.map_run_time_to_case(case_id,str(asset['run_id']),run_time)

    def map_case_time_to_asset(self, case_id: str, asset_id: str, case_time_s: float) -> float:
        asset=self.get_asset(asset_id)
        if asset is None:raise KeyError(asset_id)
        mapping=self.get_time_mapping(asset_id)
        if mapping is None:raise KeyError(f"Asset {asset_id} has no Asset→Run time mapping")
        run_time=self.map_case_time_to_run(case_id,str(asset['run_id']),case_time_s)
        scale=float(mapping['scale'])
        if abs(scale)<1e-12:raise ValueError('Asset time mapping scale cannot be zero')
        return (run_time-float(mapping['offset_s']))/scale

    def create_case_marker(self, case_id: str, *, label: str, start_s: float, end_s: float | None = None, kind: str = "marker", time_domain: str = "case", run_id: str | None = None, asset_id: str | None = None, payload: Mapping[str, Any] | None = None) -> str:
        domain=(time_domain or 'case').strip().lower()
        if domain not in {'case','run','asset'}:raise ValueError("time_domain must be case, run, or asset")
        if domain=='run' and not run_id:raise ValueError('run time marker requires run_id')
        if domain=='asset' and not asset_id:raise ValueError('asset time marker requires asset_id')
        if self.get_analysis_case(case_id) is None:raise KeyError(case_id)
        if run_id and not any(str(r['id'])==str(run_id) for r in self.list_case_runs(case_id)):raise ValueError('marker Run must be a member of the AnalysisCase')
        if asset_id:
            asset=self.get_asset(asset_id)
            if asset is None:raise KeyError(asset_id)
            if not any(str(r['id'])==str(asset['run_id']) for r in self.list_case_runs(case_id)):raise ValueError('marker Asset owning Run must be a member of the AnalysisCase')
            run_id=str(asset['run_id'])
        marker_id=new_id('mrk');now=utc_now()
        with self.transaction() as c:
            c.execute("INSERT INTO analysis_case_markers(id,case_id,kind,label,time_domain,source_run_id,source_asset_id,source_start_s,source_end_s,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(marker_id,case_id,kind,label,domain,run_id,asset_id,float(start_s),None if end_s is None else float(end_s),_json(dict(payload or {})),now,now))
            c.execute("UPDATE analysis_cases SET updated_at=? WHERE id=?",(now,case_id))
        return marker_id

    def list_case_markers(self, case_id: str) -> List[Dict[str, Any]]:
        if self.get_analysis_case(case_id) is None:raise KeyError(case_id)
        with self._connect() as c:rows=c.execute("SELECT * FROM analysis_case_markers WHERE case_id=? ORDER BY created_at",(case_id,)).fetchall()
        out=[]
        for row in rows:
            d=dict(row);d['payload']=_unjson(d.pop('payload_json',None))
            domain=str(d.get('time_domain') or 'case')
            start=float(d['source_start_s']);end=d.get('source_end_s')
            if domain=='run':
                start=self.map_run_time_to_case(case_id,str(d['source_run_id']),start);end=None if end is None else self.map_run_time_to_case(case_id,str(d['source_run_id']),float(end))
            elif domain=='asset':
                start=self.map_asset_time_to_case(case_id,str(d['source_asset_id']),start);end=None if end is None else self.map_asset_time_to_case(case_id,str(d['source_asset_id']),float(end))
            d['case_start_s']=start;d['case_end_s']=end;out.append(d)
        return sorted(out,key=lambda x:(float(x['case_start_s']),str(x.get('label') or '')))

    def delete_case_marker(self, marker_id: str) -> None:
        with self.transaction() as c:c.execute("DELETE FROM analysis_case_markers WHERE id=?",(marker_id,))

    def list_case_evidence(self, case_id: str) -> List[Dict[str, Any]]:
        with self._connect() as c:
            rows=c.execute("""SELECT ace.*,a.run_id AS linked_run_id,a.asset_type AS linked_asset_type,a.filename AS linked_filename,a.sha256 AS linked_sha256,a.size_bytes AS linked_size_bytes,a.mime_type AS linked_mime_type,a.vendor AS linked_vendor,a.storage_mode AS linked_storage_mode,a.source_kind AS linked_source_kind,a.remote_id AS linked_remote_id
                FROM analysis_case_evidence ace LEFT JOIN assets a ON a.id=ace.asset_id WHERE ace.case_id=? ORDER BY ace.created_at""",(case_id,)).fetchall()
        out=[]
        for r in rows:
            d=dict(r);d["metadata"]=_unjson(d.pop("metadata_json",None));
            if d.get("asset_id"):
                d["filename"]=d.get("linked_filename") or d.get("filename") or "";d["sha256"]=d.get("linked_sha256") or d.get("sha256") or "";d["size_bytes"]=d.get("linked_size_bytes") or d.get("size_bytes") or 0;d["mime_type"]=d.get("linked_mime_type") or d.get("mime_type") or "";d["storage_mode"]=d.get("linked_storage_mode") or d.get("storage_mode") or "linked";d["source_kind"]=d.get("linked_source_kind") or d.get("source_kind") or "run_asset"
            out.append(d)
        return out

    def list_model_snapshots(self, run_id: str | None = None, *, analysis_case_id: str | None = None) -> List[Dict[str, Any]]:
        where=[];args=[]
        if run_id is not None:where.append("run_id=?");args.append(run_id)
        if analysis_case_id is not None:where.append("analysis_case_id=?");args.append(analysis_case_id)
        if not where:raise ValueError("list_model_snapshots requires run_id or analysis_case_id")
        with self._connect() as c:rows=c.execute("SELECT * FROM model_snapshots WHERE "+" AND ".join(where)+" ORDER BY created_at DESC",args).fetchall()
        out=[]
        for r in rows:
            d=dict(r);d["inputs"]=_unjson(d.pop("inputs_json",None));d["outputs"]=_unjson(d.pop("outputs_json",None));d["quality"]=_unjson(d.pop("quality_json",None));out.append(d)
        return out

    def engineering_history(self, key: str, *, driver_id: str | None = None, vehicle_id: str | None = None, limit: int = 5000) -> List[Dict[str, Any]]:
        where=["ev.key=?"];args=[key]
        if driver_id:where.append("r.driver_id=?");args.append(driver_id)
        if vehicle_id:where.append("r.vehicle_id=?");args.append(vehicle_id)
        sql="""SELECT ev.*,r.run_datetime,r.run_key,r.category,r.car_number,d.name AS driver_name,v.name AS vehicle_name,e.name AS event_name,e.season AS season
            FROM engineering_values ev JOIN runs r ON r.id=ev.run_id LEFT JOIN drivers d ON d.id=r.driver_id LEFT JOIN vehicles v ON v.id=r.vehicle_id LEFT JOIN events e ON e.id=r.event_id
            WHERE """+" AND ".join(where)+" ORDER BY COALESCE(r.run_datetime,ev.created_at) ASC LIMIT ?";args.append(int(limit))
        with self._connect() as c:rows=c.execute(sql,args).fetchall()
        out=[]
        for r in rows:
            d=dict(r);d["value"]=_unjson(d.pop("value_json",None),None);out.append(d)
        return out

    def queue_sync(self, entity_type: str, entity_id: str, operation: str, payload: Mapping[str, Any] | None = None) -> str:
        jid=new_id("sync");now=utc_now()
        with self.transaction() as c:c.execute("INSERT INTO sync_journal(id,entity_type,entity_id,operation,payload_json,state,created_at,updated_at) VALUES(?,?,?,?,?,'pending',?,?)",(jid,entity_type,entity_id,operation,_json(dict(payload or {})),now,now))
        return jid

    def pending_sync(self) -> List[Dict[str, Any]]:
        with self._connect() as c:rows=c.execute("SELECT * FROM sync_journal WHERE state='pending' ORDER BY created_at").fetchall()
        out=[]
        for r in rows:
            d=dict(r);d["payload"]=_unjson(d.pop("payload_json",None));out.append(d)
        return out

    def stats(self) -> Dict[str, int]:
        tables=("events","runs","assets","telemetry_sessions","engineering_values","run_reports","model_snapshots","analysis_cases","analysis_case_runs","analysis_case_evidence","analysis_case_markers","incident_cases")
        out={}
        with self._connect() as c:
            for table in tables: out[table]=int(c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        return out
