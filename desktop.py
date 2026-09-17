from __future__ import annotations

"""NHRA Velocity desktop data-analysis workstation.

This is intentionally a desktop application rather than a web UI.  It uses the
same mental model as professional motorsport analysis tools: projects/workspaces
contain worksheets; worksheets contain dockable/floating displays; sessions and
parameters are application-level resources shared by all displays.
"""

import json
import html
import os
import copy
import re
import sys
import logging
import traceback
import subprocess
import time
import faulthandler
from datetime import date
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    import pyqtgraph as pg
    try:
        from PySide6 import QtMultimedia, QtMultimediaWidgets
        QT_MULTIMEDIA_AVAILABLE = True
    except ImportError:
        QtMultimedia = None
        QtMultimediaWidgets = None
        QT_MULTIMEDIA_AVAILABLE = False
except ImportError as exc:  # pragma: no cover - environment dependent
    print(
        "NHRA Velocity requires PySide6 and pyqtgraph.\n"
        "Install desktop requirements with: python -m pip install -r requirements-desktop.txt\n"
        f"Missing dependency: {exc}",
        file=sys.stderr,
    )
    raise

from runlab.branding import PRODUCT_NAME, PRODUCT_TAGLINE, PRODUCT_VERSION
from runlab.product_manifest import WORKBOOK_FORMAT_VERSION
from runlab.importers import load_telemetry, apply_channel_overrides, auto_map_channels, CANONICAL_CHANNELS, telemetry_file_candidate
from runlab.import_registry import qt_file_dialog_filter
from runlab.models import TelemetryRun, Environment, TimingData
from runlab.telemetry import detect_drag_pass_window, launch_time_override, set_launch_time_override, clear_launch_time_override
from runlab.audit import audit_run
from runlab.alignment import estimate_time_alignment
from runlab.math_channels import add_math_channel, reapply_math_channels, evaluate_run_expression, infer_expression_dimension
from runlab.units import display_label, dimension, normalize_unit, convert_value, compatible, UNITS
from runlab.knowledge import vehicle_from_run, vehicle_inputs, set_vehicle_input, set_parameter, restore_knowledge_snapshot
from runlab.reconstruction import reconstruct_delivered_power
from runlab.inverse import FitRun, FitEvidencePolicy, FitDistanceWindow, fit_vehicle
from runlab.fit_study import FitStudyDefinition, run_joint_fit_study, save_fit_study_package
from runlab.fit_uncertainty import profile_parameter, leave_one_run_out_influence
from runlab.observability import assess_observability
from runlab.scenario import create_compare_run
from runlab.models import ChannelSeries
from runlab.plotability import choose_default_plot_channels, assess_plotability
from runlab.display_data import channel_xy, prepare_plot_series
from runlab.display_cache import DisplaySeriesCache
from runlab.selftest import run_data_pipeline_selftest, format_selftest
from runlab.resources import bundled_examples_dir, brand_asset
from runlab.diagnostics import configure_logging, log_dir
from runlab.compare import reference_delta_series, delta_statistics
from runlab.compare_sets import CompareRun, CompareSet, CompareSetLibrary
from runlab.annotations import annotations_for_mode, add_bookmark, add_region, delete_annotation, annotations
from runlab.statistics import region_statistics
from runlab.signal_analysis import fft_spectrum, filter_signal, power_spectral_density, spectrogram
from runlab.envelope import multi_run_envelope
from runlab.preferences import (
    get_channel_preference, set_channel_preference, clear_channel_preference,
    learned_common_channel_overrides, learned_mapping_for_source, remember_common_channel_mapping, forget_common_channel_mapping,
    common_channel_profile_scope_options, matching_common_channel_profile, save_common_channel_profile,
    math_channel_templates, save_math_channel_template, delete_math_channel_template,
    worksheet_template_scope_options, worksheet_templates, save_worksheet_template, delete_worksheet_template,
)
from runlab.sensor_health import sensor_health
from runlab.comparison_report import comparison_summary
from runlab.derived import attach_delivered_power_reconstruction
from runlab.catalog import LocalCatalog
from runlab.catalog_bridge import sync_run_state, capture_model_snapshot, register_opened_telemetry, apply_catalog_run_authority
from runlab.sync_contract import run_sync_payload
from runlab.trends import compare_seasons
from runlab.transport import UnboundTechServicesTransport, AuthorizedTechServicesTransport
from runlab.tech_services_client import ensure_asset_cached, cache_run, cache_event, cache_case
from runlab.sync_engine import apply_tech_services_snapshot
from runlab.time_mapping import TimeAnchor, fit_time_mapping
from runlab.case_timeline import CaseTimeAnchor, fit_case_run_alignment, store_case_run_alignment, composed_mapping_for_asset
from runlab.case_playback import CasePlaybackController, case_playback_frame, sample_telemetry_at_asset_time
from runlab.workstation import channel_catalog, set_channel_alias, gates, GateDefinition, save_gate, evaluate_gate, MetricDefinition, drag_metric_report
from runlab.common_channels import common_channel_specs, common_channel_label
from runlab.racepak_config_profiles import (
    matching_profile as matching_racepak_config_profile,
    profile_scope_options as racepak_config_profile_scope_options,
    save_profile as save_racepak_config_profile,
    delete_profile as delete_racepak_config_profile,
    list_profiles as list_racepak_config_profiles,
    delete_profile_key as delete_racepak_config_profile_key,
    config_path_from_profile as racepak_config_path_from_profile,
    exact_binding_from_settings as racepak_exact_config_binding,
    exact_binding_record as racepak_exact_config_record,
    resolve_config_path as resolve_racepak_config_path,
)
from runlab.racepak_ddf import parse_ddf_structure, bind_ddf_config
from runlab.layout_profiles import capture_display_specs as capture_portable_display_specs, resolve_display_specs as resolve_portable_display_specs
from runlab.heatmap import binned_map
from runlab.display_analysis import paired_channel_data, linear_regression, channel_distribution, sample_channel_at
from runlab.definition_library import (
    DefinitionLibrary, ConstantDefinition, SegmentTemplate, PortableMetricDefinition, ConditionalRule, ReportDefinition, EventRuleDefinition,
    capture_from_run, validate_library, apply_library, run_saved_report, trend_frame, export_report, starter_library,
)
from runlab.rule_events import evaluate_event_rules, alarm_states_at
from runlab.auth import AuthManager, KeyringCredentialStore, AccessDenied
from runlab.tech_services_auth import WebsiteTechServicesAuthProvider
from runlab.tech_services_metadata import (
    MetadataSyncResult, fetch_tech_services_events, prioritize_tech_services_events, sync_tech_services_events,
)
from runlab.security import desktop_auth_required
from runlab.simulation_study import ScenarioAxis, SimulationStudyDefinition, run_scenario_sweep, export_study_table, create_scenario_run, package_study_result
from runlab.strip_analysis import analyze_strip
from runlab.legacy_reference import simulate_legacy_reference
from runlab.physics import simulate, SolverOptions
from runlab.model_enrichment import run_rsa_model_enrichment, rebuild_rsa_model_enrichment
from runlab.run_profiles import RUN_PROFILES, profile as run_profile, infer_profile, set_run_profile, resolve_profile_channels, apply_profile_rsa_defaults
from runlab.run_window import fit_window as drag_fit_window
from runlab.shift_report import attach_shift_report, build_shift_report, compare_shift_reports
from runlab.run_workspace import build_run_workspace


APP_ORG = "NHRA"
APP_ID = "NHRA.Velocity"
PROJECT_EXT = ".nhratech"


def _application_icon() -> QtGui.QIcon:
    """Load the bundled product icon without making branding a startup risk."""
    for name in ("nhra-velocity.ico", "nhra-velocity-256.png", "nhra-velocity-64.png"):
        try:
            path = brand_asset(name)
            if path.is_file():
                icon = QtGui.QIcon(str(path))
                if not icon.isNull():
                    return icon
        except Exception:
            logging.exception("Could not load brand asset %s", name)
    return QtGui.QIcon()

# Drag-racing oriented Quick Graphs.  These are canonical-role requests rather
# than vendor channel names, so the same worksheet works across RacePak,
# MoTeC, FuelTech, MaxxECU and synthetic compare sessions when mapped.
QUICK_GRAPH_PRESETS = {
    "Driveline": ["engine_rpm", "driveshaft_rpm", "clutch_rpm", "speed_mph", "longitudinal_g", "gear"],
    "Launch": ["engine_rpm", "driveshaft_rpm", "clutch_rpm", "longitudinal_g", "throttle_pct"],
    "Powertrain": ["engine_rpm", "power_hp", "torque_lbft", "throttle_pct", "boost_psi", "lambda"],
    "Speed / Accel": ["speed_mph", "wheel_speed_mph", "driveshaft_rpm", "longitudinal_g"],
    "Fuel / Air": ["throttle_pct", "boost_psi", "lambda", "afr", "engine_rpm"],
    "Model Validation": ["speed_mph", "model_speed_mph", "residual_speed_mph", "engine_rpm", "model_engine_rpm", "residual_engine_rpm"],
}


def _visible_channel_names(run: TelemetryRun) -> List[str]:
    """Source + user-calculated channels, without private canonical columns."""
    names: List[str] = []
    for name in run.native_channels:
        if name not in names:
            names.append(name)
    for name in run.data.columns:
        if str(name).startswith('__'):
            continue
        if name not in names:
            names.append(str(name))
    return names


def _source_for_canonical(run: TelemetryRun, canonical: str) -> Optional[str]:
    # Measured canonical roles must still survive the importer/unit audit, while
    # derived RSA model/residual roles are resolved through the workstation's
    # explicit virtual-channel registry.
    if canonical in run.channel_map:
        originals = run.metadata.get("original_channel_map", {})
        source = originals.get(canonical)
        if source and (source in run.data.columns or source in run.native_channels):
            return source
        mapped = run.channel_map.get(canonical)
        if mapped and (mapped in run.data.columns or mapped in run.native_channels) and not str(mapped).startswith("__"):
            return mapped
    resolved=resolve_channel(run,canonical)
    return resolved if resolved and not str(resolved).startswith("__") else None


@dataclass
class RunHandle:
    path: str
    run: TelemetryRun
    role: str = "main"  # main | reference | overlay | available
    channel_overrides: Dict[str, str] = field(default_factory=dict)
    unit_overrides: Dict[str, str] = field(default_factory=dict)
    time_alignment_s: float = 0.0
    display_name: str = ""
    catalog_run_id: str = ""
    catalog_asset_id: str = ""
    catalog_session_id: str = ""

    @property
    def label(self) -> str:
        return self.display_name.strip() or Path(self.path).stem or self.run.name

    @property
    def compare_key(self) -> str:
        """Stable-enough workbook identity for display-only Compare Sets.

        Authoritative Tech Services Runs use the server Run ID. Scratch/local
        sessions fall back to their resolved file path; this key never creates
        or infers a server Run relationship.
        """
        if self.catalog_run_id:
            return f"run:{self.catalog_run_id}"
        if self.path:
            try:
                return f"file:{Path(self.path).expanduser().resolve()}"
            except Exception:
                return f"file:{self.path}"
        return f"scratch:{self.run.name}"


class TechServicesSeasonSyncWorker(QtCore.QObject):
    """Background Tech Services metadata sync with a useful-first event pass."""

    firstEventReady = QtCore.Signal(object, str)
    progress = QtCore.Signal(int, int, str)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, catalog, client, season_year: int, *, include_entries: bool = True, include_runs: bool = True):
        super().__init__()
        self.catalog = catalog
        self.client = client
        self.season_year = int(season_year)
        self.include_entries = bool(include_entries)
        self.include_runs = bool(include_runs)

    @QtCore.Slot()
    def run(self):
        try:
            events = prioritize_tech_services_events(fetch_tech_services_events(self.client, self.season_year))
            total = MetadataSyncResult(season_year=self.season_year)
            if not events:
                self.finished.emit(total)
                return
            count = len(events)
            for index, event in enumerate(events, start=1):
                name = str(event.get('name') or event.get('event_code') or event.get('race_lookup') or 'NHRA Event')
                part = sync_tech_services_events(
                    self.catalog,
                    self.client,
                    self.season_year,
                    [event],
                    include_entries=self.include_entries,
                    include_runs=self.include_runs,
                )
                total.merge(part)
                if index == 1:
                    self.firstEventReady.emit(part, name)
                self.progress.emit(index, count, name)
            self.finished.emit(total)
        except Exception as exc:
            logging.exception('Background Tech Services metadata sync failed')
            self.failed.emit(str(exc))


class SessionStore(QtCore.QObject):
    changed = QtCore.Signal()
    activeChanged = QtCore.Signal(object)

    def __init__(self):
        super().__init__()
        self.runs: List[RunHandle] = []
        self.active_index: int = -1

    @property
    def active(self) -> Optional[RunHandle]:
        if 0 <= self.active_index < len(self.runs):
            return self.runs[self.active_index]
        return None

    def add(self, path: str, run: TelemetryRun, *, activate: bool = False, apply_preferences: bool = True) -> RunHandle:
        # Apply vendor-scoped common-channel mappings that the engineer has
        # explicitly taught Velocity on earlier data sets. Automatic importer
        # mappings still exist underneath; learned mappings win only when their
        # exact source channel is present and dimensionally safe.
        learned = learned_common_channel_overrides(run) if apply_preferences else {}
        if learned:
            run = apply_channel_overrides(run, learned, {})
        first = not self.runs
        h = RunHandle(str(path), run, "main" if first else "available", display_name=Path(path).stem, channel_overrides=dict(learned))
        self.runs.append(h)
        if first:
            self.active_index = 0
        elif activate:
            for existing in self.runs[:-1]:
                if existing.role == "main":
                    existing.role = "available"
            self.active_index = len(self.runs) - 1
            h.role = "main"
        self.changed.emit()
        self.activeChanged.emit(self.active)
        return h

    def set_active(self, index: int):
        if not (0 <= index < len(self.runs)):
            return
        self.active_index = index
        for i, h in enumerate(self.runs):
            if h.role == "main":
                h.role = "available"
        self.runs[index].role = "main"
        self.changed.emit()
        self.activeChanged.emit(self.active)

    def overlays(self) -> List[RunHandle]:
        return [h for i, h in enumerate(self.runs) if i == self.active_index or h.role in ("reference", "overlay")]


class RunBrowser(QtWidgets.QWidget):
    """Mirror of authoritative NHRA Tech Services runs.

    Runs own their assets on the website/database. The desktop never matches or
    attaches arbitrary files to a run; it only opens or caches assets already
    present in that run's Tech Services manifest.
    """
    openRunRequested = QtCore.Signal(str)
    keepOfflineRequested = QtCore.Signal(str)
    keepEventOfflineRequested = QtCore.Signal(str)
    analysisCaseRequested = QtCore.Signal(str)
    attachTelemetryRequested = QtCore.Signal(str)
    runSelectionChanged = QtCore.Signal(str)
    syncRequested = QtCore.Signal()

    def __init__(self, catalog: LocalCatalog):
        super().__init__(); self.catalog=catalog
        lay=QtWidgets.QVBoxLayout(self);lay.setContentsMargins(4,4,4,4)
        filter_row=QtWidgets.QHBoxLayout()
        self.search=QtWidgets.QLineEdit();self.search.setPlaceholderText('Search drivers / classes / runs…')
        self.event_scope=QtWidgets.QComboBox();self.event_scope.addItem('Current / last completed','latest');self.event_scope.addItem('All events','all');self.event_scope.setToolTip('Shows the current event when one is underway; otherwise the most recently completed synchronized event. Searching automatically spans all synchronized events.')
        filter_row.addWidget(self.search,1);filter_row.addWidget(self.event_scope);lay.addLayout(filter_row)
        self.tree=QtWidgets.QTreeWidget();self.tree.setHeaderLabels(['Run / Event','Driver','Class','Round','ET','MPH','Data'])
        self.tree.setColumnWidth(0,185);self.tree.setColumnWidth(1,120);self.tree.setColumnWidth(2,112);self.tree.setColumnWidth(3,48);self.tree.setColumnWidth(4,54);self.tree.setColumnWidth(5,60);self.tree.setColumnWidth(6,48)
        self.tree.setAlternatingRowColors(True);self.tree.itemDoubleClicked.connect(self._double);self.tree.currentItemChanged.connect(self._selection_changed);lay.addWidget(self.tree,1)
        self.open_btn=QtWidgets.QPushButton('Open');self.attach_btn=QtWidgets.QPushButton('Attach Data…');self.offline_btn=QtWidgets.QPushButton('Cache');self.incident_btn=QtWidgets.QPushButton('New Case');self.sync_btn=QtWidgets.QPushButton('Sync');self.refresh_btn=QtWidgets.QPushButton('Refresh')
        primary=QtWidgets.QHBoxLayout()
        for b in (self.open_btn,self.attach_btn,self.incident_btn):primary.addWidget(b)
        primary.addStretch(1);lay.addLayout(primary)
        secondary=QtWidgets.QHBoxLayout()
        for b in (self.sync_btn,self.offline_btn,self.refresh_btn):secondary.addWidget(b)
        secondary.addStretch(1);lay.addLayout(secondary)
        self.open_btn.setToolTip('Open the data already attached to the selected Tech Services Run.')
        self.attach_btn.setToolTip('Attach a local data log to the selected authoritative Run.')
        self.sync_btn.setToolTip('Sync current/recent NHRA Tech Services data in the background.')
        self.summary=QtWidgets.QLabel();self.summary.setStyleSheet('color:#9fa6ad;padding:2px');lay.addWidget(self.summary)
        self.search.textChanged.connect(lambda _t:self.refresh());self.event_scope.currentIndexChanged.connect(lambda _i:self.refresh());self.sync_btn.clicked.connect(lambda _checked=False:self.syncRequested.emit());self.refresh_btn.clicked.connect(self.refresh)
        self.open_btn.clicked.connect(lambda:self._emit(self.openRunRequested));self.attach_btn.clicked.connect(lambda:self._emit(self.attachTelemetryRequested));self.offline_btn.clicked.connect(self._offline);self.incident_btn.clicked.connect(lambda:self._emit(self.analysisCaseRequested))
        self.refresh()

    def selected_run_id(self) -> str:
        item=self.tree.currentItem()
        if item is None or item.data(0,QtCore.Qt.UserRole+1)!='run':return ''
        return str(item.data(0,QtCore.Qt.UserRole) or '')

    def selected_event_id(self) -> str:
        item=self.tree.currentItem()
        if item is None:return ''
        if item.data(0,QtCore.Qt.UserRole+1)=='event':return str(item.data(0,QtCore.Qt.UserRole) or '')
        if item.parent() is not None and item.parent().data(0,QtCore.Qt.UserRole+1)=='event':return str(item.parent().data(0,QtCore.Qt.UserRole) or '')
        return ''

    def _offline(self):
        item=self.tree.currentItem()
        if item is None:return
        typ=item.data(0,QtCore.Qt.UserRole+1);ident=str(item.data(0,QtCore.Qt.UserRole) or '')
        if typ=='run':self.keepOfflineRequested.emit(ident)
        elif typ=='event':self.keepEventOfflineRequested.emit(ident)

    def _emit(self,signal):
        rid=self.selected_run_id()
        if rid:signal.emit(rid)

    def _double(self,item,col):
        if item.data(0,QtCore.Qt.UserRole+1)=='run':self.openRunRequested.emit(str(item.data(0,QtCore.Qt.UserRole)))

    def _selection_changed(self,current,previous):
        self.runSelectionChanged.emit(self.selected_run_id())

    @staticmethod
    def _friendly_run_label(record):
        parts=[]
        run_number=record.get('run_number')
        if run_number not in (None,''):
            parts.append(f"Run {run_number}")
        car=str(record.get('car_number') or '').strip()
        if car:
            parts.append(f"#{car}")
        lane=str(record.get('lane') or '').strip()
        if lane:
            lane_label={'l':'Left','left':'Left','r':'Right','right':'Right'}.get(lane.lower(),lane)
            parts.append(lane_label)
        if parts:
            return ' · '.join(parts)
        stamp=str(record.get('run_datetime') or '').replace('T',' ')
        return stamp[11:19] if len(stamp)>=19 else (stamp[:16] or 'Run')

    @staticmethod
    def _trackside_event_order(events, today=None):
        """Current event first; otherwise most recently completed first.

        Future events never win the compact trackside scope merely because they
        have the latest date in the database. Remaining completed events are
        newest-first, then upcoming events nearest-first, then undated rows.
        """
        now = today or date.today()

        def parse(value):
            raw = str(value or '').strip()
            if not raw:
                return None
            try:
                return date.fromisoformat(raw[:10])
            except ValueError:
                return None

        def key(event):
            start = parse(event.get('start_date'))
            end = parse(event.get('end_date')) or start
            if start is not None and end is not None and start <= now <= end:
                return (0, -start.toordinal(), str(event.get('name') or ''))
            if end is not None and end < now:
                return (1, -end.toordinal(), str(event.get('name') or ''))
            if start is not None and start > now:
                return (2, start.toordinal(), str(event.get('name') or ''))
            return (3, 0, str(event.get('name') or ''))

        return sorted(list(events), key=key)

    def refresh(self):
        selected=self.selected_run_id();query=self.search.text().strip();self.tree.clear();total=0
        show_all=(self.event_scope.currentData()=='all') or bool(query)
        try:
            visible_event_index=0
            events=self.catalog.list_events()
            if not show_all:
                events=self._trackside_event_order(events)
            for event in events:
                if not show_all and visible_event_index>=1:
                    break
                if not event.get('remote_id') and str(event.get('sync_state') or '')!='synced':
                    continue
                runs=self.catalog.list_runs(event_id=event['id'],search=query,limit=5000)
                if query and not runs:continue
                label=event['name'] or 'Event'
                if event.get('season'):label=f"{event['season']} — {label}"
                root=QtWidgets.QTreeWidgetItem([label,'','','','','',f'{len(runs)} runs']);root.setData(0,QtCore.Qt.UserRole,str(event['id']));root.setData(0,QtCore.Qt.UserRole+1,'event')
                root.setToolTip(0,str(event.get('name') or 'Event'))
                f=root.font(0);f.setBold(True);root.setFont(0,f);self.tree.addTopLevelItem(root)
                contains_selected=False
                for r in runs:
                    total+=1;run_label=self._friendly_run_label(r)
                    data_logs=int(r.get('data_log_count') or 0);local_logs=int(r.get('local_data_log_count') or 0);et=r.get('et_s');mph=r.get('mph')
                    data_text=(f'{data_logs} local' if local_logs else str(data_logs)) if data_logs else '—'
                    item=QtWidgets.QTreeWidgetItem([run_label,str(r.get('driver_name') or ''),str(r.get('category') or ''),str(r.get('round') or ''),'' if et in (None,'') else f'{float(et):.3f}','' if mph in (None,'') else f'{float(mph):.2f}',data_text])
                    item.setData(0,QtCore.Qt.UserRole,str(r['id']));item.setData(0,QtCore.Qt.UserRole+1,'run')
                    detail=' · '.join(x for x in (str(r.get('remote_id') or ''),str(r.get('run_datetime') or ''),str(r.get('run_key') or '')) if x)
                    if detail:item.setToolTip(0,detail)
                    if data_logs:
                        item.setToolTip(6,f"{data_logs} Run data log(s) attached; {local_logs} available in Velocity local storage.")
                        item.setForeground(6,QtGui.QBrush(QtGui.QColor('#78d381')))
                    root.addChild(item)
                    if str(r['id'])==selected:
                        contains_selected=True;self.tree.setCurrentItem(item)
                root.setExpanded(bool(query) or contains_selected or (visible_event_index==0 and not selected))
                visible_event_index+=1
            stats=self.catalog.stats();scope_text='searching all events' if query else ('all events' if show_all else 'current / last completed')
            self.summary.setText(f"{total} shown • {stats['runs']} cached runs • {stats['assets']} attached files • {scope_text}")
        except Exception as exc:self.summary.setText(f'Catalog error: {exc}')


class AnalysisCaseBrowser(QtWidgets.QWidget):
    """Local engineering workspaces built from authoritative Tech Services Runs."""
    openRunRequested = QtCore.Signal(str)
    addSelectedRunRequested = QtCore.Signal(str)
    cacheCaseRequested = QtCore.Signal(str)
    caseSelectionChanged = QtCore.Signal(str)

    def __init__(self,catalog:LocalCatalog,parent=None):
        super().__init__(parent);self.catalog=catalog
        lay=QtWidgets.QVBoxLayout(self);lay.setContentsMargins(4,4,4,4)
        self.search=QtWidgets.QLineEdit();self.search.setPlaceholderText('Search analysis cases…');lay.addWidget(self.search)
        self.tree=QtWidgets.QTreeWidget();self.tree.setHeaderLabels(['Case / Run','Type / Role','Status / Details','Runs','Evidence','Models'])
        self.tree.setColumnWidth(0,250);self.tree.setColumnWidth(1,115);self.tree.setColumnWidth(2,170)
        self.tree.setAlternatingRowColors(True);self.tree.itemDoubleClicked.connect(self._double);self.tree.currentItemChanged.connect(self._selection_changed);lay.addWidget(self.tree,1)
        row=QtWidgets.QHBoxLayout();self.open_btn=QtWidgets.QPushButton('Open Run');self.add_btn=QtWidgets.QPushButton('Add Selected Run');self.cache_btn=QtWidgets.QPushButton('Cache Case');self.refresh_btn=QtWidgets.QPushButton('Refresh')
        for b in (self.open_btn,self.add_btn,self.cache_btn):row.addWidget(b)
        row.addStretch(1);row.addWidget(self.refresh_btn);lay.addLayout(row)
        note=QtWidgets.QLabel('Cases group multiple authoritative Runs plus incident/performance evidence and derived analysis. Permanent Run/Asset ownership is unchanged.')
        note.setWordWrap(True);note.setStyleSheet('color:#aeb4bb;padding:2px');lay.addWidget(note)
        self.search.textChanged.connect(lambda _t:self.refresh());self.refresh_btn.clicked.connect(self.refresh);self.open_btn.clicked.connect(self._open);self.add_btn.clicked.connect(self._add);self.cache_btn.clicked.connect(self._cache)
        self.refresh()

    def selected_case_id(self)->str:
        item=self.tree.currentItem()
        if item is None:return ''
        if item.data(0,QtCore.Qt.UserRole+1)=='case':return str(item.data(0,QtCore.Qt.UserRole) or '')
        if item.parent() is not None and item.parent().data(0,QtCore.Qt.UserRole+1)=='case':return str(item.parent().data(0,QtCore.Qt.UserRole) or '')
        return ''

    def selected_run_id(self)->str:
        item=self.tree.currentItem()
        if item is None or item.data(0,QtCore.Qt.UserRole+1)!='case_run':return ''
        return str(item.data(0,QtCore.Qt.UserRole) or '')

    def _open(self):
        rid=self.selected_run_id()
        if rid:self.openRunRequested.emit(rid);return
        cid=self.selected_case_id();case=self.catalog.get_analysis_case(cid) if cid else None
        if case and case.get('primary_run_id'):self.openRunRequested.emit(str(case['primary_run_id']))

    def _add(self):
        cid=self.selected_case_id()
        if cid:self.addSelectedRunRequested.emit(cid)

    def _cache(self):
        cid=self.selected_case_id()
        if cid:self.cacheCaseRequested.emit(cid)

    def _double(self,item,col):
        if item.data(0,QtCore.Qt.UserRole+1)=='case_run':self.openRunRequested.emit(str(item.data(0,QtCore.Qt.UserRole) or ''))
        elif item.data(0,QtCore.Qt.UserRole+1)=='case':
            cid=str(item.data(0,QtCore.Qt.UserRole) or '');case=self.catalog.get_analysis_case(cid)
            if case and case.get('primary_run_id'):self.openRunRequested.emit(str(case['primary_run_id']))

    def _selection_changed(self,current,previous):
        self.caseSelectionChanged.emit(self.selected_case_id())

    def refresh(self):
        selected=self.selected_case_id();query=self.search.text().strip().lower();self.tree.clear()
        for case in self.catalog.list_analysis_cases(limit=5000):
            hay=' '.join(str(case.get(k) or '') for k in ('title','case_type','status','summary')).lower();runs=self.catalog.list_case_runs(str(case['id']))
            if query and query not in hay and not any(query in ' '.join(str(r.get(k) or '') for k in ('run_key','driver_name','event_name','category','round')).lower() for r in runs):continue
            label=str(case.get('title') or 'Analysis Case');kind=str(case.get('case_type') or 'engineering').replace('_',' ').title()
            root=QtWidgets.QTreeWidgetItem([label,kind,str(case.get('status') or ''),str(case.get('run_count') or 0),str(case.get('evidence_count') or 0),str(case.get('model_count') or 0)])
            root.setData(0,QtCore.Qt.UserRole,str(case['id']));root.setData(0,QtCore.Qt.UserRole+1,'case');f=root.font(0);f.setBold(True);root.setFont(0,f);root.setToolTip(0,str(case.get('summary') or case['id']));self.tree.addTopLevelItem(root)
            for r in runs:
                run_label=str(r.get('run_key') or r.get('run_datetime') or r['id']);detail=' — '.join(x for x in (str(r.get('driver_name') or ''),str(r.get('category') or ''),str(r.get('round') or '')) if x)
                child=QtWidgets.QTreeWidgetItem([run_label,str(r.get('role') or 'reference'),detail,'','',''])
                child.setData(0,QtCore.Qt.UserRole,str(r['id']));child.setData(0,QtCore.Qt.UserRole+1,'case_run');root.addChild(child)
            root.setExpanded(bool(query))
            if str(case['id'])==selected:self.tree.setCurrentItem(root)


class CaseTimelineBrowser(QtWidgets.QWidget):
    """Auditable Asset→Run→Case time synchronization and case markers."""
    def __init__(self,catalog:LocalCatalog,parent=None):
        super().__init__(parent);self.catalog=catalog;self.case_id=''
        lay=QtWidgets.QVBoxLayout(self);lay.setContentsMargins(4,4,4,4)
        self.title=QtWidgets.QLabel('Select an Analysis Case');self.title.setWordWrap(True);lay.addWidget(self.title)
        self.tree=QtWidgets.QTreeWidget();self.tree.setHeaderLabels(['Source / Marker','Type / Role','Time Mapping / Case Time','Method / Domain','Uncertainty'])
        self.tree.setColumnWidth(0,245);self.tree.setColumnWidth(1,105);self.tree.setColumnWidth(2,235);self.tree.setColumnWidth(3,145);self.tree.setAlternatingRowColors(True);lay.addWidget(self.tree,1)
        row=QtWidgets.QHBoxLayout();self.align_btn=QtWidgets.QPushButton('Align Run…');self.map_btn=QtWidgets.QPushButton('Map Asset…');self.marker_btn=QtWidgets.QPushButton('Add Marker…');self.delete_btn=QtWidgets.QPushButton('Delete Marker');self.refresh_btn=QtWidgets.QPushButton('Refresh')
        for b in (self.align_btn,self.map_btn,self.marker_btn,self.delete_btn):row.addWidget(b)
        row.addStretch(1);row.addWidget(self.refresh_btn);lay.addLayout(row)
        note=QtWidgets.QLabel('Time is composed as Asset clock → Run clock → Case clock. Mappings change only analysis coordinates; raw evidence is never rewritten.')
        note.setWordWrap(True);note.setStyleSheet('color:#aeb4bb;padding:2px');lay.addWidget(note)
        self.align_btn.clicked.connect(self._align_run);self.map_btn.clicked.connect(self._map_asset);self.marker_btn.clicked.connect(self._add_marker);self.delete_btn.clicked.connect(self._delete_marker);self.refresh_btn.clicked.connect(self.refresh)

    def set_case(self,case_id:str):
        self.case_id=str(case_id or '');self.refresh()

    def _selected(self):
        item=self.tree.currentItem()
        if item is None:return '', ''
        return str(item.data(0,QtCore.Qt.UserRole+1) or ''),str(item.data(0,QtCore.Qt.UserRole) or '')

    def _selected_run_id(self)->str:
        item=self.tree.currentItem()
        if item is None:return ''
        typ=str(item.data(0,QtCore.Qt.UserRole+1) or '')
        if typ=='case_run':return str(item.data(0,QtCore.Qt.UserRole) or '')
        if typ=='asset' and item.parent() is not None:return str(item.parent().data(0,QtCore.Qt.UserRole) or '')
        return ''

    @staticmethod
    def _pairs(text:str,left_name:str,right_name:str):
        out=[]
        for line in str(text or '').replace(';','\n').splitlines():
            line=line.strip()
            if not line:continue
            if '=' in line:a,b=line.split('=',1)
            elif ',' in line:a,b=line.split(',',1)
            else:raise ValueError(f"Use {left_name} = {right_name}, one anchor per line")
            out.append((float(a.strip()),float(b.strip())))
        if not out:raise ValueError('At least one synchronization anchor is required')
        return out

    def _align_run(self):
        if not self.case_id:return
        run_id=self._selected_run_id()
        if not run_id:QtWidgets.QMessageBox.information(self,'Case Timeline','Select a Run or one of its Assets first.');return
        current=self.catalog.get_case_run_alignment(self.case_id,run_id) or {}
        existing=current.get('anchors') or []
        default='\n'.join(f"{a.get('run_time_s',0):g} = {a.get('case_time_s',0):g}" for a in existing) or '0 = 0'
        text,ok=QtWidgets.QInputDialog.getMultiLineText(self,'Align Run to Case','Enter anchors as  run_time = case_time\nRun seconds are never stretched; 2+ anchors quantify alignment uncertainty.',default)
        if not ok:return
        try:
            pairs=self._pairs(text,'run_time','case_time');alignment=fit_case_run_alignment([CaseTimeAnchor(a,b) for a,b in pairs],method='manual case anchors');store_case_run_alignment(self.catalog,self.case_id,run_id,alignment);self.refresh()
        except Exception as exc:QtWidgets.QMessageBox.warning(self,'Case Timeline',str(exc))

    def _map_asset(self):
        if not self.case_id:return
        typ,asset_id=self._selected()
        if typ!='asset':QtWidgets.QMessageBox.information(self,'Case Timeline','Select an Asset under a case Run first.');return
        current=self.catalog.get_time_mapping(asset_id) or {};existing=current.get('anchors') or []
        default='\n'.join(f"{a.get('asset_time_s',0):g} = {a.get('run_time_s',0):g}" for a in existing) or '0 = 0'
        text,ok=QtWidgets.QInputDialog.getMultiLineText(self,'Map Asset to Run','Enter anchors as  asset_time = run_time\nOne anchor sets offset; 2+ also fit clock scale/drift.',default)
        if not ok:return
        try:
            pairs=self._pairs(text,'asset_time','run_time');mapping=fit_time_mapping([TimeAnchor(a,b) for a,b in pairs],method='manual asset anchors')
            self.catalog.update_time_mapping(asset_id,scale=mapping.scale,offset_s=mapping.offset_s,method=mapping.method,confidence=mapping.confidence,uncertainty_s=mapping.uncertainty_s,anchors=[{'asset_time_s':a.asset_time_s,'run_time_s':a.run_time_s} for a in mapping.anchors]);self.refresh()
        except Exception as exc:QtWidgets.QMessageBox.warning(self,'Case Timeline',str(exc))

    def _add_marker(self):
        if not self.case_id:return
        typ,ident=self._selected();run_id=self._selected_run_id();domain='case';asset_id=None
        if typ=='asset':domain='asset';asset_id=ident
        elif typ=='case_run':domain='run'
        label,ok=QtWidgets.QInputDialog.getText(self,'Case Marker','Marker label:')
        if not ok or not label.strip():return
        kind,ok=QtWidgets.QInputDialog.getItem(self,'Case Marker','Type:',['marker','impact','launch','shift','chute','failure','note'],0,False)
        if not ok:return
        times,ok=QtWidgets.QInputDialog.getText(self,'Case Marker',f'{domain.title()} time — enter start or start,end:',text='0')
        if not ok:return
        try:
            vals=[float(x.strip()) for x in times.split(',') if x.strip()];
            if not vals:raise ValueError('Enter a marker time')
            self.catalog.create_case_marker(self.case_id,label=label.strip(),start_s=vals[0],end_s=vals[1] if len(vals)>1 else None,kind=str(kind),time_domain=domain,run_id=run_id or None,asset_id=asset_id);self.refresh()
        except Exception as exc:QtWidgets.QMessageBox.warning(self,'Case Marker',str(exc))

    def _delete_marker(self):
        typ,ident=self._selected()
        if typ!='marker':return
        self.catalog.delete_case_marker(ident);self.refresh()

    @staticmethod
    def _uncertainty(value):
        return '' if value is None else f'±{float(value):.4f} s'

    def refresh(self):
        self.tree.clear()
        if not self.case_id:self.title.setText('Select an Analysis Case');return
        case=self.catalog.get_analysis_case(self.case_id)
        if not case:self.title.setText('Analysis Case not found');return
        self.title.setText(f"{case.get('title') or 'Analysis Case'} — shared case timeline")
        for run in self.catalog.list_case_runs(self.case_id):
            scale=float(run.get('time_scale') or 1.0);offset=float(run.get('time_offset_s') or 0.0);mapping=f"case = {scale:.7g} × run {offset:+.6g} s"
            name=str(run.get('run_key') or run.get('driver_name') or run['id']);root=QtWidgets.QTreeWidgetItem([name,str(run.get('role') or 'reference'),mapping,str(run.get('alignment_method') or 'run_time'),self._uncertainty(run.get('alignment_uncertainty_s'))])
            root.setData(0,QtCore.Qt.UserRole,str(run['id']));root.setData(0,QtCore.Qt.UserRole+1,'case_run');f=root.font(0);f.setBold(True);root.setFont(0,f);self.tree.addTopLevelItem(root)
            for asset in self.catalog.list_assets(str(run['id'])):
                tm=self.catalog.get_time_mapping(str(asset['id']))
                if tm:mapping=f"run = {float(tm.get('scale') or 1):.7g} × asset {float(tm.get('offset_s') or 0):+.6g} s";method=str(tm.get('method') or '');unc=self._uncertainty(tm.get('uncertainty_s'))
                else:mapping='not mapped';method='';unc=''
                child=QtWidgets.QTreeWidgetItem([str(asset.get('filename') or asset['id']),str(asset.get('asset_type') or ''),mapping,method,unc]);child.setData(0,QtCore.Qt.UserRole,str(asset['id']));child.setData(0,QtCore.Qt.UserRole+1,'asset');root.addChild(child)
            root.setExpanded(True)
        markers=self.catalog.list_case_markers(self.case_id)
        if markers:
            group=QtWidgets.QTreeWidgetItem(['Case Markers','','','','']);f=group.font(0);f.setBold(True);group.setFont(0,f);self.tree.addTopLevelItem(group)
            for marker in markers:
                start=float(marker['case_start_s']);end=marker.get('case_end_s');stamp=f'{start:.4f} s' if end is None else f'{start:.4f} → {float(end):.4f} s'
                child=QtWidgets.QTreeWidgetItem([str(marker.get('label') or ''),str(marker.get('kind') or 'marker'),stamp,str(marker.get('time_domain') or 'case'),'']);child.setData(0,QtCore.Qt.UserRole,str(marker['id']));child.setData(0,QtCore.Qt.UserRole+1,'marker');group.addChild(child)
            group.setExpanded(True)


class SynchronizedReviewPanel(QtWidgets.QWidget):
    """One Case-time cursor for media, numeric evidence and Run telemetry."""
    caseTimeChanged = QtCore.Signal(str, float)
    cacheAssetRequested = QtCore.Signal(str)

    def __init__(self,catalog:LocalCatalog,parent=None):
        super().__init__(parent);self.catalog=catalog;self.case_id='';self.controller=None;self._updating=False;self._playing=False;self._last_tick=None;self._selected_asset_id='';self._numeric_runs={};self._media_asset_id=''
        lay=QtWidgets.QVBoxLayout(self);lay.setContentsMargins(4,4,4,4)
        self.title=QtWidgets.QLabel('Select an Analysis Case');self.title.setWordWrap(True);lay.addWidget(self.title)
        ctl=QtWidgets.QHBoxLayout()
        self.prev_marker=QtWidgets.QToolButton();self.prev_marker.setText('◀ Marker')
        self.back_frame=QtWidgets.QToolButton();self.back_frame.setText('◀ Frame')
        self.play_btn=QtWidgets.QToolButton();self.play_btn.setText('▶')
        self.forward_frame=QtWidgets.QToolButton();self.forward_frame.setText('Frame ▶')
        self.next_marker=QtWidgets.QToolButton();self.next_marker.setText('Marker ▶')
        self.time_spin=QtWidgets.QDoubleSpinBox();self.time_spin.setDecimals(4);self.time_spin.setSingleStep(.01);self.time_spin.setSuffix(' s');self.time_spin.setKeyboardTracking(False);self.time_spin.setMinimumWidth(120)
        self.speed=QtWidgets.QComboBox();self.speed.addItems(['0.25×','0.5×','1×','2×']);self.speed.setCurrentText('1×')
        for w in (self.prev_marker,self.back_frame,self.play_btn,self.forward_frame,self.next_marker,self.time_spin,self.speed):ctl.addWidget(w)
        ctl.addStretch(1);lay.addLayout(ctl)
        self.slider=QtWidgets.QSlider(QtCore.Qt.Horizontal);self.slider.setTracking(True);lay.addWidget(self.slider)
        self.marker_label=QtWidgets.QLabel('');self.marker_label.setStyleSheet('font-weight:600;padding:2px');lay.addWidget(self.marker_label)
        split=QtWidgets.QSplitter(QtCore.Qt.Horizontal);lay.addWidget(split,1)
        left=QtWidgets.QWidget();lv=QtWidgets.QVBoxLayout(left);lv.setContentsMargins(0,0,0,0)
        self.sources=QtWidgets.QTreeWidget();self.sources.setHeaderLabels(['Source','Type','Run time','Asset time','State','Uncertainty']);self.sources.setAlternatingRowColors(True);self.sources.setColumnWidth(0,210);self.sources.setColumnWidth(1,80);lv.addWidget(self.sources,1)
        row=QtWidgets.QHBoxLayout();self.cache_btn=QtWidgets.QPushButton('Cache Selected Source');self.refresh_btn=QtWidgets.QPushButton('Refresh');row.addWidget(self.cache_btn);row.addStretch(1);row.addWidget(self.refresh_btn);lv.addLayout(row);split.addWidget(left)
        right=QtWidgets.QWidget();rv=QtWidgets.QVBoxLayout(right);rv.setContentsMargins(0,0,0,0)
        self.viewer_stack=QtWidgets.QStackedWidget();rv.addWidget(self.viewer_stack,2)
        self.no_view=QtWidgets.QLabel('Select a synchronized media, telemetry, or IDR source.');self.no_view.setAlignment(QtCore.Qt.AlignCenter);self.no_view.setWordWrap(True);self.viewer_stack.addWidget(self.no_view)
        self.numeric_wrap=QtWidgets.QWidget();nv=QtWidgets.QVBoxLayout(self.numeric_wrap);nv.setContentsMargins(0,0,0,0);self.numeric_plot=pg.PlotWidget();self.numeric_plot.showGrid(x=True,y=True,alpha=.18);self.numeric_plot.setLabel('bottom','Case time','s');nv.addWidget(self.numeric_plot,2);self.numeric_table=QtWidgets.QTableWidget(0,4);self.numeric_table.setHorizontalHeaderLabels(['Channel','Value','Unit','Source time']);self.numeric_table.horizontalHeader().setSectionResizeMode(0,QtWidgets.QHeaderView.Stretch);nv.addWidget(self.numeric_table,1);self.viewer_stack.addWidget(self.numeric_wrap)
        if QT_MULTIMEDIA_AVAILABLE:
            self.media_wrap=QtWidgets.QWidget();mv=QtWidgets.QVBoxLayout(self.media_wrap);mv.setContentsMargins(0,0,0,0);self.video_widget=QtMultimediaWidgets.QVideoWidget();self.video_widget.setMinimumHeight(220);mv.addWidget(self.video_widget,1);self.media_status=QtWidgets.QLabel();self.media_status.setWordWrap(True);mv.addWidget(self.media_status);self.viewer_stack.addWidget(self.media_wrap)
            self.media_player=QtMultimedia.QMediaPlayer(self);self.audio_output=QtMultimedia.QAudioOutput(self);self.media_player.setAudioOutput(self.audio_output);self.media_player.setVideoOutput(self.video_widget);self.audio_output.setVolume(.75)
        else:
            self.media_wrap=None;self.media_player=None;self.audio_output=None;self.video_widget=None;self.media_status=None
        split.addWidget(right);split.setStretchFactor(0,2);split.setStretchFactor(1,3)
        note=QtWidgets.QLabel('Case time is authoritative. Media seeks and numeric readouts are derived through the stored Run/Asset mappings; raw evidence is never altered.');note.setWordWrap(True);note.setStyleSheet('color:#aeb4bb;padding:2px');lay.addWidget(note)
        self.timer=QtCore.QTimer(self);self.timer.setInterval(33);self.timer.timeout.connect(self._tick)
        self.slider.valueChanged.connect(self._slider_changed);self.time_spin.valueChanged.connect(self._spin_changed);self.play_btn.clicked.connect(self._toggle_play);self.back_frame.clicked.connect(lambda:self._step_frame(-1));self.forward_frame.clicked.connect(lambda:self._step_frame(1));self.prev_marker.clicked.connect(lambda:self._jump_marker(-1));self.next_marker.clicked.connect(lambda:self._jump_marker(1));self.sources.currentItemChanged.connect(self._source_selected);self.cache_btn.clicked.connect(self._cache_selected);self.refresh_btn.clicked.connect(self.refresh)

    def set_case(self,case_id:str):
        self._stop();self.case_id=str(case_id or '');self._selected_asset_id='';self._media_asset_id='';self._numeric_runs.clear()
        if not self.case_id:
            self.controller=None;self.title.setText('Select an Analysis Case');self.sources.clear();self.viewer_stack.setCurrentWidget(self.no_view);return
        try:self.controller=CasePlaybackController(self.catalog,self.case_id,case_time_s=0.0)
        except Exception as exc:self.controller=None;self.title.setText(str(exc));return
        self._configure_range();self.refresh();self._set_time(self.controller.case_time_s,emit=False)

    def _configure_range(self):
        if not self.controller:return
        lo,hi=self.controller.minimum_s,self.controller.maximum_s;self._updating=True
        try:
            self.time_spin.setRange(lo,hi);self.slider.setRange(int(round(lo*1000)),int(round(hi*1000)))
        finally:self._updating=False

    def _speed_value(self):
        try:return float(self.speed.currentText().replace('×',''))
        except Exception:return 1.0

    def _slider_changed(self,value):
        if not self._updating:self._set_time(float(value)/1000.0)

    def _spin_changed(self,value):
        if not self._updating:self._set_time(float(value))

    def _set_time(self,value,*,emit=True):
        if not self.controller:return
        frame=self.controller.set_time(float(value));self._updating=True
        try:self.time_spin.setValue(frame.case_time_s);self.slider.setValue(int(round(frame.case_time_s*1000)))
        finally:self._updating=False
        self._render_frame(frame)
        if emit:self.caseTimeChanged.emit(self.case_id,frame.case_time_s)

    def _render_frame(self,frame):
        selected=self._selected_asset_id;self.sources.clear();selected_item=None
        for src in frame.sources:
            at='—' if src.asset_time_s is None else f'{src.asset_time_s:.4f} s';state=[]
            state.append('cached' if src.cached else 'remote')
            if not src.mapped:state.append('unmapped')
            elif src.in_range is False:state.append('outside source')
            elif src.in_range is True:state.append('in range')
            unc='' if src.mapping_uncertainty_s is None else f'±{src.mapping_uncertainty_s:.4f} s'
            item=QtWidgets.QTreeWidgetItem([src.filename,src.source_kind,f'{src.run_time_s:.4f} s',at,', '.join(state),unc]);item.setData(0,QtCore.Qt.UserRole,src.asset_id);item.setData(0,QtCore.Qt.UserRole+1,src.source_kind);self.sources.addTopLevelItem(item)
            if src.asset_id==selected:selected_item=item
        if selected_item is not None:self.sources.setCurrentItem(selected_item)
        labels=[str(m.get('label') or m.get('kind') or 'marker') for m in frame.active_markers];self.marker_label.setText('Active: '+', '.join(labels) if labels else '')
        self._refresh_selected_view(frame)

    def _source_selected(self,current,previous):
        self._selected_asset_id='' if current is None else str(current.data(0,QtCore.Qt.UserRole) or '')
        if self.controller:self._refresh_selected_view(self.controller.frame())

    def _selected_source(self,frame):
        for src in frame.sources:
            if src.asset_id==self._selected_asset_id:return src
        return None

    def _refresh_selected_view(self,frame):
        src=self._selected_source(frame)
        if src is None:self.viewer_stack.setCurrentWidget(self.no_view);return
        if src.source_kind in ('video','audio'):
            self._show_media(src);return
        if src.source_kind in ('telemetry','idr'):
            self._show_numeric(src);return
        self.no_view.setText(f'{src.filename}\n\nNo synchronized viewer is registered for asset type {src.asset_type!r}.');self.viewer_stack.setCurrentWidget(self.no_view)

    def _show_media(self,src):
        if not QT_MULTIMEDIA_AVAILABLE or self.media_player is None:
            self.no_view.setText('Qt Multimedia is unavailable in this Python environment. The synchronization position is still shown in the source table.');self.viewer_stack.setCurrentWidget(self.no_view);return
        if not src.cached or not src.local_path or not Path(src.local_path).is_file():
            self.no_view.setText(f'{src.filename}\n\nThis source is not cached locally. Cache it before synchronized playback.');self.viewer_stack.setCurrentWidget(self.no_view);return
        if src.asset_time_s is None:
            self.no_view.setText(f'{src.filename}\n\nMap this Asset to its Run before synchronized playback.');self.viewer_stack.setCurrentWidget(self.no_view);return
        if self._media_asset_id!=src.asset_id:
            self.media_player.stop();self.media_player.setSource(QtCore.QUrl.fromLocalFile(src.local_path));self._media_asset_id=src.asset_id
        target=max(0,int(round(src.asset_time_s*1000.0)));delta=abs(int(self.media_player.position())-target)
        if not self._playing or delta>120:self.media_player.setPosition(target)
        self.media_player.setPlaybackRate(self._speed_value())
        if self._playing and src.in_range is not False:self.media_player.play()
        elif not self._playing:self.media_player.pause()
        frame_text='' if src.frame_index is None else f' • frame ≈ {src.frame_index}'
        range_text='' if src.duration_s is None else f' / {src.duration_s:.3f} s'
        self.media_status.setText(f'Asset {src.asset_time_s:.4f} s{range_text}{frame_text} • Run {src.run_time_s:.4f} s • Case {src.case_time_s:.4f} s')
        self.viewer_stack.setCurrentWidget(self.media_wrap)

    def _numeric_run(self,src):
        if src.asset_id in self._numeric_runs:return self._numeric_runs[src.asset_id]
        if not src.cached or not src.local_path or not Path(src.local_path).is_file():raise FileNotFoundError('Cache this source locally before numeric review.')
        path=self.catalog.local_asset_read_path(src.asset_id) or src.local_path
        run=load_telemetry(path);self._numeric_runs[src.asset_id]=run;return run

    def _show_numeric(self,src):
        if src.asset_time_s is None:
            self.no_view.setText(f'{src.filename}\n\nMap this Asset to its Run before synchronized numeric review.');self.viewer_stack.setCurrentWidget(self.no_view);return
        try:run=self._numeric_run(src)
        except Exception as exc:self.no_view.setText(f'{src.filename}\n\nNumeric/IDR decode unavailable: {exc}');self.viewer_stack.setCurrentWidget(self.no_view);return
        channels=choose_default_plot_channels(run)[:4]
        if not channels:channels=list(run.native_channels.keys())[:4]
        self.numeric_plot.clear()
        try:mapping=composed_mapping_for_asset(self.catalog,self.case_id,src.asset_id)
        except Exception:mapping=None
        for ch in channels:
            x,y=channel_xy(run,ch,'Logger Time')
            if mapping is not None:x=mapping.to_case_time(x)
            prepared=prepare_plot_series(x,y,max_points=12000)
            if prepared.output_points>=2:self.numeric_plot.plot(prepared.x,prepared.y,name=ch)
        cursor=pg.InfiniteLine(angle=90,movable=False);cursor.setValue(src.case_time_s);self.numeric_plot.addItem(cursor)
        rows=sample_telemetry_at_asset_time(run,src.asset_time_s,channels=channels or None,max_channels=20);self.numeric_table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            vals=[row['channel'],f"{row['value']:.6g}",row.get('unit',''),f"{row['sample_time_s']:.5f}"]
            for j,val in enumerate(vals):self.numeric_table.setItem(i,j,QtWidgets.QTableWidgetItem(str(val)))
        self.viewer_stack.setCurrentWidget(self.numeric_wrap)

    def _frame_step_s(self):
        if self.controller:
            src=self._selected_source(self.controller.frame())
            if src and src.frame_rate_hz:return 1.0/src.frame_rate_hz
        return .01

    def _step_frame(self,direction):
        if self.controller:self._set_time(self.controller.case_time_s+float(direction)*self._frame_step_s())

    def _jump_marker(self,direction):
        if not self.controller:return
        frame=self.controller.jump_marker(direction);self._set_time(frame.case_time_s)

    def _toggle_play(self):
        if not self.controller:return
        if self._playing:self._stop();return
        self._playing=True;self.play_btn.setText('Ⅱ');self._last_tick=time.perf_counter();self.timer.start()
        if self.media_player is not None:self.media_player.setPlaybackRate(self._speed_value());self.media_player.play()

    def _stop(self):
        self._playing=False;self.timer.stop();self.play_btn.setText('▶');self._last_tick=None
        if getattr(self,'media_player',None) is not None:self.media_player.pause()

    def _tick(self):
        if not self.controller:return
        now=time.perf_counter();last=self._last_tick or now;self._last_tick=now;target=self.controller.case_time_s+(now-last)*self._speed_value()
        if target>=self.controller.maximum_s:self._set_time(self.controller.maximum_s);self._stop();return
        self._set_time(target)

    def _cache_selected(self):
        if self._selected_asset_id:self.cacheAssetRequested.emit(self._selected_asset_id)

    def refresh(self):
        if not self.case_id or self.catalog.get_analysis_case(self.case_id) is None:return
        current=self.controller.case_time_s if self.controller else 0.0;self.controller=CasePlaybackController(self.catalog,self.case_id,case_time_s=current);self._configure_range();case=self.catalog.get_analysis_case(self.case_id) or {};self.title.setText(f"{case.get('title') or 'Analysis Case'} — synchronized review")
        self._set_time(current,emit=False)


class CatalogRunDetails(QtWidgets.QWidget):
    """Read-only canonical run record, independent of whether telemetry is open."""
    def __init__(self,catalog:LocalCatalog,parent=None):
        super().__init__(parent);self.catalog=catalog;self.run_id=''
        lay=QtWidgets.QVBoxLayout(self);lay.setContentsMargins(4,4,4,4)
        self.title=QtWidgets.QLabel('Select a run in Run Browser');self.title.setWordWrap(True);lay.addWidget(self.title)
        self.tree=QtWidgets.QTreeWidget();self.tree.setHeaderLabels(['Field','Value','Source']);self.tree.setAlternatingRowColors(True);self.tree.header().setSectionResizeMode(0,QtWidgets.QHeaderView.ResizeToContents);self.tree.header().setSectionResizeMode(1,QtWidgets.QHeaderView.Stretch);self.tree.header().setSectionResizeMode(2,QtWidgets.QHeaderView.ResizeToContents);lay.addWidget(self.tree,1)

    def set_run(self,run_id:str):
        self.run_id=str(run_id or '');self.refresh()

    def _group(self,label):
        item=QtWidgets.QTreeWidgetItem([label,'','']);font=item.font(0);font.setBold(True);item.setFont(0,font);self.tree.addTopLevelItem(item);return item

    def _row(self,parent,label,value,source=''):
        if value in (None,'',{}):return
        parent.addChild(QtWidgets.QTreeWidgetItem([str(label),str(value),str(source)]))

    def refresh(self):
        self.tree.clear()
        if not self.run_id:self.title.setText('Select a run in Run Browser');return
        run=self.catalog.get_run(self.run_id)
        if not run:self.title.setText(self.run_id);return
        self.title.setText(f"{run.get('event_name') or 'Local'} — {run.get('driver_name') or ''} {run.get('round') or ''}".strip())
        g=self._group('Run Identity')
        for label,key in [('Run key','run_key'),('Driver','driver_name'),('Category','category'),('Car number','car_number'),('Round / session','round'),('Lane','lane'),('Date / time','run_datetime'),('Sync state','sync_state')]:self._row(g,label,run.get(key),'catalog')
        g=self._group('Official Timing')
        labels={'reaction_time_s':'RT','sixty_ft_s':'60 ft','three_thirty_ft_s':'330 ft','eighth_mile_s':'660 ft','eighth_mile_mph':'660 MPH','thousand_ft_s':'1000 ft','thousand_ft_mph':'1000 MPH','quarter_mile_s':'ET','quarter_mile_mph':'MPH','correction_factor':'CF'}
        for key,label in labels.items():self._row(g,label,(run.get('timing') or {}).get(key),run.get('timing_provenance',''))
        if run.get('weather'):
            g=self._group('Weather / Conditions')
            for key,value in run['weather'].items():self._row(g,key,value,run.get('weather_provenance',''))
        if run.get('source'):
            g=self._group('Source / Provenance')
            for key,value in run['source'].items():self._row(g,key,value,'evidence')
        self.tree.expandAll()


class RunWorkspacePanel(QtWidgets.QWidget):
    """Run-first engineering workspace with progressive disclosure.

    The ordinary view stays intentionally compact: official Run context first,
    attached evidence/reports second, engineering/model detail last. Advanced
    actions remain available without occupying permanent screen space.
    """
    openRunRequested = QtCore.Signal(str)
    attachTelemetryRequested = QtCore.Signal(str)
    applyProfileRequested = QtCore.Signal(str, str)
    generateReportRequested = QtCore.Signal(str, str)

    def __init__(self,catalog:LocalCatalog,parent=None):
        super().__init__(parent);self.catalog=catalog;self.run_id='';self.state=None
        lay=QtWidgets.QVBoxLayout(self);lay.setContentsMargins(4,4,4,4)
        self.title=QtWidgets.QLabel('Select an authoritative Run');font=self.title.font();font.setBold(True);font.setPointSize(font.pointSize()+1);self.title.setFont(font);self.title.setWordWrap(True);lay.addWidget(self.title)
        self.subtitle=QtWidgets.QLabel('Official timing, weather and attached data logs stay centered on one Run.');self.subtitle.setWordWrap(True);self.subtitle.setStyleSheet('color:#aeb4bb');lay.addWidget(self.subtitle)

        row=QtWidgets.QHBoxLayout()
        self.open_btn=QtWidgets.QPushButton('Open Data Log')
        self.attach_btn=QtWidgets.QPushButton('Attach Data Log…')
        self.more_btn=QtWidgets.QToolButton();self.more_btn.setText('More ▾');self.more_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.more_menu=QtWidgets.QMenu(self.more_btn)
        self.profile_action=self.more_menu.addAction('Apply Class Layout')
        self.report_action=self.more_menu.addAction('Generate Standard Report')
        self.more_menu.addSeparator();self.refresh_action=self.more_menu.addAction('Refresh')
        self.more_btn.setMenu(self.more_menu)
        row.addWidget(self.open_btn);row.addWidget(self.attach_btn);row.addWidget(self.more_btn);row.addStretch(1);lay.addLayout(row)

        self.tabs=QtWidgets.QTabWidget();lay.addWidget(self.tabs,1)
        self.overview=QtWidgets.QTreeWidget();self.overview.setHeaderLabels(['Field','Value','Unit / Source']);self.overview.setAlternatingRowColors(True);self.overview.header().setSectionResizeMode(0,QtWidgets.QHeaderView.ResizeToContents);self.overview.header().setSectionResizeMode(1,QtWidgets.QHeaderView.Stretch);self.overview.header().setSectionResizeMode(2,QtWidgets.QHeaderView.ResizeToContents);self.tabs.addTab(self.overview,'Summary')

        data_wrap=QtWidgets.QWidget();dv=QtWidgets.QVBoxLayout(data_wrap);dv.setContentsMargins(0,0,0,0)
        evidence_box=QtWidgets.QGroupBox('Attached data');ev=QtWidgets.QVBoxLayout(evidence_box)
        self.assets=QtWidgets.QTableWidget(0,5);self.assets.setHorizontalHeaderLabels(['Type','File','Vendor','Authority','Cache']);self.assets.verticalHeader().setVisible(False);self.assets.horizontalHeader().setSectionResizeMode(1,QtWidgets.QHeaderView.Stretch);ev.addWidget(self.assets)
        dv.addWidget(evidence_box,2)
        reports_box=QtWidgets.QGroupBox('Standard reports');rv=QtWidgets.QVBoxLayout(reports_box)
        self.reports=QtWidgets.QTableWidget(0,3);self.reports.setHorizontalHeaderLabels(['Report','Generated','Status']);self.reports.verticalHeader().setVisible(False);self.reports.horizontalHeader().setSectionResizeMode(0,QtWidgets.QHeaderView.Stretch);rv.addWidget(self.reports)
        dv.addWidget(reports_box,1);self.tabs.addTab(data_wrap,'Data')

        self.engineering=QtWidgets.QTreeWidget();self.engineering.setHeaderLabels(['Engineering / Model','Value','Unit','Provenance']);self.engineering.setAlternatingRowColors(True);self.engineering.header().setSectionResizeMode(0,QtWidgets.QHeaderView.Stretch);self.tabs.addTab(self.engineering,'Engineering')

        self.open_btn.clicked.connect(lambda:self.openRunRequested.emit(self.run_id) if self.run_id else None)
        self.attach_btn.clicked.connect(lambda:self.attachTelemetryRequested.emit(self.run_id) if self.run_id else None)
        self.profile_action.triggered.connect(self._apply_profile);self.report_action.triggered.connect(self._generate_report);self.refresh_action.triggered.connect(self.refresh)
        self._enable_actions(False)

    def _enable_actions(self,enabled:bool):
        for w in (self.open_btn,self.attach_btn,self.more_btn):w.setEnabled(bool(enabled))

    def set_run(self,run_id:str):
        self.run_id=str(run_id or '');self.refresh()

    def _group(self,label):
        item=QtWidgets.QTreeWidgetItem([label,'','']);f=item.font(0);f.setBold(True);item.setFont(0,f);self.overview.addTopLevelItem(item);return item

    def _ov(self,parent,label,value,tail=''):
        if value in (None,'',{}):return
        if isinstance(value,float):value=f'{value:.4f}'.rstrip('0').rstrip('.')
        parent.addChild(QtWidgets.QTreeWidgetItem([str(label),str(value),str(tail)]))

    @staticmethod
    def _value_text(value):
        if isinstance(value,float):return f'{value:.6g}'
        if isinstance(value,(list,tuple,dict)):return json.dumps(value,separators=(',',':'),default=str)
        return str(value if value is not None else '')

    def _apply_profile(self):
        if self.run_id and self.state:self.applyProfileRequested.emit(self.run_id,self.state.profile_key)

    def _generate_report(self):
        if not self.run_id or not self.state:return
        expected=list(self.state.expected_reports)
        if not expected:
            QtWidgets.QMessageBox.information(self,'Run Report',f'No standardized report is defined yet for {self.state.profile_label}.');return
        missing=list(self.state.missing_expected_reports);choices=missing or expected
        report=choices[0]
        if len(choices)>1:
            report,ok=QtWidgets.QInputDialog.getItem(self,'Run Report','Report type:',choices,0,False)
            if not ok:return
        self.generateReportRequested.emit(self.run_id,str(report))

    def refresh(self):
        self.overview.clear();self.assets.setRowCount(0);self.engineering.clear();self.reports.setRowCount(0);self.state=None
        if not self.run_id:
            self.title.setText('Select an authoritative Run');self.subtitle.setText('Official timing, weather and attached data logs stay centered on one Run.');self._enable_actions(False);return
        try:self.state=build_run_workspace(self.catalog,self.run_id)
        except Exception as exc:
            self.title.setText(f'Run workspace unavailable — {exc}');self._enable_actions(False);return
        st=self.state;r=st.run;self._enable_actions(True)
        identity=' · '.join(x for x in (str(r.get('driver_name') or ''),str(r.get('category') or ''),str(r.get('round') or '')) if x)
        self.title.setText(f"{r.get('event_name') or 'Run'} — {identity or r.get('run_key') or self.run_id}")
        if st.expected_reports:
            report_status='report current' if not st.missing_expected_reports else 'report pending'
        else:
            report_status='no standard report'
        self.subtitle.setText(f"{st.profile_label} · {len(st.telemetry_assets)} data log(s) · {report_status}")

        g=self._group('Run')
        for label,key in [('Driver','driver_name'),('Category','category'),('Car number','car_number'),('Round','round'),('Lane','lane'),('Date / time','run_datetime')]:self._ov(g,label,r.get(key),'Tech Services' if r.get('sync_state')=='synced' else 'catalog')
        g=self._group('Official Timing')
        for rec in st.timing:self._ov(g,rec.label,rec.value,f'{rec.unit} · {rec.provenance}'.strip(' ·'))
        primary_weather={'temperature_f','barometer_inhg','humidity_pct','wind_mph','wind_angle_deg'}
        weather_rows=[rec for rec in st.weather if rec.key in primary_weather]
        if weather_rows:
            g=self._group('Weather')
            for rec in weather_rows:self._ov(g,rec.label,rec.value,f'{rec.unit} · {rec.provenance}'.strip(' ·'))
        self.overview.expandAll()

        self.assets.setRowCount(len(st.assets))
        for row,a in enumerate(st.assets):
            meta=a.get('metadata') or {};mapping=self.catalog.get_time_mapping(str(a['id'])) or {}
            authority='Tech Services' if a.get('source_kind')=='tech_services' else ('Local Run attachment' if meta.get('attachment_mode')=='local_working_copy' else str(a.get('source_kind') or 'local'))
            cached='verified' if a.get('storage_mode')=='managed' and self.catalog.asset_cache_valid(str(a['id'])) else ('local' if a.get('local_path') else 'remote')
            tm='' if not mapping else f"run = {float(mapping.get('scale') or 1):.7g}×asset {float(mapping.get('offset_s') or 0):+.4f}s"
            vals=(a.get('asset_type',''),a.get('filename',''),a.get('vendor',''),authority,cached)
            for col,val in enumerate(vals):
                item=QtWidgets.QTableWidgetItem(str(val or ''))
                detail=' · '.join(x for x in (str(a.get('remote_id') or ''),tm) if x)
                if detail:item.setToolTip(detail)
                self.assets.setItem(row,col,item)

        current=self.engineering.invisibleRootItem()
        measured=QtWidgets.QTreeWidgetItem(['Run values','','','']);f=measured.font(0);f.setBold(True);measured.setFont(0,f);current.addChild(measured)
        for rec in st.engineering:
            measured.addChild(QtWidgets.QTreeWidgetItem([str(rec.get('key') or ''),self._value_text(rec.get('value')),str(rec.get('unit') or ''),str(rec.get('provenance') or '')]))
        defaults=QtWidgets.QTreeWidgetItem([f'{st.profile_label} standard inputs','','','class defaults']);f=defaults.font(0);f.setBold(True);defaults.setFont(0,f);current.addChild(defaults)
        for rec in st.profile_defaults:defaults.addChild(QtWidgets.QTreeWidgetItem([rec.label,self._value_text(rec.value),rec.unit,rec.provenance]))
        if st.model_snapshots:
            models=QtWidgets.QTreeWidgetItem(['Model snapshots','','','']);f=models.font(0);f.setBold(True);models.setFont(0,f);current.addChild(models)
            for rec in st.model_snapshots:
                q=rec.get('quality') or {};qtext=', '.join(f'{k}={v}' for k,v in list(q.items())[:2])
                label=str(rec.get('name') or rec.get('model_type') or 'Model snapshot')
                value=' · '.join(x for x in (str(rec.get('model_type') or ''),str(rec.get('model_version') or '')) if x)
                models.addChild(QtWidgets.QTreeWidgetItem([label,value,'',qtext or str(rec.get('created_at') or '')]))
        self.engineering.expandAll()

        self.reports.setRowCount(len(st.reports))
        first_by_type={}
        for rec in st.reports:first_by_type.setdefault(str(rec.get('report_type') or ''),rec)
        for row,rec in enumerate(st.reports):
            rtype=str(rec.get('report_type') or '')
            comp=st.report_comparisons.get(rtype) if first_by_type.get(rtype) is rec else None
            status='—';tooltip=[]
            if comp is not None:
                alerts=int(comp.get('alerts') or 0);status=f'CHECK {alerts}' if alerts else 'stable'
                prev=' · '.join(x for x in (str(comp.get('previous_event_name') or ''),str(comp.get('previous_run_key') or ''),str(comp.get('previous_run_datetime') or '')) if x)
                if prev:tooltip.append('Previous: '+prev)
                for rr in comp.get('rows') or []:
                    dr=rr.get('delta_rpm');dt=rr.get('delta_time_s')
                    if dr is not None or dt is not None:tooltip.append(f"Shift {rr.get('shift')}: ΔRPM={'' if dr is None else f'{float(dr):+.0f}'}, Δt={'' if dt is None else f'{float(dt):+.4f}s'}")
            generated=rec.get('generated_at') or rec.get('created_at','')
            vals=(rtype,generated,status)
            detail='\n'.join(tooltip+[f"Profile: {rec.get('profile','')}",f"Version: {rec.get('report_version','')}",f"Fingerprint: {str(rec.get('fingerprint_sha256') or '')[:12]}"])
            for col,val in enumerate(vals):
                item=QtWidgets.QTableWidgetItem(str(val or ''));item.setToolTip(detail)
                if col==2 and str(val).startswith('CHECK'):item.setForeground(QtGui.QColor('#ffb454'))
                self.reports.setItem(row,col,item)


class AssetBrowser(QtWidgets.QWidget):
    """Evidence/media assets attached to the selected canonical run."""
    def __init__(self,catalog:LocalCatalog,parent=None):
        super().__init__(parent);self.catalog=catalog;self.run_id=''
        lay=QtWidgets.QVBoxLayout(self);lay.setContentsMargins(4,4,4,4)
        self.title=QtWidgets.QLabel('Select a run in Run Browser');self.title.setWordWrap(True);lay.addWidget(self.title)
        self.table=QtWidgets.QTableWidget(0,9);self.table.setHorizontalHeaderLabels(['Type','File','Authority','Cache','Vendor','Remote ID','Offset [s]','Clock scale','Method']);self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows);self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection);self.table.verticalHeader().setVisible(False);self.table.horizontalHeader().setSectionResizeMode(1,QtWidgets.QHeaderView.Stretch);lay.addWidget(self.table,1)
        row=QtWidgets.QHBoxLayout();self.edit=QtWidgets.QPushButton('Edit Time Mapping…');self.verify=QtWidgets.QPushButton('Verify Cached Hash');self.refresh_btn=QtWidgets.QPushButton('Refresh');row.addWidget(self.edit);row.addWidget(self.verify);row.addStretch(1);row.addWidget(self.refresh_btn);lay.addLayout(row)
        self.edit.clicked.connect(self._edit_mapping);self.verify.clicked.connect(self._verify);self.refresh_btn.clicked.connect(self.refresh)

    def set_run(self,run_id:str):
        self.run_id=str(run_id or '');self.refresh()

    def selected_asset_id(self)->str:
        r=self.table.currentRow()
        if r<0:return ''
        item=self.table.item(r,0);return str(item.data(QtCore.Qt.UserRole) or '') if item else ''

    def refresh(self):
        self.table.setRowCount(0)
        if not self.run_id:self.title.setText('Select a run in Run Browser');return
        run=self.catalog.get_run(self.run_id);self.title.setText(f"{run.get('event_name') or 'Local'} — {run.get('run_key') or run.get('run_datetime') or self.run_id}" if run else self.run_id)
        assets=self.catalog.list_assets(self.run_id);self.table.setRowCount(len(assets))
        for r,a in enumerate(assets):
            mapping=self.catalog.get_time_mapping(a['id']) or {}
            meta=a.get('metadata') or {}
            authority='Tech Services' if a.get('source_kind')=='tech_services' else ('Local working attachment' if meta.get('attachment_mode')=='local_working_copy' else 'Local scratch/development')
            if a.get('source_kind')=='tech_services':
                cache_state='cached' if self.catalog.asset_cache_valid(str(a['id'])) else 'remote'
            else:
                cache_state='managed local' if a.get('storage_mode')=='managed' and self.catalog.asset_cache_valid(str(a['id'])) else ('external local' if a.get('local_path') else 'missing')
            vals=[a.get('asset_type',''),a.get('filename',''),authority,cache_state,a.get('vendor',''),a.get('remote_id',''),mapping.get('offset_s',''),mapping.get('scale',''),mapping.get('method','')]
            for c,v in enumerate(vals):
                item=QtWidgets.QTableWidgetItem(str(v if v is not None else ''))
                if c==0:item.setData(QtCore.Qt.UserRole,str(a['id']))
                self.table.setItem(r,c,item)

    def _edit_mapping(self):
        aid=self.selected_asset_id()
        if not aid:return
        current=self.catalog.get_time_mapping(aid) or {'scale':1.0,'offset_s':0.0,'method':'manual','confidence':None,'uncertainty_s':None,'anchors':[]}
        dlg=QtWidgets.QDialog(self);dlg.setWindowTitle('Asset → Run Time Mapping');form=QtWidgets.QFormLayout(dlg)
        scale=QtWidgets.QDoubleSpinBox();scale.setDecimals(9);scale.setRange(.5,1.5);scale.setSingleStep(.000001);scale.setValue(float(current.get('scale',1.0) or 1.0))
        offset=QtWidgets.QDoubleSpinBox();offset.setDecimals(6);offset.setRange(-86400,86400);offset.setValue(float(current.get('offset_s',0.0) or 0.0))
        method=QtWidgets.QLineEdit(str(current.get('method') or 'manual'))
        confidence=QtWidgets.QDoubleSpinBox();confidence.setDecimals(3);confidence.setRange(-1,1);confidence.setSpecialValueText('Unknown');confidence.setValue(float(current.get('confidence')) if current.get('confidence') is not None else -1)
        uncertainty=QtWidgets.QDoubleSpinBox();uncertainty.setDecimals(6);uncertainty.setRange(-1,3600);uncertainty.setSpecialValueText('Unknown');uncertainty.setValue(float(current.get('uncertainty_s')) if current.get('uncertainty_s') is not None else -1)
        formula=QtWidgets.QLabel('Run Time = Asset Time × scale + offset\nTwo synchronization anchors later allow scale/drift to be solved automatically.');formula.setWordWrap(True)
        for label,w in [('Clock scale',scale),('Offset [s]',offset),('Method / provenance',method),('Confidence [0–1]',confidence),('Uncertainty [s]',uncertainty)]:form.addRow(label,w)
        form.addRow(formula);bb=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel);bb.accepted.connect(dlg.accept);bb.rejected.connect(dlg.reject);form.addRow(bb)
        if dlg.exec()!=QtWidgets.QDialog.Accepted:return
        self.catalog.update_time_mapping(aid,scale=scale.value(),offset_s=offset.value(),method=method.text().strip() or 'manual',confidence=None if confidence.value()<0 else confidence.value(),uncertainty_s=None if uncertainty.value()<0 else uncertainty.value(),anchors=current.get('anchors',[]));self.refresh()

    def _verify(self):
        aid=self.selected_asset_id()
        if not aid:return
        a=self.catalog.get_asset(aid)
        if not a:return
        if not a.get('sha256'):QtWidgets.QMessageBox.information(self,'Verify Cached Hash','This asset has no authoritative SHA-256 to verify.');return
        ok=self.catalog.asset_cache_valid(aid)
        QtWidgets.QMessageBox.information(self,'Verify Cached Hash','PASS — cached bytes match the authoritative SHA-256.' if ok else 'FAIL — asset is not cached or its hash does not match.')


class ChannelTree(QtWidgets.QTreeWidget):
    channelActivated = QtCore.Signal(str)
    channelPropertiesRequested = QtCore.Signal(str)
    channelAliasRequested = QtCore.Signal(str)
    commonChannelRequested = QtCore.Signal(str)
    channelFavoriteRequested = QtCore.Signal(str, bool)
    calculatedChannelEditRequested = QtCore.Signal(str)
    calculatedChannelDeleteRequested = QtCore.Signal(str)
    channelRemoveRequested = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self.setHeaderLabels(["Parameter", "Alias", "Unit", "Hz", "Common Channel", "Source"])
        self.setColumnWidth(0, 220); self.setColumnWidth(1, 120); self.setColumnWidth(2, 65)
        self.setColumnWidth(3, 55); self.setColumnWidth(4, 105); self.setColumnWidth(5, 85)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True); self.setAlternatingRowColors(True)
        self.itemDoubleClicked.connect(self._double)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self._run: Optional[TelemetryRun] = None

    def set_run(self, run: Optional[TelemetryRun], filter_text: str = "", view_mode: str = "essentials"):
        self._run = run; self.clear()
        if run is None: return
        mode=str(view_mode or 'essentials').lower()
        query=str(filter_text or '').strip()
        p=infer_profile(run)
        essential=set(resolve_profile_channels(run,p.key,limit=12))
        if p.key=='generic_drag':
            essential.update(choose_default_plot_channels(run,limit=10))
        groups: Dict[str, QtWidgets.QTreeWidgetItem] = {}
        labels={
            'angular_speed':'Rotational Speed','speed':'Vehicle Speed','acceleration':'Acceleration',
            'pressure':'Pressure','temperature':'Temperature','power':'Power','torque':'Torque',
            'voltage':'Electrical','current':'Electrical','ratio':'Ratios / Percent',
        }
        for rec in channel_catalog(run, query):
            pref=get_channel_preference(run,rec.name)
            favorite=bool(pref.get('favorite',False))
            # The ordinary trackside view is intentionally small. A search is
            # treated as an explicit request to look across every channel.
            if mode=='essentials' and not query and not favorite and rec.name not in essential:
                continue
            if favorite:
                group_name='★ Favorites'
            elif rec.name in essential:
                group_name=f'Standard — {p.label}'
            else:
                group_name='Math Channels' if rec.source_kind=='calculated' else labels.get(rec.dimension,'Other')
            parent=groups.get(group_name)
            if parent is None:
                parent=QtWidgets.QTreeWidgetItem([group_name]); parent.setFlags(parent.flags() & ~QtCore.Qt.ItemIsDragEnabled)
                font=parent.font(0); font.setBold(True); parent.setFont(0,font); self.addTopLevelItem(parent); groups[group_name]=parent
            rate=f"{rec.sample_rate_hz:g}" if rec.sample_rate_hz else ''
            common = common_channel_label(rec.canonical_role) if rec.canonical_role else ''
            source_label='Math' if rec.source_kind=='calculated' else rec.source_kind.capitalize(); item=QtWidgets.QTreeWidgetItem([rec.name,rec.alias,display_label(rec.unit),rate,common,source_label])
            item.setData(0,QtCore.Qt.UserRole,rec.name); parent.addChild(item)
        for priority in (f'Standard — {p.label}','★ Favorites'):
            parent=groups.get(priority)
            if parent is not None:
                idx=self.indexOfTopLevelItem(parent)
                if idx>0:
                    parent=self.takeTopLevelItem(idx); self.insertTopLevelItem(0,parent)
        self.expandAll()

    def _double(self, item, _column):
        name=item.data(0,QtCore.Qt.UserRole)
        if name:self.channelActivated.emit(str(name))

    def mimeData(self, items):
        mime=super().mimeData(items); channels=[i.data(0,QtCore.Qt.UserRole) for i in items if i.data(0,QtCore.Qt.UserRole)]
        if channels:mime.setData("application/x-nhra-velocity-channels",json.dumps(channels).encode("utf-8"))
        return mime

    def _menu(self, pos):
        item=self.itemAt(pos)
        if not item:return
        name=item.data(0,QtCore.Qt.UserRole)
        if not name:return
        menu=QtWidgets.QMenu(self); props=menu.addAction("Channel Properties…"); common=menu.addAction("Assign Common Channel…"); alias=menu.addAction("Set Display Alias…"); add=menu.addAction("Add to active waveform"); remove=menu.addAction("Remove from active waveform")
        pref=get_channel_preference(self._run,str(name)) if self._run is not None else {}
        favorite=bool(pref.get('favorite',False))
        fav_action=menu.addAction('Remove from Favorites' if favorite else 'Add to Favorites')
        math_names={str(d.get('name','')) for d in (self._run.metadata.get('math_channels',[]) if self._run else []) if isinstance(d,dict)}
        edit_math=None;delete_math=None
        if str(name) in math_names:
            menu.addSeparator();edit_math=menu.addAction("Edit math channel…"); delete_math=menu.addAction("Delete math channel")
        chosen=menu.exec(self.viewport().mapToGlobal(pos))
        if chosen==props:self.channelPropertiesRequested.emit(str(name))
        elif chosen==common:self.commonChannelRequested.emit(str(name))
        elif chosen==alias:self.channelAliasRequested.emit(str(name))
        elif chosen==add:self.channelActivated.emit(str(name))
        elif chosen==remove:self.channelRemoveRequested.emit(str(name))
        elif chosen==fav_action:self.channelFavoriteRequested.emit(str(name),not favorite)
        elif edit_math is not None and chosen==edit_math:self.calculatedChannelEditRequested.emit(str(name))
        elif delete_math is not None and chosen==delete_math:self.calculatedChannelDeleteRequested.emit(str(name))


class SessionDock(QtWidgets.QTreeWidget):
    activeRequested = QtCore.Signal(int)
    roleChanged = QtCore.Signal(int, str)
    alignmentChanged = QtCore.Signal(int, float)
    autoAlignRequested = QtCore.Signal(int)
    renameRequested = QtCore.Signal(int, str)
    removeRequested = QtCore.Signal(int)

    def __init__(self, store: SessionStore):
        super().__init__()
        self.store = store
        self.setHeaderLabels(["Session", "Role", "Align", "Vendor"])
        self.setColumnWidth(0, 220)
        self.setColumnWidth(1, 80)
        self.setColumnWidth(2, 70)
        self.itemDoubleClicked.connect(self._activate)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        store.changed.connect(self.refresh)

    def refresh(self):
        self.clear()
        for idx, h in enumerate(self.store.runs):
            align = f"{h.time_alignment_s:+.4f}s" if abs(h.time_alignment_s) > 1e-9 else "0.0000s"
            item = QtWidgets.QTreeWidgetItem([h.label, h.role.capitalize(), align, h.run.vendor])
            item.setData(0, QtCore.Qt.UserRole, idx)
            if idx == self.store.active_index:
                f = item.font(0); f.setBold(True); item.setFont(0, f)
            self.addTopLevelItem(item)

    def _activate(self, item, _col):
        idx = item.data(0, QtCore.Qt.UserRole)
        if idx is not None:
            self.activeRequested.emit(int(idx))

    def _menu(self, pos):
        item = self.itemAt(pos)
        if not item:
            return
        idx = int(item.data(0, QtCore.Qt.UserRole))
        menu = QtWidgets.QMenu(self)
        make_main = menu.addAction("Make Main")
        make_ref = menu.addAction("Set as Reference")
        make_overlay = menu.addAction("Set as Overlay")
        clear = menu.addAction("Available / not displayed")
        menu.addSeparator()
        align = menu.addAction("Set time alignment offset…")
        auto_align = menu.addAction("Auto-align to Main")
        reset_align = menu.addAction("Reset time alignment")
        menu.addSeparator()
        rename = menu.addAction("Rename session…")
        remove = menu.addAction("Remove session")
        chosen = menu.exec(self.viewport().mapToGlobal(pos))
        if chosen == make_main:
            self.activeRequested.emit(idx)
        elif chosen == make_ref:
            self.roleChanged.emit(idx, "reference")
        elif chosen == make_overlay:
            self.roleChanged.emit(idx, "overlay")
        elif chosen == clear:
            self.roleChanged.emit(idx, "available")
        elif chosen == align:
            current = float(self.store.runs[idx].time_alignment_s)
            value, ok = QtWidgets.QInputDialog.getDouble(self, "Session alignment", "Time offset applied to this compare session (s):", current, -10.0, 10.0, 5)
            if ok:
                self.alignmentChanged.emit(idx, float(value))
        elif chosen == auto_align:
            self.autoAlignRequested.emit(idx)
        elif chosen == reset_align:
            self.alignmentChanged.emit(idx, 0.0)
        elif chosen == rename:
            current = self.store.runs[idx].label
            value, ok = QtWidgets.QInputDialog.getText(self, "Rename session", "Display name:", text=current)
            if ok and str(value).strip():
                self.renameRequested.emit(idx, str(value).strip())
        elif chosen == remove:
            answer = QtWidgets.QMessageBox.question(self, "Remove session", f"Remove {self.store.runs[idx].label} from this project?\n\nThe source file is not deleted.")
            if answer == QtWidgets.QMessageBox.Yes:
                self.removeRequested.emit(idx)


class CursorBus(QtCore.QObject):
    moved = QtCore.Signal(float)
    cursorAMoved = QtCore.Signal(float)
    cursorBMoved = QtCore.Signal(float)
    rangeChanged = QtCore.Signal(float, float, object)

    def __init__(self):
        super().__init__()
        self.x = 0.0
        self.a = 0.0
        self.b = 1.0



class VelocityWaveformViewBox(pg.ViewBox):
    """Waveform interaction tuned for motorsport review.

    Left-button drag is reserved for the engineering cursor, matching the
    ATLAS-style review workflow. Middle-button drag retains X-pan and the
    wheel/right-button interactions remain delegated to pyqtgraph with Y
    interaction disabled by the owning WaveformDisplay.
    """
    cursorDragged = QtCore.Signal(float)

    def mouseDragEvent(self, ev, axis=None):
        try:
            if ev.button() == QtCore.Qt.LeftButton:
                pos = self.mapSceneToView(ev.scenePos())
                self.cursorDragged.emit(float(pos.x()))
                ev.accept()
                return
        except Exception:
            pass
        super().mouseDragEvent(ev, axis=axis)


class WaveformDisplay(QtWidgets.QWidget):
    titleChanged = QtCore.Signal(str)

    def __init__(self, store: SessionStore, cursors: CursorBus, parent=None):
        super().__init__(parent)
        self.store = store
        self.cursors = cursors
        self.channels: List[str] = []
        # Per-display styling belongs to the workbook/worksheet, not the raw
        # telemetry file.  Keys are source channel names; values are simple
        # JSON-serializable display properties.
        self.channel_styles: Dict[str, Dict[str, Any]] = {}
        self.x_mode = "Time from Launch"
        self.compare = False
        self.show_readout = False
        self.show_navigator = False
        self.show_legend = True
        self.show_ab_cursors = False
        self.reference_visible = False
        self.show_stat_delta = True
        self.show_stat_min = False
        self.show_stat_max = False
        self.show_stat_mean = False
        self.show_stat_std = False
        self.max_render_points = 50000
        # Interactive cursor sampling is deliberately cached.  The v0.36
        # implementation rebuilt/sorted full channel arrays on every mouse
        # event, which made otherwise modest motorsport logs feel sluggish.
        self._data_cache = DisplaySeriesCache(max_entries=512)
        self._plots: List[Any] = []
        self._lines: List[Tuple[Any, Any, Any]] = []
        self._reference_regions: List[Any] = []
        self._plot_headers: List[Tuple[Any, Any, List[str]]] = []
        self._waveform_shortcuts: List[Any] = []
        self._syncing = False
        self._range_history: List[Tuple[float,float]] = []
        self._last_range: Optional[Tuple[float,float]] = None
        self.setAcceptDrops(True)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Keep the always-visible waveform controls intentionally small.  Less
        # common A/B, event, bookmark and display options live under More.
        ctl = QtWidgets.QHBoxLayout()
        ctl.setContentsMargins(4, 3, 4, 3)
        ctl.addWidget(QtWidgets.QLabel("Layout"))
        self.layout_mode = QtWidgets.QComboBox()
        self.layout_mode.addItems(["Stacked Channels", "Stacked Units", "Grouped Channels", "Overlay"])
        self.layout_mode.currentTextChanged.connect(lambda _x: self.refresh())
        ctl.addWidget(self.layout_mode)
        self.zero_label = QtWidgets.QLabel("Cursor  0.0000")
        self.zero_label.setMinimumWidth(125)
        ctl.addWidget(self.zero_label)

        self.events_box = QtWidgets.QCheckBox("Event markers")
        self.events_box.setChecked(True)
        self.events_box.stateChanged.connect(lambda _x: self.refresh())
        self.set_a_button = QtWidgets.QToolButton(); self.set_a_button.setText("A ← Cursor")
        self.set_b_button = QtWidgets.QToolButton(); self.set_b_button.setText("B ← Cursor")
        self.prev_event_button = QtWidgets.QToolButton(); self.prev_event_button.setText("◀ Event")
        self.next_event_button = QtWidgets.QToolButton(); self.next_event_button.setText("Event ▶")
        self.bookmark_button = QtWidgets.QToolButton(); self.bookmark_button.setText("Bookmark")
        self.region_button = QtWidgets.QToolButton(); self.region_button.setText("Region A-B")
        self.fit_button = QtWidgets.QToolButton(); self.fit_button.setText("Fit Run"); self.fit_button.setToolTip("Fit the drag-racing pass (Ctrl+F)")
        self.zero_button = QtWidgets.QToolButton(); self.zero_button.setText("Zero: Auto ▾"); self.zero_button.setToolTip("Set the current cursor position as launch (T=0), or return to automatic launch detection")
        self.zero_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        zero_menu = QtWidgets.QMenu(self.zero_button)
        zero_menu.addAction("Set Cursor as Launch (T=0)", self._set_launch_zero_from_cursor)
        zero_menu.addAction("Use Auto-Detected Launch", self._clear_launch_zero)
        self.zero_button.setMenu(zero_menu)
        self.back_button = QtWidgets.QToolButton(); self.back_button.setText("◀ View"); self.back_button.setToolTip("Return to previous X-range")
        self.properties_button = QtWidgets.QToolButton(); self.properties_button.setText("Display…")
        self.snap_box = QtWidgets.QCheckBox("Snap cursors"); self.snap_box.setChecked(True)
        self.set_a_button.clicked.connect(self._set_a_from_cursor)
        self.set_b_button.clicked.connect(self._set_b_from_cursor)
        self.fit_button.clicked.connect(self._fit_run)
        self.back_button.clicked.connect(self._previous_view)
        self.properties_button.clicked.connect(self._display_properties)
        self.prev_event_button.clicked.connect(lambda: self._jump_event(-1))
        self.next_event_button.clicked.connect(lambda: self._jump_event(1))
        self.bookmark_button.clicked.connect(self._add_bookmark)
        self.region_button.clicked.connect(self._add_region)

        ctl.addWidget(self.back_button)
        ctl.addWidget(self.fit_button)
        ctl.addWidget(self.zero_button)
        self.stats_button = QtWidgets.QToolButton(); self.stats_button.setText("Stats ▾")
        self.stats_button.setToolTip("Reference-to-cursor statistics: Delta / Min / Max / Mean / Std. Press R to place the reference cursor.")
        self.stats_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        stats_menu = QtWidgets.QMenu(self.stats_button)
        self._header_stat_actions = {}
        for label, attr, shortcut in [
            ('Delta vs Ref', 'show_stat_delta', 'E'),
            ('Minimum', 'show_stat_min', 'M'),
            ('Maximum', 'show_stat_max', 'X'),
            ('Mean', 'show_stat_mean', 'N'),
            ('Std dev', 'show_stat_std', 'Q'),
        ]:
            action = stats_menu.addAction(label); action.setCheckable(True); action.setChecked(bool(getattr(self, attr))); action.setShortcut(shortcut)
            action.toggled.connect(lambda checked, a=attr: self._set_readout_stat(a, checked))
            self._header_stat_actions[attr] = action
        stats_menu.addSeparator(); stats_menu.addAction('Clear statistics', self._clear_header_statistics)
        self.stats_button.setMenu(stats_menu); self._update_stats_button()
        ctl.addWidget(self.stats_button)
        self.more_button = QtWidgets.QToolButton()
        self.more_button.setText("More ▾")
        self.more_button.setToolTip('Click: Cursor   Drag cursor line: scrub   Shift+click: A   Ctrl+click: B   Wheel: zoom X')
        self.more_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        more = QtWidgets.QMenu(self.more_button)
        self.more_events_action = more.addAction("Event markers"); self.more_events_action.setCheckable(True); self.more_events_action.setChecked(True)
        self.more_events_action.toggled.connect(self.events_box.setChecked)
        self.more_nav_action = more.addAction("Full-run navigator"); self.more_nav_action.setCheckable(True); self.more_nav_action.setChecked(False)
        self.more_nav_action.toggled.connect(self._set_navigator_visible)
        self.more_ab_action = more.addAction("A/B cursors and Δ readout"); self.more_ab_action.setCheckable(True); self.more_ab_action.setChecked(False)
        self.more_ab_action.toggled.connect(self._set_ab_visible)
        self.more_snap_action = more.addAction("Snap cursor to samples"); self.more_snap_action.setCheckable(True); self.more_snap_action.setChecked(True)
        self.more_snap_action.toggled.connect(self.snap_box.setChecked)
        self.more_readout_action = more.addAction("Detailed channel table"); self.more_readout_action.setCheckable(True); self.more_readout_action.setChecked(False)
        self.more_readout_action.toggled.connect(self._set_readout_visible)
        readout_columns=more.addMenu('Detailed table columns')
        self._readout_stat_actions={}
        for label,attr in [('Δ vs Ref','show_stat_delta'),('Minimum','show_stat_min'),('Maximum','show_stat_max'),('Mean','show_stat_mean'),('Std dev','show_stat_std')]:
            action=readout_columns.addAction(label);action.setCheckable(True);action.setChecked(bool(getattr(self,attr)));action.toggled.connect(lambda checked,a=attr:self._set_readout_stat(a,checked));self._readout_stat_actions[attr]=action
        more.addSeparator()
        more.addAction("Set A from Cursor", self._set_a_from_cursor)
        more.addAction("Set B from Cursor", self._set_b_from_cursor)
        more.addAction("Previous event", lambda: self._jump_event(-1))
        more.addAction("Next event", lambda: self._jump_event(1))
        more.addAction("Add bookmark", self._add_bookmark)
        more.addAction("Add A-B region", self._add_region)
        more.addSeparator()
        more.addAction("Fit drag run", self._fit_run)
        more.addAction("Fit full logger recording", self._fit_full)
        more.addSeparator()
        more.addAction("Set Cursor as Launch (T=0)", self._set_launch_zero_from_cursor)
        more.addAction("Use Auto-Detected Launch", self._clear_launch_zero)
        more.addSeparator()
        self.remove_channel_menu = more.addMenu("Remove channel")
        self.remove_channel_menu.aboutToShow.connect(self._populate_remove_channel_menu)
        more.addAction("Display properties…", self._display_properties)
        self.more_button.setMenu(more)
        ctl.addWidget(self.more_button)
        ctl.addStretch(1)
        self.render_status=QtWidgets.QLabel("No traces rendered")
        self.render_status.setToolTip("Waveform renderer status")
        ctl.addWidget(self.render_status)
        layout.addLayout(ctl)

        # i2/ATLAS-style readout immediately above the traces.  A user should
        # not need a separate display just to know the value under the cursor.
        self.readout = QtWidgets.QTableWidget(0, 10)
        self.readout.setHorizontalHeaderLabels(["Channel", "Unit", "Cursor", "Ref", "Δ", "Min", "Max", "Mean", "Std", "B"])
        self.readout.verticalHeader().setVisible(False);self.readout.verticalHeader().setDefaultSectionSize(19);self.readout.verticalHeader().setMinimumSectionSize(18)
        header=self.readout.horizontalHeader(); header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents); header.setSectionResizeMode(0,QtWidgets.QHeaderView.Stretch);header.setMinimumHeight(22)
        self.readout.setMinimumHeight(48);self.readout.setMaximumHeight(168);self.readout.setWordWrap(False)
        self.readout.setToolTip("Optional detailed value table. Normal cursor/reference values are shown directly in each waveform band.")
        self.readout.setColumnHidden(8, True); self.readout.setColumnHidden(9, True)
        self.readout.setAlternatingRowColors(True)
        self.readout.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.readout.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.readout.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.readout.customContextMenuRequested.connect(self._readout_menu)
        self._set_stat_column_visibility()
        self.readout.setVisible(self.show_readout)
        layout.addWidget(self.readout)

        self.graph = pg.GraphicsLayoutWidget()
        self.graph.setBackground((20, 22, 25))
        try:
            self.graph.ci.layout.setContentsMargins(2, 2, 2, 2)
            self.graph.ci.layout.setSpacing(1)
        except Exception:
            pass
        layout.addWidget(self.graph, 1)

        # Full-session navigator / zoom window.  This is deliberately kept
        # simple and fast: one representative channel plus a draggable region
        # controlling the synchronized waveform X range.
        self.navigator = pg.PlotWidget(background=(16, 18, 21))
        self.navigator.setMouseEnabled(x=True, y=False)
        self.navigator.setMaximumHeight(92)
        self.navigator.setMinimumHeight(60)
        self.navigator.showGrid(x=True, y=False, alpha=0.12)
        self.navigator.hideAxis('left')
        self.nav_region = pg.LinearRegionItem(values=[0.0, 1.0], orientation=pg.LinearRegionItem.Vertical, movable=True, brush=pg.mkBrush(70, 120, 170, 45))
        self.navigator.addItem(self.nav_region)
        self.nav_region.sigRegionChanged.connect(self._navigator_changed)
        layout.addWidget(self.navigator)
        self.navigator.setVisible(self.show_navigator)

        # ATLAS-style cursor surface: click positions the shared cursor and the
        # vertical cursor line itself is draggable. Merely hovering over a
        # waveform never changes engineering state. Shift/Ctrl click place A/B.
        self.graph.setToolTip('Click or left-drag: move cursor   R: reference cursor   M/X/N/Q/E: statistics   Right-click: channel actions   +/-: zoom X   Middle-drag: pan X   Wheel: zoom X')
        self.graph.scene().sigMouseClicked.connect(self._scene_mouse_clicked)
        self.graph.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.graph.customContextMenuRequested.connect(self._waveform_context_menu)
        self._install_waveform_shortcuts()

        # Cursor readout is also coalesced.  Signals can still move cursor lines
        # immediately; expensive text/table work happens at most ~30 Hz.
        self._readout_timer = QtCore.QTimer(self)
        self._readout_timer.setSingleShot(True)
        self._readout_timer.setInterval(33)
        self._readout_timer.timeout.connect(self._refresh_readout)

        store.changed.connect(self._store_changed)
        cursors.moved.connect(self._external_cursor)
        cursors.cursorAMoved.connect(self._external_a)
        cursors.cursorBMoved.connect(self._external_b)
        cursors.moved.connect(self._schedule_readout)
        cursors.cursorAMoved.connect(self._schedule_readout)
        cursors.cursorBMoved.connect(self._schedule_readout)
        cursors.rangeChanged.connect(self._external_range)


    def _set_readout_visible(self, visible: bool):
        self.show_readout = bool(visible)
        self.readout.setVisible(self.show_readout)
        if getattr(self, 'more_readout_action', None) is not None and self.more_readout_action.isChecked() != self.show_readout:
            self.more_readout_action.setChecked(self.show_readout)

    def _bind_waveform_shortcut(self, sequence: str, callback):
        shortcut = QtGui.QShortcut(QtGui.QKeySequence(sequence), self)
        shortcut.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
        shortcut.activated.connect(callback)
        self._waveform_shortcuts.append(shortcut)
        return shortcut

    def _install_waveform_shortcuts(self):
        # WidgetWithChildrenShortcut is deliberate: focus normally belongs to a
        # pyqtgraph child item, so relying only on QWidget.keyPressEvent causes
        # R / +/- to appear intermittent.
        self._bind_waveform_shortcut('R', self._toggle_reference_cursor)
        self._bind_waveform_shortcut('+', lambda: self._zoom_x(0.70))
        self._bind_waveform_shortcut('=', lambda: self._zoom_x(0.70))
        self._bind_waveform_shortcut('-', lambda: self._zoom_x(1.40))
        self._bind_waveform_shortcut('M', lambda: self._toggle_stat_shortcut('show_stat_min'))
        self._bind_waveform_shortcut('X', lambda: self._toggle_stat_shortcut('show_stat_max'))
        self._bind_waveform_shortcut('N', lambda: self._toggle_stat_shortcut('show_stat_mean'))
        self._bind_waveform_shortcut('E', lambda: self._toggle_stat_shortcut('show_stat_delta'))
        self._bind_waveform_shortcut('Q', lambda: self._toggle_stat_shortcut('show_stat_std'))
        self._bind_waveform_shortcut('Ctrl+Z', self._previous_view)
        self._bind_waveform_shortcut('Ctrl+Alt+Z', self._fit_run)

    def _toggle_stat_shortcut(self, attr: str):
        self._set_readout_stat(attr, not bool(getattr(self, attr, False)))

    def _clear_header_statistics(self):
        for attr in ('show_stat_delta','show_stat_min','show_stat_max','show_stat_mean','show_stat_std'):
            setattr(self, attr, False)
        self._set_stat_column_visibility(); self._update_stats_button(); self._refresh_readout()

    def _populate_remove_channel_menu(self):
        self.remove_channel_menu.clear()
        if not self.channels:
            action=self.remove_channel_menu.addAction('(no channels)'); action.setEnabled(False); return
        for channel in list(self.channels):
            self.remove_channel_menu.addAction(str(channel), lambda checked=False, c=channel: self.remove_channel(c))

    def _plot_at_widget_pos(self, pos):
        try:
            scene_pos=self.graph.mapToScene(pos)
        except Exception:
            return None
        for plot, _item, chans in self._plot_headers:
            try:
                if plot.sceneBoundingRect().contains(scene_pos):
                    return plot, list(chans)
            except Exception:
                continue
        return None

    def _waveform_context_menu(self, pos):
        hit=self._plot_at_widget_pos(pos)
        menu=QtWidgets.QMenu(self)
        channels=list(hit[1]) if hit else list(self.channels)
        if len(channels)==1:
            channel=channels[0]
            menu.addAction(f'Remove {channel}', lambda: self.remove_channel(channel))
            menu.addAction(f'Trace properties — {channel}…', lambda: self._trace_properties(channel))
            idx=self.channels.index(channel) if channel in self.channels else -1
            if idx>0: menu.addAction('Move channel up', lambda c=channel: self._move_channel(c,-1))
            if 0<=idx<len(self.channels)-1: menu.addAction('Move channel down', lambda c=channel: self._move_channel(c,1))
        elif channels:
            remove_menu=menu.addMenu('Remove channel')
            for channel in channels:
                remove_menu.addAction(str(channel), lambda checked=False, c=channel: self.remove_channel(c))
        menu.addSeparator()
        menu.addAction('Set reference at cursor (R)', self._set_a_from_cursor)
        menu.addAction('Set cursor as Launch (T=0)', self._set_launch_zero_from_cursor)
        menu.exec(self.graph.mapToGlobal(pos))

    def _move_channel(self, channel: str, direction: int):
        if channel not in self.channels:return
        i=self.channels.index(channel);j=max(0,min(len(self.channels)-1,i+int(direction)))
        if i==j:return
        self.channels[i],self.channels[j]=self.channels[j],self.channels[i];self.refresh()

    def _cursor_dragged(self, x: float):
        # Left-drag anywhere in a waveform is the primary engineering cursor
        # gesture. Panning remains available with middle-drag.
        self.setFocus(QtCore.Qt.MouseFocusReason)
        self._cursor_move(float(x))

    def _update_reference_regions(self):
        lo = min(float(self.cursors.a), float(self.cursors.x))
        hi = max(float(self.cursors.a), float(self.cursors.x))
        for region in self._reference_regions:
            try:
                region.setRegion((lo, hi))
                region.setVisible(bool(self.reference_visible))
            except Exception:
                pass

    @staticmethod
    def _fmt_cursor_value(value: float) -> str:
        return f"{float(value):.6g}" if np.isfinite(value) else "—"

    def _position_plot_header(self, plot, item):
        try:
            xr, yr = plot.viewRange()
            xspan = max(float(xr[1]) - float(xr[0]), 1e-12)
            yspan = max(float(yr[1]) - float(yr[0]), 1e-12)
            item.setPos(float(xr[0]) + xspan * 0.006, float(yr[1]) - yspan * 0.015)
        except Exception:
            pass

    def _refresh_plot_headers(self):
        handle = self.store.active
        if handle is None:
            return
        for plot, item, chans in self._plot_headers:
            chunks = []
            for channel in chans:
                vals = self._data_cache.sample_many(
                    handle.run,
                    channel,
                    (self.cursors.x, self.cursors.a),
                    self.x_mode,
                    handle.time_alignment_s,
                )
                vals = self._convert_for_display(channel, handle.run, vals)
                current = vals[0] if len(vals) else np.nan
                ref = vals[1] if len(vals) > 1 else np.nan
                delta = current - ref if np.isfinite(current) and np.isfinite(ref) else np.nan
                color = self._style_for(channel, self.channels.index(channel) if channel in self.channels else 0).get('color', '#dddddd')
                unit = display_label(self._display_unit(channel, handle.run))
                current_text = self._fmt_cursor_value(current)
                aliases = handle.run.metadata.get('channel_aliases',{}) if isinstance(handle.run.metadata.get('channel_aliases',{}),dict) else {}
                display_name=str(aliases.get(channel,'') or '')
                if not display_name:
                    originals=handle.run.metadata.get('original_channel_map',{}) if isinstance(handle.run.metadata.get('original_channel_map',{}),dict) else {}
                    canonical=next((role for role,source in originals.items() if str(source)==str(channel)), '')
                    display_name=common_channel_label(canonical) if canonical else str(channel)
                name = html.escape(display_name)
                unit_text = f" {html.escape(str(unit))}" if unit else ""
                chunk = (
                    f"<span style='color:{color};font-weight:600'>{name}</span>"
                    f"&nbsp;<span style='color:#f2f2f2'>{current_text}{unit_text}</span>"
                )
                if self.reference_visible:
                    chunk += f"&nbsp;&nbsp;<span style='color:#ff6b6b'>R {self._fmt_cursor_value(ref)}</span>"
                    if self.show_stat_delta:
                        chunk += f"&nbsp;<span style='color:#b8bec6'>Δ {self._fmt_cursor_value(delta)}</span>"
                    if self.show_stat_min or self.show_stat_max or self.show_stat_mean or self.show_stat_std:
                        stats=self._data_cache.region_summary(handle.run,channel,self.cursors.a,self.cursors.x,self.x_mode,handle.time_alignment_s)
                        stat_raw=np.asarray([stats.get('min',np.nan),stats.get('max',np.nan),stats.get('mean',np.nan),stats.get('std',np.nan)],dtype=float)
                        stat_vals=self._convert_for_display(channel,handle.run,stat_raw)
                        if self.show_stat_min: chunk += f"&nbsp;<span style='color:#d0d4da'>Min {self._fmt_cursor_value(stat_vals[0])}</span>"
                        if self.show_stat_max: chunk += f"&nbsp;<span style='color:#d0d4da'>Max {self._fmt_cursor_value(stat_vals[1])}</span>"
                        if self.show_stat_mean: chunk += f"&nbsp;<span style='color:#d0d4da'>Avg {self._fmt_cursor_value(stat_vals[2])}</span>"
                        if self.show_stat_std: chunk += f"&nbsp;<span style='color:#d0d4da'>σ {self._fmt_cursor_value(stat_vals[3])}</span>"
                chunks.append(chunk)
            try:
                item.setHtml("&nbsp;&nbsp;&nbsp;&nbsp;".join(chunks))
                self._position_plot_header(plot, item)
            except Exception:
                pass

    def _set_launch_zero_from_cursor(self):
        handle = self.store.active
        if handle is None:
            return
        mode = str(self.x_mode or '').strip().lower()
        try:
            selected_x=float(self.cursors.x)
            current = detect_drag_pass_window(handle.run)
            old_launch=float(current.launch_time_s)
            old_alignment=float(handle.time_alignment_s)
            if mode.startswith('logger'):
                selected_logger_time=selected_x
            elif mode.startswith('time'):
                # Display X = logger time - current launch + compare alignment.
                # Convert the selected display coordinate back to the logger clock
                # before changing either launch zero or alignment.
                selected_logger_time=old_launch + selected_x - old_alignment
            else:
                QtWidgets.QMessageBox.information(
                    self,
                    'Set Launch Zero',
                    'Switch the X axis to Time from Launch or Logger Time, place the cursor at the true launch point, then choose Set Cursor as Launch (T=0).',
                )
                return

            tc = handle.run.channel_map.get('time_s')
            if tc and tc in handle.run.data.columns:
                times = pd.to_numeric(handle.run.data[tc], errors='coerce').to_numpy(float)
                finite = times[np.isfinite(times)]
                if len(finite) and not (float(np.nanmin(finite)) <= selected_logger_time <= float(np.nanmax(finite))):
                    raise ValueError('Selected launch zero is outside the logger time range')

            old_ref=float(self.cursors.a); old_b=float(self.cursors.b)
            set_launch_time_override(handle.run, selected_logger_time)
            # detect_drag_pass_window snaps a manual zero to the nearest physical
            # logger sample. Persist that effective value so display and catalog
            # cannot disagree by a sample interval after reopening.
            effective=float(detect_drag_pass_window(handle.run).launch_time_s)
            set_launch_time_override(handle.run, effective)

            # A compare/display alignment intentionally moves a trace relative to
            # T=0. If it remains non-zero, a user-selected launch can appear offset
            # even though the launch override itself is correct. Explicit re-zero
            # makes the selected point authoritative and clears that display-only
            # alignment. Preserve reference/B on the same physical samples.
            handle.time_alignment_s=0.0
            if mode.startswith('time'):
                coordinate_shift=old_launch - effective - old_alignment
                self.cursors.a=old_ref + coordinate_shift
                self.cursors.b=old_b + coordinate_shift
                target_cursor=0.0
            else:
                # Logger Time is an absolute logger clock and must not be
                # translated just because the launch reference changed.
                target_cursor=selected_logger_time

            catalog = getattr(self.store, 'catalog', None)
            if catalog is not None and handle.catalog_asset_id:
                mapping = catalog.get_time_mapping(handle.catalog_asset_id) or {}
                scale = float(mapping.get('scale') or 1.0)
                catalog.update_time_mapping(
                    handle.catalog_asset_id,
                    scale=scale,
                    offset_s=-scale * effective,
                    method='manual launch zero',
                    confidence=1.0,
                    uncertainty_s=0.0,
                    anchors=[{'asset_time_s': effective, 'run_time_s': 0.0}],
                )
            self.cursors.x = float(target_cursor)
            self._data_cache.clear()
            self.store.changed.emit()
            self.cursors.cursorAMoved.emit(self.cursors.a)
            self.cursors.cursorBMoved.emit(self.cursors.b)
            self.cursors.moved.emit(self.cursors.x)
            msg=f'Launch zero set at logger {effective:.6f} s'
            if abs(old_alignment)>1e-9:
                msg += f' · cleared {old_alignment:+.4f} s display alignment'
            win=self.window(); status=getattr(win,'statusBar',None)
            if callable(status): status().showMessage(msg,6000)
        except Exception as exc:
            logging.exception('Could not set manual launch zero')
            QtWidgets.QMessageBox.warning(self, 'Set Launch Zero', str(exc))

    def _clear_launch_zero(self):
        handle = self.store.active
        if handle is None:
            return
        try:
            clear_launch_time_override(handle.run)
            detected = detect_drag_pass_window(handle.run)
            catalog = getattr(self.store, 'catalog', None)
            if catalog is not None and handle.catalog_asset_id:
                mapping = catalog.get_time_mapping(handle.catalog_asset_id) or {}
                scale = float(mapping.get('scale') or 1.0)
                launch = float(detected.launch_time_s)
                catalog.update_time_mapping(
                    handle.catalog_asset_id,
                    scale=scale,
                    offset_s=-scale * launch,
                    method=f'auto launch detection ({detected.confidence})',
                    confidence=None,
                    uncertainty_s=None,
                    anchors=[],
                )
            self.cursors.x = 0.0
            self.store.changed.emit()
            self.cursors.moved.emit(0.0)
        except Exception as exc:
            logging.exception('Could not restore automatic launch zero')
            QtWidgets.QMessageBox.warning(self, 'Launch Zero', str(exc))

    def _refresh_zero_control(self):
        manual = self.store.active is not None and launch_time_override(self.store.active.run) is not None
        self.zero_button.setText('Zero: Manual ▾' if manual else 'Zero: Auto ▾')
        if manual:
            self.zero_button.setStyleSheet('font-weight:bold;')
        else:
            self.zero_button.setStyleSheet('')

    def _store_changed(self):
        # Run replacement, compare alignment, calculated-channel changes and
        # canonical remapping can all change display X/Y.  One invalidation here
        # keeps the hot cursor path simple and deterministic.
        self._data_cache.clear()
        self._refresh_zero_control()
        self.refresh()

    def _schedule_readout(self, *_args):
        # The compact per-band headers are the primary live readout now, so
        # cursor/reference changes must refresh even when the optional detailed
        # table is hidden.  dev.11 returned early here, which let the cursor line
        # move while its displayed value/ref/delta stayed stale until some other
        # action forced a redraw.
        self.zero_label.setText(f"Cursor  {self.cursors.x:.4f}")
        if not self._readout_timer.isActive():
            self._readout_timer.start()

    def _set_navigator_visible(self, visible: bool):
        self.show_navigator = bool(visible)
        self.navigator.setVisible(self.show_navigator)
        if self.show_navigator:
            self._refresh_navigator()

    def _set_ab_visible(self, visible: bool):
        self.show_ab_cursors = bool(visible)
        # Cursor A is always the useful reference for live statistics; the
        # optional B column remains available for legacy A/B workflows.
        self.readout.setColumnHidden(9, not self.show_ab_cursors)
        for lines in self._lines:
            lines[1].setVisible(self.reference_visible)  # A is the statistics reference
            lines[2].setVisible(self.show_ab_cursors)
        self._refresh_readout()

    def _scene_x(self, scene_pos) -> Optional[float]:
        for plot in self._plots:
            try:
                if plot.sceneBoundingRect().contains(scene_pos):
                    return float(plot.vb.mapSceneToView(scene_pos).x())
            except Exception:
                continue
        return None

    def _scene_mouse_clicked(self, event):
        try:
            if event.button() != QtCore.Qt.LeftButton:
                return
            x = self._scene_x(event.scenePos())
        except Exception:
            return
        if x is not None and np.isfinite(x):
            try:mods=event.modifiers()
            except Exception:mods=QtWidgets.QApplication.keyboardModifiers()
            if mods & QtCore.Qt.ShiftModifier:self._a_move(x)
            elif mods & QtCore.Qt.ControlModifier:self._b_move(x)
            else:self._cursor_move(x)

    def _style_for(self, channel: str, index: int) -> Dict[str, Any]:
        defaults = ['#5bc0eb', '#f9c74f', '#90be6d', '#f94144', '#c77dff', '#43aa8b', '#f8961e', '#e0e0e0']
        # Cross-project defaults provide familiar colours/units/scales without
        # mutating source telemetry. Project-local styles always win.
        style: Dict[str, Any] = {}
        if self.store.active is not None:
            try: style.update(get_channel_preference(self.store.active.run, channel))
            except Exception: pass
        style.update(self.channel_styles.get(channel, {}))
        style.setdefault('color', defaults[index % len(defaults)])
        style.setdefault('width', 1.6)
        self.channel_styles[channel] = dict(style)
        return style

    def _display_unit(self, channel: str, run: Optional[TelemetryRun] = None) -> str:
        run = run or (self.store.active.run if self.store.active else None)
        source_unit = normalize_unit(run.units.get(channel, '')) if run is not None else ''
        preferred = normalize_unit(self.channel_styles.get(channel, {}).get('display_unit', ''))
        if preferred and source_unit and dimension(preferred) == dimension(source_unit):
            return preferred
        return source_unit

    def _convert_for_display(self, channel: str, run: TelemetryRun, values: np.ndarray) -> np.ndarray:
        source_unit = normalize_unit(run.units.get(channel, ''))
        target_unit = self._display_unit(channel, self.store.active.run if self.store.active else run)
        if not source_unit or not target_unit or source_unit == target_unit:
            return np.asarray(values, dtype=float)
        if dimension(source_unit) != dimension(target_unit):
            return np.asarray(values, dtype=float)
        try:
            return np.asarray(convert_value(np.asarray(values, dtype=float), source_unit, target_unit), dtype=float)
        except Exception:
            return np.asarray(values, dtype=float)

    def _trace_properties(self, channel: str):
        active = self.store.active
        if active is None:
            return
        style = self._style_for(channel, self.channels.index(channel) if channel in self.channels else 0)
        source_unit = normalize_unit(active.run.units.get(channel, ''))
        source_dim = dimension(source_unit)

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(f'Trace Properties — {channel}')
        form = QtWidgets.QFormLayout(dlg)

        color_btn = QtWidgets.QPushButton(style.get('color', '#ffffff'))
        color_btn.setStyleSheet(f"background:{style.get('color','#ffffff')}; color:#101010;")
        def choose_color():
            c = QtWidgets.QColorDialog.getColor(QtGui.QColor(style.get('color','#ffffff')), dlg, f'Trace color — {channel}')
            if c.isValid():
                color_btn.setText(c.name()); color_btn.setStyleSheet(f'background:{c.name()}; color:#101010;')
        color_btn.clicked.connect(choose_color)
        form.addRow('Color', color_btn)

        width = QtWidgets.QDoubleSpinBox(); width.setRange(0.5, 8.0); width.setSingleStep(0.2); width.setDecimals(1); width.setValue(float(style.get('width',1.6)))
        form.addRow('Line width', width)

        axis_group = QtWidgets.QLineEdit(str(style.get('axis_group','') or ''))
        axis_group.setPlaceholderText('Blank = its own axis')
        axis_group.setToolTip('In Grouped Channels mode, traces with the same nonblank group name AND display unit share one waveform band. Velocity never combines incompatible units automatically.')
        form.addRow('Axis group', axis_group)

        unit_box = QtWidgets.QComboBox()
        compatible_units = [k for k,v in UNITS.items() if k and source_dim != 'unknown' and v.dimension == source_dim]
        if source_unit and source_unit not in compatible_units:
            compatible_units.insert(0, source_unit)
        for key in compatible_units:
            unit_box.addItem(display_label(key) or key, key)
        current_unit = self._display_unit(channel, active.run)
        idx = unit_box.findData(current_unit)
        if idx >= 0: unit_box.setCurrentIndex(idx)
        unit_box.setEnabled(bool(compatible_units))
        form.addRow('Display unit', unit_box)

        auto_y = QtWidgets.QCheckBox('Automatic Y range')
        auto_y.setChecked(not ('y_min' in style or 'y_max' in style))
        form.addRow('', auto_y)
        ymin = QtWidgets.QDoubleSpinBox(); ymax = QtWidgets.QDoubleSpinBox()
        for spin in (ymin,ymax):
            spin.setRange(-1e9,1e9); spin.setDecimals(6); spin.setSingleStep(1.0)
        if 'y_min' in style: ymin.setValue(float(style['y_min']))
        if 'y_max' in style: ymax.setValue(float(style['y_max']))
        ymin.setEnabled(not auto_y.isChecked()); ymax.setEnabled(not auto_y.isChecked())
        auto_y.toggled.connect(lambda checked: (ymin.setEnabled(not checked), ymax.setEnabled(not checked)))
        form.addRow('Y minimum', ymin); form.addRow('Y maximum', ymax)

        global_pref=QtWidgets.QCheckBox('Use these settings as the cross-project default for this parameter')
        global_pref.setToolTip('Stored by canonical engineering role when one exists; otherwise by source-channel name.')
        clear_global=QtWidgets.QPushButton('Clear global default')
        clear_global.clicked.connect(lambda: clear_channel_preference(active.run, channel))
        form.addRow('',global_pref); form.addRow('',clear_global)

        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept); buttons.rejected.connect(dlg.reject); form.addRow(buttons)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        new_style = self.channel_styles.setdefault(channel,{})
        new_style['color']=color_btn.text().strip()
        new_style['width']=float(width.value())
        group_name=str(axis_group.text() or '').strip()
        if group_name:new_style['axis_group']=group_name
        else:new_style.pop('axis_group',None)
        if unit_box.isEnabled() and unit_box.currentData(): new_style['display_unit']=str(unit_box.currentData())
        else: new_style.pop('display_unit',None)
        if auto_y.isChecked():
            new_style.pop('y_min',None); new_style.pop('y_max',None)
        else:
            lo=float(ymin.value()); hi=float(ymax.value())
            if hi <= lo:
                QtWidgets.QMessageBox.warning(self,'Invalid Y range','Y maximum must be greater than Y minimum.')
                return
            new_style['y_min']=lo; new_style['y_max']=hi
        if global_pref.isChecked():
            try:
                pref=get_channel_preference(active.run,channel); favorite=pref.get('favorite')
                pref.update(new_style)
                if favorite is not None:pref['favorite']=favorite
                set_channel_preference(active.run,channel,pref)
            except Exception:logging.getLogger(__name__).exception('Could not save global channel preference')
        self.refresh()

    def _display_properties(self):
        dlg=QtWidgets.QDialog(self); dlg.setWindowTitle('Waveform Display Properties'); dlg.resize(480,360)
        form=QtWidgets.QFormLayout(dlg)
        layout_box=QtWidgets.QComboBox(); layout_box.addItems(['Stacked Channels','Stacked Units','Grouped Channels','Overlay']); layout_box.setCurrentText(self.layout_mode.currentText())
        compare=QtWidgets.QCheckBox('Overlay Reference / compare sessions'); compare.setChecked(bool(self.compare))
        events=QtWidgets.QCheckBox('Show event/timing markers'); events.setChecked(self.events_box.isChecked())
        readout=QtWidgets.QCheckBox('Show cursor value table'); readout.setChecked(bool(self.show_readout))
        navigator=QtWidgets.QCheckBox('Show full-run navigator'); navigator.setChecked(bool(self.show_navigator))
        legend=QtWidgets.QCheckBox('Show trace legends'); legend.setChecked(bool(self.show_legend))
        snap=QtWidgets.QCheckBox('Snap cursors to native samples'); snap.setChecked(self.snap_box.isChecked())
        points=QtWidgets.QSpinBox(); points.setRange(1000,500000); points.setSingleStep(5000); points.setValue(int(self.max_render_points)); points.setSuffix(' pts / trace')
        form.addRow('Layout',layout_box); form.addRow('',compare); form.addRow('',events); form.addRow('',readout); form.addRow('',navigator); form.addRow('',legend); form.addRow('',snap); form.addRow('Render point budget',points)
        help_text=QtWidgets.QLabel('The render point budget controls peak-preserving display decimation only. Raw logger samples remain unchanged.'); help_text.setWordWrap(True); form.addRow(help_text)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel); buttons.accepted.connect(dlg.accept); buttons.rejected.connect(dlg.reject); form.addRow(buttons)
        if dlg.exec()!=QtWidgets.QDialog.Accepted:return
        self.layout_mode.setCurrentText(layout_box.currentText()); self.compare=compare.isChecked(); self.events_box.setChecked(events.isChecked()); self.show_readout=readout.isChecked(); self.show_navigator=navigator.isChecked(); self.show_legend=legend.isChecked(); self.snap_box.setChecked(snap.isChecked()); self.max_render_points=int(points.value())
        self.more_events_action.setChecked(self.events_box.isChecked()); self.more_nav_action.setChecked(self.show_navigator); self.more_snap_action.setChecked(self.snap_box.isChecked())
        self.readout.setVisible(self.show_readout); self.navigator.setVisible(self.show_navigator); self.refresh()

    def _cursor_sample_grid(self) -> np.ndarray:
        if self.store.active is None:
            return np.array([], dtype=float)
        handle=self.store.active
        for c in self.channels:
            grid=self._data_cache.snap_grid(handle.run,c,self.x_mode,handle.time_alignment_s)
            if len(grid):
                return grid
        return np.array([], dtype=float)

    def _snap_x(self, x: float) -> float:
        if not self.snap_box.isChecked() or self.store.active is None:
            return float(x)
        return self._data_cache.nearest(self._cursor_sample_grid(), float(x))

    def _step_cursor(self, direction: int, count: int = 1):
        grid=self._cursor_sample_grid()
        if not len(grid):
            return
        current=float(self.cursors.x)
        idx=int(np.searchsorted(grid,current,side='left'))
        if idx>=len(grid):idx=len(grid)-1
        elif idx>0 and abs(float(grid[idx-1])-current)<=abs(float(grid[idx])-current):idx-=1
        idx=max(0,min(len(grid)-1,idx + int(direction)*max(1,int(count))))
        self.cursors.x=float(grid[idx])
        self.cursors.moved.emit(self.cursors.x)

    def _set_readout_stat(self, attr: str, visible: bool):
        if not hasattr(self,attr):
            return
        setattr(self,attr,bool(visible))
        self._set_stat_column_visibility(); self._update_stats_button(); self._refresh_readout()

    def _update_stats_button(self):
        if not hasattr(self,'stats_button'):return
        labels=[]
        if self.show_stat_delta:labels.append('Δ')
        if self.show_stat_min:labels.append('Min')
        if self.show_stat_max:labels.append('Max')
        if self.show_stat_mean:labels.append('Avg')
        if self.show_stat_std:labels.append('σ')
        self.stats_button.setText(('Stats: '+','.join(labels)+' ▾') if labels else 'Stats ▾')

    def _set_stat_column_visibility(self):
        # Fixed table columns: Δ=4 Min=5 Max=6 Mean=7 Std=8 B=9.
        self.readout.setColumnHidden(4,not self.show_stat_delta)
        self.readout.setColumnHidden(5,not self.show_stat_min)
        self.readout.setColumnHidden(6,not self.show_stat_max)
        self.readout.setColumnHidden(7,not self.show_stat_mean)
        self.readout.setColumnHidden(8,not self.show_stat_std)
        self.readout.setColumnHidden(9,not self.show_ab_cursors)
        for action_map in (getattr(self,'_readout_stat_actions',{}), getattr(self,'_header_stat_actions',{})):
            for attr,action in action_map.items():
                wanted=bool(getattr(self,attr))
                if action.isChecked()!=wanted:
                    action.blockSignals(True); action.setChecked(wanted); action.blockSignals(False)

    def _toggle_reference_cursor(self):
        # ATLAS-style R shortcut: adding a reference captures the current
        # cursor location; pressing R again removes the reference.
        if self.reference_visible:
            self.reference_visible = False
        else:
            self.reference_visible = True
            self.cursors.a = float(self.cursors.x)
            self.cursors.cursorAMoved.emit(self.cursors.a)
        for lines in self._lines:
            lines[1].setVisible(self.reference_visible)
        self._update_reference_regions()
        self._refresh_readout()

    def _zoom_x(self, factor: float):
        if not self._plots:
            return
        lo,hi=self._plots[0].viewRange()[0]
        lo=float(lo);hi=float(hi)
        cursor=float(self.cursors.x)
        center=cursor if lo <= cursor <= hi else (lo+hi)/2.0
        half=max(1e-9,(hi-lo)*float(factor)/2.0)
        self._plots[0].setXRange(center-half,center+half,padding=0)

    def _cycle_x_mode(self):
        self.set_x_mode('Distance from Launch' if self.x_mode!='Distance from Launch' else 'Time from Launch')

    def _cursor_boundary(self, end: bool):
        grid=self._cursor_sample_grid()
        if len(grid):
            self.cursors.x=float(grid[-1] if end else grid[0]);self.cursors.moved.emit(self.cursors.x)

    def keyPressEvent(self, event):
        key=event.key();mods=event.modifiers()
        if key in (QtCore.Qt.Key_Left, QtCore.Qt.Key_Right):
            direction=-1 if key==QtCore.Qt.Key_Left else 1
            if mods & QtCore.Qt.AltModifier:
                self._jump_event(direction)
            else:
                step=10 if (mods & (QtCore.Qt.ControlModifier|QtCore.Qt.ShiftModifier)) else 1
                self._step_cursor(direction,step)
            event.accept();return
        if key==QtCore.Qt.Key_Home:self._cursor_boundary(False);event.accept();return
        if key==QtCore.Qt.Key_End:self._cursor_boundary(True);event.accept();return
        if key==QtCore.Qt.Key_PageUp:self._step_cursor(-1,100);event.accept();return
        if key==QtCore.Qt.Key_PageDown:self._step_cursor(1,100);event.accept();return
        if mods & QtCore.Qt.ControlModifier and key==QtCore.Qt.Key_BracketLeft:self._jump_event(-1);event.accept();return
        if mods & QtCore.Qt.ControlModifier and key==QtCore.Qt.Key_BracketRight:self._jump_event(1);event.accept();return
        if key in (QtCore.Qt.Key_Plus,QtCore.Qt.Key_Equal):self._zoom_x(.70);event.accept();return
        if key==QtCore.Qt.Key_Minus:self._zoom_x(1.40);event.accept();return
        if key==QtCore.Qt.Key_D:self._display_properties();event.accept();return
        if key==QtCore.Qt.Key_K:self._cycle_x_mode();event.accept();return
        if key==QtCore.Qt.Key_R:self._toggle_reference_cursor();event.accept();return
        if key in (QtCore.Qt.Key_P,QtCore.Qt.Key_Insert):
            win=self.window(); search=getattr(win,'channel_search',None)
            if search is not None:search.setFocus(QtCore.Qt.ShortcutFocusReason);search.selectAll()
            event.accept();return
        if key==QtCore.Qt.Key_Delete:
            row=self.readout.currentRow()
            if 0<=row<len(self.channels):self.remove_channel(self.channels[row])
            event.accept();return
        stat_map={QtCore.Qt.Key_M:'show_stat_min',QtCore.Qt.Key_X:'show_stat_max',QtCore.Qt.Key_N:'show_stat_mean',QtCore.Qt.Key_E:'show_stat_delta',QtCore.Qt.Key_Q:'show_stat_std'}
        attr=stat_map.get(key)
        if attr:
            setattr(self,attr,not bool(getattr(self,attr)));self._set_stat_column_visibility();self._refresh_readout();event.accept();return
        super().keyPressEvent(event)

    def _jump_event(self, direction: int):
        active=self.store.active
        if active is None:return
        positions=sorted({float(x) for _name,x in self._event_positions(active.run) if np.isfinite(x)})
        if not positions:return
        current=float(self.cursors.x); eps=1e-9
        if direction < 0:
            candidates=[x for x in positions if x < current-eps]
            target=candidates[-1] if candidates else positions[0]
        else:
            candidates=[x for x in positions if x > current+eps]
            target=candidates[0] if candidates else positions[-1]
        self.cursors.x=float(target); self.cursors.moved.emit(self.cursors.x)

    def _add_bookmark(self):
        active=self.store.active
        if active is None:return
        label,ok=QtWidgets.QInputDialog.getText(self,'Add bookmark','Bookmark name:')
        if not ok:return
        label=str(label).strip() or 'Bookmark'
        add_bookmark(active.run,float(self.cursors.x),label,x_mode=self.x_mode)
        self.store.changed.emit(); self.refresh()

    def _add_region(self):
        active=self.store.active
        if active is None:return
        a=float(self.cursors.a); b=float(self.cursors.b)
        if abs(b-a) < 1e-12:
            QtWidgets.QMessageBox.information(self,'Add region','Set A and B cursors to different positions first.');return
        label,ok=QtWidgets.QInputDialog.getText(self,'Add A-B region','Region name:')
        if not ok:return
        try:add_region(active.run,a,b,str(label).strip() or 'Region',x_mode=self.x_mode)
        except Exception as exc:QtWidgets.QMessageBox.warning(self,'Add region',str(exc));return
        self.store.changed.emit(); self.refresh()

    def _previous_view(self):
        if not self._plots or not self._range_history:
            return
        lo,hi=self._range_history.pop()
        self._syncing=True
        try:
            self._plots[0].setXRange(lo,hi,padding=0)
            self.nav_region.setRegion((lo,hi))
        finally:self._syncing=False
        self._last_range=(lo,hi)
        self.cursors.rangeChanged.emit(lo,hi,self)

    def _set_a_from_cursor(self):
        self.reference_visible = True
        self.cursors.a = float(self.cursors.x)
        self.cursors.cursorAMoved.emit(self.cursors.a)
        for lines in self._lines:
            lines[1].setVisible(True)
        self._update_reference_regions()
        self._refresh_readout()

    def _set_b_from_cursor(self):
        self.cursors.b = float(self.cursors.x)
        self.cursors.cursorBMoved.emit(self.cursors.b)

    def _fit_run(self):
        if not self._plots or self.store.active is None:
            return
        active=self.store.active
        try:
            p=infer_profile(active.run)
            window=drag_fit_window(active.run,self.x_mode,finish_distance_ft=p.finish_distance_ft)
            lo,hi=float(window.x_min),float(window.x_max)
            if np.isfinite(lo) and np.isfinite(hi) and hi>lo:
                self._plots[0].setXRange(lo,hi,padding=0)
                for plot in self._plots: plot.enableAutoRange(axis=pg.ViewBox.YAxis,enable=True)
                self._syncing=True
                try:self.nav_region.setRegion((lo,hi))
                finally:self._syncing=False
                self._last_range=(lo,hi)
                self.cursors.rangeChanged.emit(lo,hi,self)
        except Exception:
            logging.getLogger(__name__).exception('Could not fit drag run; using full logger range')
            self._fit_full()

    def _fit_full(self):
        if not self._plots:
            return
        active = self.store.active
        if active is None:
            return
        lo = np.inf; hi = -np.inf
        for c in self.channels:
            x, _y = self._x_data(active, c)
            finite = x[np.isfinite(x)]
            if len(finite):
                lo = min(lo, float(np.nanmin(finite))); hi = max(hi, float(np.nanmax(finite)))
        if np.isfinite(lo) and np.isfinite(hi) and hi > lo:
            self._plots[0].setXRange(lo, hi, padding=0.01)
            for p in self._plots:
                p.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)

    def _readout_menu(self, pos):
        row = self.readout.rowAt(pos.y())
        if row < 0 or row >= len(self.channels):
            return
        channel = self.channels[row]
        menu = QtWidgets.QMenu(self)
        properties_action = menu.addAction('Trace properties…')
        color_action = menu.addAction('Set trace color…')
        up_action = menu.addAction('Move up')
        down_action = menu.addAction('Move down')
        menu.addSeparator()
        remove_action = menu.addAction('Remove from waveform')
        chosen = menu.exec(self.readout.viewport().mapToGlobal(pos))
        if chosen == properties_action:
            self._trace_properties(channel)
        elif chosen == color_action:
            current = QtGui.QColor(self._style_for(channel, row).get('color', '#ffffff'))
            color = QtWidgets.QColorDialog.getColor(current, self, f'Trace color — {channel}')
            if color.isValid():
                self.channel_styles.setdefault(channel, {})['color'] = color.name()
                self.refresh()
        elif chosen == up_action and row > 0:
            self.channels[row-1], self.channels[row] = self.channels[row], self.channels[row-1]
            self.refresh()
        elif chosen == down_action and row < len(self.channels)-1:
            self.channels[row+1], self.channels[row] = self.channels[row], self.channels[row+1]
            self.refresh()
        elif chosen == remove_action:
            self.remove_channel(channel)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-nhra-velocity-channels"):
            event.acceptProposedAction()

    def dropEvent(self, event):
        try:
            channels = json.loads(bytes(event.mimeData().data("application/x-nhra-velocity-channels")).decode("utf-8"))
            changed = False
            for c in channels:
                if c not in self.channels:
                    self.channels.append(c); changed = True
            if changed:
                self.refresh()
            event.acceptProposedAction()
        except Exception:
            event.ignore()

    def add_channel(self, channel: str):
        if channel not in self.channels:
            self.channels.append(channel)
            self.refresh()

    def remove_channel(self, channel: str):
        if channel in self.channels:
            self.channels.remove(channel)
            self.refresh()

    def set_x_mode(self, mode: str):
        if self.x_mode == mode:
            return
        self.x_mode = mode
        self._data_cache.clear()
        self.refresh()

    def _x_data(self, handle: RunHandle, channel: str) -> Tuple[np.ndarray, np.ndarray]:
        return self._data_cache.xy(handle.run, channel, self.x_mode, handle.time_alignment_s)

    def _event_positions(self, run: TelemetryRun):
        events = [("Launch", 0.0)]
        if self.x_mode == "Distance from Launch":
            events += [("60",60.0),("330",330.0),("660",660.0),("1000",1000.0),("1320",1320.0)]
        elif self.x_mode == 'Normalized Run %':
            timing=run.timing.to_dict(); finish=timing.get('quarter_mile_s')
            if finish:
                for label,key in [('60','sixty_ft_s'),('330','three_thirty_ft_s'),('660','eighth_mile_s'),('1000','thousand_ft_s'),('1320','quarter_mile_s')]:
                    v=timing.get(key)
                    if v is not None: events.append((label,float(v)/float(finish)*100.0))
        elif self.x_mode == "Time from Launch":
            timing = run.timing.to_dict()
            for label, key in [("60","sixty_ft_s"),("330","three_thirty_ft_s"),("660","eighth_mile_s"),("1000","thousand_ft_s"),("1320","quarter_mile_s")]:
                v=timing.get(key)
                if v is not None: events.append((label,float(v)))
        for ann in annotations_for_mode(run,self.x_mode):
            if ann.kind == 'bookmark': events.append((ann.label,float(ann.x1)))
            elif ann.kind == 'region':
                events.append((f'{ann.label} start',float(ann.x1)))
                if ann.x2 is not None: events.append((f'{ann.label} end',float(ann.x2)))
        return events

    def _sample_at(self, handle: RunHandle, channel: str, x: float) -> float:
        vals=self._data_cache.sample_many(handle.run,channel,[float(x)],self.x_mode,handle.time_alignment_s)
        vals=self._convert_for_display(channel,handle.run,vals)
        return float(vals[0]) if len(vals) and np.isfinite(vals[0]) else np.nan

    def _ensure_readout_items(self):
        if self.readout.rowCount()!=len(self.channels):
            self.readout.setRowCount(len(self.channels))
        visible_rows=max(1,min(len(self.channels),7))
        self.readout.setFixedHeight(max(48,min(168,26 + visible_rows*19)))
        for row in range(len(self.channels)):
            for col in range(10):
                if self.readout.item(row,col) is None:
                    self.readout.setItem(row,col,QtWidgets.QTableWidgetItem(''))

    def _refresh_readout(self):
        handle = self.store.active
        ref_state = f"  Ref {self.cursors.a:.4f}" if self.reference_visible else ""
        self.zero_label.setText(f"Cursor  {self.cursors.x:.4f}{ref_state}")
        self._refresh_plot_headers()
        self._update_reference_regions()
        if not self.show_readout:
            return
        self._ensure_readout_items()
        if handle is None:
            return
        positions=(self.cursors.x,self.cursors.a,self.cursors.b)
        for row, channel in enumerate(self.channels):
            vals=self._data_cache.sample_many(handle.run,channel,positions,self.x_mode,handle.time_alignment_s)
            vals=self._convert_for_display(channel,handle.run,vals)
            current = vals[0] if len(vals)>0 else np.nan
            ref = vals[1] if len(vals)>1 and self.reference_visible else np.nan
            bval = vals[2] if len(vals)>2 else np.nan
            delta = current - ref if np.isfinite(current) and np.isfinite(ref) else np.nan
            if self.reference_visible:
                stats=self._data_cache.region_summary(handle.run,channel,self.cursors.a,self.cursors.x,self.x_mode,handle.time_alignment_s)
                stat_values=self._convert_for_display(channel,handle.run,np.asarray([stats.get('min',np.nan),stats.get('max',np.nan),stats.get('mean',np.nan),stats.get('std',np.nan)],dtype=float))
            else:
                stat_values=np.asarray([np.nan,np.nan,np.nan,np.nan],dtype=float)
            def fmt(v): return f"{float(v):.6g}" if np.isfinite(v) else "—"
            pieces = [channel, display_label(self._display_unit(channel, handle.run)), fmt(current), fmt(ref), fmt(delta), fmt(stat_values[0]), fmt(stat_values[1]), fmt(stat_values[2]), fmt(stat_values[3]), fmt(bval)]
            for col, text in enumerate(pieces):
                item=self.readout.item(row,col)
                text=str(text)
                if item.text()!=text:item.setText(text)
                if col == 0:
                    color = self._style_for(channel, row)['color']
                    if item.foreground().color().name()!=QtGui.QColor(color).name():item.setForeground(QtGui.QColor(color))

    def refresh(self):
        try:
            self._refresh_impl()
        except Exception as exc:
            logging.getLogger(__name__).exception("Waveform render failed")
            self.graph.clear(); self._plots.clear(); self._lines.clear(); self._reference_regions.clear(); self._plot_headers.clear()
            self.render_status.setText("RENDER ERROR — see diagnostic log")
            self.render_status.setStyleSheet("color:#ff7b72; font-weight:bold;")
            try:
                label=pg.LabelItem(f'Waveform render error: {type(exc).__name__}: {exc}', color='#ff7b72')
                self.graph.addItem(label,row=0,col=0)
            except Exception:
                pass

    def _refresh_impl(self):
        self.graph.clear()
        self.render_status.setText("Rendering…"); self.render_status.setStyleSheet("")
        self._rendered_curve_count=0; self._rendered_point_count=0
        self._plots.clear(); self._lines.clear(); self._reference_regions.clear(); self._plot_headers.clear()
        active = self.store.active
        if active is None:
            return
        run = active.run
        if not self.channels:
            # A successful import should immediately display useful data.
            # Canonical drag-racing channels are preferred; otherwise fall back
            # to the first numeric source channels in file order.
            self.channels = choose_default_plot_channels(run, limit=5)
        # Remove stale display references when switching to a differently named
        # logger. If none survive, repopulate from this session's defaults.
        available = set(_visible_channel_names(run))
        if self.channels and not any(c in available for c in self.channels):
            self.channels = choose_default_plot_channels(run, limit=5)
        if not self.channels:
            label = pg.LabelItem('No numeric channels are available to plot. Open Data Integrity for import diagnostics.', color='#e8a15b')
            self.graph.addItem(label, row=0, col=0)
            return

        # i2/ATLAS-style display modes. Stacked Channels gives each parameter
        # its own scale; Stacked Units shares exact display units; Grouped
        # Channels lets the engineer explicitly name an axis group; Overlay
        # intentionally puts everything on one graph. Group keys include the
        # display unit so a typo cannot silently put psi and rpm on one axis.
        groups: Dict[str, List[str]] = {}
        mode = self.layout_mode.currentText()
        for c in self.channels:
            unit = self._display_unit(c, run)
            if mode == "Overlay":
                key = "overlay"
            elif mode == "Stacked Units":
                key = f"unit:{dimension(unit)}:{unit}" if unit else f"channel:{c}"
            elif mode == "Grouped Channels":
                group_name = str(self.channel_styles.get(c, {}).get('axis_group', '') or '').strip()
                key = f"group:{group_name}:{dimension(unit)}:{unit}" if group_name else f"channel:{c}"
            else:
                key = f"channel:{c}"
            groups.setdefault(key, []).append(c)

        first_plot = None
        for row, (_group, chans) in enumerate(groups.items()):
            vb = VelocityWaveformViewBox(enableMenu=False)
            vb.cursorDragged.connect(self._cursor_dragged)
            p = self.graph.addPlot(row=row, col=0, viewBox=vb)
            p.setMouseEnabled(x=True, y=False)  # wheel/right/middle navigation affects X only; left-drag owns the cursor
            p.showGrid(x=True, y=True, alpha=0.15)
            # In a one-channel stacked plot the Y-axis already names the trace;
            # a legend just steals plot area.  Keep legends for overlays, unit
            # groups and compare runs where they carry real information.
            if self.show_legend and (self.compare or len(chans)>1 or mode=='Overlay'):
                p.addLegend(offset=(-8, 8), labelTextColor='#d6d6d6', brush=pg.mkBrush(24,26,29,180), pen=pg.mkPen('#44484d'))
            p.getAxis('left').setTextPen('#aeb4bb'); p.getAxis('bottom').setTextPen('#aeb4bb')
            try:p.getAxis('left').setWidth(52)
            except Exception:pass
            if first_plot is None:
                first_plot = p
            else:
                p.setXLink(first_plot)
            self._plots.append(p)
            for local_idx, c in enumerate(chans):
                for run_idx, handle in enumerate(self.store.overlays() if self.compare else [active]):
                    # For compare sessions, use exact channel name when present; if
                    # absent, fall back to the same canonical role.
                    target = c
                    if target not in handle.run.data.columns and target not in handle.run.native_channels:
                        role = next((k for k, v in run.metadata.get('original_channel_map', {}).items() if v == c), None)
                        target = handle.run.metadata.get('original_channel_map', {}).get(role, '') if role else ''
                    if not target:
                        continue
                    x, y = self._x_data(handle, target)
                    source_unit = normalize_unit(handle.run.units.get(target, ''))
                    target_unit = self._display_unit(c, run)
                    if source_unit and target_unit and dimension(source_unit) == dimension(target_unit) and source_unit != target_unit:
                        try: y = np.asarray(convert_value(np.asarray(y,float), source_unit, target_unit), dtype=float)
                        except Exception: y = np.asarray(y,float)
                    prepared=prepare_plot_series(x,y,max_points=self.max_render_points)
                    if prepared.output_points < 2:
                        logging.getLogger(__name__).warning("Skipped trace %s from %s: %s", target, handle.label, prepared.warning or 'fewer than two drawable samples')
                        continue
                    x=prepared.x; y=prepared.y
                    if prepared.warning:
                        logging.getLogger(__name__).warning("Display repair for %s/%s: %s", handle.label, target, prepared.warning)
                    style = self._style_for(c, self.channels.index(c))
                    color = style.get('color', '#e0e0e0')
                    base_width = float(style.get('width', 1.6))
                    pen = pg.mkPen(color, width=base_width if handle is active else max(0.8, base_width*0.65),
                                   style=QtCore.Qt.SolidLine if handle is active else QtCore.Qt.DashLine)
                    name = c if handle is active else f"{c} — {handle.label}"
                    curve=p.plot(x, y, pen=pen, name=name)
                    self._rendered_curve_count=getattr(self,'_rendered_curve_count',0)+1
                    self._rendered_point_count=getattr(self,'_rendered_point_count',0)+int(len(x))
            label_unit = self._display_unit(chans[0], run)
            # The per-band header carries the channel name/current/reference
            # values. Keep the Y axis narrow and numeric, like ATLAS/i2.
            p.setLabel('left', display_label(label_unit) if label_unit else '')
            if row == len(groups)-1:
                p.setLabel('bottom', self.x_mode)
            else:
                p.hideAxis('bottom')
            manual_ranges=[]
            for ch in chans:
                st=self.channel_styles.get(ch,{})
                if 'y_min' in st and 'y_max' in st:
                    manual_ranges.append((float(st['y_min']),float(st['y_max'])))
            if manual_ranges:
                p.setYRange(min(v[0] for v in manual_ranges), max(v[1] for v in manual_ranges), padding=0)
                p.enableAutoRange(axis=pg.ViewBox.YAxis, enable=False)
            ref_region = pg.LinearRegionItem(
                values=(float(self.cursors.a), float(self.cursors.x)),
                orientation=pg.LinearRegionItem.Vertical,
                movable=False,
                brush=pg.mkBrush(160, 160, 160, 28),
                pen=pg.mkPen(None),
            )
            ref_region.setZValue(-15); ref_region.setVisible(self.reference_visible); p.addItem(ref_region)
            self._reference_regions.append(ref_region)

            cursor = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen('#f4f4f4', width=1.2))
            ca = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen('#ff5252', width=1.2))
            cb = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen('#00e5ff', width=1, style=QtCore.Qt.DashLine))
            cursor.setValue(self.cursors.x); ca.setValue(self.cursors.a); cb.setValue(self.cursors.b)
            ca.setVisible(self.reference_visible); cb.setVisible(self.show_ab_cursors)
            p.addItem(cursor); p.addItem(ca); p.addItem(cb)

            band_header = pg.TextItem(
                '',
                anchor=(0, 0),
                fill=pg.mkBrush(18, 20, 23, 215),
                border=pg.mkPen('#363a3f', width=1),
            )
            band_header.setZValue(1000)
            p.addItem(band_header, ignoreBounds=True)
            self._plot_headers.append((p, band_header, list(chans)))
            p.sigRangeChanged.connect(lambda _plot, _ranges, pp=p, hh=band_header: self._position_plot_header(pp, hh))
            if self.events_box.isChecked():
                for ann in annotations_for_mode(run,self.x_mode):
                    if ann.kind=='region' and ann.x2 is not None:
                        region=pg.LinearRegionItem(values=(float(ann.x1),float(ann.x2)),movable=False,brush=pg.mkBrush(QtGui.QColor(ann.color).red(),QtGui.QColor(ann.color).green(),QtGui.QColor(ann.color).blue(),28),pen=pg.mkPen(ann.color,width=1,style=QtCore.Qt.DotLine))
                        region.setZValue(-20); p.addItem(region)
                for ev_name, ev_x in self._event_positions(run):
                    ev = pg.InfiniteLine(pos=ev_x, angle=90, movable=False, pen=pg.mkPen('#666a70', width=1, style=QtCore.Qt.DotLine), label=ev_name, labelOpts={'position':0.94,'color':'#8f949a'})
                    p.addItem(ev)
            cursor.sigPositionChanged.connect(lambda line: self._cursor_move(float(line.value())))
            ca.sigPositionChanged.connect(lambda line: self._a_move(float(line.value())))
            cb.sigPositionChanged.connect(lambda line: self._b_move(float(line.value())))
            self._lines.append((cursor, ca, cb))
            if first_plot is p:
                p.sigXRangeChanged.connect(lambda plot, rng: self._range_changed(rng))
        self.readout.setVisible(self.show_readout)
        self.navigator.setVisible(self.show_navigator)
        if self.show_navigator:self._refresh_navigator()
        self._refresh_readout()
        if self._rendered_curve_count:
            self.render_status.setText(f"{self._rendered_curve_count} curves / {self._rendered_point_count:,} pts")
            self.render_status.setStyleSheet("color:#78d381;")
        else:
            self.render_status.setText("NO CURVES — inspect Data Integrity")
            self.render_status.setStyleSheet("color:#ffb86b; font-weight:bold;")

    def _refresh_navigator(self):
        self.navigator.clear()
        self.navigator.addItem(self.nav_region)
        active = self.store.active
        if active is None:
            return
        run = active.run
        candidate = None
        for canonical in ('speed_mph', 'engine_rpm', 'driveshaft_rpm', 'longitudinal_g'):
            candidate = _source_for_canonical(run, canonical)
            if candidate:
                break
        if not candidate and self.channels:
            candidate = self.channels[0]
        if not candidate:
            return
        x, y = self._x_data(active, candidate)
        prepared=prepare_plot_series(x,y,max_points=10000)
        if prepared.output_points < 2:
            return
        xx=prepared.x; yy=prepared.y
        self.navigator.plot(xx, yy, pen=pg.mkPen('#6e879b', width=1))
        self.navigator.setXRange(float(np.nanmin(xx)), float(np.nanmax(xx)), padding=0.01)
        # Preserve the current main-view range when possible; otherwise start
        # with the whole pass visible.
        if self._plots:
            lo, hi = self._plots[0].viewRange()[0]
            if np.isfinite(lo) and np.isfinite(hi) and hi > lo:
                self._syncing=True
                try: self.nav_region.setRegion((float(lo), float(hi)))
                finally: self._syncing=False

    def _navigator_changed(self):
        if self._syncing or not self._plots:
            return
        lo, hi = self.nav_region.getRegion()
        self._syncing=True
        try:
            self._plots[0].setXRange(float(lo), float(hi), padding=0)
        finally:
            self._syncing=False
        self.cursors.rangeChanged.emit(float(lo), float(hi), self)

    def _cursor_move(self, x):
        if self._syncing: return
        x=self._snap_x(x)
        if abs(float(x)-float(self.cursors.x))<1e-12:return
        self.cursors.x = x; self.cursors.moved.emit(x)
    def _a_move(self, x):
        if self._syncing: return
        x=self._snap_x(x); self.cursors.a = x; self.cursors.cursorAMoved.emit(x)
    def _b_move(self, x):
        if self._syncing: return
        x=self._snap_x(x); self.cursors.b = x; self.cursors.cursorBMoved.emit(x)
    def _external_cursor(self, x):
        self._set_lines(0, x); self._update_reference_regions()
    def _external_a(self, x):
        self._set_lines(1, x); self._update_reference_regions()
    def _external_b(self, x): self._set_lines(2, x)
    def _set_lines(self, idx, x):
        self._syncing = True
        try:
            for lines in self._lines: lines[idx].setValue(x)
        finally: self._syncing = False
    def _external_range(self, lo, hi, source):
        if source is self or self._syncing or not self._plots: return
        self._syncing=True
        try:
            self._plots[0].setXRange(float(lo),float(hi),padding=0)
            self.nav_region.setRegion((float(lo), float(hi)))
        finally:self._syncing=False
    def _range_changed(self, rng):
        if self._syncing: return
        try:
            lo, hi = float(rng[0]), float(rng[1])
            if self._last_range is not None:
                plo,phi=self._last_range
                span=max(abs(phi-plo),1e-9)
                if abs(lo-plo)>span*1e-4 or abs(hi-phi)>span*1e-4:
                    if not self._range_history or self._range_history[-1]!=(plo,phi):
                        self._range_history.append((plo,phi))
                        if len(self._range_history)>40:self._range_history=self._range_history[-40:]
            self._last_range=(lo,hi)
            self._syncing=True
            try: self.nav_region.setRegion((lo, hi))
            finally: self._syncing=False
            self.cursors.rangeChanged.emit(lo, hi, self)
        except Exception: pass


class ValuesDisplay(QtWidgets.QTableWidget):
    def __init__(self, store: SessionStore, cursors: CursorBus, waveform: Optional[WaveformDisplay] = None):
        super().__init__()
        self.store = store; self.cursors = cursors; self.waveform = waveform
        self.setColumnCount(6)
        self.setHorizontalHeaderLabels(["Channel", "Unit", "Cursor", "A", "B", "B-A"])
        self.horizontalHeader().setStretchLastSection(True)
        self.setAlternatingRowColors(True)
        self._timer=QtCore.QTimer(self);self._timer.setSingleShot(True);self._timer.setInterval(33);self._timer.timeout.connect(self.refresh)
        for sig in (cursors.moved, cursors.cursorAMoved, cursors.cursorBMoved):
            sig.connect(self._schedule)
        store.activeChanged.connect(lambda _: self.refresh());store.changed.connect(self._schedule)

    def _schedule(self,*_args):
        if not self._timer.isActive():self._timer.start()

    def refresh(self):
        h = self.store.active
        channels = self.waveform.channels if (h and self.waveform) else []
        if self.rowCount()!=len(channels):self.setRowCount(len(channels))
        if not h or not self.waveform:return
        positions=(self.cursors.x,self.cursors.a,self.cursors.b)
        for r, c in enumerate(channels):
            vals=self.waveform._data_cache.sample_many(h.run,c,positions,self.waveform.x_mode,h.time_alignment_s)
            vals=self.waveform._convert_for_display(c,h.run,vals)
            delta = vals[2] - vals[1] if len(vals)>=3 and np.isfinite(vals[1]) and np.isfinite(vals[2]) else np.nan
            row = [c, display_label(self.waveform._display_unit(c,h.run)), *[f"{v:.6g}" if np.isfinite(v) else "" for v in vals[:3]], f"{delta:.6g}" if np.isfinite(delta) else ""]
            for col, val in enumerate(row):
                item=self.item(r,col)
                if item is None:item=QtWidgets.QTableWidgetItem('');self.setItem(r,col,item)
                text=str(val)
                if item.text()!=text:item.setText(text)


class GaugeDisplay(QtWidgets.QWidget):
    """Single-channel numeric/bar/dial/bit dashboard display driven by worksheet cursor."""
    def __init__(self, store: SessionStore, cursors: CursorBus):
        super().__init__(); self.store=store; self.cursors=cursors; self.x_mode='Time from Launch'
        self._data_cache=DisplaySeriesCache(max_entries=64);self._auto_ranges={}
        self._timer=QtCore.QTimer(self);self._timer.setSingleShot(True);self._timer.setInterval(33);self._timer.timeout.connect(self.refresh)
        lay=QtWidgets.QVBoxLayout(self); lay.setContentsMargins(6,6,6,6)
        ctl=QtWidgets.QHBoxLayout(); self.channel=QtWidgets.QComboBox(); self.mode=QtWidgets.QComboBox(); self.mode.addItems(['Numeric','Bar','Dial','Bit'])
        self.auto=QtWidgets.QCheckBox('Auto range'); self.auto.setChecked(True)
        ctl.addWidget(QtWidgets.QLabel('Channel'));ctl.addWidget(self.channel,1);ctl.addWidget(QtWidgets.QLabel('Style'));ctl.addWidget(self.mode);ctl.addWidget(self.auto);lay.addLayout(ctl)
        rng=QtWidgets.QHBoxLayout(); self.minimum=QtWidgets.QDoubleSpinBox();self.maximum=QtWidgets.QDoubleSpinBox();self.threshold=QtWidgets.QDoubleSpinBox()
        for w in (self.minimum,self.maximum,self.threshold): w.setRange(-1e12,1e12);w.setDecimals(5)
        self.minimum.setValue(0);self.maximum.setValue(100);self.threshold.setValue(0.5)
        rng.addWidget(QtWidgets.QLabel('Min'));rng.addWidget(self.minimum);rng.addWidget(QtWidgets.QLabel('Max'));rng.addWidget(self.maximum);rng.addWidget(QtWidgets.QLabel('Bit threshold'));rng.addWidget(self.threshold);lay.addLayout(rng)
        self.title=QtWidgets.QLabel('No channel');self.title.setAlignment(QtCore.Qt.AlignCenter);lay.addWidget(self.title)
        self.value=QtWidgets.QLabel('—');self.value.setAlignment(QtCore.Qt.AlignCenter);f=self.value.font();f.setPointSize(28);f.setBold(True);self.value.setFont(f);lay.addWidget(self.value)
        self.bar=QtWidgets.QProgressBar();self.bar.setRange(0,1000);self.bar.setTextVisible(False);lay.addWidget(self.bar)
        self.dial=QtWidgets.QDial();self.dial.setRange(0,1000);self.dial.setNotchesVisible(True);lay.addWidget(self.dial,1)
        self.bit=QtWidgets.QLabel('OFF');self.bit.setAlignment(QtCore.Qt.AlignCenter);fb=self.bit.font();fb.setPointSize(24);fb.setBold(True);self.bit.setFont(fb);lay.addWidget(self.bit,1)
        for w in (self.channel,self.mode): w.currentTextChanged.connect(self.refresh)
        for w in (self.minimum,self.maximum,self.threshold): w.valueChanged.connect(self.refresh)
        self.auto.toggled.connect(self.refresh);cursors.moved.connect(self._schedule);store.activeChanged.connect(lambda _h:self.populate());store.changed.connect(self._store_changed);self.populate()
    def _schedule(self,*_args):
        if not self._timer.isActive():self._timer.start()
    def set_x_mode(self,mode): self.x_mode=str(mode);self._data_cache.clear();self._auto_ranges.clear();self.refresh()
    def _store_changed(self): self._data_cache.clear();self._auto_ranges.clear();self.populate(self.channel.currentText())
    def populate(self,preferred=''):
        current=preferred or self.channel.currentText();self.channel.blockSignals(True);self.channel.clear();h=self.store.active
        if h:self.channel.addItems(_visible_channel_names(h.run))
        if current:
            i=self.channel.findText(current);self.channel.setCurrentIndex(i if i>=0 else 0)
        self.channel.blockSignals(False);self.refresh()
    def _range(self,h,name):
        lo=float(self.minimum.value());hi=float(self.maximum.value())
        if self.auto.isChecked():
            key=(id(h.run),name,self.x_mode,round(float(h.time_alignment_s),12))
            cached=self._auto_ranges.get(key)
            if cached is not None:return cached
            try:
                _x,y=self._data_cache.xy(h.run,name,self.x_mode,h.time_alignment_s);y=np.asarray(y,float);y=y[np.isfinite(y)]
                if len(y):lo=float(np.nanmin(y));hi=float(np.nanmax(y))
            except Exception:pass
            if not np.isfinite(lo+hi) or hi<=lo:hi=lo+1.0
            self._auto_ranges[key]=(lo,hi);return lo,hi
        if not np.isfinite(lo+hi) or hi<=lo:hi=lo+1.0
        return lo,hi
    def refresh(self):
        h=self.store.active;name=self.channel.currentText();mode=self.mode.currentText()
        self.bar.setVisible(mode=='Bar');self.dial.setVisible(mode=='Dial');self.bit.setVisible(mode=='Bit');self.value.setVisible(mode!='Bit')
        if not h or not name:self.title.setText('No channel');self.value.setText('—');return
        vals=self._data_cache.sample_many(h.run,name,[float(self.cursors.x)],self.x_mode,h.time_alignment_s)
        v=float(vals[0]) if len(vals) else float('nan')
        unit=display_label(h.run.units.get(name,'')) or h.run.units.get(name,'');self.title.setText(f'{name}' + (f' [{unit}]' if unit else ''))
        if not np.isfinite(v):self.value.setText('—');self.bit.setText('OUT OF RANGE');return
        self.value.setText(f'{v:.6g}')
        lo,hi=self._range(h,name);frac=float(np.clip((v-lo)/(hi-lo),0,1));scaled=int(round(frac*1000));self.bar.setValue(scaled);self.dial.setValue(scaled)
        on=v>=float(self.threshold.value());self.bit.setText('ON' if on else 'OFF')


class ScatterDisplay(QtWidgets.QWidget):
    """Advanced XY scatter with optional Z colour, gate and linear regression."""
    def __init__(self, store: SessionStore):
        super().__init__(); self.store=store
        lay=QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0,0,0,0)
        controls=QtWidgets.QHBoxLayout(); self.xbox=QtWidgets.QComboBox(); self.ybox=QtWidgets.QComboBox();self.zbox=QtWidgets.QComboBox();self.gate=QtWidgets.QComboBox();self.regression=QtWidgets.QCheckBox('Linear fit')
        controls.addWidget(QtWidgets.QLabel('X'));controls.addWidget(self.xbox,1);controls.addWidget(QtWidgets.QLabel('Y'));controls.addWidget(self.ybox,1);controls.addWidget(QtWidgets.QLabel('Z colour'));controls.addWidget(self.zbox,1);controls.addWidget(QtWidgets.QLabel('Gate'));controls.addWidget(self.gate);controls.addWidget(self.regression);lay.addLayout(controls)
        self.stats=QtWidgets.QLabel('');self.stats.setWordWrap(True);lay.addWidget(self.stats)
        self.plot=pg.PlotWidget(background=(20,22,25));self.plot.showGrid(x=True,y=True,alpha=.15);lay.addWidget(self.plot,1)
        for box in (self.xbox,self.ybox,self.zbox,self.gate): box.currentIndexChanged.connect(self.refresh)
        self.regression.toggled.connect(self.refresh);store.activeChanged.connect(lambda _h:self.populate());store.changed.connect(self._store_changed);self.populate()
    def _store_changed(self):self.populate(self.xbox.currentText(),self.ybox.currentText(),self.zbox.currentData(),self.gate.currentData())
    def populate(self,xpref='',ypref='',zpref=None,gpref=None):
        h=self.store.active
        for box in (self.xbox,self.ybox,self.zbox,self.gate):box.blockSignals(True);box.clear()
        self.zbox.addItem('(none)','');self.gate.addItem('(none)','')
        if h:
            names=_visible_channel_names(h.run);self.xbox.addItems(names);self.ybox.addItems(names)
            for n in names:self.zbox.addItem(n,n)
            for g in gates(h.run):self.gate.addItem(g.name,g.expression)
        for box,pref,data in ((self.xbox,xpref,None),(self.ybox,ypref,None)):
            if pref:
                i=box.findText(pref);box.setCurrentIndex(i if i>=0 else 0)
        if zpref:
            i=self.zbox.findData(zpref);self.zbox.setCurrentIndex(i if i>=0 else 0)
        if gpref:
            i=self.gate.findData(gpref);self.gate.setCurrentIndex(i if i>=0 else 0)
        for box in (self.xbox,self.ybox,self.zbox,self.gate):box.blockSignals(False)
        self.refresh()
    def refresh(self):
        self.plot.clear();h=self.store.active
        if not h:return
        xname,yname=self.xbox.currentText(),self.ybox.currentText();zname=str(self.zbox.currentData() or '');gate_expr=str(self.gate.currentData() or '')
        if not xname or not yname:return
        try:
            data=paired_channel_data(h.run,xname,yname,zname or None,gate_expression=gate_expr,max_points=20000)
            if data.points<2:return
            if data.z is None:
                self.plot.plot(data.x,data.y,pen=None,symbol='o',symbolSize=4,symbolBrush='#5bc0eb')
            else:
                z=np.asarray(data.z,float);zlo=float(np.nanpercentile(z,2));zhi=float(np.nanpercentile(z,98));span=max(zhi-zlo,1e-12);r=np.clip((z-zlo)/span,0,1)
                brushes=[pg.mkBrush(QtGui.QColor.fromHsvF(float(.68*(1-v)),.85,.95,.85)) for v in r]
                item=pg.ScatterPlotItem(x=data.x,y=data.y,size=5,pen=None,brush=brushes);self.plot.addItem(item)
            text=f'{data.points:,} points' + (f' | gate: {self.gate.currentText()}' if gate_expr else '')
            if self.regression.isChecked():
                fit=linear_regression(data.x,data.y);xx=np.array([fit.x_min,fit.x_max]);self.plot.plot(xx,fit.predict(xx),pen=pg.mkPen('#f9c74f',width=2));text+=f' | y={fit.slope:.5g}x{fit.intercept:+.5g} | R²={fit.r_squared:.5f}'
            self.stats.setText(text);self.plot.setLabel('bottom',xname);self.plot.setLabel('left',yname)
        except Exception as exc:self.stats.setText(f'Scatter unavailable: {exc}')


class HistogramDisplay(QtWidgets.QWidget):
    """Sample/time-weighted and cumulative channel distribution."""
    def __init__(self, store: SessionStore):
        super().__init__();self.store=store
        lay=QtWidgets.QVBoxLayout(self);lay.setContentsMargins(0,0,0,0)
        ctl=QtWidgets.QHBoxLayout();self.channel=QtWidgets.QComboBox();self.bins=QtWidgets.QSpinBox();self.bins.setRange(10,500);self.bins.setValue(60);self.mode=QtWidgets.QComboBox();self.mode.addItems(['Samples','% Samples','Time [s]','% Time']);self.cumulative=QtWidgets.QCheckBox('Cumulative');self.gate=QtWidgets.QComboBox()
        ctl.addWidget(QtWidgets.QLabel('Channel'));ctl.addWidget(self.channel,1);ctl.addWidget(QtWidgets.QLabel('Bins'));ctl.addWidget(self.bins);ctl.addWidget(self.mode);ctl.addWidget(self.cumulative);ctl.addWidget(QtWidgets.QLabel('Gate'));ctl.addWidget(self.gate);lay.addLayout(ctl)
        self.stats=QtWidgets.QLabel('');lay.addWidget(self.stats);self.plot=pg.PlotWidget(background=(20,22,25));self.plot.showGrid(x=True,y=True,alpha=.15);lay.addWidget(self.plot,1)
        for w in (self.channel,self.mode,self.gate):w.currentIndexChanged.connect(self.refresh)
        self.bins.valueChanged.connect(self.refresh);self.cumulative.toggled.connect(self.refresh);store.activeChanged.connect(lambda _h:self.populate());store.changed.connect(self._store_changed);self.populate()
    def _store_changed(self):self.populate(self.channel.currentText(),self.gate.currentData())
    def populate(self,preferred='',gpref=None):
        self.channel.blockSignals(True);self.gate.blockSignals(True);self.channel.clear();self.gate.clear();self.gate.addItem('(none)','');h=self.store.active
        if h:
            self.channel.addItems(_visible_channel_names(h.run))
            for g in gates(h.run):self.gate.addItem(g.name,g.expression)
        if preferred:
            i=self.channel.findText(preferred);self.channel.setCurrentIndex(i if i>=0 else 0)
        if gpref:
            i=self.gate.findData(gpref);self.gate.setCurrentIndex(i if i>=0 else 0)
        self.channel.blockSignals(False);self.gate.blockSignals(False);self.refresh()
    def refresh(self):
        self.plot.clear();h=self.store.active;name=self.channel.currentText()
        if not h or not name:return
        modes={'Samples':'samples','% Samples':'percent_samples','Time [s]':'time','% Time':'percent_time'}
        try:
            result=channel_distribution(h.run,name,bins=int(self.bins.value()),mode=modes[self.mode.currentText()],cumulative=self.cumulative.isChecked(),gate_expression=str(self.gate.currentData() or ''))
            widths=np.diff(result.edges);bg=pg.BarGraphItem(x=result.centers,height=result.values,width=widths*.95,brush='#5bc0eb');self.plot.addItem(bg)
            label={'samples':'Samples','percent_samples':'% Samples','time':'Time [s]','percent_time':'% Time'}[result.mode];self.plot.setLabel('bottom',name);self.plot.setLabel('left',('Cumulative ' if result.cumulative else '')+label)
            self.stats.setText(f'{result.used_points:,} samples' + (f' | {result.total_time_s:.5g} s represented' if result.mode in {'time','percent_time'} else '') + (f' | gate: {self.gate.currentText()}' if self.gate.currentData() else ''))
        except Exception as exc:self.stats.setText(f'Distribution unavailable: {exc}')


class SpectrumDisplay(QtWidgets.QWidget):
    """FFT amplitude or Welch PSD for a selected telemetry channel."""
    def __init__(self, store: SessionStore, cursors: Optional[CursorBus]=None):
        super().__init__(); self.store=store; self.cursors=cursors; self.x_mode='Time from Launch'
        lay=QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0,0,0,0)
        ctl=QtWidgets.QHBoxLayout(); self.channel=QtWidgets.QComboBox(); self.mode=QtWidgets.QComboBox(); self.mode.addItems(['FFT Amplitude','PSD (Welch)','Spectrogram']); self.window=QtWidgets.QComboBox(); self.window.addItems(['hann','hamming','blackman','boxcar'])
        self.maxfreq=QtWidgets.QDoubleSpinBox(); self.maxfreq.setRange(0.1,50000); self.maxfreq.setValue(500); self.maxfreq.setDecimals(1); self.maxfreq.setSuffix(' Hz')
        self.logy=QtWidgets.QCheckBox('Log amplitude'); self.use_ab=QtWidgets.QCheckBox('Reference-to-cursor only')
        ctl.addWidget(QtWidgets.QLabel('Channel'));ctl.addWidget(self.channel,1);ctl.addWidget(QtWidgets.QLabel('Mode'));ctl.addWidget(self.mode);ctl.addWidget(QtWidgets.QLabel('Window'));ctl.addWidget(self.window);ctl.addWidget(QtWidgets.QLabel('Max'));ctl.addWidget(self.maxfreq);ctl.addWidget(self.logy);ctl.addWidget(self.use_ab)
        lay.addLayout(ctl)
        self.stats=QtWidgets.QLabel('Select a channel with a valid timebase.'); self.stats.setWordWrap(True); lay.addWidget(self.stats)
        self.plot=pg.PlotWidget(background=(20,22,25)); self.plot.showGrid(x=True,y=True,alpha=.15); lay.addWidget(self.plot,1)
        self.channel.currentTextChanged.connect(self.refresh); self.mode.currentTextChanged.connect(self.refresh); self.window.currentTextChanged.connect(self.refresh); self.maxfreq.valueChanged.connect(self.refresh); self.logy.toggled.connect(self.refresh); self.use_ab.toggled.connect(self.refresh)
        if self.cursors is not None:
            self.cursors.cursorAMoved.connect(lambda _x:self.refresh() if self.use_ab.isChecked() else None); self.cursors.moved.connect(lambda _x:self.refresh() if self.use_ab.isChecked() else None)
        store.activeChanged.connect(lambda _h:self.populate()); store.changed.connect(self._store_changed); self.populate()
    def _store_changed(self):
        current=self.channel.currentText(); self.populate(current)
    def populate(self, preferred=None):
        current=preferred or self.channel.currentText(); self.channel.blockSignals(True); self.channel.clear(); h=self.store.active
        if h:self.channel.addItems(_visible_channel_names(h.run))
        if current:
            i=self.channel.findText(current); self.channel.setCurrentIndex(i if i>=0 else 0)
        self.channel.blockSignals(False); self.refresh()
    def refresh(self):
        self.plot.clear(); h=self.store.active; name=self.channel.currentText()
        if not h or not name:return
        # FFT requires seconds, not Sample Index. Native channels always retain
        # their logger clock; rectangular channels require a validated time map.
        if name not in h.run.native_channels and not h.run.channel_map.get('time_s'):
            self.stats.setText('FFT unavailable: this session has no validated time channel. Sample Index is view-only.'); return
        try:
            x,y=channel_xy(h.run,name,'Logger Time',0.0)
            if self.use_ab.isChecked():
                if self.cursors is None: raise ValueError('Reference-to-cursor spectrum is unavailable without worksheet cursors.')
                region_x,region_y=channel_xy(h.run,name,self.x_mode,h.time_alignment_s)
                n=min(len(x),len(y),len(region_x),len(region_y)); x=x[:n];y=y[:n];region_x=region_x[:n]
                a=min(float(self.cursors.a),float(self.cursors.x)); b=max(float(self.cursors.a),float(self.cursors.x))
                keep=np.isfinite(x)&np.isfinite(y)&np.isfinite(region_x)&(region_x>=a)&(region_x<=b)
                if int(keep.sum())<8: raise ValueError('Reference-to-cursor region contains too few samples for FFT.')
                x=np.asarray(x[keep],float);y=np.asarray(y[keep],float)
            if self.mode.currentText().startswith('Spectrogram'):
                result=spectrogram(x,y,max_frequency_hz=float(self.maxfreq.value()),window=self.window.currentText())
                density=np.asarray(result.density,float)
                if self.logy.isChecked(): density=10*np.log10(np.maximum(density,1e-30))
                image=pg.ImageItem();image.setImage(density.T,autoLevels=True)
                if len(result.time_s)>1 and len(result.frequency_hz)>1:
                    rect=QtCore.QRectF(float(result.time_s[0]),float(result.frequency_hz[0]),float(result.time_s[-1]-result.time_s[0]),float(result.frequency_hz[-1]-result.frequency_hz[0]));image.setRect(rect)
                self.plot.addItem(image);self.plot.setLabel('bottom','Logger Time [s]');self.plot.setLabel('left','Frequency [Hz]')
                peak_idx=np.unravel_index(int(np.nanargmax(result.density)),result.density.shape);peakf=float(result.frequency_hz[peak_idx[0]]);peakt=float(result.time_s[peak_idx[1]])
                self.stats.setText(f'Spectrogram  |  sample rate {result.sample_rate_hz:.3f} Hz  |  peak energy near {peakf:.4g} Hz at {peakt:.4g} s  |  segment {result.segment_points} samples')
            elif self.mode.currentText().startswith('PSD'):
                result=power_spectral_density(x,y,max_frequency_hz=float(self.maxfreq.value()),window=self.window.currentText())
                values=np.asarray(result.density,float)
                unit=display_label(h.run.units.get(name,'')) or h.run.units.get(name,'')
                if self.logy.isChecked():
                    values=10*np.log10(np.maximum(values,1e-30)); ylabel='PSD [dB/Hz]'
                else:
                    ylabel='Power spectral density'+(f' [{unit}²/Hz]' if unit else ' [unit²/Hz]')
                self.plot.plot(result.frequency_hz,values,pen=pg.mkPen('#5bc0eb',width=1.4)); self.plot.setLabel('bottom','Frequency [Hz]'); self.plot.setLabel('left',ylabel)
                if len(result.frequency_hz)>1:
                    idx=int(np.argmax(result.density[1:])+1); peakf=float(result.frequency_hz[idx]); peak=float(result.density[idx])
                    self.stats.setText(f'PSD  |  sample rate {result.sample_rate_hz:.3f} Hz  |  resolution {result.resolution_hz:.5g} Hz  |  peak {peakf:.4g} Hz @ {peak:.5g}  |  Welch segment {result.segment_points} samples')
            else:
                result=fft_spectrum(x,y,max_frequency_hz=float(self.maxfreq.value()),window=self.window.currentText())
                amp=np.asarray(result.amplitude,float)
                if self.logy.isChecked():
                    amp=20*np.log10(np.maximum(amp,1e-15)); ylabel='Amplitude [dB]'
                else:
                    unit=display_label(h.run.units.get(name,'')); ylabel='Amplitude'+(f' [{unit}]' if unit else '')
                self.plot.plot(result.frequency_hz,amp,pen=pg.mkPen('#5bc0eb',width=1.4)); self.plot.setLabel('bottom','Frequency [Hz]'); self.plot.setLabel('left',ylabel)
                if len(result.frequency_hz)>1:
                    idx=int(np.argmax(result.amplitude[1:])+1); peakf=float(result.frequency_hz[idx]); peaka=float(result.amplitude[idx])
                    self.stats.setText(f'FFT  |  sample rate {result.sample_rate_hz:.3f} Hz  |  resolution {result.resolution_hz:.5g} Hz  |  peak {peakf:.4g} Hz @ {peaka:.5g}  |  {result.source_points:,} source samples')
        except Exception as exc:self.stats.setText(f'Spectrum unavailable: {exc}')

    def set_x_mode(self, mode: str):
        self.x_mode=str(mode or 'Time from Launch');
        if self.use_ab.isChecked(): self.refresh()


class LoadMapDisplay(QtWidgets.QWidget):
    """ATLAS-style 2-D load/mixture/occupancy map."""
    def __init__(self, store: SessionStore):
        super().__init__(); self.store=store
        lay=QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0,0,0,0)
        ctl=QtWidgets.QGridLayout(); self.xbox=QtWidgets.QComboBox(); self.ybox=QtWidgets.QComboBox(); self.zbox=QtWidgets.QComboBox()
        self.stat=QtWidgets.QComboBox(); self.stat.addItems(['mean','median','min','max','std','count'])
        self.bins=QtWidgets.QSpinBox(); self.bins.setRange(5,100); self.bins.setValue(30); self.gate=QtWidgets.QComboBox()
        ctl.addWidget(QtWidgets.QLabel('X'),0,0);ctl.addWidget(self.xbox,0,1);ctl.addWidget(QtWidgets.QLabel('Y'),0,2);ctl.addWidget(self.ybox,0,3)
        ctl.addWidget(QtWidgets.QLabel('Z / value'),1,0);ctl.addWidget(self.zbox,1,1);ctl.addWidget(QtWidgets.QLabel('Statistic'),1,2);ctl.addWidget(self.stat,1,3);ctl.addWidget(QtWidgets.QLabel('Bins'),1,4);ctl.addWidget(self.bins,1,5);ctl.addWidget(QtWidgets.QLabel('Gate'),2,0);ctl.addWidget(self.gate,2,1,1,3)
        lay.addLayout(ctl)
        self.info=QtWidgets.QLabel('Select X/Y and a Z channel, or use Count for occupancy.'); self.info.setWordWrap(True); lay.addWidget(self.info)
        self.plot=pg.PlotWidget(background=(20,22,25)); self.plot.showGrid(x=True,y=True,alpha=.10); lay.addWidget(self.plot,1)
        for w in (self.xbox,self.ybox,self.zbox,self.stat,self.gate): w.currentTextChanged.connect(self.refresh)
        self.bins.valueChanged.connect(self.refresh); store.activeChanged.connect(lambda _h:self.populate()); store.changed.connect(self._store_changed); self.populate()
    def _store_changed(self): self.populate(self.xbox.currentText(),self.ybox.currentText(),self.zbox.currentText())
    def populate(self,xpref='',ypref='',zpref=''):
        h=self.store.active; names=_visible_channel_names(h.run) if h else []
        for box,pref in ((self.xbox,xpref),(self.ybox,ypref),(self.zbox,zpref)):
            box.blockSignals(True);box.clear();box.addItems(names)
            if pref:
                i=box.findText(pref);box.setCurrentIndex(i if i>=0 else 0)
            box.blockSignals(False)
        if len(names)>1 and not ypref:self.ybox.setCurrentIndex(1)
        if len(names)>2 and not zpref:self.zbox.setCurrentIndex(2)
        current_gate=self.gate.currentData();self.gate.blockSignals(True);self.gate.clear();self.gate.addItem('(no gate)','')
        if h:
            for g in gates(h.run):self.gate.addItem(g.name,g.name)
        if current_gate:
            i=self.gate.findData(current_gate);self.gate.setCurrentIndex(i if i>=0 else 0)
        self.gate.blockSignals(False);self.refresh()
    def _series(self,run,name):
        x,y=channel_xy(run,name,'Logger Time',0.0); p=prepare_plot_series(x,y,max_points=250000)
        return np.asarray(p.x,float),np.asarray(p.y,float)
    def refresh(self):
        self.plot.clear(); h=self.store.active
        if not h:return
        xn,yn,zn=self.xbox.currentText(),self.ybox.currentText(),self.zbox.currentText(); stat=self.stat.currentText()
        if not xn or not yn:return
        try:
            gate_name=str(self.gate.currentData() or '')
            if gate_name:
                # Gates intentionally operate on the rectangular analysis clock;
                # no hidden interpolation is performed inside a boolean condition.
                required=[xn,yn]+([] if stat=='count' else [zn])
                if any(name not in h.run.data.columns for name in required):raise ValueError('This gate uses the normalized analysis table. Selected native-only channels must be mapped/normalized first.')
                mask=evaluate_gate(h.run,next(g.expression for g in gates(h.run) if g.name==gate_name))
                xv=pd.to_numeric(h.run.data[xn],errors='coerce').to_numpy(float);yv=pd.to_numeric(h.run.data[yn],errors='coerce').to_numpy(float);zv=None if stat=='count' else pd.to_numeric(h.run.data[zn],errors='coerce').to_numpy(float)
                result=binned_map(xv,yv,zv,bins=(int(self.bins.value()),int(self.bins.value())),statistic=stat,mask=mask)
            else:
                tx,x=self._series(h.run,xn);ty,y=self._series(h.run,yn)
                series=[(tx,x),(ty,y)]
                if stat!='count':
                    if not zn:raise ValueError('Choose a Z/value channel for this statistic.')
                    tz,z=self._series(h.run,zn);series.append((tz,z))
                lo=max(v[0][0] for v in series if len(v[0]));hi=min(v[0][-1] for v in series if len(v[0]))
                if not np.isfinite(lo+hi) or hi<=lo:raise ValueError('Selected channels do not overlap in time.')
                base=min(series,key=lambda v:len(v[0]))[0];t=base[(base>=lo)&(base<=hi)]
                if len(t)<3:raise ValueError('Too few overlapping samples for a load map.')
                xv=np.interp(t,tx,x);yv=np.interp(t,ty,y);zv=None if stat=='count' else np.interp(t,tz,z)
                result=binned_map(xv,yv,zv,bins=(int(self.bins.value()),int(self.bins.value())),statistic=stat)
            image=pg.ImageItem();image.setImage(np.asarray(result.values,float).T,autoLevels=True)
            rect=QtCore.QRectF(float(result.x_edges[0]),float(result.y_edges[0]),float(result.x_edges[-1]-result.x_edges[0]),float(result.y_edges[-1]-result.y_edges[0]));image.setRect(rect);self.plot.addItem(image)
            self.plot.setLabel('bottom',xn+(f' [{display_label(h.run.units.get(xn,""))}]' if h.run.units.get(xn) else ''))
            self.plot.setLabel('left',yn+(f' [{display_label(h.run.units.get(yn,""))}]' if h.run.units.get(yn) else ''))
            occupied=int(np.sum(result.counts>0)); self.info.setText(f'{stat.title()} map  |  {result.used_points:,} samples  |  {occupied} occupied cells  |  {int(self.bins.value())}×{int(self.bins.value())} bins')
        except Exception as exc:self.info.setText(f'Load map unavailable: {exc}')


class MetricReportDisplay(QtWidgets.QWidget):
    """Reusable Run/segment KPI table; each Run uses its own official timing."""
    def __init__(self, store: SessionStore):
        super().__init__();self.store=store
        lay=QtWidgets.QVBoxLayout(self);lay.setContentsMargins(0,0,0,0)
        ctl=QtWidgets.QHBoxLayout();self.channel=QtWidgets.QComboBox();self.stat=QtWidgets.QComboBox();self.stat.addItems(['mean','min','max','median','std','rms','range','start','end','delta','integral','slope','p05','p95'])
        self.xmode=QtWidgets.QComboBox();self.xmode.addItems(['Time from Launch','Distance from Launch','Normalized Run %'])
        ctl.addWidget(QtWidgets.QLabel('Channel'));ctl.addWidget(self.channel,1);ctl.addWidget(QtWidgets.QLabel('Metric'));ctl.addWidget(self.stat);ctl.addWidget(QtWidgets.QLabel('Segments'));ctl.addWidget(self.xmode);lay.addLayout(ctl)
        self.note=QtWidgets.QLabel('Main + Reference/Overlay sessions. Time-mode segments use each Run’s own official NHRA timestamps.');self.note.setWordWrap(True);lay.addWidget(self.note)
        self.table=QtWidgets.QTableWidget(0,7);self.table.setHorizontalHeaderLabels(['Run','Segment','Value','Unit','Samples','Start','End']);self.table.setAlternatingRowColors(True);self.table.verticalHeader().setVisible(False);self.table.horizontalHeader().setSectionResizeMode(1,QtWidgets.QHeaderView.Stretch);lay.addWidget(self.table,1)
        self.channel.currentTextChanged.connect(self.refresh);self.stat.currentTextChanged.connect(self.refresh);self.xmode.currentTextChanged.connect(self.refresh);store.activeChanged.connect(lambda _h:self.populate());store.changed.connect(self._store_changed);self.populate()
    def _store_changed(self):self.populate(str(self.channel.currentData() or self.channel.currentText()))
    def populate(self,preferred=''):
        self.channel.blockSignals(True);self.channel.clear();h=self.store.active
        if h:
            for rec in channel_catalog(h.run):
                if rec.numeric:self.channel.addItem(rec.alias or rec.name,rec.name)
        if preferred:
            i=self.channel.findData(preferred);self.channel.setCurrentIndex(i if i>=0 else 0)
        self.channel.blockSignals(False);self.refresh()
    def refresh(self):
        self.table.setRowCount(0);active=self.store.active
        if not active:return
        source=str(self.channel.currentData() or self.channel.currentText())
        role=next((r.canonical_role for r in channel_catalog(active.run) if r.name==source and r.canonical_role),'')
        metric_channel=role or source
        try:
            sessions=[(h.label,h.run) for h in self.store.overlays()]
            frame=drag_metric_report(sessions,[MetricDefinition(f'{self.stat.currentText()} {source}',metric_channel,self.stat.currentText())],x_mode=self.xmode.currentText())
            self.table.setRowCount(len(frame))
            for r,rec in frame.reset_index(drop=True).iterrows():
                vals=[rec['run'],rec['segment'],('—' if not np.isfinite(rec['value']) else f"{float(rec['value']):.6g}"),display_label(rec['unit']) or rec['unit'],rec['count'],f"{float(rec['start']):.5g}",f"{float(rec['end']):.5g}"]
                for c,v in enumerate(vals):self.table.setItem(r,c,QtWidgets.QTableWidgetItem(str(v)))
            self.note.setText(f'{len(sessions)} Run(s)  |  {len(frame)} KPI rows  |  channel key: {metric_channel}')
        except Exception as exc:self.note.setText(f'Metric report unavailable: {exc}')


class SavedReportDisplay(QtWidgets.QWidget):
    """Saved portable report evaluated across Main/Reference/Overlay sessions."""
    def __init__(self, store: SessionStore):
        super().__init__(); self.store=store
        lay=QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0,0,0,0)
        ctl=QtWidgets.QHBoxLayout(); self.report=QtWidgets.QComboBox(); self.export_btn=QtWidgets.QPushButton('Export…')
        ctl.addWidget(QtWidgets.QLabel('Saved report')); ctl.addWidget(self.report,1); ctl.addWidget(self.export_btn); lay.addLayout(ctl)
        self.note=QtWidgets.QLabel('Portable reports use canonical channel roles and each Run’s own official timing.'); self.note.setWordWrap(True); lay.addWidget(self.note)
        self.table=QtWidgets.QTableWidget(0,8); self.table.setHorizontalHeaderLabels(['Run','Segment','Metric','Value','Unit','Status','Severity','Samples']);self.table.setAlternatingRowColors(True);self.table.verticalHeader().setVisible(False);self.table.horizontalHeader().setSectionResizeMode(2,QtWidgets.QHeaderView.Stretch);lay.addWidget(self.table,1)
        self.report.currentTextChanged.connect(self.refresh); self.export_btn.clicked.connect(self._export); store.changed.connect(self.populate); store.activeChanged.connect(lambda _h:self.populate()); self.populate()
    def _lib(self): return getattr(self.store,'analysis_library',DefinitionLibrary())
    def populate(self):
        current=self.report.currentText(); self.report.blockSignals(True); self.report.clear(); self.report.addItems(sorted(self._lib().reports))
        if current:
            i=self.report.findText(current); self.report.setCurrentIndex(i if i>=0 else 0)
        self.report.blockSignals(False); self.refresh()
    def _frame(self):
        name=self.report.currentText();
        if not name:return pd.DataFrame()
        return run_saved_report(self._lib(),name,[(h.label,h.run) for h in self.store.overlays()])
    def refresh(self):
        self.table.setRowCount(0)
        try: frame=self._frame()
        except Exception as exc:self.note.setText(f'Saved report unavailable: {exc}');return
        self.table.setRowCount(len(frame))
        for r,rec in frame.reset_index(drop=True).iterrows():
            value='—' if not np.isfinite(float(rec['value'])) else f"{float(rec['value']):.6g}"
            vals=[rec['run'],rec['segment'],rec['metric'],value,display_label(rec['unit']) or rec['unit'],rec['status'],rec['severity'],rec['count']]
            for c,v in enumerate(vals):
                item=QtWidgets.QTableWidgetItem(str(v));
                if c in (5,6) and str(rec.get('severity','')).lower() in ('warning','high','error','critical'): item.setBackground(QtGui.QColor(90,55,25))
                self.table.setItem(r,c,item)
        self.note.setText(f'{len(self.store.overlays())} Run(s)  |  {len(frame)} result rows  |  library: {self._lib().name}')
    def _export(self):
        try: frame=self._frame()
        except Exception as exc: QtWidgets.QMessageBox.critical(self,'Report export',str(exc));return
        if frame.empty:return
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Export saved analysis report','report.xlsx','Excel (*.xlsx);;CSV (*.csv);;JSON (*.json)')
        if not path:return
        try: export_report(frame,path); self.note.setText(f'Exported {path}')
        except Exception as exc:QtWidgets.QMessageBox.critical(self,'Report export failed',str(exc))


class SavedTrendDisplay(QtWidgets.QWidget):
    """Run-by-Run trend of one KPI/segment from a saved report."""
    def __init__(self, store: SessionStore):
        super().__init__(); self.store=store
        lay=QtWidgets.QVBoxLayout(self);lay.setContentsMargins(0,0,0,0)
        ctl=QtWidgets.QGridLayout();self.report=QtWidgets.QComboBox();self.metric=QtWidgets.QComboBox();self.segment=QtWidgets.QComboBox()
        ctl.addWidget(QtWidgets.QLabel('Report'),0,0);ctl.addWidget(self.report,0,1);ctl.addWidget(QtWidgets.QLabel('Metric'),0,2);ctl.addWidget(self.metric,0,3);ctl.addWidget(QtWidgets.QLabel('Segment'),1,0);ctl.addWidget(self.segment,1,1,1,3);lay.addLayout(ctl)
        self.note=QtWidgets.QLabel();lay.addWidget(self.note);self.plot=pg.PlotWidget(background=(20,22,25));self.plot.showGrid(x=True,y=True,alpha=.15);lay.addWidget(self.plot,1)
        self.report.currentTextChanged.connect(self._report_changed);self.metric.currentTextChanged.connect(self.refresh);self.segment.currentTextChanged.connect(self.refresh);store.changed.connect(self.populate);store.activeChanged.connect(lambda _h:self.populate());self.populate()
    def _lib(self):return getattr(self.store,'analysis_library',DefinitionLibrary())
    def populate(self):
        current=self.report.currentText();self.report.blockSignals(True);self.report.clear();self.report.addItems(sorted(self._lib().reports));
        if current:
            i=self.report.findText(current);self.report.setCurrentIndex(i if i>=0 else 0)
        self.report.blockSignals(False);self._report_changed()
    def _report_changed(self):
        rep=self._lib().reports.get(self.report.currentText());cm=self.metric.currentText();cs=self.segment.currentText();self.metric.blockSignals(True);self.segment.blockSignals(True);self.metric.clear();self.segment.clear()
        if rep:self.metric.addItems(rep.metrics);self.segment.addItems(rep.segments)
        if cm:
            i=self.metric.findText(cm);self.metric.setCurrentIndex(i if i>=0 else 0)
        if cs:
            i=self.segment.findText(cs);self.segment.setCurrentIndex(i if i>=0 else 0)
        self.metric.blockSignals(False);self.segment.blockSignals(False);self.refresh()
    def refresh(self):
        self.plot.clear();r=self.report.currentText();m=self.metric.currentText();seg=self.segment.currentText()
        if not (r and m and seg):return
        try:frame=trend_frame(self._lib(),r,[(h.label,h.run) for h in self.store.overlays()],m,seg)
        except Exception as exc:self.note.setText(f'Trend unavailable: {exc}');return
        if frame.empty:self.note.setText('No trend rows.');return
        y=pd.to_numeric(frame['value'],errors='coerce').to_numpy(float);x=np.arange(len(y),dtype=float);self.plot.plot(x,y,pen=pg.mkPen('#5bc0eb',width=2),symbol='o',symbolSize=7)
        axis=self.plot.getAxis('bottom');axis.setTicks([[(float(i),str(label)) for i,label in enumerate(frame['run'])]]);unit=str(frame['unit'].iloc[0] or '');self.plot.setLabel('left',m+(f' [{display_label(unit) or unit}]' if unit else ''));self.note.setText(f'{m} — {seg}  |  {len(frame)} Run(s)')



class StripModelDisplay(QtWidgets.QWidget):
    """NHRA downtrack view with measured-vs-RSA model residuals."""
    def __init__(self, store: SessionStore):
        super().__init__(); self.store=store
        lay=QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0,0,0,0)
        ctl=QtWidgets.QHBoxLayout(); self.channel=QtWidgets.QComboBox(); self.channel.addItems(['speed_mph','engine_rpm','driveshaft_rpm','longitudinal_g'])
        self.engine=QtWidgets.QComboBox(); self.engine.addItems(['Quarter Pro Reference','Smooth Optimizer'])
        self.step=QtWidgets.QSpinBox(); self.step.setRange(1,50); self.step.setValue(5); self.step.setSuffix(' ft')
        ctl.addWidget(QtWidgets.QLabel('Channel')); ctl.addWidget(self.channel); ctl.addWidget(QtWidgets.QLabel('Model')); ctl.addWidget(self.engine); ctl.addWidget(QtWidgets.QLabel('Grid')); ctl.addWidget(self.step); ctl.addStretch(1); lay.addLayout(ctl)
        self.note=QtWidgets.QLabel('Measured telemetry and RSA/Quarter Pro prediction on one physical downtrack axis. Model − measured residuals are shown below.'); self.note.setWordWrap(True); lay.addWidget(self.note)
        self.graph=pg.GraphicsLayoutWidget(); lay.addWidget(self.graph,2)
        self.table=QtWidgets.QTableWidget(0,8); self.table.setHorizontalHeaderLabels(['Beam','Distance','Observed ET','Modeled ET','ΔET','Observed MPH','Modeled MPH','ΔMPH']); self.table.verticalHeader().setVisible(False); self.table.setAlternatingRowColors(True); self.table.horizontalHeader().setSectionResizeMode(0,QtWidgets.QHeaderView.Stretch); lay.addWidget(self.table,1)
        self.channel.currentTextChanged.connect(self.refresh); self.engine.currentTextChanged.connect(self.refresh); self.step.valueChanged.connect(self.refresh)
        store.activeChanged.connect(lambda _h:self.refresh()); store.changed.connect(self.refresh); self.refresh()

    def _model(self, run):
        vehicle,missing=vehicle_from_run(run,require_explicit=False)
        if missing:
            raise ValueError('Vehicle model incomplete: '+', '.join(missing))
        if self.engine.currentIndex()==0:
            return simulate_legacy_reference(vehicle,run.environment)
        return simulate(vehicle,run.environment,options=SolverOptions(dt_s=.0025))

    def refresh(self):
        self.graph.clear(); self.table.setRowCount(0); h=self.store.active
        if h is None:return
        try:
            event_rows=None; lib=getattr(self.store,'analysis_library',None)
            if lib is not None and getattr(lib,'event_rules',None):
                try:event_rows=evaluate_event_rules(lib,h.run)
                except Exception:event_rows=None
            model=self._model(h.run)
            result=analyze_strip(h.run,model,distance_step_ft=float(self.step.value()),rule_events=event_rows)
            role=self.channel.currentText(); obs=result.observed.get(role,np.array([])); pred=result.modeled.get(role,np.array([])); resid=result.residuals.get(role,np.array([])); x=result.distance_ft
            top=self.graph.addPlot(row=0,col=0); top.showGrid(x=True,y=True,alpha=.15); top.addLegend(); top.plot(x,obs,pen=pg.mkPen('#5bc0eb',width=2),name='Measured'); top.plot(x,pred,pen=pg.mkPen('#f4a261',width=2,style=QtCore.Qt.DashLine),name='RSA model'); top.setLabel('left',role); top.hideAxis('bottom')
            bottom=self.graph.addPlot(row=1,col=0); bottom.setXLink(top); bottom.showGrid(x=True,y=True,alpha=.15); bottom.plot(x,resid,pen=pg.mkPen('#e76f51',width=1.5)); bottom.addLine(y=0,pen=pg.mkPen('#777777',style=QtCore.Qt.DotLine)); bottom.setLabel('left','Model − measured'); bottom.setLabel('bottom','Distance from launch [ft]')
            for event in result.events:
                pen=pg.mkPen('#666a70',width=1,style=QtCore.Qt.DotLine)
                if event.severity.lower() in ('warning','high','error','critical'): pen=pg.mkPen('#e9c46a',width=1,style=QtCore.Qt.DotLine)
                for plot in (top,bottom): plot.addItem(pg.InfiniteLine(pos=float(event.distance_ft),angle=90,movable=False,pen=pen,label=event.label if plot is top else None,labelOpts={'position':.92,'color':'#8f949a'} if plot is top else None))
            frame=result.timing_residuals.reset_index(drop=True); self.table.setRowCount(len(frame))
            for r,rec in frame.iterrows():
                vals=[rec['point'],f"{float(rec['distance_ft']):.0f}",*(('—' if pd.isna(rec[c]) else f"{float(rec[c]):.5g}") for c in ['observed_et_s','modeled_et_s','et_residual_s','observed_mph','modeled_mph','mph_residual'])]
                for c,v in enumerate(vals):
                    item=QtWidgets.QTableWidgetItem(str(v));
                    if c in (4,7) and v!='—':
                        try:
                            val=abs(float(v));
                            if (c==4 and val>.02) or (c==7 and val>1.0): item.setBackground(QtGui.QColor(90,55,25))
                        except Exception: pass
                    self.table.setItem(r,c,item)
            available=', '.join(result.diagnostics.get('observed_roles',[])) or 'none'
            self.note.setText(f'{self.engine.currentText()}  |  measured roles: {available}  |  {len(result.events)} strip events. Launch/rollout coordinate uncertainty is intentionally not hidden by time-warping the data.')
        except Exception as exc:
            self.note.setText(f'Strip/model analysis unavailable: {exc}')


class EnvelopeDisplay(QtWidgets.QWidget):
    """Aligned min/max/mean envelope across Main + selected compare sessions."""
    def __init__(self, store: SessionStore):
        super().__init__(); self.store=store
        lay=QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0,0,0,0)
        ctl=QtWidgets.QHBoxLayout(); self.channel=QtWidgets.QComboBox(); self.xmode=QtWidgets.QComboBox(); self.xmode.addItems(['Time from Launch','Distance from Launch','Normalized Run %','Logger Time'])
        self.grid=QtWidgets.QSpinBox(); self.grid.setRange(100,10000); self.grid.setValue(2000); self.grid.setSingleStep(250)
        ctl.addWidget(QtWidgets.QLabel('Channel'));ctl.addWidget(self.channel,1);ctl.addWidget(QtWidgets.QLabel('X axis'));ctl.addWidget(self.xmode);ctl.addWidget(QtWidgets.QLabel('Grid'));ctl.addWidget(self.grid)
        lay.addLayout(ctl)
        self.stats=QtWidgets.QLabel('Requires Main plus at least one Reference/Overlay session.'); self.stats.setWordWrap(True); lay.addWidget(self.stats)
        self.plot=pg.PlotWidget(background=(20,22,25)); self.plot.showGrid(x=True,y=True,alpha=.15); lay.addWidget(self.plot,1)
        self.channel.currentTextChanged.connect(self.refresh); self.xmode.currentTextChanged.connect(self.refresh); self.grid.valueChanged.connect(self.refresh)
        store.activeChanged.connect(lambda _h:self.populate()); store.changed.connect(self._store_changed); self.populate()
    def _store_changed(self):self.populate(self.channel.currentText())
    def populate(self,preferred=None):
        current=preferred or self.channel.currentText(); self.channel.blockSignals(True); self.channel.clear(); h=self.store.active
        if h:self.channel.addItems(_visible_channel_names(h.run))
        if current:
            i=self.channel.findText(current); self.channel.setCurrentIndex(i if i>=0 else 0)
        self.channel.blockSignals(False);self.refresh()
    def refresh(self):
        self.plot.clear(); active=self.store.active; name=self.channel.currentText()
        if not active or not name:return
        sessions=[(active.run,active.time_alignment_s)]
        labels=[active.label]
        for idx,h in enumerate(self.store.runs):
            if idx==self.store.active_index:continue
            if h.role in ('reference','overlay'):
                sessions.append((h.run,h.time_alignment_s));labels.append(h.label)
        if len(sessions)<2:
            self.stats.setText('Envelope unavailable: mark at least one additional session Reference or Overlay.');return
        try:
            result=multi_run_envelope(sessions,name,x_mode=self.xmode.currentText(),grid_points=int(self.grid.value()))
            lo=self.plot.plot(result.x,result.minimum,pen=pg.mkPen('#5b6470',width=1)); hi=self.plot.plot(result.x,result.maximum,pen=pg.mkPen('#5b6470',width=1))
            fill=pg.FillBetweenItem(lo,hi,brush=pg.mkBrush(91,192,235,42));self.plot.addItem(fill)
            self.plot.plot(result.x,result.mean,pen=pg.mkPen('#5bc0eb',width=2.0),name='Mean')
            self.plot.setLabel('bottom',self.xmode.currentText());unit=display_label(result.unit) or result.unit;self.plot.setLabel('left',name+(f' [{unit}]' if unit else ''))
            mean_std=float(np.nanmean(result.std));span=float(np.nanmax(result.maximum-result.minimum))
            self.stats.setText(f'{result.run_count} compatible runs  |  overlap {result.overlap[0]:.5g} to {result.overlap[1]:.5g}  |  mean σ {mean_std:.5g}  |  max envelope width {span:.5g}')
        except Exception as exc:self.stats.setText(f'Envelope unavailable: {exc}')


class RegionStatisticsDisplay(QtWidgets.QTableWidget):
    def __init__(self, store: SessionStore, cursors: CursorBus, waveform: Optional[WaveformDisplay]=None):
        super().__init__(); self.store=store; self.cursors=cursors; self.waveform=waveform
        self.headers=['Channel','Unit','Samples','Start','End','Δ','Min','Max','Mean','Median','Std','RMS']
        self.setColumnCount(len(self.headers)); self.setHorizontalHeaderLabels(self.headers); self.setAlternatingRowColors(True); self.setSortingEnabled(False)
        self.horizontalHeader().setStretchLastSection(True)
        cursors.cursorAMoved.connect(lambda _x:self.refresh()); cursors.moved.connect(lambda _x:self.refresh()); store.activeChanged.connect(lambda _h:self.refresh()); store.changed.connect(self.refresh)
        self.refresh()
    def refresh(self):
        h=self.store.active; channels=self.waveform.channels if (h and self.waveform) else []
        self.setRowCount(0)
        if not h or not channels:return
        mode=self.waveform.x_mode if self.waveform else 'Time from Launch'
        rows=region_statistics(h.run,channels,self.cursors.a,self.cursors.x,x_mode=mode,alignment_s=h.time_alignment_s)
        self.setRowCount(len(rows))
        for r,row in enumerate(rows):
            unit=display_label(self.waveform._display_unit(row['channel'],h.run) if self.waveform else h.run.units.get(row['channel'],''))
            vals=[row['channel'],unit,row['count'],row['start'],row['end'],row['delta'],row['min'],row['max'],row['mean'],row['median'],row['std'],row['rms']]
            for c,v in enumerate(vals):
                text=str(v) if c<3 else (f'{float(v):.6g}' if np.isfinite(float(v)) else '')
                self.setItem(r,c,QtWidgets.QTableWidgetItem(text))


class DeltaDisplay(QtWidgets.QWidget):
    """Reference-minus-main comparison trace with aligned interpolation."""
    def __init__(self, store: SessionStore):
        super().__init__(); self.store=store
        lay=QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0,0,0,0)
        ctl=QtWidgets.QHBoxLayout(); self.channel=QtWidgets.QComboBox(); self.reference=QtWidgets.QComboBox(); self.sign=QtWidgets.QComboBox(); self.xmode=QtWidgets.QComboBox()
        self.sign.addItems(['Reference - Main','Main - Reference']); self.xmode.addItems(['Time from Launch','Distance from Launch','Normalized Run %','Logger Time','Sample Index'])
        ctl.addWidget(QtWidgets.QLabel('Channel'));ctl.addWidget(self.channel,1);ctl.addWidget(QtWidgets.QLabel('Reference'));ctl.addWidget(self.reference,1);ctl.addWidget(self.sign);ctl.addWidget(self.xmode)
        lay.addLayout(ctl)
        self.stats=QtWidgets.QLabel('Select a main/reference channel pair.'); self.stats.setWordWrap(True); lay.addWidget(self.stats)
        self.plot=pg.PlotWidget(background=(20,22,25)); self.plot.showGrid(x=True,y=True,alpha=.15); lay.addWidget(self.plot,1)
        self.channel.currentTextChanged.connect(self.refresh); self.reference.currentIndexChanged.connect(self.refresh); self.sign.currentTextChanged.connect(self.refresh); self.xmode.currentTextChanged.connect(self.refresh)
        store.changed.connect(self.populate); store.activeChanged.connect(lambda _h:self.populate()); self.populate()

    def populate(self):
        current_channel=self.channel.currentText(); current_ref=self.reference.currentData()
        self.channel.blockSignals(True); self.reference.blockSignals(True); self.channel.clear(); self.reference.clear()
        active=self.store.active
        if active:
            self.channel.addItems(_visible_channel_names(active.run))
            for idx,h in enumerate(self.store.runs):
                if idx==self.store.active_index:continue
                self.reference.addItem(f'{h.label} [{h.role}]',idx)
        if current_channel:
            i=self.channel.findText(current_channel); self.channel.setCurrentIndex(i if i>=0 else 0)
        if current_ref is not None:
            i=self.reference.findData(current_ref); self.reference.setCurrentIndex(i if i>=0 else 0)
        self.channel.blockSignals(False); self.reference.blockSignals(False); self.refresh()

    def refresh(self):
        self.plot.clear(); active=self.store.active
        idx=self.reference.currentData(); channel=self.channel.currentText()
        if active is None or idx is None or not channel:
            self.stats.setText('Load a Main session and at least one reference/overlay session.'); return
        try:
            ref=self.store.runs[int(idx)]
            sign='main-reference' if self.sign.currentText().startswith('Main') else 'reference-main'
            series=reference_delta_series(active.run,ref.run,channel,x_mode=self.xmode.currentText(),main_alignment_s=active.time_alignment_s,reference_alignment_s=ref.time_alignment_s,sign=sign,max_points=50000)
            st=delta_statistics(series)
            self.plot.plot(series.x,series.delta,pen=pg.mkPen('#f9c74f',width=1.5))
            self.plot.addLine(y=0.0,pen=pg.mkPen('#777b80',style=QtCore.Qt.DashLine))
            unit=display_label(series.unit) or series.unit
            self.plot.setLabel('left',self.sign.currentText()+(f' [{unit}]' if unit else '')); self.plot.setLabel('bottom',self.xmode.currentText())
            self.stats.setText(f"{series.reference_channel} vs {series.main_channel}  |  mean {st['mean']:.5g}  RMS {st['rms']:.5g}  max |Δ| {st['max_abs']:.5g}  |  {st['count']:,} samples")
        except Exception as exc:
            self.stats.setText(f'Delta unavailable: {exc}')


def _run_event_rows(run: TelemetryRun):
    rows=[]
    try:
        window=detect_drag_pass_window(run)
        launch=float(window.launch_time_s)
        rows.append({'event':'Launch / zero','time_s':0.0,'distance_ft':0.0,'source':window.method})
        if window.peak_time_s is not None:
            rows.append({'event':'Peak speed','time_s':float(window.peak_time_s-launch),'distance_ft':np.nan,'source':'telemetry'})
    except Exception:
        launch=0.0
    timing=run.timing.to_dict()
    for label,key,dist in [('60 ft','sixty_ft_s',60),('330 ft','three_thirty_ft_s',330),('660 ft','eighth_mile_s',660),('1000 ft','thousand_ft_s',1000),('1320 ft','quarter_mile_s',1320)]:
        value=timing.get(key)
        if value is not None:
            rows.append({'event':label,'time_s':float(value),'distance_ft':float(dist),'source':'official timing'})
    # WOT event when throttle is available.
    tc=run.channel_map.get('time_s'); th=run.channel_map.get('throttle_pct')
    if tc and th and tc in run.data and th in run.data:
        t=pd.to_numeric(run.data[tc],errors='coerce').to_numpy(float)
        y=pd.to_numeric(run.data[th],errors='coerce').to_numpy(float)
        good=np.isfinite(t)&np.isfinite(y)
        idx=np.flatnonzero(good & (y>=90.0))
        if len(idx):
            rel=float(t[idx[0]]-launch)
            if -2.0 <= rel <= 20.0:
                rows.append({'event':'WOT','time_s':rel,'distance_ft':np.nan,'source':'throttle'})
    # Gear changes from mapped telemetry when present.
    gc=run.channel_map.get('gear')
    if tc and gc and tc in run.data and gc in run.data:
        t=pd.to_numeric(run.data[tc],errors='coerce').to_numpy(float)
        g=pd.to_numeric(run.data[gc],errors='coerce').to_numpy(float)
        valid=np.isfinite(t)&np.isfinite(g)
        if valid.sum()>2:
            gi=np.rint(g).astype(float)
            for i in range(1,len(gi)):
                if valid[i] and valid[i-1] and gi[i]>=1 and gi[i-1]>=1 and gi[i]!=gi[i-1]:
                    rel=float(t[i]-launch)
                    if -1.0 <= rel <= 30.0:
                        rows.append({'event':f'Shift {int(gi[i-1])}→{int(gi[i])}','time_s':rel,'distance_ft':np.nan,'source':'gear channel'})
    # Fill distance for telemetry events from canonical speed where possible.
    sc=run.channel_map.get('speed_mph')
    if tc and sc and tc in run.data and sc in run.data:
        t=pd.to_numeric(run.data[tc],errors='coerce').to_numpy(float)
        v=pd.to_numeric(run.data[sc],errors='coerce').to_numpy(float)
        mask=np.isfinite(t)&np.isfinite(v)
        if mask.sum()>=3:
            tt=t[mask]; vv=v[mask]; order=np.argsort(tt); tt=tt[order]; vv=vv[order]
            dt=np.diff(tt,prepend=tt[0]); dt[0]=0
            dist=np.cumsum(np.maximum(vv,0)*1.4666666667*np.maximum(dt,0))
            launch_dist=float(np.interp(launch,tt,dist))
            for row in rows:
                if not np.isfinite(row['distance_ft']):
                    abs_t=launch+row['time_s']
                    if tt[0]<=abs_t<=tt[-1]: row['distance_ft']=float(np.interp(abs_t,tt,dist)-launch_dist)
    for ann in annotations(run):
        mode=str(ann.x_mode).lower()
        if mode.startswith('time'):
            rows.append({'event':ann.label,'time_s':float(ann.x1),'distance_ft':np.nan,'source':f'user {ann.kind}','annotation_id':ann.id})
            if ann.kind=='region' and ann.x2 is not None:
                rows.append({'event':f'{ann.label} end','time_s':float(ann.x2),'distance_ft':np.nan,'source':'user region','annotation_id':ann.id})
        elif mode.startswith('distance'):
            rows.append({'event':ann.label,'time_s':np.nan,'distance_ft':float(ann.x1),'source':f'user {ann.kind}','annotation_id':ann.id})
    rows.sort(key=lambda r:(np.inf if not np.isfinite(r['time_s']) else r['time_s'],r['event']))
    return rows


class ComparisonSummaryDisplay(QtWidgets.QWidget):
    def __init__(self, store: SessionStore):
        super().__init__(); self.store=store
        lay=QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0,0,0,0)
        ctl=QtWidgets.QHBoxLayout(); self.reference=QtWidgets.QComboBox(); ctl.addWidget(QtWidgets.QLabel('Reference'));ctl.addWidget(self.reference,1); lay.addLayout(ctl)
        self.table=QtWidgets.QTableWidget(); self.headers=['Section','Location','Metric','Unit','Main','Reference','Δ Ref-Main']; self.table.setColumnCount(len(self.headers)); self.table.setHorizontalHeaderLabels(self.headers); self.table.setAlternatingRowColors(True);self.table.horizontalHeader().setStretchLastSection(True);lay.addWidget(self.table,1)
        self.reference.currentIndexChanged.connect(self.refresh);store.changed.connect(self.populate);store.activeChanged.connect(lambda _h:self.populate());self.populate()
    def populate(self):
        current=self.reference.currentData();self.reference.blockSignals(True);self.reference.clear()
        for idx,h in enumerate(self.store.runs):
            if idx==self.store.active_index:continue
            self.reference.addItem(f'{h.label} [{h.role}]',idx)
        if current is not None:
            i=self.reference.findData(current);self.reference.setCurrentIndex(i if i>=0 else 0)
        self.reference.blockSignals(False);self.refresh()
    def refresh(self):
        self.table.setRowCount(0);active=self.store.active;idx=self.reference.currentData()
        if active is None or idx is None:return
        try:table=comparison_summary(active.run,self.store.runs[int(idx)].run,main_alignment_s=active.time_alignment_s,reference_alignment_s=self.store.runs[int(idx)].time_alignment_s)
        except Exception as exc:
            logging.getLogger(__name__).exception('Comparison summary failed');self.table.setRowCount(1);self.table.setItem(0,0,QtWidgets.QTableWidgetItem(f'Unavailable: {exc}'));return
        self.table.setRowCount(len(table))
        for r,(_,row) in enumerate(table.iterrows()):
            vals=[row['section'],row['location'],row['metric'],display_label(row['unit']) or row['unit'],row['main'],row['reference'],row['delta']]
            for c,v in enumerate(vals):
                if isinstance(v,(float,np.floating)):text=f'{float(v):.6g}' if np.isfinite(float(v)) else ''
                else:text=str(v)
                self.table.setItem(r,c,QtWidgets.QTableWidgetItem(text))


class EventDisplay(QtWidgets.QTableWidget):
    def __init__(self, store: SessionStore, cursors: CursorBus):
        super().__init__(); self.store=store; self.cursors=cursors; self._rows=[]
        self.setColumnCount(5); self.setHorizontalHeaderLabels(['Event','Time from launch','Distance','Source','Severity'])
        self.horizontalHeader().setStretchLastSection(True); self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.cellDoubleClicked.connect(self._jump)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu); self.customContextMenuRequested.connect(self._menu)
        store.activeChanged.connect(lambda _:self.refresh()); store.changed.connect(self.refresh); self.refresh()
    def refresh(self):
        h=self.store.active; self._rows=[]; self.setRowCount(0)
        if not h:return
        self._rows=_run_event_rows(h.run)
        lib=getattr(self.store,'analysis_library',None)
        if lib and getattr(lib,'event_rules',None):
            try:
                derived=evaluate_event_rules(lib,h.run)
                for _,rec in derived.iterrows():
                    self._rows.append({'event':rec['rule'],'time_s':float(rec['start_s']),'distance_ft':float('nan'),'source':'Analysis Rule','severity':rec['severity']})
            except Exception:logging.exception('Could not evaluate saved event rules')
        self._rows=sorted(self._rows,key=lambda x:(float(x.get('time_s',float('inf'))) if np.isfinite(float(x.get('time_s',float('nan')))) else float('inf'),str(x.get('event',''))))
        self.setRowCount(len(self._rows))
        for r,row in enumerate(self._rows):
            time_text=f"{row['time_s']:.4f} s" if np.isfinite(row['time_s']) else ''
            vals=[row['event'],time_text,f"{row['distance_ft']:.1f} ft" if np.isfinite(row['distance_ft']) else '',row['source'],row.get('severity','')]
            for c,v in enumerate(vals): self.setItem(r,c,QtWidgets.QTableWidgetItem(str(v)))
    def _jump(self,row,_col):
        if 0<=row<len(self._rows) and np.isfinite(self._rows[row]['time_s']):
            x=float(self._rows[row]['time_s']); self.cursors.x=x; self.cursors.moved.emit(x)
    def _menu(self,pos):
        row=self.rowAt(pos.y())
        if row<0 or row>=len(self._rows):return
        rec=self._rows[row]; ann_id=rec.get('annotation_id')
        menu=QtWidgets.QMenu(self); jump=menu.addAction('Move cursor here'); delete=None
        if ann_id: delete=menu.addAction('Delete user annotation')
        chosen=menu.exec(self.viewport().mapToGlobal(pos))
        if chosen==jump:self._jump(row,0)
        elif delete is not None and chosen==delete:
            h=self.store.active
            if h and delete_annotation(h.run,str(ann_id)):
                self.store.changed.emit(); self.refresh()


class AlarmStatusDisplay(QtWidgets.QTableWidget):
    """Historical alarm state at the shared Run-time cursor."""
    def __init__(self, store: SessionStore, cursors: CursorBus):
        super().__init__();self.store=store;self.cursors=cursors
        self.setColumnCount(5);self.setHorizontalHeaderLabels(['Rule','State','Severity','Type','Last event']);self.setAlternatingRowColors(True);self.horizontalHeader().setStretchLastSection(True)
        cursors.moved.connect(lambda _x:self.refresh());store.activeChanged.connect(lambda _h:self.refresh());store.changed.connect(self.refresh);self.refresh()
    def refresh(self):
        h=self.store.active;lib=getattr(self.store,'analysis_library',None);self.setRowCount(0)
        if not h or not lib or not getattr(lib,'event_rules',None):return
        try: rows=alarm_states_at(lib,h.run,float(self.cursors.x))
        except Exception:return
        self.setRowCount(len(rows))
        for r,rec in enumerate(rows):
            vals=[rec['rule'],'ACTIVE' if rec['active'] else '—',rec['severity'],rec['event_type'],'' if rec['last_event_s'] is None else f"{float(rec['last_event_s']):.4f} s"]
            for c,v in enumerate(vals):
                item=QtWidgets.QTableWidgetItem(str(v));
                if c==1 and rec['active']:item.setForeground(QtGui.QColor('#ff9f43'))
                self.setItem(r,c,item)


class NotepadDisplay(QtWidgets.QTextEdit):
    def __init__(self, store: SessionStore):
        super().__init__(); self.store=store; self._loading=False
        self.setPlaceholderText('Run notes, setup observations, crew comments…')
        store.activeChanged.connect(lambda _:self.refresh()); self.textChanged.connect(self._changed); self.refresh()
    def refresh(self):
        self._loading=True
        try:
            h=self.store.active; self.setPlainText(str(h.run.metadata.get('user_notes','')) if h else '')
        finally:self._loading=False
    def _changed(self):
        if self._loading:return
        h=self.store.active
        if h:
            h.run.metadata['user_notes']=self.toPlainText(); self.store.changed.emit()


class SensorHealthDisplay(QtWidgets.QTableWidget):
    def __init__(self, store: SessionStore):
        super().__init__(); self.store=store
        self.headers=['Status','Channel','Unit','Samples','Finite %','Hz','Clock issues','Flat %','Step outliers','Min','Max','Std','Note']
        self.setColumnCount(len(self.headers)); self.setHorizontalHeaderLabels(self.headers); self.setAlternatingRowColors(True); self.setSortingEnabled(True); self.horizontalHeader().setStretchLastSection(True)
        store.activeChanged.connect(lambda _h:self.refresh()); store.changed.connect(self.refresh); self.refresh()
    def refresh(self):
        h=self.store.active; self.setRowCount(0)
        if not h:return
        table=sensor_health(h.run); self.setSortingEnabled(False); self.setRowCount(len(table))
        for r,(_,row) in enumerate(table.iterrows()):
            values=[row.get('status',''),row.get('channel',''),display_label(row.get('unit','')) or row.get('unit',''),int(row.get('samples',0)),row.get('finite_pct',np.nan),row.get('sample_rate_hz',np.nan),int(row.get('clock_violations',0)),row.get('flatline_pct',np.nan),int(row.get('step_outliers',0)),row.get('minimum',np.nan),row.get('maximum',np.nan),row.get('std',np.nan),row.get('note','')]
            for c,v in enumerate(values):
                if isinstance(v,(float,np.floating)):
                    text=f'{float(v):.6g}' if np.isfinite(float(v)) else ''
                else:text=str(v)
                item=QtWidgets.QTableWidgetItem(text)
                if c==0:
                    color={'ERROR':'#ff7b72','WARN':'#f9c74f','OK':'#78d381'}.get(text,'#d0d0d0');item.setForeground(QtGui.QColor(color))
                self.setItem(r,c,item)
        self.setSortingEnabled(True)


class AuditDisplay(QtWidgets.QTableWidget):
    def __init__(self, store: SessionStore):
        super().__init__(); self.store=store
        self.setColumnCount(4); self.setHorizontalHeaderLabels(['Severity','Category','Item','Message'])
        self.horizontalHeader().setStretchLastSection(True); self.setAlternatingRowColors(True)
        store.activeChanged.connect(lambda _: self.refresh()); self.refresh()
    def refresh(self):
        h=self.store.active; self.setRowCount(0)
        if not h:return
        df=audit_run(h.run); self.setRowCount(len(df))
        for r,row in df.iterrows():
            vals=[row['severity'],row['category'],row['item'],row['message']]
            for c,v in enumerate(vals):
                item=QtWidgets.QTableWidgetItem(str(v)); self.setItem(r,c,item)
                if c==0:
                    item.setForeground({'ERROR':QtGui.QColor('#ff6b6b'),'WARNING':QtGui.QColor('#ffd166'),'OK':QtGui.QColor('#90be6d')}.get(str(v),QtGui.QColor('#cccccc')))


class KnowledgeDisplay(QtWidgets.QTableWidget):
    """Parameter provenance / confidence table for the active run."""
    def __init__(self, store: SessionStore):
        super().__init__(); self.store=store
        self.setColumnCount(8)
        self.setHorizontalHeaderLabels(['Parameter','Value','Unit','Provenance','Confidence','Lower','Upper','Method / Notes'])
        self.horizontalHeader().setSectionResizeMode(0,QtWidgets.QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1,QtWidgets.QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(2,QtWidgets.QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(3,QtWidgets.QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(4,QtWidgets.QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(7,QtWidgets.QHeaderView.Stretch)
        self.setAlternatingRowColors(True);self.setSortingEnabled(True)
        store.activeChanged.connect(lambda _:self.refresh());store.changed.connect(self.refresh);self.refresh()
    def refresh(self):
        h=self.store.active;self.setSortingEnabled(False);self.setRowCount(0)
        if not h:self.setSortingEnabled(True);return
        recs=h.run.metadata.get('parameter_knowledge',{})
        rows=[]
        for key,rec in recs.items():
            if not isinstance(rec,dict):continue
            rows.append((key,rec))
        self.setRowCount(len(rows))
        for r,(key,rec) in enumerate(sorted(rows,key=lambda x:x[0])):
            value=rec.get('value','')
            if isinstance(value,(list,tuple)):value=', '.join(f'{x:g}' if isinstance(x,(int,float)) else str(x) for x in value)
            conf=rec.get('confidence',None); conf='' if conf is None else f'{100*float(conf):.0f}%'
            method=str(rec.get('method','') or '')
            notes=str(rec.get('notes','') or '')
            vals=[key,value,rec.get('unit',''),rec.get('provenance',''),conf,rec.get('lower',''),rec.get('upper',''),(' — '.join(x for x in (method,notes) if x))]
            for c,v in enumerate(vals):self.setItem(r,c,QtWidgets.QTableWidgetItem('' if v is None else str(v)))
        self.setSortingEnabled(True)


class MetadataEditor(QtWidgets.QTreeWidget):
    """Editable run setup / knowledge sheet with provenance."""

    MODEL_FIELDS = [
        ("weight_lb", "Race weight", "lb"),
        ("wheelbase_in", "Wheelbase", "in"),
        ("rollout_in", "Rollout", "in"),
        ("front_overhang_in", "Front overhang", "in"),
        ("cg_height_in", "CG height", "in"),
        ("static_front_weight_lb", "Static front axle weight", "lb"),
        ("frontal_area_ft2", "Frontal area", "ft²"),
        ("drag_coefficient", "Drag coefficient Cd", ""),
        ("lift_coefficient", "Lift coefficient Cl", ""),
        ("body_style", "Legacy body-style code", "code"),
        ("traction_index", "Traction index", ""),
        ("final_drive_ratio", "Final drive ratio", ""),
        ("final_drive_efficiency", "Final drive efficiency", ""),
        ("tire_diameter_in", "Tire diameter", "in"),
        ("tire_width_in", "Tire width", "in"),
        ("tire_growth_scale", "Tire growth scale", ""),
        ("launch_rpm", "Launch RPM", "rpm"),
        ("transmission_type", "Transmission type", "clutch / converter"),
        ("stall_rpm", "Converter stall / clutch reference RPM", "rpm"),
        ("slippage", "Converter/slip ratio", ""),
        ("torque_multiplication", "Torque multiplication", ""),
        ("lockup_after_first", "Lockup after first gear", "0 / 1"),
        ("shift_duration_s", "Shift duration", "s"),
        ("engine_pmi", "Engine PMI", "lb-ft²"),
        ("transmission_pmi", "Transmission PMI", "lb-ft²"),
        ("tires_pmi", "Tires PMI", "lb-ft²"),
        ("gear_ratios", "Gear ratios", "comma separated"),
        ("gear_efficiencies", "Gear efficiencies", "comma separated"),
        ("shift_rpms", "Shift RPMs", "comma separated"),
        ("dyno_rpm", "Power curve RPM nodes", "comma separated"),
        ("dyno_hp", "Power curve HP nodes", "hp · comma separated"),
    ]

    def __init__(self, store: SessionStore):
        super().__init__(); self.store=store; self._loading=False
        self.setHeaderLabels(['Run / Vehicle Parameter','Value','Unit / Provenance'])
        self.setColumnWidth(0,235); self.setColumnWidth(1,165); self.setColumnWidth(2,210)
        self.setAlternatingRowColors(True)
        self.itemChanged.connect(self._changed)
        store.activeChanged.connect(lambda _: self.refresh()); self.refresh()

    def _group(self, title):
        parent=QtWidgets.QTreeWidgetItem([title]); f=parent.font(0);f.setBold(True);parent.setFont(0,f)
        parent.setFlags(parent.flags() & ~QtCore.Qt.ItemIsEditable)
        self.addTopLevelItem(parent); return parent

    def _editable(self, parent, label, value, third, kind, key):
        text='' if value is None else (', '.join(str(x) for x in value) if isinstance(value,(list,tuple)) else str(value))
        item=QtWidgets.QTreeWidgetItem([label,text,third])
        item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
        item.setData(0,QtCore.Qt.UserRole,(kind,key))
        parent.addChild(item); return item

    def refresh(self):
        self._loading=True
        try:
            self.clear(); h=self.store.active
            if not h:return
            run=h.run
            from runlab.knowledge import get_parameter, vehicle_inputs
            p=self._group('Logger / Session Metadata')
            hidden={'unit_provenance','data_warnings','channel_quality','original_channel_map','vehicle_inputs','parameter_knowledge','environment_provenance','timing_provenance','math_channels','channel_aliases','gates','inferred_dyno_curve','vehicle_model','scenario_changes'}
            for k,v in run.metadata.items():
                if k in hidden or isinstance(v,(dict,list)) or v in (None,''):
                    continue
                child=QtWidgets.QTreeWidgetItem([str(k),str(v),'file']); child.setFlags(child.flags() & ~QtCore.Qt.ItemIsEditable); p.addChild(child)

            envp=self._group('Weather / Environment')
            env_prov=run.metadata.get('environment_provenance',{})
            env_units={'elevation_ft':'ft','temperature_f':'°F','barometer_inhg':'inHg','humidity_pct':'%','wind_mph':'mph','wind_angle_deg':'deg','track_temperature_f':'°F','fuel_system':'code'}
            for key,val in run.environment.to_dict().items():
                src=env_prov.get(key,'default / user editable')
                self._editable(envp,key,val,f"{env_units.get(key,'')} · {src}".strip(' ·'),'environment',key)

            tp=self._group('Official Timing')
            tim_prov=run.metadata.get('timing_provenance',{})
            timing_units={'sixty_ft_s':'s','three_thirty_ft_s':'s','eighth_mile_s':'s','eighth_mile_mph':'mph','thousand_ft_s':'s','quarter_mile_s':'s','quarter_mile_mph':'mph'}
            for key,val in run.timing.to_dict().items():
                src=tim_prov.get(key,'user editable')
                self._editable(tp,key,val,f"{timing_units.get(key,'')} · {src}".strip(' ·'),'timing',key)

            vp=self._group('Vehicle / Modeling Inputs')
            vals=vehicle_inputs(run)
            for key,label,unit in self.MODEL_FIELDS:
                rec=get_parameter(run,f'vehicle.{key}')
                prov=(rec.provenance if rec else ('inferred' if key in ('dyno_rpm','dyno_hp') and run.metadata.get('inferred_dyno_curve') else 'user / inference'))
                value=vals.get(key)
                if value in (None,'') and key in ('dyno_rpm','dyno_hp') and isinstance(run.metadata.get('inferred_dyno_curve'),dict):
                    value=run.metadata['inferred_dyno_curve'].get('rpm' if key=='dyno_rpm' else 'hp')
                self._editable(vp,label,value,f"{unit} · {prov}".strip(' ·'),'vehicle',key)

            notes=self._group('Run Notes')
            self._editable(notes,'Notes',run.metadata.get('user_notes',''),'user','metadata','user_notes')

            warnings=run.metadata.get('data_warnings',[])
            if warnings:
                wp=self._group('Import / Unit Warnings')
                for i,w in enumerate(warnings):
                    item=QtWidgets.QTreeWidgetItem([f'Warning {i+1}',str(w),'audit']); item.setForeground(1,QtGui.QColor('#ffd166')); wp.addChild(item)
            self.expandAll()
        finally:
            self._loading=False

    def _parse(self, text, kind, key):
        text=str(text).strip()
        if kind=='metadata': return text
        if kind=='vehicle' and key in ('transmission_type',): return text.lower()
        if kind=='vehicle' and key in ('gear_ratios','gear_efficiencies','shift_rpms','dyno_rpm','dyno_hp'):
            if not text:return []
            return [float(x.strip()) for x in text.replace(';',',').split(',') if x.strip()]
        if kind=='vehicle' and key in ('lockup_after_first',):
            return text.lower() in ('1','true','yes','y','on')
        if not text:
            return None
        return float(text)

    def _changed(self,item,column):
        if self._loading or column!=1:return
        spec=item.data(0,QtCore.Qt.UserRole)
        if not spec:return
        h=self.store.active
        if not h:return
        kind,key=spec
        try:
            from runlab.knowledge import set_vehicle_input
            value=self._parse(item.text(1),kind,key)
            run=h.run
            if kind=='environment':
                if value is None: raise ValueError('Environment values cannot be blank; enter the measured value or keep the current value.')
                setattr(run.environment,key,int(value) if key=='fuel_system' else float(value))
                run.metadata.setdefault('environment_provenance',{})[key]='user'
            elif kind=='timing':
                setattr(run.timing,key,None if value is None else float(value))
                if value is None: run.metadata.setdefault('timing_provenance',{}).pop(key,None)
                else: run.metadata.setdefault('timing_provenance',{})[key]='user'
            elif kind=='vehicle':
                unit=next((u for k,l,u in self.MODEL_FIELDS if k==key),'')
                set_vehicle_input(run,key,value,unit,'user')
            elif kind=='metadata':
                run.metadata[key]=value
            self.store.changed.emit()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self,'Invalid setup value',str(exc)); self.refresh()


class Worksheet(QtWidgets.QMainWindow):
    def __init__(self, store: SessionStore, cursors: CursorBus, name='Data'):
        super().__init__(); self.store=store; self.cursors=cursors; self.name=name
        self.setDockOptions(QtWidgets.QMainWindow.AllowNestedDocks | QtWidgets.QMainWindow.AllowTabbedDocks | QtWidgets.QMainWindow.GroupedDragging)
        self._display_count=0
        self.waveforms: List[WaveformDisplay]=[]
        self.setCentralWidget(QtWidgets.QWidget())
        self.add_waveform()

    def _dock(self,title,widget,area=QtCore.Qt.TopDockWidgetArea, *, display_type=None, object_name=None):
        d=QtWidgets.QDockWidget(title,self); d.setWidget(widget)
        if object_name:
            d.setObjectName(str(object_name))
        else:
            d.setObjectName(f'{display_type or title}_{self._display_count}')
        d.setProperty('techdata_display_type', display_type or title.lower())
        self._display_count+=1
        d.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)
        d.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable|QtWidgets.QDockWidget.DockWidgetFloatable|QtWidgets.QDockWidget.DockWidgetClosable)
        # A dock should never be "stuck" because its child carries a large
        # minimum size.  Let the QMainWindow splitter own the geometry.
        widget.setMinimumSize(0, 0)
        d.setMinimumSize(0, 0)
        d.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        self.addDockWidget(area,d)
        return d

    def add_waveform(self, object_name=None):
        w=WaveformDisplay(self.store,self.cursors)
        self.waveforms.append(w)
        if len(self.waveforms) == 1:
            # The primary task is looking at telemetry, so the primary waveform
            # owns the worksheet center.  Analysis displays dock around it.
            old = self.takeCentralWidget()
            if old is not None:
                old.deleteLater()
            w.setObjectName(str(object_name or 'PrimaryWaveform'))
            self.setCentralWidget(w)
        else:
            self._dock('Waveform',w,display_type='waveform',object_name=object_name)
        return w
    def add_values(self, object_name=None):
        w=self.waveforms[0] if self.waveforms else None
        return self._dock('Values',ValuesDisplay(self.store,self.cursors,w),QtCore.Qt.RightDockWidgetArea,display_type='values',object_name=object_name)
    def add_gauge(self, object_name=None):
        return self._dock('Gauge / Status',GaugeDisplay(self.store,self.cursors),QtCore.Qt.RightDockWidgetArea,display_type='gauge',object_name=object_name)
    def add_region_stats(self, object_name=None):
        w=self.waveforms[0] if self.waveforms else None
        return self._dock('Cursor Region Statistics',RegionStatisticsDisplay(self.store,self.cursors,w),QtCore.Qt.BottomDockWidgetArea,display_type='region_stats',object_name=object_name)
    def add_scatter(self, object_name=None):
        return self._dock('Scatter',ScatterDisplay(self.store),QtCore.Qt.RightDockWidgetArea,display_type='scatter',object_name=object_name)
    def add_histogram(self, object_name=None):
        return self._dock('Histogram',HistogramDisplay(self.store),QtCore.Qt.RightDockWidgetArea,display_type='histogram',object_name=object_name)
    def add_spectrum(self, object_name=None):
        return self._dock('FFT / PSD Spectrum',SpectrumDisplay(self.store,self.cursors),QtCore.Qt.RightDockWidgetArea,display_type='spectrum',object_name=object_name)
    def add_load_map(self, object_name=None):
        return self._dock('Load / Heat Map',LoadMapDisplay(self.store),QtCore.Qt.RightDockWidgetArea,display_type='load_map',object_name=object_name)
    def add_metric_report(self, object_name=None):
        return self._dock('Segment / KPI Report',MetricReportDisplay(self.store),QtCore.Qt.RightDockWidgetArea,display_type='metric_report',object_name=object_name)
    def add_saved_report(self, object_name=None):
        return self._dock('Saved Analysis Report',SavedReportDisplay(self.store),QtCore.Qt.RightDockWidgetArea,display_type='saved_report',object_name=object_name)
    def add_saved_trend(self, object_name=None):
        return self._dock('Saved KPI Trend',SavedTrendDisplay(self.store),QtCore.Qt.RightDockWidgetArea,display_type='saved_trend',object_name=object_name)
    def add_strip_model(self, object_name=None):
        return self._dock('NHRA Strip / Model Residuals',StripModelDisplay(self.store),QtCore.Qt.RightDockWidgetArea,display_type='strip_model',object_name=object_name)
    def add_envelope(self, object_name=None):
        return self._dock('Multi-Run Envelope',EnvelopeDisplay(self.store),QtCore.Qt.RightDockWidgetArea,display_type='envelope',object_name=object_name)
    def add_delta(self, object_name=None):
        return self._dock('Reference Delta',DeltaDisplay(self.store),QtCore.Qt.RightDockWidgetArea,display_type='delta',object_name=object_name)
    def add_audit(self, object_name=None):
        return self._dock('Data Audit',AuditDisplay(self.store),QtCore.Qt.BottomDockWidgetArea,display_type='audit',object_name=object_name)
    def add_sensor_health(self, object_name=None):
        return self._dock('Sensor Health',SensorHealthDisplay(self.store),QtCore.Qt.BottomDockWidgetArea,display_type='sensor_health',object_name=object_name)
    def add_knowledge(self, object_name=None):
        return self._dock('Engineering Knowledge',KnowledgeDisplay(self.store),QtCore.Qt.BottomDockWidgetArea,display_type='knowledge',object_name=object_name)
    def add_events(self, object_name=None):
        return self._dock('Events',EventDisplay(self.store,self.cursors),QtCore.Qt.RightDockWidgetArea,display_type='events',object_name=object_name)
    def add_alarm_status(self, object_name=None):
        return self._dock('Alarm Status',AlarmStatusDisplay(self.store,self.cursors),QtCore.Qt.RightDockWidgetArea,display_type='alarm_status',object_name=object_name)
    def add_comparison_summary(self, object_name=None):
        return self._dock('Run Comparison Summary',ComparisonSummaryDisplay(self.store),QtCore.Qt.RightDockWidgetArea,display_type='comparison_summary',object_name=object_name)
    def add_notepad(self, object_name=None):
        return self._dock('Notepad',NotepadDisplay(self.store),QtCore.Qt.RightDockWidgetArea,display_type='notepad',object_name=object_name)

    def set_x_mode(self,mode):
        for w in self.waveforms:w.set_x_mode(mode)
        for w in self.findChildren(SpectrumDisplay):w.set_x_mode(mode)
        for w in self.findChildren(GaugeDisplay):w.set_x_mode(mode)
    def add_channel(self,c):
        if not self.waveforms:self.add_waveform()
        self.waveforms[0].add_channel(c)

    @staticmethod
    def _waveform_config(widget: WaveformDisplay) -> Dict[str, Any]:
        return {
            'channels': list(widget.channels),
            'layout_mode': widget.layout_mode.currentText(),
            'event_markers': widget.events_box.isChecked(),
            'compare': bool(widget.compare),
            'snap_cursors': widget.snap_box.isChecked(),
            'channel_styles': widget.channel_styles,
            'show_readout': bool(widget.show_readout),
            'show_navigator': bool(widget.show_navigator),
            'show_legend': bool(widget.show_legend),
            'show_ab_cursors': bool(widget.show_ab_cursors),
            'reference_visible': bool(widget.reference_visible),
            'show_stat_delta': bool(widget.show_stat_delta), 'show_stat_min': bool(widget.show_stat_min), 'show_stat_max': bool(widget.show_stat_max), 'show_stat_mean': bool(widget.show_stat_mean), 'show_stat_std': bool(widget.show_stat_std),
            'max_render_points': int(widget.max_render_points),
        }

    def display_specs(self):
        specs=[]
        if self.waveforms:
            primary = self.waveforms[0]
            specs.append({
                'type': 'waveform',
                'title': 'Waveform',
                'object_name': primary.objectName() or 'PrimaryWaveform',
                'config': self._waveform_config(primary),
            })
        for dock in self.findChildren(QtWidgets.QDockWidget):
            widget=dock.widget(); dtype=str(dock.property('techdata_display_type') or '')
            cfg={}
            if isinstance(widget,WaveformDisplay):
                cfg=self._waveform_config(widget)
            elif isinstance(widget,GaugeDisplay):
                cfg={'channel':widget.channel.currentText(),'mode':widget.mode.currentText(),'auto_range':widget.auto.isChecked(),'minimum':float(widget.minimum.value()),'maximum':float(widget.maximum.value()),'threshold':float(widget.threshold.value())}
            elif isinstance(widget,ScatterDisplay):
                cfg={'x':widget.xbox.currentText(),'y':widget.ybox.currentText(),'z':widget.zbox.currentData() or '','gate':widget.gate.currentData() or '','regression':widget.regression.isChecked()}
            elif isinstance(widget,HistogramDisplay):
                cfg={'channel':widget.channel.currentText(),'bins':int(widget.bins.value()),'mode':widget.mode.currentText(),'cumulative':widget.cumulative.isChecked(),'gate':widget.gate.currentData() or ''}
            elif isinstance(widget,SpectrumDisplay):
                cfg={'channel':widget.channel.currentText(),'mode':widget.mode.currentText(),'window':widget.window.currentText(),'max_frequency_hz':float(widget.maxfreq.value()),'log_amplitude':widget.logy.isChecked(),'use_ab':widget.use_ab.isChecked()}
            elif isinstance(widget,LoadMapDisplay):
                cfg={'x':widget.xbox.currentText(),'y':widget.ybox.currentText(),'z':widget.zbox.currentText(),'statistic':widget.stat.currentText(),'bins':int(widget.bins.value()),'gate':widget.gate.currentData() or ''}
            elif isinstance(widget,MetricReportDisplay):
                cfg={'channel':widget.channel.currentData() or widget.channel.currentText(),'statistic':widget.stat.currentText(),'x_mode':widget.xmode.currentText()}
            elif isinstance(widget,SavedReportDisplay):
                cfg={'report':widget.report.currentText()}
            elif isinstance(widget,SavedTrendDisplay):
                cfg={'report':widget.report.currentText(),'metric':widget.metric.currentText(),'segment':widget.segment.currentText()}
            elif isinstance(widget,StripModelDisplay):
                cfg={'channel':widget.channel.currentText(),'engine':widget.engine.currentText(),'step_ft':int(widget.step.value())}
            elif isinstance(widget,EnvelopeDisplay):
                cfg={'channel':widget.channel.currentText(),'x_mode':widget.xmode.currentText(),'grid_points':int(widget.grid.value())}
            elif isinstance(widget,DeltaDisplay):
                cfg={'channel':widget.channel.currentText(),'reference_index':widget.reference.currentData(),'sign':widget.sign.currentText(),'x_mode':widget.xmode.currentText()}
            elif isinstance(widget,ComparisonSummaryDisplay):
                cfg={'reference_index':widget.reference.currentData()}
            specs.append({'type':dtype,'title':dock.windowTitle(),'object_name':dock.objectName(),'config':cfg})
        return specs

    def clear_displays(self):
        for dock in list(self.findChildren(QtWidgets.QDockWidget)):
            dock.setParent(None); dock.deleteLater()
        central = self.takeCentralWidget()
        if central is not None:
            central.setParent(None); central.deleteLater()
        self.setCentralWidget(QtWidgets.QWidget())
        self.waveforms.clear(); self._display_count=0

    def restore_display_specs(self,specs):
        if not specs:
            return
        self.clear_displays()
        # Waveforms first so Values displays can bind to the primary waveform.
        ordered=sorted(specs,key=lambda x: 0 if x.get('type')=='waveform' else 1)
        for spec in ordered:
            dtype=spec.get('type'); obj=spec.get('object_name'); cfg=spec.get('config') or {}
            if dtype=='waveform':
                w=self.add_waveform(obj)
                w.channels=list(cfg.get('channels',[]))
                w.channel_styles={str(k):dict(v) for k,v in (cfg.get('channel_styles') or {}).items()}
                idx=w.layout_mode.findText(cfg.get('layout_mode','Stacked Channels'))
                if idx>=0:w.layout_mode.setCurrentIndex(idx)
                w.events_box.setChecked(bool(cfg.get('event_markers',True)))
                w.compare=bool(cfg.get('compare',True)); w.snap_box.setChecked(bool(cfg.get('snap_cursors',True)))
                w.show_readout=bool(cfg.get('show_readout',False)); w.show_navigator=bool(cfg.get('show_navigator',False)); w.show_legend=bool(cfg.get('show_legend',True)); w.show_ab_cursors=bool(cfg.get('show_ab_cursors',False)); w.reference_visible=bool(cfg.get('reference_visible',False)); w.show_stat_delta=bool(cfg.get('show_stat_delta',True)); w.show_stat_min=bool(cfg.get('show_stat_min',False)); w.show_stat_max=bool(cfg.get('show_stat_max',False)); w.show_stat_mean=bool(cfg.get('show_stat_mean',False)); w.show_stat_std=bool(cfg.get('show_stat_std',False)); w.max_render_points=int(cfg.get('max_render_points',50000) or 50000)
                w.more_events_action.setChecked(w.events_box.isChecked()); w.more_nav_action.setChecked(w.show_navigator); w.more_ab_action.setChecked(w.show_ab_cursors); w.more_snap_action.setChecked(w.snap_box.isChecked()); w.more_readout_action.setChecked(w.show_readout)
                for attr,action in getattr(w,'_readout_stat_actions',{}).items(): action.setChecked(bool(getattr(w,attr)))
                w.readout.setVisible(w.show_readout); w.navigator.setVisible(w.show_navigator); w._set_stat_column_visibility(); w._set_ab_visible(w.show_ab_cursors); w.refresh()
            elif dtype=='values': self.add_values(obj)
            elif dtype=='gauge':
                dock=self.add_gauge(obj);w=dock.widget()
                if cfg.get('channel'):
                    i=w.channel.findText(cfg['channel']);w.channel.setCurrentIndex(i if i>=0 else 0)
                if cfg.get('mode'):
                    i=w.mode.findText(cfg['mode']);w.mode.setCurrentIndex(i if i>=0 else 0)
                w.auto.setChecked(bool(cfg.get('auto_range',True)));w.minimum.setValue(float(cfg.get('minimum',0.0)));w.maximum.setValue(float(cfg.get('maximum',100.0)));w.threshold.setValue(float(cfg.get('threshold',0.5)));w.refresh()
            elif dtype=='region_stats': self.add_region_stats(obj)
            elif dtype=='scatter':
                dock=self.add_scatter(obj); w=dock.widget()
                if cfg.get('x'):
                    i=w.xbox.findText(cfg['x']); w.xbox.setCurrentIndex(i if i>=0 else 0)
                if cfg.get('y'):
                    i=w.ybox.findText(cfg['y']); w.ybox.setCurrentIndex(i if i>=0 else 0)
                if cfg.get('z'):
                    i=w.zbox.findData(cfg['z']);w.zbox.setCurrentIndex(i if i>=0 else 0)
                if cfg.get('gate'):
                    i=w.gate.findData(cfg['gate']);w.gate.setCurrentIndex(i if i>=0 else 0)
                w.regression.setChecked(bool(cfg.get('regression',False)));w.refresh()
            elif dtype=='histogram':
                dock=self.add_histogram(obj); w=dock.widget(); w.bins.setValue(int(cfg.get('bins',60)))
                if cfg.get('channel'):
                    i=w.channel.findText(cfg['channel']); w.channel.setCurrentIndex(i if i>=0 else 0)
                if cfg.get('mode'):
                    i=w.mode.findText(cfg['mode']);w.mode.setCurrentIndex(i if i>=0 else 0)
                w.cumulative.setChecked(bool(cfg.get('cumulative',False)))
                if cfg.get('gate'):
                    i=w.gate.findData(cfg['gate']);w.gate.setCurrentIndex(i if i>=0 else 0)
                w.refresh()
            elif dtype=='spectrum':
                dock=self.add_spectrum(obj); w=dock.widget()
                if cfg.get('channel'):
                    i=w.channel.findText(cfg['channel']); w.channel.setCurrentIndex(i if i>=0 else 0)
                if cfg.get('mode'):
                    i=w.mode.findText(cfg['mode']); w.mode.setCurrentIndex(i if i>=0 else 0)
                if cfg.get('window'):
                    i=w.window.findText(cfg['window']); w.window.setCurrentIndex(i if i>=0 else 0)
                w.maxfreq.setValue(float(cfg.get('max_frequency_hz',500.0))); w.logy.setChecked(bool(cfg.get('log_amplitude',False))); w.use_ab.setChecked(bool(cfg.get('use_ab',False))); w.refresh()
            elif dtype=='load_map':
                dock=self.add_load_map(obj);w=dock.widget();w.bins.setValue(int(cfg.get('bins',30)))
                for box,key in ((w.xbox,'x'),(w.ybox,'y'),(w.zbox,'z')):
                    if cfg.get(key):
                        i=box.findText(cfg[key]);box.setCurrentIndex(i if i>=0 else 0)
                if cfg.get('statistic'):
                    i=w.stat.findText(cfg['statistic']);w.stat.setCurrentIndex(i if i>=0 else 0)
                if cfg.get('gate'):
                    i=w.gate.findData(cfg['gate']);w.gate.setCurrentIndex(i if i>=0 else 0)
                w.refresh()
            elif dtype=='metric_report':
                dock=self.add_metric_report(obj);w=dock.widget()
                if cfg.get('channel'):
                    i=w.channel.findData(cfg['channel']);w.channel.setCurrentIndex(i if i>=0 else 0)
                if cfg.get('statistic'):
                    i=w.stat.findText(cfg['statistic']);w.stat.setCurrentIndex(i if i>=0 else 0)
                if cfg.get('x_mode'):
                    i=w.xmode.findText(cfg['x_mode']);w.xmode.setCurrentIndex(i if i>=0 else 0)
                w.refresh()
            elif dtype=='saved_report':
                dock=self.add_saved_report(obj);w=dock.widget();i=w.report.findText(cfg.get('report',''));w.report.setCurrentIndex(i if i>=0 else 0);w.refresh()
            elif dtype=='saved_trend':
                dock=self.add_saved_trend(obj);w=dock.widget();i=w.report.findText(cfg.get('report',''));w.report.setCurrentIndex(i if i>=0 else 0);w._report_changed();i=w.metric.findText(cfg.get('metric',''));w.metric.setCurrentIndex(i if i>=0 else 0);i=w.segment.findText(cfg.get('segment',''));w.segment.setCurrentIndex(i if i>=0 else 0);w.refresh()
            elif dtype=='strip_model':
                dock=self.add_strip_model(obj);w=dock.widget();i=w.channel.findText(cfg.get('channel',''));w.channel.setCurrentIndex(i if i>=0 else 0);i=w.engine.findText(cfg.get('engine',''));w.engine.setCurrentIndex(i if i>=0 else 0);w.step.setValue(int(cfg.get('step_ft',5)));w.refresh()
            elif dtype=='envelope':
                dock=self.add_envelope(obj); w=dock.widget()
                if cfg.get('channel'):
                    i=w.channel.findText(cfg['channel']); w.channel.setCurrentIndex(i if i>=0 else 0)
                if cfg.get('x_mode'):
                    i=w.xmode.findText(cfg['x_mode']); w.xmode.setCurrentIndex(i if i>=0 else 0)
                w.grid.setValue(int(cfg.get('grid_points',2000))); w.refresh()
            elif dtype=='delta':
                dock=self.add_delta(obj); w=dock.widget()
                if cfg.get('channel'):
                    i=w.channel.findText(cfg['channel']); w.channel.setCurrentIndex(i if i>=0 else 0)
                if cfg.get('sign'):
                    i=w.sign.findText(cfg['sign']); w.sign.setCurrentIndex(i if i>=0 else 0)
                if cfg.get('x_mode'):
                    i=w.xmode.findText(cfg['x_mode']); w.xmode.setCurrentIndex(i if i>=0 else 0)
                ref_idx=cfg.get('reference_index')
                if ref_idx is not None:
                    i=w.reference.findData(ref_idx); w.reference.setCurrentIndex(i if i>=0 else 0)
                w.refresh()
            elif dtype=='audit': self.add_audit(obj)
            elif dtype=='sensor_health': self.add_sensor_health(obj)
            elif dtype=='knowledge': self.add_knowledge(obj)
            elif dtype=='events': self.add_events(obj)
            elif dtype=='alarm_status': self.add_alarm_status(obj)
            elif dtype=='comparison_summary':
                dock=self.add_comparison_summary(obj); w=dock.widget()
                ref_idx=cfg.get('reference_index')
                if ref_idx is not None:
                    i=w.reference.findData(ref_idx); w.reference.setCurrentIndex(i if i>=0 else 0)
                w.refresh()
            elif dtype=='notepad': self.add_notepad(obj)
        if not self.waveforms:
            self.add_waveform()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        icon=_application_icon()
        if not icon.isNull(): self.setWindowIcon(icon)
        self.setWindowTitle(f"{PRODUCT_NAME} — Data Analysis — {PRODUCT_VERSION}")
        self.resize(1540, 940)
        self.setAcceptDrops(True)
        self.setDockOptions(QtWidgets.QMainWindow.AllowNestedDocks | QtWidgets.QMainWindow.AllowTabbedDocks | QtWidgets.QMainWindow.GroupedDragging | QtWidgets.QMainWindow.AnimatedDocks)
        self.catalog=LocalCatalog()
        self.auth_provider=WebsiteTechServicesAuthProvider()
        self.auth=AuthManager(self.auth_provider,KeyringCredentialStore())
        self.auth_required=desktop_auth_required()
        # Permanent server Run→Asset transport remains fail-closed until the
        # website exposes that contract. Metadata/timing sync uses existing GET
        # APIs; explicit local working attachments stay in Velocity only.
        self.tech_services=AuthorizedTechServicesTransport(UnboundTechServicesTransport(),self.auth,enforce=self.auth_required)
        self._tech_sync_thread=None
        self._tech_sync_worker=None
        self._tech_sync_user_initiated=False
        self.simulation_studies=[]
        self.compare_sets=CompareSetLibrary()
        self.store=SessionStore(); self.store.catalog=self.catalog; self.cursors=CursorBus(); self.project_path:Optional[str]=None
        self.analysis_library=DefinitionLibrary(name='Workbook Analysis Library'); self.store.analysis_library=self.analysis_library
        self.worksheets=QtWidgets.QTabWidget(); self.worksheets.setTabsClosable(True); self.worksheets.setMovable(True)
        self.worksheets.setDocumentMode(True); self.worksheets.setElideMode(QtCore.Qt.ElideRight); self.worksheets.setUsesScrollButtons(True)
        self.worksheets.tabBar().setExpanding(False)
        self.new_sheet_button=QtWidgets.QToolButton(); self.new_sheet_button.setText('+'); self.new_sheet_button.setToolTip('New worksheet (Ctrl+Shift+N)')
        self.new_sheet_button.clicked.connect(lambda: self.add_worksheet())
        self.worksheets.setCornerWidget(self.new_sheet_button, QtCore.Qt.TopRightCorner)
        self.setCentralWidget(self.worksheets)
        self.worksheets.tabCloseRequested.connect(self._close_sheet)
        self._build_actions(); self._build_toolbar(); self._build_docks(); self._build_menus()
        self._refresh_account_actions()
        self.add_worksheet('Data')
        self._apply_workspace_layout('simple')
        self.store.activeChanged.connect(self._active_changed)
        self.store.changed.connect(self._refresh_session_selectors)
        self._refresh_session_selectors()
        self.statusBar().showMessage('Open a data log to begin. Ctrl+O')
        # Recovery snapshots are deliberately separate from user project files.
        autosave_root=Path(QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.AppLocalDataLocation) or str(Path.home()/'.nhra-velocity'))
        autosave_root.mkdir(parents=True,exist_ok=True)
        self._recovery_path=autosave_root/'autosave-recovery.nhratech'
        self._autosave_timer=QtCore.QTimer(self); self._autosave_timer.setInterval(90_000)
        self._autosave_timer.timeout.connect(self._write_recovery_snapshot); self._autosave_timer.start()
        QtCore.QTimer.singleShot(0,self._offer_recovery)

    def _build_actions(self):
        self.a_open=QtGui.QAction('Open Data Log…',self); self.a_open.setShortcut(QtGui.QKeySequence.Open); self.a_open.triggered.connect(self.open_logs)
        self.a_folder=QtGui.QAction('Open Data Log Folder…',self); self.a_folder.triggered.connect(self.open_log_folder)
        self.a_demo=QtGui.QAction('Open Bundled Native Demos',self); self.a_demo.triggered.connect(self._open_bundled_demos)
        self.a_import_support=QtGui.QAction('Import Support / Diagnostics…',self); self.a_import_support.triggered.connect(self._show_import_support)
        self.a_selftest=QtGui.QAction('Run Import / Plot Data Self-Test…',self); self.a_selftest.triggered.connect(self._run_data_selftest)
        self.a_logs=QtGui.QAction('Open Diagnostic Log Folder',self); self.a_logs.triggered.connect(self._open_log_folder)
        self.a_save=QtGui.QAction('Save Workbook…',self); self.a_save.setShortcut(QtGui.QKeySequence.Save); self.a_save.triggered.connect(self.save_project)
        self.a_load=QtGui.QAction('Open Workbook…',self); self.a_load.triggered.connect(self.open_project)
        self.a_keep_offline=QtGui.QAction('Cache Active Asset Offline',self); self.a_keep_offline.triggered.connect(self._keep_active_offline)
        self.a_capture_snapshot=QtGui.QAction('Capture Vehicle Model Snapshot…',self); self.a_capture_snapshot.triggered.connect(self._capture_model_snapshot)
        self.a_history=QtGui.QAction('Engineering History…',self); self.a_history.triggered.connect(self._engineering_history)
        self.a_apply_sync=QtGui.QAction('Apply Tech Services Snapshot (Development)…',self); self.a_apply_sync.triggered.connect(self._apply_sync_snapshot)
        self.a_site_sync=QtGui.QAction('Sync NHRA Tech Services Data…',self); self.a_site_sync.triggered.connect(self._sync_tech_services_data)
        self.a_attach_selected_run=QtGui.QAction('Attach Data Log to Selected Run…',self); self.a_attach_selected_run.triggered.connect(self._attach_local_telemetry_to_selected_run)
        self.a_recovery=QtGui.QAction('Recover Autosave…',self); self.a_recovery.triggered.connect(lambda:self._recover_snapshot(force=True))
        self.a_sheet=QtGui.QAction('New Worksheet',self); self.a_sheet.setShortcut('Ctrl+Shift+N'); self.a_sheet.triggered.connect(lambda:self.add_worksheet())
        self.a_duplicate_sheet=QtGui.QAction('Duplicate Worksheet',self); self.a_duplicate_sheet.setShortcut('Ctrl+Shift+D'); self.a_duplicate_sheet.triggered.connect(self._duplicate_current_sheet)
        self.a_command_palette=QtGui.QAction('Command Palette…',self); self.a_command_palette.setShortcut('Ctrl+K'); self.a_command_palette.triggered.connect(self._command_palette)
        self.a_fit_run=QtGui.QAction('Fit Drag Run',self); self.a_fit_run.setShortcut('Ctrl+F'); self.a_fit_run.triggered.connect(self._fit_current_run)
        self.a_fit_full=QtGui.QAction('Fit Full Logger Recording',self); self.a_fit_full.setShortcut('Ctrl+Shift+F'); self.a_fit_full.triggered.connect(self._fit_full_recording)
        self.a_standard_layout=QtGui.QAction('Apply Standard Class Layout…',self); self.a_standard_layout.triggered.connect(self._choose_standard_layout)
        self.a_shift_report=QtGui.QAction('Pro Stock Shift Report…',self); self.a_shift_report.setShortcut('Ctrl+Shift+P'); self.a_shift_report.triggered.connect(self._pro_stock_shift_report)
        self.a_shortcuts=QtGui.QAction('Keyboard Shortcuts…',self); self.a_shortcuts.triggered.connect(self._show_keyboard_shortcuts)
        self.a_integration_status=QtGui.QAction('Tech Services Integration Status…',self); self.a_integration_status.triggered.connect(self._show_integration_status)
        self.a_data_setup=QtGui.QAction('Data Log Setup / Readiness…',self); self.a_data_setup.setShortcut('Ctrl+Alt+D'); self.a_data_setup.triggered.connect(self._show_data_log_readiness)
        self.a_racepak_profiles=QtGui.QAction('RacePak Configuration Profiles…',self); self.a_racepak_profiles.triggered.connect(self._racepak_profile_manager)
        self.a_about=QtGui.QAction('About NHRA Velocity…',self); self.a_about.triggered.connect(self._show_about)
        self.a_layout_simple=QtGui.QAction('Simple Workspace',self); self.a_layout_simple.setShortcut('Ctrl+1'); self.a_layout_simple.triggered.connect(lambda:self._apply_workspace_layout('simple'))
        self.a_layout_investigation=QtGui.QAction('Investigation Workspace',self); self.a_layout_investigation.setShortcut('Ctrl+2'); self.a_layout_investigation.triggered.connect(lambda:self._apply_workspace_layout('investigation'))
        self.a_layout_full=QtGui.QAction('Full Engineering Workspace',self); self.a_layout_full.setShortcut('Ctrl+3'); self.a_layout_full.triggered.connect(lambda:self._apply_workspace_layout('full'))
        self.a_focus_analysis=QtGui.QAction('Focus Analysis',self); self.a_focus_analysis.setCheckable(True); self.a_focus_analysis.setShortcut('Ctrl+Enter'); self.a_focus_analysis.triggered.connect(self._toggle_focus_analysis)
        self.a_wave=QtGui.QAction('Waveform Display',self); self.a_wave.triggered.connect(lambda:self.current_sheet().add_waveform())
        self.a_values=QtGui.QAction('Values Display',self); self.a_values.triggered.connect(lambda:self.current_sheet().add_values())
        self.a_gauge=QtGui.QAction('Gauge / Status Display',self); self.a_gauge.triggered.connect(lambda:self.current_sheet().add_gauge())
        self.a_region_stats=QtGui.QAction('Cursor Region Statistics',self); self.a_region_stats.setShortcut('Ctrl+Shift+R'); self.a_region_stats.triggered.connect(lambda:self.current_sheet().add_region_stats())
        self.a_scatter=QtGui.QAction('Scatter Display',self); self.a_scatter.triggered.connect(lambda:self.current_sheet().add_scatter())
        self.a_hist=QtGui.QAction('Histogram Display',self); self.a_hist.triggered.connect(lambda:self.current_sheet().add_histogram())
        self.a_spectrum=QtGui.QAction('FFT / PSD Spectrum Display',self); self.a_spectrum.triggered.connect(lambda:self.current_sheet().add_spectrum())
        self.a_load_map=QtGui.QAction('Load / Heat Map Display',self); self.a_load_map.triggered.connect(lambda:self.current_sheet().add_load_map())
        self.a_metric_report=QtGui.QAction('Segment / KPI Report',self); self.a_metric_report.triggered.connect(lambda:self.current_sheet().add_metric_report())
        self.a_envelope=QtGui.QAction('Multi-Run Envelope Display',self); self.a_envelope.triggered.connect(lambda:self.current_sheet().add_envelope())
        self.a_delta=QtGui.QAction('Reference Delta Display',self); self.a_delta.triggered.connect(lambda:self.current_sheet().add_delta())
        self.a_audit=QtGui.QAction('Data Audit Display',self); self.a_audit.triggered.connect(lambda:self.current_sheet().add_audit())
        self.a_sensor_health=QtGui.QAction('Sensor Health Display',self); self.a_sensor_health.triggered.connect(lambda:self.current_sheet().add_sensor_health())
        self.a_knowledge=QtGui.QAction('Engineering Knowledge Display',self); self.a_knowledge.triggered.connect(lambda:self.current_sheet().add_knowledge())
        self.a_events=QtGui.QAction('Event Display',self); self.a_events.triggered.connect(lambda:self.current_sheet().add_events())
        self.a_alarm_status=QtGui.QAction('Alarm Status Display',self); self.a_alarm_status.triggered.connect(lambda:self.current_sheet().add_alarm_status())
        self.a_library_event_rule=QtGui.QAction('Event / Alarm Rule…',self); self.a_library_event_rule.triggered.connect(self._new_library_event_rule)
        self.a_comparison_summary=QtGui.QAction('Run Comparison Summary',self); self.a_comparison_summary.triggered.connect(lambda:self.current_sheet().add_comparison_summary())
        self.a_notepad=QtGui.QAction('Notepad Display',self); self.a_notepad.triggered.connect(lambda:self.current_sheet().add_notepad())
        self.a_gate=QtGui.QAction('Data Gate…',self); self.a_gate.triggered.connect(self._new_data_gate)
        self.a_library_import=QtGui.QAction('Import Analysis Library…',self); self.a_library_import.triggered.connect(self._import_analysis_library)
        self.a_library_export=QtGui.QAction('Export Analysis Library…',self); self.a_library_export.triggered.connect(self._export_analysis_library)
        self.a_library_capture=QtGui.QAction('Capture Active Run Definitions',self); self.a_library_capture.triggered.connect(self._capture_analysis_library)
        self.a_library_constant=QtGui.QAction('Library Constant…',self); self.a_library_constant.triggered.connect(self._new_library_constant)
        self.a_library_metric=QtGui.QAction('Saved Metric…',self); self.a_library_metric.triggered.connect(self._new_library_metric)
        self.a_library_segment=QtGui.QAction('Saved Segment…',self); self.a_library_segment.triggered.connect(self._new_library_segment)
        self.a_library_condition=QtGui.QAction('Conditional Rule…',self); self.a_library_condition.triggered.connect(self._new_library_condition)
        self.a_library_report=QtGui.QAction('Saved Report…',self); self.a_library_report.triggered.connect(self._new_library_report)
        self.a_saved_report=QtGui.QAction('Saved Analysis Report Display',self); self.a_saved_report.triggered.connect(lambda:self.current_sheet().add_saved_report())
        self.a_saved_trend=QtGui.QAction('Saved KPI Trend Display',self); self.a_saved_trend.triggered.connect(lambda:self.current_sheet().add_saved_trend())
        self.a_strip_model=QtGui.QAction('NHRA Strip / Model Residuals',self); self.a_strip_model.triggered.connect(lambda:self.current_sheet().add_strip_model())
        self.a_common_channels=QtGui.QAction('Common Channel Mapping…',self); self.a_common_channels.setShortcut('Ctrl+Alt+M'); self.a_common_channels.triggered.connect(self._common_channel_mapping_dialog)
        self.a_racepak_config=QtGui.QAction('RacePak DDF Configuration…',self); self.a_racepak_config.triggered.connect(self._racepak_config_dialog)
        self.a_math=QtGui.QAction('Math Channel Builder…',self); self.a_math.setShortcut('Ctrl+M'); self.a_math.triggered.connect(self._new_math_channel)
        self.a_reconstruct=QtGui.QAction('Reconstruct Delivered Power…',self); self.a_reconstruct.triggered.connect(self._reconstruct_power)
        self.a_infer=QtGui.QAction('Inference Center…',self); self.a_infer.setShortcut('Ctrl+I'); self.a_infer.triggered.connect(self._inference_center)
        self.a_compare_run=QtGui.QAction('Create Compare Run…',self); self.a_compare_run.setShortcut('Ctrl+Shift+C'); self.a_compare_run.triggered.connect(self._create_compare_run)
        self.a_compare_manager=QtGui.QAction('Compare Workspace Manager…',self); self.a_compare_manager.setShortcut('Ctrl+Shift+R'); self.a_compare_manager.triggered.connect(self._compare_workspace_manager)
        self.a_compare_set_save=QtGui.QAction('Save Current Compare Set…',self); self.a_compare_set_save.triggered.connect(self._save_current_compare_set)
        self.a_compare_set_apply=QtGui.QAction('Apply Named Compare Set…',self); self.a_compare_set_apply.triggered.connect(self._apply_named_compare_set)
        self.a_compare_set_delete=QtGui.QAction('Delete Named Compare Set…',self); self.a_compare_set_delete.triggered.connect(self._delete_named_compare_set)
        self.a_compare_ref_prev=QtGui.QAction('Previous Reference Run',self); self.a_compare_ref_prev.setShortcut('Ctrl+Alt+Left'); self.a_compare_ref_prev.triggered.connect(lambda:self._step_compare_reference(-1))
        self.a_compare_ref_next=QtGui.QAction('Next Reference Run',self); self.a_compare_ref_next.setShortcut('Ctrl+Alt+Right'); self.a_compare_ref_next.triggered.connect(lambda:self._step_compare_reference(1))
        self.a_sim_study=QtGui.QAction('Simulation Study Center…',self); self.a_sim_study.setShortcut('Ctrl+Shift+S'); self.a_sim_study.triggered.connect(self._simulation_study_center)
        self.a_model_channels=QtGui.QAction('Attach RSA Model / Residual Channels…',self); self.a_model_channels.triggered.connect(self._attach_rsa_model_channels)
        self.a_template_save=QtGui.QAction('Save Worksheet as Template…',self); self.a_template_save.triggered.connect(self._save_worksheet_template)
        self.a_template_apply=QtGui.QAction('Apply Worksheet Template…',self); self.a_template_apply.setShortcut('Ctrl+Alt+T'); self.a_template_apply.triggered.connect(self._apply_worksheet_template)
        self.a_template_manage=QtGui.QAction('Manage Worksheet Templates…',self); self.a_template_manage.triggered.connect(self._manage_worksheet_templates)
        self.a_account=QtGui.QAction('NHRA Tech Services Account…',self); self.a_account.triggered.connect(self._show_account_access)
        self.a_signin=QtGui.QAction('Sign in to NHRA Tech Services…',self); self.a_signin.triggered.connect(self._sign_in)
        self.a_signout=QtGui.QAction('Sign out',self); self.a_signout.triggered.connect(self._sign_out)
        self.a_tile=QtGui.QAction('Tile Dock Displays',self)

    def _build_toolbar(self):
        # Permanent toolbar = the trackside path. Advanced layout/report/tools
        # live in menus or Ctrl+K so the app does not turn into a cockpit.
        tb=self.addToolBar('Main'); tb.setObjectName('MainToolbar'); tb.setMovable(False); tb.setIconSize(QtCore.QSize(18,18))
        tb.addAction(self.a_open); tb.addAction(self.a_save); tb.addAction(self.a_fit_run); tb.addSeparator()
        tb.addWidget(QtWidgets.QLabel(' Run '))
        self.run_selector=QtWidgets.QComboBox(); self.run_selector.setMinimumContentsLength(14); self.run_selector.setMinimumWidth(180); self.run_selector.setToolTip('Active run data log'); self.run_selector.currentIndexChanged.connect(self._toolbar_run_changed); tb.addWidget(self.run_selector)
        tb.addSeparator(); tb.addWidget(QtWidgets.QLabel(' X '))
        self.xmode=QtWidgets.QComboBox(); self.xmode.addItems(['Time from Launch','Distance from Launch','Normalized Run %','Logger Time','Sample Index']); self.xmode.currentTextChanged.connect(self._xmode_changed); tb.addWidget(self.xmode)
        tb.addSeparator(); self.compare_box=QtWidgets.QCheckBox('Compare'); self.compare_box.setChecked(False); self.compare_box.setToolTip('Overlay the Reference/Compare sessions. Ctrl+Shift+R opens the Compare Workspace Manager.'); self.compare_box.stateChanged.connect(self._compare_changed); tb.addWidget(self.compare_box)
        self.reference_label=QtWidgets.QLabel(' Ref ');tb.addWidget(self.reference_label)
        self.reference_selector=QtWidgets.QComboBox(); self.reference_selector.setMinimumContentsLength(12); self.reference_selector.setMinimumWidth(150); self.reference_selector.setToolTip('Reference session used by waveform compare'); self.reference_selector.currentIndexChanged.connect(self._toolbar_reference_changed); tb.addWidget(self.reference_selector)
        self.reference_label.setVisible(False);self.reference_selector.setVisible(False)

    def _build_docks(self):
        # Authoritative Tech Services Run/Asset mirror with local analysis cache.
        self.run_browser=RunBrowser(self.catalog)
        self.run_browser.openRunRequested.connect(self._open_catalog_run)
        self.run_browser.keepOfflineRequested.connect(self._keep_run_offline)
        self.run_browser.keepEventOfflineRequested.connect(self._keep_event_offline)
        self.run_browser.analysisCaseRequested.connect(self._create_analysis_case)
        self.run_browser.attachTelemetryRequested.connect(self._attach_local_telemetry_to_run)
        self.run_browser.syncRequested.connect(self._sync_tech_services_data)
        run_dock=QtWidgets.QDockWidget('NHRA Tech Services Runs',self); run_dock.setObjectName('RunBrowserDock'); run_dock.setWidget(self.run_browser); self.addDockWidget(QtCore.Qt.LeftDockWidgetArea,run_dock)
        self.case_browser=AnalysisCaseBrowser(self.catalog);self.case_browser.openRunRequested.connect(self._open_catalog_run);self.case_browser.addSelectedRunRequested.connect(self._add_selected_run_to_case);self.case_browser.cacheCaseRequested.connect(self._cache_analysis_case)
        case_dock=QtWidgets.QDockWidget('Analysis Cases',self);case_dock.setObjectName('AnalysisCasesDock');case_dock.setWidget(self.case_browser);self.addDockWidget(QtCore.Qt.LeftDockWidgetArea,case_dock);self.tabifyDockWidget(run_dock,case_dock);run_dock.raise_()
        self.asset_browser=AssetBrowser(self.catalog);self.run_browser.runSelectionChanged.connect(self.asset_browser.set_run)
        d=QtWidgets.QDockWidget('Run Assets',self);d.setObjectName('AssetsDock');d.setWidget(self.asset_browser);self.addDockWidget(QtCore.Qt.BottomDockWidgetArea,d);asset_dock=d
        self.case_timeline=CaseTimelineBrowser(self.catalog);self.case_browser.caseSelectionChanged.connect(self.case_timeline.set_case)
        d=QtWidgets.QDockWidget('Case Timeline / Sync',self);d.setObjectName('CaseTimelineDock');d.setWidget(self.case_timeline);self.addDockWidget(QtCore.Qt.BottomDockWidgetArea,d);self.tabifyDockWidget(asset_dock,d);asset_dock.raise_()
        self.case_review=SynchronizedReviewPanel(self.catalog);self.case_browser.caseSelectionChanged.connect(self.case_review.set_case);self.case_review.caseTimeChanged.connect(self._case_review_time_changed);self.case_review.cacheAssetRequested.connect(self._keep_asset_offline)
        d=QtWidgets.QDockWidget('Synchronized Case Review',self);d.setObjectName('CaseReviewDock');d.setWidget(self.case_review);self.addDockWidget(QtCore.Qt.BottomDockWidgetArea,d);self.tabifyDockWidget(asset_dock,d);asset_dock.raise_()
        self.catalog_run_details=CatalogRunDetails(self.catalog);self.run_browser.runSelectionChanged.connect(self.catalog_run_details.set_run)
        d=QtWidgets.QDockWidget('Canonical Run Record',self);d.setObjectName('CatalogRunDetailsDock');d.setWidget(self.catalog_run_details);self.addDockWidget(QtCore.Qt.RightDockWidgetArea,d);canonical_dock=d
        self.run_workspace=RunWorkspacePanel(self.catalog);self.run_browser.runSelectionChanged.connect(self.run_workspace.set_run);self.run_workspace.openRunRequested.connect(self._open_catalog_run);self.run_workspace.attachTelemetryRequested.connect(self._attach_local_telemetry_to_run);self.run_workspace.applyProfileRequested.connect(self._apply_profile_to_catalog_run);self.run_workspace.generateReportRequested.connect(self._generate_standard_run_report)
        self.run_browser.runSelectionChanged.connect(self._catalog_run_selected)
        d=QtWidgets.QDockWidget('Run Workspace',self);d.setObjectName('RunWorkspaceDock');d.setWidget(self.run_workspace);self.addDockWidget(QtCore.Qt.RightDockWidgetArea,d);self.tabifyDockWidget(canonical_dock,d);d.raise_()
        # Sessions / compare sets
        self.session_tree=SessionDock(self.store); self.session_tree.activeRequested.connect(self.store.set_active); self.session_tree.roleChanged.connect(self._role_changed); self.session_tree.alignmentChanged.connect(self._alignment_changed); self.session_tree.autoAlignRequested.connect(self._auto_align_session); self.session_tree.renameRequested.connect(self._rename_session); self.session_tree.removeRequested.connect(self._remove_session)
        d=QtWidgets.QDockWidget('Sessions / Compare Sets',self); d.setObjectName('SessionsDock'); d.setWidget(self.session_tree); self.addDockWidget(QtCore.Qt.LeftDockWidgetArea,d)
        # Channel browser defaults to the small class-relevant set. The full
        # logger catalog is one selector away, and any search spans all channels.
        chwrap=QtWidgets.QWidget(); v=QtWidgets.QVBoxLayout(chwrap); v.setContentsMargins(4,4,4,4)
        filter_row=QtWidgets.QHBoxLayout()
        self.channel_scope=QtWidgets.QComboBox();self.channel_scope.addItem('Essentials','essentials');self.channel_scope.addItem('All channels','all');self.channel_scope.setToolTip('Essentials shows favorites plus the standard channels for the active run type.')
        self.channel_search=QtWidgets.QLineEdit(); self.channel_search.setPlaceholderText('Search channels…  (Ctrl+P)')
        filter_row.addWidget(self.channel_scope);filter_row.addWidget(self.channel_search,1);v.addLayout(filter_row)
        self.search_shortcut=QtGui.QShortcut(QtGui.QKeySequence('Ctrl+P'), self); self.search_shortcut.activated.connect(self._focus_parameter_search); self.quick_access_shortcut=QtGui.QShortcut(QtGui.QKeySequence('Ctrl+Q'),self); self.quick_access_shortcut.activated.connect(self._focus_parameter_search)
        self.channels=ChannelTree(); self.channels.channelActivated.connect(self._channel_add); self.channels.channelRemoveRequested.connect(self._channel_remove); self.channels.channelPropertiesRequested.connect(self._channel_properties); self.channels.commonChannelRequested.connect(self._assign_common_channel); self.channels.channelAliasRequested.connect(self._set_channel_alias); self.channels.channelFavoriteRequested.connect(self._set_channel_favorite); self.channels.calculatedChannelEditRequested.connect(self._edit_math_channel); self.channels.calculatedChannelDeleteRequested.connect(self._delete_math_channel); v.addWidget(self.channels,1)
        self.channel_search.textChanged.connect(lambda _t:self._refresh_channel_explorer());self.channel_scope.currentIndexChanged.connect(lambda _i:self._refresh_channel_explorer())
        params_dock=QtWidgets.QDockWidget('Channel Explorer',self); params_dock.setObjectName('ParametersDock'); params_dock.setWidget(chwrap); self.addDockWidget(QtCore.Qt.LeftDockWidgetArea,params_dock)
        # Run selection and channel selection are the two ordinary entry points;
        # keep them in one left-side tab group rather than two permanent panes.
        self.tabifyDockWidget(run_dock,params_dock);params_dock.raise_()
        # Run metadata / setup sheet
        self.metadata=MetadataEditor(self.store); d=QtWidgets.QDockWidget('Run Details / Setup',self); d.setObjectName('MetadataDock'); d.setWidget(self.metadata); self.addDockWidget(QtCore.Qt.RightDockWidgetArea,d)
        # Audit always available at app level
        self.audit=AuditDisplay(self.store); d=QtWidgets.QDockWidget('Data Integrity',self); d.setObjectName('AuditDock'); d.setWidget(self.audit); self.addDockWidget(QtCore.Qt.BottomDockWidgetArea,d); d.hide()

        # Normalize dock behavior in one place.  Child minimum sizes are cleared
        # so splitters can always resize panels instead of appearing locked.
        self._app_docks = {}
        for dock in self.findChildren(QtWidgets.QDockWidget):
            dock.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)
            dock.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable | QtWidgets.QDockWidget.DockWidgetFloatable | QtWidgets.QDockWidget.DockWidgetClosable)
            dock.setMinimumSize(0, 0)
            if dock.widget() is not None:
                dock.widget().setMinimumSize(0, 0)
            self._app_docks[dock.objectName()] = dock

    def _apply_workspace_layout(self, mode: str):
        mode = str(mode or 'simple').lower()
        docks = getattr(self, '_app_docks', {})
        if not docks:
            return
        visible = {
            'simple': {'RunBrowserDock','ParametersDock','RunWorkspaceDock'},
            'investigation': {'RunBrowserDock','SessionsDock','ParametersDock','MetadataDock','AuditDock'},
            'full': set(docks),
        }.get(mode, {'ParametersDock'})
        for name, dock in docks.items():
            dock.setVisible(name in visible)
        left = docks.get('ParametersDock')
        right = docks.get('RunWorkspaceDock')
        if left is not None and left.isVisible():
            try:self.resizeDocks([left], [320], QtCore.Qt.Horizontal)
            except Exception:pass
            if mode=='simple':left.raise_()
        if right is not None and right.isVisible():
            try:self.resizeDocks([right], [300], QtCore.Qt.Horizontal)
            except Exception:pass
        self.statusBar().showMessage(
            {'simple':'Simple workspace — Run + waveform + essential channels',
             'investigation':'Investigation workspace',
             'full':'Full engineering workspace'}.get(mode, 'Workspace updated'),
            3000,
        )

    def _toggle_focus_analysis(self, checked=False):
        checked = bool(checked)
        docks = getattr(self, '_app_docks', {})
        if checked:
            self._focus_restore = {name: dock.isVisible() for name, dock in docks.items()}
            for dock in docks.values():
                dock.hide()
            self.statusBar().showMessage('Focus Analysis — Ctrl+Enter to restore side panels', 4000)
        else:
            restore = getattr(self, '_focus_restore', None)
            if restore:
                for name, dock in docks.items():
                    dock.setVisible(bool(restore.get(name, False)))
            else:
                self._apply_workspace_layout('simple')
            self.statusBar().showMessage('Analysis panels restored', 2500)

    def _build_menus(self):
        m=self.menuBar().addMenu('&File'); m.addAction(self.a_open); m.addAction(self.a_folder); m.addAction(self.a_demo); m.addSeparator(); m.addAction(self.a_load); m.addAction(self.a_recovery); m.addAction(self.a_save); m.addSeparator(); m.addAction(self.a_keep_offline); m.addSeparator(); m.addAction('Exit',self.close)
        m=self.menuBar().addMenu('&Worksheet'); m.addAction(self.a_sheet); m.addAction(self.a_duplicate_sheet); m.addSeparator(); m.addAction(self.a_fit_run); m.addAction(self.a_fit_full); m.addAction(self.a_standard_layout)
        tm=m.addMenu('Worksheet Templates'); tm.addAction(self.a_template_apply); tm.addAction(self.a_template_save); tm.addAction(self.a_template_manage)
        qg=m.addMenu('Quick Graph')
        for preset in QUICK_GRAPH_PRESETS:
            qg.addAction(preset, lambda checked=False, name=preset: self._apply_quick_graph(name))
        add=m.addMenu('Add Display'); add.addAction(self.a_wave); add.addAction(self.a_values); add.addAction(self.a_gauge); add.addAction(self.a_region_stats); add.addAction(self.a_scatter); add.addAction(self.a_hist); add.addAction(self.a_spectrum); add.addAction(self.a_load_map); add.addAction(self.a_metric_report); add.addAction(self.a_saved_report); add.addAction(self.a_saved_trend); add.addAction(self.a_strip_model); add.addAction(self.a_envelope); add.addAction(self.a_delta); add.addAction(self.a_comparison_summary); add.addAction(self.a_events); add.addAction(self.a_alarm_status); add.addAction(self.a_notepad); add.addAction(self.a_audit); add.addAction(self.a_sensor_health); add.addAction(self.a_knowledge)
        m=self.menuBar().addMenu('&Data'); m.addAction('Run Details / Setup…',lambda:self.metadata.setFocus()); m.addAction(self.a_data_setup); m.addSeparator(); m.addAction(self.a_common_channels); m.addAction(self.a_racepak_config); m.addAction(self.a_racepak_profiles); m.addAction(self.a_math); m.addAction(self.a_gate); libm=m.addMenu('Analysis Definition Library'); [libm.addAction(a) for a in (self.a_library_import,self.a_library_export,self.a_library_capture,self.a_library_constant,self.a_library_metric,self.a_library_segment,self.a_library_condition,self.a_library_event_rule,self.a_library_report)]; m.addSeparator(); m.addAction(self.a_site_sync); m.addAction(self.a_attach_selected_run); m.addAction(self.a_keep_offline); m.addAction(self.a_capture_snapshot); m.addAction(self.a_history); m.addSeparator(); m.addAction(self.a_apply_sync)
        m.addAction('Data Integrity Audit…',self._show_audit); m.addAction(self.a_sensor_health)
        m=self.menuBar().addMenu('&Analysis')
        quick=m.addMenu('Quick Analysis')
        for action in (self.a_region_stats,self.a_hist,self.a_scatter,self.a_spectrum,self.a_load_map,self.a_sensor_health): quick.addAction(action)
        m.addAction(self.a_shift_report); m.addSeparator(); m.addAction(self.a_metric_report); m.addAction(self.a_saved_report); m.addAction(self.a_saved_trend); m.addAction(self.a_strip_model); m.addAction(self.a_envelope); m.addAction(self.a_delta); m.addAction(self.a_comparison_summary); m.addSeparator()
        m.addAction(self.a_reconstruct)
        m.addAction(self.a_infer)
        m.addAction(self.a_capture_snapshot)
        m.addAction(self.a_history)
        m.addSeparator()
        m.addAction(self.a_compare_run)
        csm=m.addMenu('Compare Sets'); csm.addAction(self.a_compare_manager); csm.addSeparator(); csm.addAction(self.a_compare_set_save); csm.addAction(self.a_compare_set_apply); csm.addAction(self.a_compare_set_delete); csm.addSeparator(); csm.addAction(self.a_compare_ref_prev); csm.addAction(self.a_compare_ref_next)
        m.addAction(self.a_sim_study)
        m.addAction(self.a_model_channels)
        m=self.menuBar().addMenu('&Account'); m.addAction(self.a_signin); m.addAction(self.a_signout); m.addSeparator(); m.addAction(self.a_account)
        m=self.menuBar().addMenu('&View'); m.addAction(self.a_command_palette); m.addSeparator()
        lm=m.addMenu('Workspace Layout'); lm.addAction(self.a_layout_simple); lm.addAction(self.a_layout_investigation); lm.addAction(self.a_layout_full); m.addAction(self.a_focus_analysis)
        m.addSeparator()
        for dock in self.findChildren(QtWidgets.QDockWidget): m.addAction(dock.toggleViewAction())
        m=self.menuBar().addMenu('&Help'); m.addAction(self.a_about); m.addSeparator(); m.addAction(self.a_shortcuts); m.addAction(self.a_integration_status); m.addSeparator(); m.addAction(self.a_import_support); m.addAction(self.a_selftest); m.addAction(self.a_demo); m.addSeparator(); m.addAction(self.a_logs)

    def _duplicate_current_sheet(self):
        source=self.current_sheet(); base=self.worksheets.tabText(self.worksheets.currentIndex())
        name=f'{base} Copy'; n=2
        existing={self.worksheets.tabText(i) for i in range(self.worksheets.count())}
        while name in existing:
            name=f'{base} Copy {n}'; n+=1
        specs=source.display_specs(); state=bytes(source.saveState()).hex()
        target=self.add_worksheet(name); target.restore_display_specs(specs)
        try:target.restoreState(QtCore.QByteArray.fromHex(state.encode()))
        except Exception:pass
        self.statusBar().showMessage(f'Duplicated worksheet: {name}',4000)

    def _command_palette(self):
        commands=[
            ('Open Log…',self.open_logs),('Open Log Folder…',self.open_log_folder),('Save Workbook…',self.save_project),
            ('New Worksheet',lambda:self.add_worksheet()),('Duplicate Worksheet',self._duplicate_current_sheet),('Apply Worksheet Template…',self._apply_worksheet_template),('Save Worksheet as Template…',self._save_worksheet_template),('Fit Drag Run (Ctrl+F)',self._fit_current_run),('Fit Full Logger Recording',self._fit_full_recording),('Apply Standard Class Layout…',self._choose_standard_layout),
            ('Add Waveform',lambda:self.current_sheet().add_waveform()),('Add Values',lambda:self.current_sheet().add_values()),('Add Gauge / Status',lambda:self.current_sheet().add_gauge()),
            ('Add Scatter',lambda:self.current_sheet().add_scatter()),('Add Histogram',lambda:self.current_sheet().add_histogram()),
            ('Add FFT / PSD Spectrum',lambda:self.current_sheet().add_spectrum()),('Add Load / Heat Map',lambda:self.current_sheet().add_load_map()),('Add Segment / KPI Report',lambda:self.current_sheet().add_metric_report()),('Add NHRA Strip / Model Residuals',lambda:self.current_sheet().add_strip_model()),('Add Multi-Run Envelope',lambda:self.current_sheet().add_envelope()),
            ('Add Reference Delta',lambda:self.current_sheet().add_delta()),('Add Run Comparison Summary',lambda:self.current_sheet().add_comparison_summary()),('Add Alarm Status',lambda:self.current_sheet().add_alarm_status()),('Add Cursor Region Statistics',lambda:self.current_sheet().add_region_stats()),('Add Sensor Health',lambda:self.current_sheet().add_sensor_health()),
            ('Pro Stock Shift Report…',self._pro_stock_shift_report),('Data Log Setup / Readiness…',self._show_data_log_readiness),('Common Channel Mapping…',self._common_channel_mapping_dialog),('RacePak DDF Configuration…',self._racepak_config_dialog),('RacePak Configuration Profiles…',self._racepak_profile_manager),('Math Channel Builder…',self._new_math_channel),('Data Gate…',self._new_data_gate),('Reconstruct Delivered Power…',self._reconstruct_power),
            ('Inference Center…',self._inference_center),('Create Compare Run…',self._create_compare_run),('Compare Workspace Manager…',self._compare_workspace_manager),('Save Current Compare Set…',self._save_current_compare_set),('Apply Named Compare Set…',self._apply_named_compare_set),('Next Reference Run',lambda:self._step_compare_reference(1)),('Previous Reference Run',lambda:self._step_compare_reference(-1)),('Simulation Study Center…',self._simulation_study_center),('Capture Vehicle Model Snapshot…',self._capture_model_snapshot),('Engineering History…',self._engineering_history),('Sync NHRA Tech Services Data…',self._sync_tech_services_data),('Attach Data Log to Selected Run…',self._attach_local_telemetry_to_selected_run),('Keep Active Asset Offline',self._keep_active_offline),
            ('Run Import / Plot Data Self-Test…',self._run_data_selftest),('Open Diagnostic Log Folder',self._open_log_folder),
        ]
        labels=[x[0] for x in commands]
        choice,ok=QtWidgets.QInputDialog.getItem(self,'Command Palette','Command:',labels,0,False)
        if not ok or not choice:return
        for label,fn in commands:
            if label==choice:
                fn();break

    def current_sheet(self)->Worksheet:
        w=self.worksheets.currentWidget(); assert isinstance(w,Worksheet); return w
    def add_worksheet(self,name=None):
        name=name or f'Worksheet {self.worksheets.count()+1}'; w=Worksheet(self.store,self.cursors,name); self.worksheets.addTab(w,name); self.worksheets.setCurrentWidget(w); w.set_x_mode(self.xmode.currentText()); return w
    def _close_sheet(self,i):
        if self.worksheets.count()>1:self.worksheets.removeTab(i)
    def _xmode_changed(self,mode):
        for i in range(self.worksheets.count()): self.worksheets.widget(i).set_x_mode(mode)
    def _refresh_session_selectors(self):
        if not hasattr(self,'run_selector') or not hasattr(self,'reference_selector'):
            return
        self.run_selector.blockSignals(True); self.reference_selector.blockSignals(True)
        try:
            self.run_selector.clear()
            for idx,h in enumerate(self.store.runs):
                label=h.label + (f'  [{h.run.vendor}]' if h.run.vendor else '')
                self.run_selector.addItem(label,idx)
            if 0<=self.store.active_index<len(self.store.runs):
                pos=self.run_selector.findData(self.store.active_index)
                if pos>=0:self.run_selector.setCurrentIndex(pos)

            self.reference_selector.clear(); self.reference_selector.addItem('— choose —',-1)
            ref_idx=-1
            for idx,h in enumerate(self.store.runs):
                if idx==self.store.active_index:continue
                self.reference_selector.addItem(h.label,idx)
                if h.role=='reference':ref_idx=idx
            pos=self.reference_selector.findData(ref_idx) if ref_idx>=0 else 0
            self.reference_selector.setCurrentIndex(pos if pos>=0 else 0)
            self.reference_selector.setEnabled(bool(self.compare_box.isChecked()) and self.reference_selector.count()>1)
            self.run_selector.setEnabled(bool(self.store.runs))
        finally:
            self.run_selector.blockSignals(False); self.reference_selector.blockSignals(False)
        self._refresh_profile_selector()

    def _toolbar_run_changed(self, combo_index):
        if combo_index<0:return
        idx=self.run_selector.itemData(combo_index)
        if idx is None:return
        idx=int(idx)
        if idx!=self.store.active_index:self.store.set_active(idx)

    def _toolbar_reference_changed(self, combo_index):
        if combo_index<0:return
        data=self.reference_selector.itemData(combo_index)
        idx=int(data) if data is not None else -1
        for i,h in enumerate(self.store.runs):
            if h.role=='reference' and i!=idx:h.role='overlay'
        if 0<=idx<len(self.store.runs) and idx!=self.store.active_index:
            self.store.runs[idx].role='reference'
            self.compare_box.blockSignals(True); self.compare_box.setChecked(True); self.compare_box.blockSignals(False)
            for wi in range(self.worksheets.count()):
                for w in self.worksheets.widget(wi).waveforms:w.compare=True
        elif idx<0:
            for h in self.store.runs:
                if h.role=='reference':h.role='available'
        self.store.changed.emit()

    def _compare_changed(self,state):
        enabled=bool(state)
        assigned=False
        if enabled and not any(h.role=='reference' for h in self.store.runs):
            for idx,h in enumerate(self.store.runs):
                if idx!=self.store.active_index:
                    h.role='reference'; assigned=True; break
        for i in range(self.worksheets.count()):
            for w in self.worksheets.widget(i).waveforms:w.compare=enabled
        self.reference_selector.setEnabled(enabled and self.reference_selector.count()>1)
        if hasattr(self,'reference_label'):self.reference_label.setVisible(enabled)
        self.reference_selector.setVisible(enabled)
        if assigned:
            self.store.changed.emit()
        else:
            for i in range(self.worksheets.count()):
                for w in self.worksheets.widget(i).waveforms:w.refresh()
            self._refresh_session_selectors()
    def _role_changed(self,idx,role):
        if 0<=idx<len(self.store.runs):
            if role=='reference':
                for i,h in enumerate(self.store.runs):
                    if i!=idx and h.role=='reference':h.role='overlay'
            self.store.runs[idx].role=role; self.store.changed.emit()
    def _alignment_changed(self, idx, offset):
        if 0 <= idx < len(self.store.runs):
            self.store.runs[idx].time_alignment_s = float(offset)
            self.store.changed.emit()

    def _auto_align_session(self, idx):
        if not (0 <= idx < len(self.store.runs)) or self.store.active is None:
            return
        target = self.store.runs[idx]
        if target is self.store.active:
            self.statusBar().showMessage('The Main session is already the alignment reference.', 3500)
            return
        try:
            result = estimate_time_alignment(self.store.active.run, target.run)
            target.time_alignment_s = float(result.offset_s)
            self.store.changed.emit()
            self.statusBar().showMessage(
                f'Auto-aligned {target.label}: {result.offset_s:+.4f} s using {result.canonical} (corr {result.score:.3f})', 7000
            )
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, 'Automatic alignment', str(exc))

    def _rename_session(self, idx, value):
        if 0 <= idx < len(self.store.runs):
            self.store.runs[idx].display_name = str(value).strip()
            self.store.changed.emit()

    def _remove_session(self, idx):
        if not (0 <= idx < len(self.store.runs)):
            return
        self.store.runs.pop(idx)
        if not self.store.runs:
            self.store.active_index = -1
            self.store.changed.emit(); self.store.activeChanged.emit(None)
            return
        if idx < self.store.active_index:
            self.store.active_index -= 1
        elif idx == self.store.active_index:
            self.store.active_index = min(idx, len(self.store.runs)-1)
        # Exactly one session is the main session.
        for i,h in enumerate(self.store.runs):
            if h.role == 'main': h.role = 'available'
        self.store.runs[self.store.active_index].role = 'main'
        self.store.changed.emit(); self.store.activeChanged.emit(self.store.active)

    def _save_worksheet_template(self):
        h=self.store.active
        if h is None:
            QtWidgets.QMessageBox.information(self,'Worksheet Template','Open a data log before saving a portable worksheet template.');return
        ws=self.current_sheet()
        name,ok=QtWidgets.QInputDialog.getText(self,'Save Worksheet Template','Template name:',text=self.worksheets.tabText(self.worksheets.currentIndex()))
        if not ok or not str(name).strip():return
        scope_options=worksheet_template_scope_options(h.run)
        labels=[label for _key,label in scope_options]
        label,ok=QtWidgets.QInputDialog.getItem(self,'Save Worksheet Template','Reuse scope:',labels,0,False)
        if not ok:return
        scope=next(key for key,text in scope_options if text==label)
        payload={
            'x_mode':self.xmode.currentText(),
            'display_specs':capture_portable_display_specs(h.run,ws.display_specs()),
            'dock_state':bytes(ws.saveState()).hex(),
        }
        try:
            save_worksheet_template(str(name).strip(),payload,run=h.run,scope=scope)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self,'Worksheet Template',str(exc));return
        self.statusBar().showMessage(f'Saved portable worksheet template: {str(name).strip()} ({label})',6000)

    @staticmethod
    def _template_scope_label(rec: dict) -> str:
        scope=str(rec.get('scope') or 'global')
        context=rec.get('context',{}) if isinstance(rec.get('context',{}),dict) else {}
        if scope=='vehicle_category':
            vehicle=context.get('vehicle_name') or (f"#{context.get('car_number')}" if context.get('car_number') else context.get('vehicle_id')) or 'vehicle'
            return f"Vehicle + Category — {vehicle} / {context.get('category') or '?'}"
        if scope=='category': return f"Category — {context.get('category') or '?'}"
        return 'All vehicles / categories'

    def _apply_worksheet_template_record(self, rec: dict):
        h=self.store.active
        if h is None:return
        payload=rec.get('payload',{}) if isinstance(rec.get('payload',{}),dict) else {}
        portable=payload.get('display_specs',[]) if isinstance(payload.get('display_specs',[]),list) else []
        specs,missing=resolve_portable_display_specs(h.run,portable)
        if not specs:
            QtWidgets.QMessageBox.warning(self,'Worksheet Template','This template contains no usable display definitions.');return
        desired_x=str(payload.get('x_mode') or self.xmode.currentText())
        idx=self.xmode.findText(desired_x)
        if idx>=0:self.xmode.setCurrentIndex(idx)
        ws=self.current_sheet();ws.restore_display_specs(specs)
        state=str(payload.get('dock_state') or '')
        if state:
            try:ws.restoreState(QtCore.QByteArray.fromHex(state.encode()))
            except Exception:logging.exception('Could not restore worksheet template dock state')
        ws.set_x_mode(self.xmode.currentText())
        if missing:
            preview=', '.join(missing[:6]) + ('…' if len(missing)>6 else '')
            self.statusBar().showMessage(f"Applied template {rec.get('name','')} — {len(missing)} unavailable channel reference(s): {preview}",9000)
        else:
            self.statusBar().showMessage(f"Applied worksheet template: {rec.get('name','')}",5000)
        QtCore.QTimer.singleShot(0,self._fit_current_run)

    def _apply_worksheet_template(self):
        h=self.store.active
        if h is None:
            QtWidgets.QMessageBox.information(self,'Worksheet Template','Open a data log before applying a worksheet template.');return
        rows=worksheet_templates(run=h.run,compatible_only=True)
        if not rows:
            QtWidgets.QMessageBox.information(self,'Worksheet Template','No worksheet templates are compatible with this Run yet. Save the current worksheet as a template first.');return
        labels=[f"{r.get('name','Template')}  —  {self._template_scope_label(r)}" for r in rows]
        choice,ok=QtWidgets.QInputDialog.getItem(self,'Apply Worksheet Template','Template:',labels,0,False)
        if not ok:return
        rec=rows[labels.index(choice)]
        self._apply_worksheet_template_record(rec)

    def _manage_worksheet_templates(self):
        h=self.store.active
        rows=worksheet_templates(run=h.run if h else None,compatible_only=False)
        dlg=QtWidgets.QDialog(self);dlg.setWindowTitle('Worksheet Templates');dlg.resize(900,440)
        v=QtWidgets.QVBoxLayout(dlg)
        note=QtWidgets.QLabel('Templates store Common Channel identities when available. Raw source-channel references remain exact and are never fuzzy-matched on another data log.');note.setWordWrap(True);v.addWidget(note)
        table=QtWidgets.QTableWidget(0,4);table.setHorizontalHeaderLabels(['Name','Scope','Context','Ready for active Run']);table.verticalHeader().setVisible(False);table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows);table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection);v.addWidget(table,1)
        def fill():
            nonlocal rows
            rows=worksheet_templates(run=self.store.active.run if self.store.active else None,compatible_only=False)
            table.setRowCount(len(rows))
            for r,rec in enumerate(rows):
                ctx=rec.get('context',{}) if isinstance(rec.get('context',{}),dict) else {}
                context=' / '.join(x for x in [str(ctx.get('vehicle_name') or ctx.get('car_number') or ''),str(ctx.get('category') or '')] if x) or '—'
                vals=[str(rec.get('name') or ''),str(rec.get('scope') or 'global').replace('_',' ').title(),context,'Yes' if rec.get('compatible') else 'No']
                for c,text in enumerate(vals):
                    item=QtWidgets.QTableWidgetItem(text);item.setData(QtCore.Qt.UserRole,str(rec.get('id') or ''));table.setItem(r,c,item)
            table.horizontalHeader().setSectionResizeMode(0,QtWidgets.QHeaderView.Stretch);table.horizontalHeader().setSectionResizeMode(1,QtWidgets.QHeaderView.ResizeToContents);table.horizontalHeader().setSectionResizeMode(2,QtWidgets.QHeaderView.Stretch);table.horizontalHeader().setSectionResizeMode(3,QtWidgets.QHeaderView.ResizeToContents)
        fill()
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close);apply_btn=buttons.addButton('Apply',QtWidgets.QDialogButtonBox.ActionRole);delete_btn=buttons.addButton('Delete',QtWidgets.QDialogButtonBox.DestructiveRole)
        def selected_rec():
            row=table.currentRow()
            if row<0:return None
            ident=str(table.item(row,0).data(QtCore.Qt.UserRole) or '')
            return next((x for x in rows if str(x.get('id'))==ident),None)
        def apply_selected():
            rec=selected_rec()
            if rec is None:return
            if not rec.get('compatible'):
                QtWidgets.QMessageBox.information(dlg,'Worksheet Template','That template scope does not match the active Run.');return
            self._apply_worksheet_template_record(rec);dlg.accept()
        def delete_selected():
            rec=selected_rec()
            if rec is None:return
            if QtWidgets.QMessageBox.question(dlg,'Delete Worksheet Template',f"Delete {rec.get('name','this template')}?")==QtWidgets.QMessageBox.Yes:
                delete_worksheet_template(str(rec.get('id') or ''));fill()
        apply_btn.clicked.connect(apply_selected);delete_btn.clicked.connect(delete_selected);buttons.rejected.connect(dlg.reject);v.addWidget(buttons);dlg.exec()

    def _compare_workspace_manager(self):
        if not self.store.runs:
            QtWidgets.QMessageBox.information(self,'Compare Workspace','Open at least one data log first.');return
        dlg=QtWidgets.QDialog(self);dlg.setWindowTitle('Compare Workspace Manager');dlg.resize(980,560)
        v=QtWidgets.QVBoxLayout(dlg)
        intro=QtWidgets.QLabel('Choose one Main Run and, when comparing, one Reference Run. Additional Runs may be overlays. Alignment offsets are display-only and never rewrite logger time.');intro.setWordWrap(True);v.addWidget(intro)
        top=QtWidgets.QHBoxLayout();saved=QtWidgets.QComboBox();load_btn=QtWidgets.QPushButton('Load Saved Set');top.addWidget(QtWidgets.QLabel('Named Compare Set'));top.addWidget(saved,1);top.addWidget(load_btn);v.addLayout(top)
        table=QtWidgets.QTableWidget(len(self.store.runs),5);table.setHorizontalHeaderLabels(['Session','Vendor','Role','Alignment (s)','Identity']);table.verticalHeader().setVisible(False);table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows);v.addWidget(table,1)
        role_boxes=[];align_spins=[]
        for row,h in enumerate(self.store.runs):
            table.setItem(row,0,QtWidgets.QTableWidgetItem(h.label));table.setItem(row,1,QtWidgets.QTableWidgetItem(h.run.vendor or ''))
            role=QtWidgets.QComboBox();role.addItem('Available','available');role.addItem('Main','main');role.addItem('Reference','reference');role.addItem('Overlay','overlay');idx=role.findData(h.role if h.role in ('available','main','reference','overlay') else 'available');role.setCurrentIndex(max(0,idx));table.setCellWidget(row,2,role);role_boxes.append(role)
            spin=QtWidgets.QDoubleSpinBox();spin.setRange(-10.0,10.0);spin.setDecimals(5);spin.setSingleStep(0.01);spin.setValue(float(h.time_alignment_s));spin.setSuffix(' s');table.setCellWidget(row,3,spin);align_spins.append(spin)
            table.setItem(row,4,QtWidgets.QTableWidgetItem(h.compare_key))
        table.horizontalHeader().setSectionResizeMode(0,QtWidgets.QHeaderView.Stretch);table.horizontalHeader().setSectionResizeMode(1,QtWidgets.QHeaderView.ResizeToContents);table.horizontalHeader().setSectionResizeMode(2,QtWidgets.QHeaderView.ResizeToContents);table.horizontalHeader().setSectionResizeMode(3,QtWidgets.QHeaderView.ResizeToContents);table.horizontalHeader().setSectionResizeMode(4,QtWidgets.QHeaderView.Stretch)
        status=QtWidgets.QLabel('');status.setWordWrap(True);v.addWidget(status)
        toolrow=QtWidgets.QHBoxLayout();auto_btn=QtWidgets.QPushButton('Auto-align compare Runs to Main');reset_btn=QtWidgets.QPushButton('Reset offsets');save_btn=QtWidgets.QPushButton('Save as Named Compare Set…');toolrow.addWidget(auto_btn);toolrow.addWidget(reset_btn);toolrow.addStretch(1);toolrow.addWidget(save_btn);v.addLayout(toolrow)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply|QtWidgets.QDialogButtonBox.Close);v.addWidget(buttons)

        def refresh_saved():
            saved.clear();saved.addItem('— current live workspace —','')
            for cs in self.compare_sets.sets:saved.addItem(cs.name,cs.id)
        refresh_saved()
        if self.compare_sets.active:
            i=saved.findData(self.compare_sets.active.id)
            if i>=0:saved.setCurrentIndex(i)

        def table_rows():
            rows=[]
            for i,h in enumerate(self.store.runs):
                rows.append(CompareRun(h.compare_key,h.label,role_boxes[i].currentData()!='available',float(align_spins[i].value()),str(role_boxes[i].currentData())))
            return rows

        def validate_rows(rows):
            active=[r for r in rows if r.enabled and r.role!='available']
            mains=[r for r in active if r.role=='main'];refs=[r for r in active if r.role=='reference']
            if len(mains)!=1:return False,'Choose exactly one Main Run.'
            if len(active)>1 and len(refs)!=1:return False,'A comparison workspace needs exactly one Reference Run when more than one Run is displayed.'
            return True,''

        def apply_live(close=False):
            rows=table_rows();ok,msg=validate_rows(rows)
            if not ok:QtWidgets.QMessageBox.warning(dlg,'Compare Workspace',msg);return False
            main_key=next(r.run_key for r in rows if r.enabled and r.role=='main')
            for i,(h,row) in enumerate(zip(self.store.runs,rows)):
                h.role=row.role if row.enabled else 'available';h.time_alignment_s=float(row.alignment_s)
                if h.compare_key==main_key:self.store.active_index=i
            self.store.changed.emit();self.store.activeChanged.emit(self.store.active)
            comparing=sum(1 for r in rows if r.enabled and r.role in ('reference','overlay'))>0
            self.compare_box.blockSignals(True);self.compare_box.setChecked(comparing);self.compare_box.blockSignals(False)
            self._compare_changed(1 if comparing else 0)
            self._refresh_session_selectors();status.setText('Applied live compare workspace. Source telemetry was not modified.')
            if close:dlg.accept()
            return True

        def load_saved():
            ident=str(saved.currentData() or '')
            if not ident:return
            cs=next((x for x in self.compare_sets.sets if x.id==ident),None)
            if cs is None:return
            by_key={r.run_key:r for r in cs.runs};missing=[]
            for i,h in enumerate(self.store.runs):
                rec=by_key.get(h.compare_key)
                role_boxes[i].setCurrentIndex(max(0,role_boxes[i].findData(rec.role if rec and rec.enabled else 'available')))
                align_spins[i].setValue(float(rec.alignment_s) if rec else 0.0)
            loaded_keys={h.compare_key for h in self.store.runs}
            missing=[r.label or r.run_key for r in cs.runs if r.enabled and r.run_key not in loaded_keys]
            status.setText(f"Loaded {cs.name}." + (f" {len(missing)} saved Run(s) are not currently loaded: {', '.join(missing[:4])}" if missing else ''))

        def auto_align():
            rows=table_rows();ok,msg=validate_rows(rows)
            if not ok:QtWidgets.QMessageBox.warning(dlg,'Auto Alignment',msg);return
            main_i=next(i for i,r in enumerate(rows) if r.enabled and r.role=='main');main=self.store.runs[main_i]
            results=[];failures=[]
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try:
                for i,row in enumerate(rows):
                    if i==main_i or not row.enabled or row.role not in ('reference','overlay'):continue
                    try:
                        result=estimate_time_alignment(main.run,self.store.runs[i].run);align_spins[i].setValue(float(result.offset_s));results.append(f"{self.store.runs[i].label}: {result.offset_s:+.4f}s ({result.canonical}, r={result.score:.3f})")
                    except Exception as exc:failures.append(f"{self.store.runs[i].label}: {exc}")
            finally:QtWidgets.QApplication.restoreOverrideCursor()
            status.setText('Auto alignment — ' + ('; '.join(results) if results else 'no Runs aligned') + ((' | Could not align: '+'; '.join(failures)) if failures else ''))

        def save_named():
            rows=table_rows();ok,msg=validate_rows(rows)
            if not ok:QtWidgets.QMessageBox.warning(dlg,'Compare Workspace',msg);return
            name,accepted=QtWidgets.QInputDialog.getText(dlg,'Save Compare Set','Compare Set name:',text=self.compare_sets.active.name if self.compare_sets.active else 'Compare Set 1')
            if not accepted or not str(name).strip():return
            name=str(name).strip();existing=next((x for x in self.compare_sets.sets if x.name.casefold()==name.casefold()),None);cs=existing or CompareSet(name);cs.name=name;cs.runs=[r for r in rows if r.enabled];cs.reference_run_key=next((r.run_key for r in cs.runs if r.role=='reference'),'')
            if existing is None:self.compare_sets.sets.append(cs)
            self.compare_sets.active_id=cs.id;refresh_saved();saved.setCurrentIndex(max(0,saved.findData(cs.id)));apply_live(False);status.setText(f'Saved Compare Set: {name}')

        load_btn.clicked.connect(load_saved);auto_btn.clicked.connect(auto_align);reset_btn.clicked.connect(lambda:[spin.setValue(0.0) for spin in align_spins]);save_btn.clicked.connect(save_named);buttons.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(lambda:apply_live(False));buttons.rejected.connect(dlg.reject);dlg.exec()

    def _current_compare_rows(self) -> list[CompareRun]:
        rows=[]
        for h in self.store.runs:
            if h.role not in ('main','reference','overlay'):
                continue
            rows.append(CompareRun(h.compare_key,h.label,True,float(h.time_alignment_s),h.role))
        return rows

    def _save_current_compare_set(self):
        rows=self._current_compare_rows()
        if not rows:
            QtWidgets.QMessageBox.information(self,'Compare Sets','Open at least one Run before saving a Compare Set.');return
        default=self.compare_sets.active.name if self.compare_sets.active else 'Compare Set 1'
        name,ok=QtWidgets.QInputDialog.getText(self,'Save Compare Set','Compare Set name:',text=default)
        if not ok or not str(name).strip():return
        name=str(name).strip()
        existing=next((x for x in self.compare_sets.sets if x.name.casefold()==name.casefold()),None)
        cs=existing or CompareSet(name)
        cs.name=name;cs.runs=rows
        cs.reference_run_key=next((r.run_key for r in rows if r.role=='reference'),'')
        if existing is None:self.compare_sets.sets.append(cs)
        self.compare_sets.active_id=cs.id
        self.statusBar().showMessage(f'Saved Compare Set: {name}',4000)

    def _apply_compare_set_object(self, cs: CompareSet):
        by_key={h.compare_key:(i,h) for i,h in enumerate(self.store.runs)}
        # Compare Sets only change display/session state; they never attach files
        # or infer missing server Run→Asset relationships.
        for h in self.store.runs:
            h.role='available'
        missing=[];main_index=None
        for row in cs.runs:
            match=by_key.get(row.run_key)
            if not match:
                missing.append(row.label or row.run_key);continue
            idx,h=match
            if not row.enabled:continue
            h.role=row.role if row.role in ('main','reference','overlay') else 'overlay'
            h.time_alignment_s=float(row.alignment_s)
            if h.role=='main':main_index=idx
        if main_index is None and self.store.runs:
            main_index=self.store.active_index if 0<=self.store.active_index<len(self.store.runs) else 0
            self.store.runs[main_index].role='main'
        if main_index is not None:self.store.active_index=main_index
        self.compare_sets.active_id=cs.id
        self.store.changed.emit();self.store.activeChanged.emit(self.store.active)
        for i in range(self.worksheets.count()):
            for w in self.worksheets.widget(i).waveforms:w.refresh()
        message=f'Applied Compare Set: {cs.name}'
        if missing:message+=f' — {len(missing)} saved Run(s) are not currently loaded'
        self.statusBar().showMessage(message,7000)

    def _apply_named_compare_set(self):
        if not self.compare_sets.sets:
            QtWidgets.QMessageBox.information(self,'Compare Sets','No named Compare Sets are saved in this workbook yet.');return
        names=[x.name for x in self.compare_sets.sets]
        current=0
        if self.compare_sets.active:
            try:current=names.index(self.compare_sets.active.name)
            except ValueError:pass
        name,ok=QtWidgets.QInputDialog.getItem(self,'Apply Compare Set','Compare Set:',names,current,False)
        if not ok:return
        cs=next(x for x in self.compare_sets.sets if x.name==name)
        self._apply_compare_set_object(cs)

    def _delete_named_compare_set(self):
        if not self.compare_sets.sets:return
        names=[x.name for x in self.compare_sets.sets]
        name,ok=QtWidgets.QInputDialog.getItem(self,'Delete Compare Set','Compare Set:',names,0,False)
        if not ok:return
        cs=next(x for x in self.compare_sets.sets if x.name==name)
        self.compare_sets.delete(cs.id)
        self.statusBar().showMessage(f'Deleted Compare Set: {name}',4000)

    def _step_compare_reference(self, direction:int):
        cs=self.compare_sets.active
        if cs is None:
            QtWidgets.QMessageBox.information(self,'Compare Sets','Apply or save a named Compare Set first.');return
        # Main is held fixed; stepping rotates the reference through the other
        # enabled comparison Runs.
        candidates=[r for r in cs.runs if r.enabled and r.role!='main']
        if not candidates:
            self.statusBar().showMessage('This Compare Set has no reference/overlay Runs to step through.',5000);return
        keys=[r.run_key for r in candidates]
        current=cs.reference_run_key if cs.reference_run_key in keys else keys[0]
        idx=keys.index(current);new=keys[(idx+(1 if direction>=0 else -1))%len(keys)]
        old=cs.reference_run_key
        for r in cs.runs:
            if r.run_key==old and r.role=='reference':r.role='overlay'
            if r.run_key==new:r.role='reference'
        cs.reference_run_key=new
        self._apply_compare_set_object(cs)

    def _fit_current_run(self):
        ws=self.current_sheet()
        for w in ws.waveforms:
            w._fit_run()
        self.statusBar().showMessage('Fit to drag-racing pass (Ctrl+F)',2500)

    def _fit_full_recording(self):
        ws=self.current_sheet()
        for w in ws.waveforms:
            w._fit_full()
        self.statusBar().showMessage('Fit to full logger recording (Ctrl+Shift+F)',2500)

    def _refresh_profile_selector(self):
        if not hasattr(self,'profile_selector'):
            return
        h=self.store.active
        key=str(h.run.metadata.get('analysis_profile','') or '') if h else ''
        self.profile_selector.blockSignals(True)
        try:
            idx=self.profile_selector.findData(key) if key else 0
            self.profile_selector.setCurrentIndex(idx if idx>=0 else 0)
            self.profile_selector.setEnabled(h is not None)
        finally:
            self.profile_selector.blockSignals(False)

    def _profile_selected(self,index):
        if self.store.active is None:return
        key=str(self.profile_selector.itemData(index) or '')
        if not key:
            key=infer_profile(self.store.active.run).key
        self._apply_standard_profile_layout(key)

    def _choose_standard_layout(self):
        if self.store.active is None:
            QtWidgets.QMessageBox.information(self,'Standard Class Layout','Open a telemetry Run first.');return
        labels=[p.label for p in RUN_PROFILES]
        inferred=infer_profile(self.store.active.run)
        start=next((i for i,p in enumerate(RUN_PROFILES) if p.key==inferred.key),0)
        label,ok=QtWidgets.QInputDialog.getItem(self,'Standard Class Layout','Run type / NHRA category:',labels,start,False)
        if not ok:return
        p=next(p for p in RUN_PROFILES if p.label==label)
        self._apply_standard_profile_layout(p.key)

    def _apply_standard_profile_layout(self,key):
        h=self.store.active
        if h is None:return
        try:p=run_profile(str(key))
        except Exception:p=infer_profile(h.run)
        set_run_profile(h.run,p.key)
        applied=apply_profile_rsa_defaults(h.run,p.key,overwrite=False)
        self.xmode.setCurrentText('Time from Launch')
        ws=self.current_sheet()
        ws.clear_displays()
        # Standard layouts are deliberately one useful worksheet, not a wall of
        # graphs. Class-specific quick graphs remain available when more depth is
        # needed.
        channels=resolve_profile_channels(h.run,p.key,limit=8)
        if not channels:channels=choose_default_plot_channels(h.run,limit=6)
        w=ws.add_waveform();w.channels=channels;w.layout_mode.setCurrentText('Stacked Channels');w.setToolTip(f'{p.label} — standard');w.refresh()
        # Layout application stays side-effect free beyond display/profile seed
        # choices. Standard reports are generated explicitly from Run Workspace.
        self.store.changed.emit()
        self._refresh_profile_selector()
        QtCore.QTimer.singleShot(0,self._fit_current_run)
        seed_note=f'; {len(applied)} RSA class defaults seeded' if applied else ''
        self.statusBar().showMessage(f'Applied {p.label} standard layout — {len(channels)} core channel(s){seed_note}',7000)

    def _pro_stock_shift_report(self):
        h=self.store.active
        if h is None:
            QtWidgets.QMessageBox.information(self,'Pro Stock Shift Report','Open a telemetry Run first.');return
        try:
            report=attach_shift_report(h.run,profile='pro_stock')
            if h.catalog_run_id:
                self.catalog.save_run_report(h.catalog_run_id,report,source_asset_id=h.catalog_asset_id or None,label='Pro Stock Shift Report')
                if hasattr(self,'run_workspace'):self.run_workspace.set_run(h.catalog_run_id)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self,'Pro Stock Shift Report',str(exc));return
        reference=next((x for x in self.store.runs if x.role=='reference' and x is not h),None)
        comparisons=[]
        if reference is not None:
            try:comparisons=compare_shift_reports(report,build_shift_report(reference.run,profile='pro_stock'))
            except Exception:comparisons=[]
        by_shift={int(r.get('shift',0)):r for r in comparisons}
        events=list(report.get('events',[]) or [])
        dlg=QtWidgets.QDialog(self);dlg.setWindowTitle(f'Pro Stock Shift Report — {h.label}');dlg.resize(1120,480)
        v=QtWidgets.QVBoxLayout(dlg)
        info=QtWidgets.QLabel('Derived report stored with the workbook metadata. Shift RPM is the pre-drop engine-RPM peak; Ref deltas use the selected Compare reference Run.')
        info.setWordWrap(True);v.addWidget(info)
        table=QtWidgets.QTableWidget(len(events),10);table.setHorizontalHeaderLabels(['Shift','Time (s)','Shift RPM','Post RPM','RPM Drop','DS RPM','Clutch RPM','Δ RPM vs Ref','Δ Time vs Ref','Status']);table.verticalHeader().setVisible(False)
        for row,event in enumerate(events):
            comp=by_shift.get(int(event.get('shift',row+1)),{})
            values=[event.get('shift'),event.get('time_s'),event.get('engine_rpm'),event.get('post_shift_rpm'),event.get('rpm_drop'),event.get('driveshaft_rpm'),event.get('clutch_rpm'),comp.get('delta_rpm'),comp.get('delta_time_s'),'CHECK' if comp.get('alert') else '']
            for col,value in enumerate(values):
                if isinstance(value,(float,np.floating)) and np.isfinite(value): text=f'{float(value):.1f}' if col not in (1,8) else f'{float(value):.4f}'
                elif value is None:text='—'
                else:text=str(value)
                item=QtWidgets.QTableWidgetItem(text)
                if col==9 and text=='CHECK':item.setForeground(QtGui.QColor('#ffb454'))
                table.setItem(row,col,item)
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents);table.horizontalHeader().setStretchLastSection(True);v.addWidget(table,1)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        export=buttons.addButton('Export CSV…',QtWidgets.QDialogButtonBox.ActionRole)
        export.clicked.connect(lambda:self._export_shift_report_csv(report,comparisons,h.label))
        buttons.rejected.connect(dlg.reject);buttons.clicked.connect(lambda b: dlg.reject() if b==buttons.button(QtWidgets.QDialogButtonBox.Close) else None);v.addWidget(buttons)
        self.store.changed.emit();dlg.exec()

    def _export_shift_report_csv(self,report,comparisons,label):
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Export Pro Stock shift report',f'{label}_shift_report.csv','CSV (*.csv)')
        if not path:return
        rows=[];comp={int(x.get('shift',0)):x for x in comparisons}
        for event in report.get('events',[]) or []:
            row=dict(event);row.update({f'reference_{k}':v for k,v in comp.get(int(event.get('shift',0)),{}).items() if k!='shift'});rows.append(row)
        pd.DataFrame(rows).to_csv(path,index=False);self.statusBar().showMessage(f'Exported shift report: {path}',5000)

    def _show_keyboard_shortcuts(self):
        text=(
            '<b>Waveform / McLaren-familiar workflow</b><br>'
            'Ctrl+F — fit the drag-racing pass (launch → finish with margin)<br>'
            'Ctrl+Shift+F — fit the entire logger recording<br>'
            'Left / Right — step live cursor one sample<br>'
            'Shift+Left / Shift+Right — move cursor faster (ATLAS); Ctrl+Left/Right also retained<br>'
            'Ctrl+[ / Ctrl+] — previous / next event (ATLAS); Alt+Left/Right also supported<br>'
            'Click / left-drag waveform — position or scrub the live cursor &nbsp;&nbsp; Middle-drag — pan X<br>'
            'Home / End — cursor to recording boundary &nbsp;&nbsp; + / - — zoom X around cursor<br>'
            'Ctrl+Z — previous zoom &nbsp;&nbsp; Ctrl+Alt+Z — fit drag run<br>'
            'R — add/remove red reference cursor at current position &nbsp;&nbsp; M/X/N/E/Q — toggle Min/Max/Mean/Delta/Std statistics between Ref and Cursor<br>'
            'K — cycle Time/Distance axis &nbsp;&nbsp; D — display properties &nbsp;&nbsp; P/Insert — parameter search<br>'
            'Shift+click waveform — place reference cursor directly &nbsp;&nbsp; Ctrl+click — place cursor B<br><br>'
            '<b>Application</b><br>'
            'Ctrl+O — open log &nbsp;&nbsp; Ctrl+S — save workbook &nbsp;&nbsp; Ctrl+K — command palette<br>'
            'Ctrl+P / Ctrl+Q — channel search / Quick Access &nbsp;&nbsp; Ctrl+M — Math Channel Builder &nbsp;&nbsp; Ctrl+Alt+M — Common Channel Mapping<br>Ctrl+Alt+D — Data Log Setup / Readiness &nbsp;&nbsp; Ctrl+Alt+T — apply Worksheet Template &nbsp;&nbsp; Ctrl+Shift+R — Compare Workspace Manager<br>Ctrl+I — inference center<br>'
            'Ctrl+Shift+P — Pro Stock shift report &nbsp;&nbsp; Ctrl+Shift+R — Ref-to-Cursor statistics display<br>'
            'Ctrl+Alt+Left / Right — step Compare reference Run &nbsp;&nbsp; Ctrl+Enter — focus/restore analysis workspace<br><br>'
            'Additional McLaren-style bindings will be added deliberately as their exact behavior is verified; the application will not silently assign familiar keys to different actions.'
        )
        QtWidgets.QMessageBox.information(self,'Keyboard Shortcuts',text)

    def _show_integration_status(self):
        status=self.auth.status()
        text=(
            '<b>NHRA Tech Services integration — existing website contract</b><br><br>'
            '✓ Uses the same nhratechservices.com account; no second user database.<br>'
            '✓ Login is sent directly to the existing HTTPS login API; the password is never stored.<br>'
            '✓ The returned seven-day Bearer token is stored only in the OS credential vault.<br>'
            '✓ Server capabilities are refreshed from the protected capabilities endpoint.<br>'
            '✓ Tech Master Events and Event Entries can be mirrored read-only.<br>'
            '✓ Official normalized parity timing Runs can be mirrored read-only by race_lookup.<br>'
            f"✓ Current account status: {'signed in' if status.signed_in else 'signed out'}.<br><br>"
            '<b>Still intentionally fail-closed:</b><br>'
            '• parity.php does not expose its event_entry_id bridge, so Velocity does not guess Entry→Run ownership;<br>'
            '• the site does not yet expose a permanent Run→Asset manifest/download API; Velocity therefore supports an explicit local working attachment to a selected authoritative Run, stored in the local object store and never uploaded automatically;<br>'
            '• Velocity performs no Tech Services data writes through this integration.<br><br>'
            'In other words: we can share identity, event/entry metadata and official timing today without changing the website repository.'
        )
        QtWidgets.QMessageBox.information(self,'Tech Services Integration Status',text)

    def _refresh_channel_explorer(self):
        run=self.store.active.run if self.store.active else None
        scope=str(self.channel_scope.currentData() or 'essentials') if hasattr(self,'channel_scope') else 'essentials'
        text=self.channel_search.text() if hasattr(self,'channel_search') else ''
        self.channels.set_run(run,text,scope)

    def _focus_parameter_search(self):
        self.channel_search.setFocus(QtCore.Qt.ShortcutFocusReason)
        self.channel_search.selectAll()

    def _channel_add(self,c): self.current_sheet().add_channel(c)

    def _channel_remove(self,c):
        ws=self.current_sheet()
        if ws.waveforms:
            ws.waveforms[0].remove_channel(str(c))


    def _quick_graph_selected(self, index):
        if index <= 0:
            return
        name = self.quick_graph.itemText(index)
        self._apply_quick_graph(name)
        self.quick_graph.setCurrentIndex(0)

    def _apply_quick_graph(self, name):
        handle = self.store.active
        if not handle or name not in QUICK_GRAPH_PRESETS:
            return
        channels = []
        for canonical in QUICK_GRAPH_PRESETS[name]:
            src = _source_for_canonical(handle.run, canonical)
            if src and src not in channels:
                channels.append(src)
        if not channels:
            QtWidgets.QMessageBox.information(self, 'Quick Graph', f'No mapped channels for {name}. Assign Common Channels in Data → Common Channel Mapping first.')
            return
        ws = self.current_sheet()
        if not ws.waveforms:
            ws.add_waveform()
        ws.waveforms[0].channels = channels
        ws.waveforms[0].refresh()
        self.statusBar().showMessage(f'Quick Graph: {name} — {len(channels)} channels', 4000)

    def _set_channel_favorite(self, channel, enabled):
        h=self.store.active
        if not h:return
        pref=get_channel_preference(h.run,channel)
        if enabled:
            pref['favorite']=True
            set_channel_preference(h.run,channel,pref)
        else:
            pref.pop('favorite',None)
            if pref:set_channel_preference(h.run,channel,pref)
            else:clear_channel_preference(h.run,channel)
        self._refresh_channel_explorer()
        self.statusBar().showMessage(('Added to' if enabled else 'Removed from')+f' Favorites: {channel}',3000)

    def _common_channel_scope_combo(self, run, *, current_scope: str = ''):
        combo=QtWidgets.QComboBox()
        combo.addItem('This data log only — do not create/update a reusable profile','')
        for scope,label in common_channel_profile_scope_options(run):
            combo.addItem(label,scope)
        if current_scope:
            idx=combo.findData(current_scope)
            if idx>=0:combo.setCurrentIndex(idx)
        return combo

    def _persist_exact_channel_settings(self, handle):
        """Persist mapping/unit choices for this exact catalog data-log asset.

        Reusable mapping profiles are only defaults for a matching context.  An
        exact data-log choice is higher authority and must survive reopen even
        when it intentionally disagrees with the driver/category profile.
        """
        if handle is None or not str(handle.catalog_asset_id or '').strip():
            return
        self.catalog.update_telemetry_session_settings(
            str(handle.catalog_asset_id),
            {
                'common_channel_overrides':dict(handle.channel_overrides),
                'unit_overrides':dict(handle.unit_overrides),
            },
        )

    def _show_about(self):
        dlg=QtWidgets.QDialog(self); dlg.setWindowTitle(f'About {PRODUCT_NAME}'); dlg.resize(560,430)
        lay=QtWidgets.QVBoxLayout(dlg); lay.setContentsMargins(28,24,28,24); lay.setSpacing(14)
        icon_label=QtWidgets.QLabel(); icon_label.setAlignment(QtCore.Qt.AlignCenter)
        pix=QtGui.QPixmap(str(brand_asset('nhra-velocity-256.png')))
        if not pix.isNull(): icon_label.setPixmap(pix.scaled(112,112,QtCore.Qt.KeepAspectRatio,QtCore.Qt.SmoothTransformation))
        lay.addWidget(icon_label)
        title=QtWidgets.QLabel(PRODUCT_NAME); title.setAlignment(QtCore.Qt.AlignCenter)
        f=title.font(); f.setPointSize(max(f.pointSize()+8,18)); f.setBold(True); title.setFont(f); lay.addWidget(title)
        tagline=QtWidgets.QLabel(PRODUCT_TAGLINE); tagline.setAlignment(QtCore.Qt.AlignCenter); tagline.setWordWrap(True); lay.addWidget(tagline)
        version=QtWidgets.QLabel(f'Version {PRODUCT_VERSION}'); version.setAlignment(QtCore.Qt.AlignCenter); lay.addWidget(version)
        body=QtWidgets.QLabel(
            'NHRA technical data analysis, multi-vendor logger review, vehicle-performance reconstruction and simulation.\n\n'
            'Authoritative Run identity comes from NHRA Tech Services; local data logs and engineering definitions remain explicit and auditable.'
        ); body.setWordWrap(True); body.setAlignment(QtCore.Qt.AlignCenter); lay.addWidget(body)
        lay.addStretch(1)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close); buttons.rejected.connect(dlg.reject); buttons.accepted.connect(dlg.accept); lay.addWidget(buttons)
        dlg.exec()

    def _show_data_log_readiness(self):
        h=self.store.active
        if not h:
            rid=self.run_browser.selected_run_id() if hasattr(self,'run_browser') else ''
            record=self.catalog.get_run(rid) if rid else None
            if record:
                QtWidgets.QMessageBox.information(
                    self,'Data Log Setup / Readiness',
                    f"{record.get('driver_name') or 'Selected Run'} — {record.get('category') or ''}\n\n"
                    'The authoritative Run is selected, but no local data log is currently open. Attach or open a data log to review configuration readiness.'
                )
            else:
                QtWidgets.QMessageBox.information(self,'Data Log Setup / Readiness','Open a data log or select an authoritative Tech Services Run first.')
            return
        run=h.run
        originals=run.metadata.get('original_channel_map',{}) if isinstance(run.metadata.get('original_channel_map'),dict) else {}
        mapped=[]
        for spec in common_channel_specs():
            src=str(originals.get(spec.key) or '')
            if src: mapped.append((spec.label,src))
        core_keys=['engine_rpm','driveshaft_rpm','speed_mph','throttle_pct','gear','longitudinal_g']
        core=[]
        for key in core_keys:
            src=str(originals.get(key) or '')
            core.append((common_channel_label(key),src or 'Not mapped'))
        manual_zero=launch_time_override(run)
        warnings=[str(x) for x in (run.metadata.get('data_warnings') or [])]
        source_format=str(run.metadata.get('source_format') or run.vendor or 'Unknown')
        racepak_line='Not applicable'
        if self._racepak_is_ddf_handle(h):
            exact={}
            if h.catalog_asset_id:
                session=self.catalog.get_telemetry_session(str(h.catalog_asset_id)) or {}
                exact=racepak_exact_config_binding(session.get('settings') or {})
            profile=matching_racepak_config_profile(run)
            if exact:
                cfg=exact.get('config') if isinstance(exact.get('config'),dict) else exact
                racepak_line='Exact data-log config — '+str((cfg or {}).get('filename') or 'managed config')
            elif profile:
                cfg=profile.get('config') or {}
                racepak_line='Reusable context profile — '+str(cfg.get('filename') or 'managed config')
            elif run.metadata.get('ddf_config_path'):
                racepak_line='Active config — '+Path(str(run.metadata.get('ddf_config_path'))).name
            else:
                racepak_line='Raw DDF channel ids only — config profile recommended'
        timing_present=any(getattr(run.timing,name,None) not in (None,'') for name in ('sixty_ft_s','three_thirty_ft_s','eighth_mile_s','quarter_mile_s'))
        weather_present=bool(run.metadata.get('environment_provenance'))
        rows=''.join(f'<tr><td>{html.escape(label)}</td><td>{html.escape(src)}</td></tr>' for label,src in core)
        warn_html='<br>'.join('• '+html.escape(w) for w in warnings[:8]) if warnings else 'None'
        run_text=('Yes — '+html.escape(h.catalog_run_id)) if h.catalog_run_id else 'No — scratch/local session'
        html_text=(
            f'<h2>{html.escape(h.label)}</h2>'
            '<table cellspacing="6">'
            f'<tr><td><b>Source</b></td><td>{html.escape(source_format)}</td></tr>'
            f'<tr><td><b>Authoritative Run</b></td><td>{run_text}</td></tr>'
            f'<tr><td><b>Managed attachment</b></td><td>{"Yes" if h.catalog_asset_id else "No"}</td></tr>'
            f'<tr><td><b>RacePak definition</b></td><td>{html.escape(racepak_line)}</td></tr>'
            f'<tr><td><b>Common Channels</b></td><td>{len(mapped)} mapped</td></tr>'
            f'<tr><td><b>Math channels</b></td><td>{len(run.metadata.get("math_channels") or [])}</td></tr>'
            f'<tr><td><b>Launch zero</b></td><td>{("Manual @ %.6f s" % manual_zero) if manual_zero is not None else "Automatic detection"}</td></tr>'
            f'<tr><td><b>Official timing</b></td><td>{"Present" if timing_present else "Not present"}</td></tr>'
            f'<tr><td><b>Weather</b></td><td>{"Present" if weather_present else "Not present"}</td></tr>'
            '</table>'
            f'<h3>Core drag-racing Common Channels</h3><table cellspacing="6">{rows}</table>'
            f'<h3>Data warnings</h3><p>{warn_html}</p>'
        )
        dlg=QtWidgets.QDialog(self); dlg.setWindowTitle('Data Log Setup / Readiness'); dlg.resize(760,620)
        lay=QtWidgets.QVBoxLayout(dlg); view=QtWidgets.QTextBrowser(); view.setHtml(html_text); lay.addWidget(view,1)
        row=QtWidgets.QHBoxLayout(); common=QtWidgets.QPushButton('Common Channels…'); math_btn=QtWidgets.QPushButton('Math Channels…'); race=QtWidgets.QPushButton('RacePak Config…'); close=QtWidgets.QPushButton('Close')
        row.addWidget(common); row.addWidget(math_btn)
        if self._racepak_is_ddf_handle(h): row.addWidget(race)
        row.addStretch(1); row.addWidget(close); lay.addLayout(row)
        common.clicked.connect(lambda: (dlg.accept(), self._common_channel_mapping_dialog()))
        math_btn.clicked.connect(lambda: (dlg.accept(), self._new_math_channel()))
        race.clicked.connect(lambda: (dlg.accept(), self._racepak_config_dialog()))
        close.clicked.connect(dlg.accept); dlg.exec()

    def _racepak_profile_manager(self):
        dlg=QtWidgets.QDialog(self); dlg.setWindowTitle('RacePak Configuration Profiles'); dlg.resize(980,500)
        lay=QtWidgets.QVBoxLayout(dlg)
        note=QtWidgets.QLabel('Reusable RacePak definitions are deliberately narrow. Exact per-data-log configuration remains higher authority than these defaults.'); note.setWordWrap(True); lay.addWidget(note)
        table=QtWidgets.QTableWidget(0,7); table.setHorizontalHeaderLabels(['Scope','Driver / Vehicle','Category','Config','Channels','Updated','Status']); table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows); table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection); table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers); lay.addWidget(table,1)
        records=[]
        def refresh():
            nonlocal records
            records=list_racepak_config_profiles(); table.setRowCount(len(records))
            for row_index,rec in enumerate(records):
                ctx=rec.get('context') or {}; cfg=rec.get('config') or {}; scope=str(rec.get('scope') or '')
                who=(ctx.get('driver_name') or ctx.get('driver_id')) if scope=='driver_category' else (ctx.get('vehicle_name') or ctx.get('car_number') or ctx.get('vehicle_id'))
                vals=[scope.replace('_',' + ').title(),str(who or ''),str(ctx.get('category') or ''),str(cfg.get('filename') or ''),str(cfg.get('connect4_definition_count') or ''),str(rec.get('updated_at') or ''),('Ready' if rec.get('valid') else 'Missing / changed config')]
                for col,val in enumerate(vals):
                    item=QtWidgets.QTableWidgetItem(val); item.setData(QtCore.Qt.UserRole,rec.get('profile_key') if col==0 else None); table.setItem(row_index,col,item)
                if table.item(row_index,3): table.item(row_index,3).setToolTip(str(cfg.get('managed_path') or '')+'\nSHA-256: '+str(cfg.get('sha256') or ''))
            table.resizeColumnsToContents(); table.horizontalHeader().setStretchLastSection(True)
        refresh()
        row=QtWidgets.QHBoxLayout(); add=QtWidgets.QPushButton('Add / Replace for Current Run…'); remove=QtWidgets.QPushButton('Delete Selected'); refresh_btn=QtWidgets.QPushButton('Refresh'); close=QtWidgets.QPushButton('Close'); row.addWidget(add); row.addWidget(remove); row.addWidget(refresh_btn); row.addStretch(1); row.addWidget(close); lay.addLayout(row)
        def add_current():
            dlg.hide(); self._racepak_config_dialog(); dlg.show(); refresh()
        def remove_selected():
            r=table.currentRow()
            if r<0 or r>=len(records): return
            rec=records[r]; cfg=rec.get('config') or {}
            answer=QtWidgets.QMessageBox.question(dlg,'Delete RacePak profile',f"Delete reusable profile for {cfg.get('filename') or 'this configuration'}?\n\nExact configurations already pinned to historical DDFs are not removed.")
            if answer==QtWidgets.QMessageBox.Yes:
                delete_racepak_config_profile_key(str(rec.get('profile_key') or '')); refresh()
        add.clicked.connect(add_current); remove.clicked.connect(remove_selected); refresh_btn.clicked.connect(refresh); close.clicked.connect(dlg.accept); dlg.exec()

    @staticmethod
    def _racepak_is_ddf_handle(handle):
        if handle is None:
            return False
        return str(handle.run.metadata.get('source_format') or '').lower().startswith('racepak raw ddf') or Path(str(handle.path or '')).suffix.lower()=='.ddf'

    @staticmethod
    def _racepak_translate_overrides_by_channel_id(old_run, new_run, overrides):
        """Translate exact Common Channel overrides across a config rename.

        This is intentionally not semantic guessing.  It only follows the exact
        RacePak _CONNECT4_COMMAND/channel id already embedded in both decoded
        channel objects.  If an id is not present on both sides, the override is
        left unchanged and normal validation can reject it.
        """
        old_id={}
        for name,ch in getattr(old_run,'native_channels',{}).items():
            cid=getattr(ch,'metadata',{}).get('racepak_connect4_command') if getattr(ch,'metadata',None) else None
            if cid is not None: old_id[str(name)]=int(cid)
        new_name={}
        for name,ch in getattr(new_run,'native_channels',{}).items():
            cid=getattr(ch,'metadata',{}).get('racepak_connect4_command') if getattr(ch,'metadata',None) else None
            if cid is not None: new_name[int(cid)]=str(name)
        out={}
        for role,source in dict(overrides or {}).items():
            source=str(source or '')
            if not source:
                out[role]='';continue
            if source in new_run.data.columns:
                out[role]=source;continue
            cid=old_id.get(source)
            out[role]=new_name.get(cid,source) if cid is not None else source
        return out

    def _racepak_config_context(self):
        h=self.store.active
        if self._racepak_is_ddf_handle(h):
            record=self.catalog.get_run(str(h.catalog_run_id)) if str(h.catalog_run_id or '') else None
            return h,record
        rid=self.run_browser.selected_run_id() if hasattr(self,'run_browser') else ''
        record=self.catalog.get_run(rid) if rid else None
        return None,record

    def _reload_racepak_ddf_handle(self, handle, config_path: str):
        old_run=handle.run
        run=load_telemetry(handle.path,racepak_config_path=config_path)
        if handle.catalog_run_id:
            apply_catalog_run_authority(self.catalog,str(handle.catalog_run_id),run)
        profile_overrides=learned_common_channel_overrides(run)
        exact=self._racepak_translate_overrides_by_channel_id(old_run,run,handle.channel_overrides)
        # Profile defaults are below exact-data-log authority.
        combined={**profile_overrides,**exact}
        invalid=[]
        for role,source in list(combined.items()):
            if source and source not in run.data.columns:
                invalid.append(f'{role} → {source}')
                combined.pop(role,None)
        if combined or handle.unit_overrides:
            run=apply_channel_overrides(run,combined,handle.unit_overrides)
        handle.run=run
        handle.channel_overrides=combined
        self._persist_exact_channel_settings(handle)
        if handle.catalog_asset_id:
            run.metadata['catalog_asset_id']=handle.catalog_asset_id
            run.metadata['catalog_telemetry_session_id']=handle.catalog_session_id
            self._restore_catalog_launch_zero(handle)
        self.store.changed.emit();self.store.activeChanged.emit(handle)
        if invalid:
            QtWidgets.QMessageBox.information(
                self,'RacePak DDF Configuration',
                'The config was applied, but these old Common Channel mappings could not be carried forward because the exact RacePak channel id was not present in the new config:\n\n'+'\n'.join(invalid)+
                '\n\nReview Data → Common Channel Mapping before using portable analysis.'
            )

    def _racepak_config_dialog(self):
        handle,record=self._racepak_config_context()
        if handle is None and record is None:
            QtWidgets.QMessageBox.information(
                self,'RacePak DDF Configuration',
                'Open a RacePak DDF or select an authoritative Tech Services Run first.'
            );return
        if handle is not None and not self._racepak_is_ddf_handle(handle):
            QtWidgets.QMessageBox.information(self,'RacePak DDF Configuration','The active data log is not a RacePak DDF.');return

        settings={}
        exact={}
        if handle is not None and handle.catalog_asset_id:
            session=self.catalog.get_telemetry_session(str(handle.catalog_asset_id)) or {}
            settings=session.get('settings') or {}
            exact=racepak_exact_config_binding(settings)
        context_obj=record if record is not None else handle.run
        profile=matching_racepak_config_profile(context_obj)
        profile_path=racepak_config_path_from_profile(profile) if profile else ''
        exact_cfg=exact.get('config') if isinstance(exact.get('config'),dict) else exact
        exact_path=str(exact_cfg.get('managed_path') or '') if isinstance(exact_cfg,dict) else ''
        active_path=str(handle.run.metadata.get('ddf_config_path') or '') if handle is not None else ''
        initial=exact_path or profile_path or active_path

        dlg=QtWidgets.QDialog(self);dlg.setWindowTitle('RacePak DDF Configuration');dlg.resize(800,430)
        lay=QtWidgets.QVBoxLayout(dlg)
        if record is not None:
            identity=' · '.join(x for x in (str(record.get('driver_name') or ''),str(record.get('category') or ''),str(record.get('car_number') or '')) if x)
            lay.addWidget(QtWidgets.QLabel(f'<b>Context:</b> {html.escape(identity or "Selected Tech Services Run")}'))
        intro=QtWidgets.QLabel(
            'A RacePak DDF contains the samples and stable channel IDs. The matching RCG/RPK configuration supplies channel names and units. '
            'Velocity never treats a RacePak config as vendor-global. An exact data-log binding wins; otherwise an explicitly saved Driver/Category or Vehicle/Category profile is used.'
        );intro.setWordWrap(True);lay.addWidget(intro)
        form=QtWidgets.QFormLayout();lay.addLayout(form)
        current_exact='None'
        if exact_path: current_exact=f"{Path(exact_path).name}  [{str(exact_cfg.get('sha256') or '')[:10]}]"
        current_profile='None'
        if profile_path:
            cfg=profile.get('config',{}) if isinstance(profile,dict) else {}
            current_profile=f"{cfg.get('filename') or Path(profile_path).name} — {str(profile.get('scope') or '').replace('_',' + ')}"
        form.addRow('Exact data-log config',QtWidgets.QLabel(current_exact))
        form.addRow('Matching reusable profile',QtWidgets.QLabel(current_profile))
        file_row=QtWidgets.QHBoxLayout();path_edit=QtWidgets.QLineEdit(initial);browse=QtWidgets.QPushButton('Browse…');file_row.addWidget(path_edit,1);file_row.addWidget(browse);form.addRow('Configuration file',file_row)
        scope=QtWidgets.QComboBox()
        if handle is not None and handle.catalog_asset_id:
            scope.addItem('This data log only — pin exact configuration','exact')
        for key,label in racepak_config_profile_scope_options(context_obj):scope.addItem(label,key)
        if scope.count()==0:
            scope.addItem('This data log only','exact')
        form.addRow('Save / apply as',scope)
        status=QtWidgets.QLabel('Choose an .rcg file or a prior .rpk containing the same DataLink channel definitions.');status.setWordWrap(True);form.addRow('Validation',status)

        def choose_file():
            start=path_edit.text().strip() or ''
            chosen,_=QtWidgets.QFileDialog.getOpenFileName(dlg,'Choose RacePak DDF configuration',start,'RacePak configuration (*.rcg *.RCG *.rpk *.RPK);;All files (*.*)')
            if chosen:path_edit.setText(chosen);validate_file()
        browse.clicked.connect(choose_file)

        def validate_file():
            config=Path(path_edit.text().strip())
            if not config.is_file():status.setText('Configuration file not found.');return False
            try:
                # Profile save performs general RacePak config validation.  When
                # a DDF is active, additionally prove the channel ids/sample-rate
                # signature match this exact recording before allowing Apply.
                if handle is not None:
                    structure=parse_ddf_structure(handle.path)
                    binding=bind_ddf_config(structure,config.read_bytes())
                    if binding.duplicate_config_ids:
                        raise ValueError('Duplicate _CONNECT4_COMMAND ids: '+', '.join(map(str,binding.duplicate_config_ids[:12])))
                    if binding.rate_mismatches:
                        raise ValueError('Sample-rate mismatch: '+'; '.join(binding.rate_mismatches[:8]))
                    matched=len(structure.recorded_descriptors)-len(binding.unmatched_ddf_ids)
                    status.setText(f'Valid for this DDF: {matched}/{len(structure.recorded_descriptors)} recorded channel IDs matched; {len(binding.unmatched_ddf_ids)} unmatched.')
                else:
                    # Do not save yet, but inspect through the same strict parser
                    # by creating a managed record only on Apply.
                    from runlab.racepak_config_profiles import inspect_racepak_config
                    cfg=inspect_racepak_config(config)
                    status.setText(f'Valid RacePak configuration: {cfg.connect4_definition_count} DDF-identifiable channels.')
                return True
            except Exception as exc:
                status.setText(f'Not valid: {exc}');return False
        path_edit.editingFinished.connect(validate_file)

        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('Apply')
        buttons.accepted.connect(dlg.accept);buttons.rejected.connect(dlg.reject);lay.addWidget(buttons)
        if initial:validate_file()
        if dlg.exec()!=QtWidgets.QDialog.Accepted:return
        config=Path(path_edit.text().strip())
        if not validate_file():
            QtWidgets.QMessageBox.warning(self,'RacePak DDF Configuration','The selected configuration did not validate. Nothing was changed.');return
        try:
            scope_key=str(scope.currentData() or '')
            managed_path=''
            source='explicit_exact'
            if scope_key in {'driver_category','vehicle_category'}:
                saved=save_racepak_config_profile(context_obj,config,scope=scope_key)
                managed_path=racepak_config_path_from_profile(saved)
                source='context_profile'
            else:
                rec=racepak_exact_config_record(config,source='explicit_exact')
                cfg=rec.get('config',{})
                managed_path=str(cfg.get('managed_path') or '')
            if not managed_path:
                raise ValueError('Velocity could not preserve a managed copy of the configuration.')
            # If an exact DDF is in front of us, pin the actual config used even
            # when it also came from a reusable context profile. Historical logs
            # must not silently change when that profile is edited later.
            if handle is not None and handle.catalog_asset_id:
                pin_source=saved.get('config') if scope_key in {'driver_category','vehicle_category'} and isinstance(saved,dict) else managed_path
                pin=racepak_exact_config_record(pin_source,source=source)
                self.catalog.update_telemetry_session_settings(str(handle.catalog_asset_id),{'racepak_ddf_config':pin})
                self._reload_racepak_ddf_handle(handle,managed_path)
            msg='RacePak DDF configuration applied.'
            if scope_key in {'driver_category','vehicle_category'}:
                msg+=f' Future matching DDFs will use this {scope.currentText()} profile and each attached log will be pinned to the exact config it used.'
            else:
                msg+=' This configuration is pinned only to the current data log.'
            self.statusBar().showMessage(msg,9000)
        except Exception as exc:
            logging.exception('RacePak DDF configuration failed')
            QtWidgets.QMessageBox.critical(self,'RacePak DDF Configuration',str(exc))

    def _assign_common_channel(self, channel):
        h=self.store.active
        if not h:return
        run=h.run
        original=run.metadata.get('original_channel_map',{}) if isinstance(run.metadata.get('original_channel_map',{}),dict) else {}
        current=next((role for role,source in original.items() if str(source)==str(channel)), '')
        profile=matching_common_channel_profile(run)
        profile_scope=str(profile.get('scope') or '') if profile else ''
        dlg=QtWidgets.QDialog(self);dlg.setWindowTitle(f'Assign Common Channel — {channel}');dlg.resize(620,300)
        form=QtWidgets.QFormLayout(dlg)
        form.addRow('Source channel',QtWidgets.QLabel(str(channel)))
        role=QtWidgets.QComboBox();role.addItem('(not assigned)','')
        for spec in common_channel_specs():
            suffix=f' [{spec.unit_label}]' if spec.unit_label else ''
            role.addItem(f'{spec.label}{suffix}',spec.key)
        idx=role.findData(current);role.setCurrentIndex(idx if idx>=0 else 0)
        form.addRow('Common channel',role)
        scope=self._common_channel_scope_combo(run,current_scope=profile_scope)
        form.addRow('Reusable profile',scope)
        note=QtWidgets.QLabel(
            'Mapping authority is intentionally narrow: this exact data log wins first; an explicitly saved '
            'Driver/Category or Vehicle/Category profile is only a default for matching future logs; importer '
            'auto-detection is last. Velocity does not create vendor-global RPM/speed rules.'
        )
        note.setWordWrap(True);form.addRow(note)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel);buttons.accepted.connect(dlg.accept);buttons.rejected.connect(dlg.reject);form.addRow(buttons)
        if dlg.exec()!=QtWidgets.QDialog.Accepted:return
        chosen=str(role.currentData() or '')
        scope_key=str(scope.currentData() or '')
        try:
            if chosen:
                target=next((spec.unit for spec in common_channel_specs() if spec.key==chosen),'')
                source_unit=normalize_unit(run.units.get(channel,''))
                if target and source_unit and not compatible(source_unit,target):
                    raise ValueError(f'{channel} is {display_label(source_unit) or source_unit}; {common_channel_label(chosen)} expects {display_label(target) or target}.')
            if current and current!=chosen:
                h.channel_overrides[current]=''
            if chosen:
                h.channel_overrides[chosen]=str(channel)
            elif current:
                h.channel_overrides[current]=''
            h.run=apply_channel_overrides(h.run,h.channel_overrides,h.unit_overrides)
            if h.run.metadata.get('math_channels'):reapply_math_channels(h.run,list(h.run.metadata.get('math_channels',[])))
            self._persist_exact_channel_settings(h)
            if scope_key and chosen:
                # Merge the single edited assignment into the explicitly chosen
                # narrow profile.  Choosing "This data log only" never deletes
                # or silently rewrites an existing reusable profile.
                remember_common_channel_mapping(h.run,str(channel),chosen,scope=scope_key)
            self.store.changed.emit();self.store.activeChanged.emit(h)
            suffix=f' · saved to {scope.currentText()}' if scope_key and chosen else ' · this data log only'
            self.statusBar().showMessage(f'{channel} → {common_channel_label(chosen) if chosen else "unassigned"}{suffix}',6000)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self,'Common Channel Mapping',str(exc))

    def _common_channel_mapping_dialog(self):
        h=self.store.active
        if not h:
            QtWidgets.QMessageBox.information(self,'Common Channel Mapping','Open a data log first.');return
        run=h.run
        dlg=QtWidgets.QDialog(self);dlg.setWindowTitle(f'Common Channel Mapping — {h.label}');dlg.resize(980,720)
        lay=QtWidgets.QVBoxLayout(dlg)
        intro=QtWidgets.QLabel(
            'Map this exact data log to Velocity common engineering channels. Exact data-log assignments are stored '
            'with this attached asset and always win. If you explicitly save a reusable profile, it is scoped to the '
            'matching driver/category or vehicle/category plus logger vendor — never globally by channel name.'
        )
        intro.setWordWrap(True);lay.addWidget(intro)
        table=QtWidgets.QTableWidget();table.setColumnCount(5);table.setHorizontalHeaderLabels(['Common Channel','Expected Unit','Source Channel','Source Unit','Status']);table.verticalHeader().setVisible(False)
        specs=common_channel_specs();table.setRowCount(len(specs));table.setAlternatingRowColors(True)
        visible=[rec for rec in channel_catalog(run) if rec.numeric and rec.name in run.data.columns and rec.source_kind in {'native','rectangular'} and not str(rec.name).startswith('__')]
        originals=run.metadata.get('original_channel_map',{}) if isinstance(run.metadata.get('original_channel_map',{}),dict) else {}
        profile=matching_common_channel_profile(run);profile_scope=str(profile.get('scope') or '') if profile else ''
        profile_mappings=dict(profile.get('mappings',{})) if profile and isinstance(profile.get('mappings'),dict) else {}
        combos={}
        for row,spec in enumerate(specs):
            table.setItem(row,0,QtWidgets.QTableWidgetItem(spec.label));table.item(row,0).setData(QtCore.Qt.UserRole,spec.key)
            table.setItem(row,1,QtWidgets.QTableWidgetItem(spec.unit_label))
            combo=QtWidgets.QComboBox();combo.addItem('(unassigned)','')
            target=spec.unit
            compatible_rows=[];other_rows=[]
            for rec in visible:
                source_unit=normalize_unit(rec.unit)
                compatible_known=bool(target and source_unit and compatible(source_unit,target))
                label=rec.alias or rec.name
                if rec.alias: label=f'{rec.alias}  ({rec.name})'
                if rec.unit: label+=f'  [{display_label(rec.unit) or rec.unit}]'
                (compatible_rows if compatible_known else other_rows).append((label,rec.name))
            for label,name in compatible_rows+other_rows:combo.addItem(label,name)
            current=str(originals.get(spec.key,'') or '')
            idx=combo.findData(current);combo.setCurrentIndex(idx if idx>=0 else 0);table.setCellWidget(row,2,combo);combos[spec.key]=combo
            table.setItem(row,3,QtWidgets.QTableWidgetItem(display_label(run.units.get(current,'')) if current else ''))
            if spec.key in h.channel_overrides:
                status='Data log override'
            elif profile_mappings.get(spec.key)==current and current:
                status='Context profile'
            else:
                status='Importer auto' if current else 'Unmapped'
            table.setItem(row,4,QtWidgets.QTableWidgetItem(status))
            combo.currentIndexChanged.connect(lambda _i,r=row,c=combo: table.setItem(r,3,QtWidgets.QTableWidgetItem(display_label(run.units.get(str(c.currentData() or ''),'')) if c.currentData() else '')))
        table.horizontalHeader().setSectionResizeMode(0,QtWidgets.QHeaderView.ResizeToContents);table.horizontalHeader().setSectionResizeMode(1,QtWidgets.QHeaderView.ResizeToContents);table.horizontalHeader().setSectionResizeMode(2,QtWidgets.QHeaderView.Stretch);table.horizontalHeader().setSectionResizeMode(3,QtWidgets.QHeaderView.ResizeToContents);table.horizontalHeader().setSectionResizeMode(4,QtWidgets.QHeaderView.ResizeToContents)
        lay.addWidget(table,1)
        profile_row=QtWidgets.QHBoxLayout();profile_row.addWidget(QtWidgets.QLabel('Reusable profile:'))
        scope=self._common_channel_scope_combo(run,current_scope=profile_scope);profile_row.addWidget(scope,1)
        profile_note=QtWidgets.QLabel('Saving is optional. "This data log only" is the safest choice when you are not sure the logger configuration is truly reusable.')
        profile_note.setWordWrap(True);profile_row.addWidget(profile_note,2);lay.addLayout(profile_row)
        row=QtWidgets.QHBoxLayout();auto_btn=QtWidgets.QPushButton('Suggest mappings');clear_btn=QtWidgets.QPushButton('Clear assignments');row.addWidget(auto_btn);row.addWidget(clear_btn);row.addStretch(1);lay.addLayout(row)
        def auto_detect():
            guessed=auto_map_channels([rec.name for rec in visible],run.units)
            for canonical,source in guessed.items():
                combo=combos.get(canonical)
                if combo is not None:
                    idx=combo.findData(source)
                    if idx>=0:combo.setCurrentIndex(idx)
        auto_btn.clicked.connect(auto_detect)
        clear_btn.clicked.connect(lambda: [combo.setCurrentIndex(0) for combo in combos.values()])
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel);buttons.accepted.connect(dlg.accept);buttons.rejected.connect(dlg.reject);lay.addWidget(buttons)
        if dlg.exec()!=QtWidgets.QDialog.Accepted:return
        try:
            selected_map={}
            for spec in specs:
                selected=str(combos[spec.key].currentData() or '')
                if not selected:continue
                if spec.unit:
                    source_unit=normalize_unit(run.units.get(selected,''))
                    if source_unit and not compatible(source_unit,spec.unit):
                        raise ValueError(f'{spec.label}: {selected} is {display_label(source_unit) or source_unit}, expected {spec.unit_label}.')
                selected_map[spec.key]=selected
            changes=0
            # Record explicit differences, including deliberate clears, so this
            # exact data log can disagree with a reusable context profile.
            all_roles={spec.key for spec in specs}
            for canonical in all_roles:
                current=str(originals.get(canonical,'') or '')
                selected=str(combos[canonical].currentData() or '')
                if selected!=current:
                    h.channel_overrides[canonical]=selected
                    changes+=1
            h.run=apply_channel_overrides(h.run,h.channel_overrides,h.unit_overrides)
            if h.run.metadata.get('math_channels'):reapply_math_channels(h.run,list(h.run.metadata.get('math_channels',[])))
            self._persist_exact_channel_settings(h)
            scope_key=str(scope.currentData() or '')
            if scope_key:
                save_common_channel_profile(h.run,selected_map,scope=scope_key)
            self.store.changed.emit();self.store.activeChanged.emit(h)
            mapped=sum(1 for source in h.run.metadata.get('original_channel_map',{}).values() if source)
            suffix=f' · profile saved: {scope.currentText()}' if scope_key else ' · no reusable profile changed'
            self.statusBar().showMessage(f'Common channel mapping updated — {mapped} roles mapped, {changes} changed{suffix}',7000)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self,'Common Channel Mapping',str(exc))

    def _set_channel_alias(self, channel):
        h=self.store.active
        if not h:return
        current=str(h.run.metadata.get('channel_aliases',{}).get(channel,'') or '')
        value,ok=QtWidgets.QInputDialog.getText(self,'Display Alias',f'Display alias for {channel}:',text=current)
        if not ok:return
        try:
            set_channel_alias(h.run,channel,str(value).strip())
            self.store.changed.emit();self._refresh_channel_explorer()
        except Exception as exc:QtWidgets.QMessageBox.warning(self,'Display Alias',str(exc))

    def _delete_math_channel(self, channel):
        h = self.store.active
        if not h or channel not in h.run.data.columns:
            return
        answer = QtWidgets.QMessageBox.question(self, 'Delete math channel', f'Delete math channel {channel!r} from this project session?\n\nThe source telemetry file is not modified.')
        if answer != QtWidgets.QMessageBox.Yes:
            return
        h.run.data.drop(columns=[channel], inplace=True, errors='ignore')
        h.run.units.pop(channel, None)
        h.run.metadata.get('unit_provenance', {}).pop(channel, None)
        h.run.metadata['math_channels'] = [d for d in h.run.metadata.get('math_channels', []) if str(d.get('name','')) != channel]
        # Remove stale display references and canonical overrides.
        for key, value in list(h.channel_overrides.items()):
            if value == channel:
                h.channel_overrides.pop(key, None)
        for i in range(self.worksheets.count()):
            ws = self.worksheets.widget(i)
            for wave in ws.waveforms:
                if channel in wave.channels:
                    wave.remove_channel(channel)
        self.store.changed.emit(); self.store.activeChanged.emit(h)

    def _new_data_gate(self):
        h=self.store.active
        if not h:
            QtWidgets.QMessageBox.information(self,'Data Gate','Open a telemetry session first.');return
        dlg=QtWidgets.QDialog(self);dlg.setWindowTitle('Data Gate / Condition');dlg.resize(640,360)
        form=QtWidgets.QFormLayout(dlg);name=QtWidgets.QLineEdit();name.setPlaceholderText('e.g. WOT High RPM')
        expr=QtWidgets.QPlainTextEdit();expr.setMaximumHeight(100);expr.setPlaceholderText('e.g. (`TPS` > 95) and (`Engine RPM` > 8000)')
        desc=QtWidgets.QLineEdit();desc.setPlaceholderText('Optional description / intended use')
        form.addRow('Name',name);form.addRow('Condition',expr);form.addRow('Description',desc)
        hint=QtWidgets.QLabel('Safe boolean conditions support < <= > >= == !=, and/or/not, arithmetic, abs(), isfinite(), and between(channel, low, high).\nGates are reusable analysis definitions for future plots, histograms, metrics, reports, alarms and live telemetry. Native-only mixed-rate channels must be normalized before cross-channel gating.');hint.setWordWrap(True);form.addRow(hint)
        existing=', '.join(g.name for g in gates(h.run)) or '(none)';form.addRow('Existing gates',QtWidgets.QLabel(existing))
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel);buttons.accepted.connect(dlg.accept);buttons.rejected.connect(dlg.reject);form.addRow(buttons)
        if dlg.exec()!=QtWidgets.QDialog.Accepted:return
        gname=name.text().strip();expression=expr.toPlainText().strip()
        if not gname or not expression:
            QtWidgets.QMessageBox.warning(self,'Data Gate','Gate name and condition are required.');return
        try:
            mask=evaluate_gate(h.run,expression);save_gate(h.run,GateDefinition(gname,expression,desc.text().strip()))
            matched=int(mask.sum());total=len(mask);self.store.changed.emit()
            self.statusBar().showMessage(f'Data gate saved: {gname} — {matched:,}/{total:,} samples currently match',7000)
        except Exception as exc:QtWidgets.QMessageBox.critical(self,'Data Gate Rejected',str(exc))

    def _new_math_channel(self):
        self._math_channel_builder('')

    def _edit_math_channel(self, channel):
        self._math_channel_builder(str(channel or ''))

    def _math_channel_builder(self, existing_channel=''):
        h=self.store.active
        if not h:
            QtWidgets.QMessageBox.information(self,'Math Channel Builder','Open a data log first.');return
        run=h.run
        existing={str(d.get('name','')):d for d in run.metadata.get('math_channels',[]) if isinstance(d,dict)}
        current=existing.get(existing_channel,{})

        dlg=QtWidgets.QDialog(self);dlg.setWindowTitle('Math Channel Builder');dlg.resize(960,650)
        main=QtWidgets.QVBoxLayout(dlg)
        top=QtWidgets.QGridLayout()
        name=QtWidgets.QLineEdit(str(current.get('name','') or existing_channel));name.setPlaceholderText('e.g. Clutch Slip Ratio')
        unit=QtWidgets.QComboBox();unit.setEditable(True);unit.addItem('(unassigned)','')
        for key in sorted(k for k in UNITS if k):unit.addItem(display_label(key) or key,key)
        existing_unit=str(current.get('unit','') or '')
        idx=unit.findData(existing_unit)
        if idx>=0:unit.setCurrentIndex(idx)
        template=QtWidgets.QComboBox();template.addItem('(formula template)','')
        templates=math_channel_templates()
        for label in sorted(templates):template.addItem(label,label)
        top.addWidget(QtWidgets.QLabel('Output name'),0,0);top.addWidget(name,0,1)
        top.addWidget(QtWidgets.QLabel('Unit'),0,2);top.addWidget(unit,0,3)
        top.addWidget(QtWidgets.QLabel('Template'),1,0);top.addWidget(template,1,1,1,3)
        main.addLayout(top)

        split=QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        refs=QtWidgets.QTreeWidget();refs.setHeaderLabels(['Reference','Unit / Meaning']);refs.setColumnWidth(0,255)
        common_root=QtWidgets.QTreeWidgetItem(['Common Channels','portable across logger vendors']);font=common_root.font(0);font.setBold(True);common_root.setFont(0,font);refs.addTopLevelItem(common_root)
        originals=run.metadata.get('original_channel_map',{}) if isinstance(run.metadata.get('original_channel_map',{}),dict) else {}
        for spec in common_channel_specs():
            source=str(originals.get(spec.key,'') or '')
            label=f'{spec.label}  (@{spec.key})'
            detail=(spec.unit_label or 'unitless') + (f'  ← {source}' if source else '  — unmapped')
            item=QtWidgets.QTreeWidgetItem([label,detail]);item.setData(0,QtCore.Qt.UserRole,f'@{spec.key}');
            if not source:item.setForeground(0,QtGui.QBrush(QtGui.QColor('#7e858c')))
            common_root.addChild(item)
        source_root=QtWidgets.QTreeWidgetItem(['Source / Calculated Channels','run-specific']);font=source_root.font(0);font.setBold(True);source_root.setFont(0,font);refs.addTopLevelItem(source_root)
        for rec in channel_catalog(run):
            display=rec.alias or rec.name
            if rec.alias:display=f'{rec.alias}  ({rec.name})'
            item=QtWidgets.QTreeWidgetItem([display,display_label(rec.unit) or rec.unit]);item.setData(0,QtCore.Qt.UserRole,f'`{rec.name}`');source_root.addChild(item)
        refs.expandItem(common_root);refs.expandItem(source_root)
        split.addWidget(refs)

        editor_wrap=QtWidgets.QWidget();editor_lay=QtWidgets.QVBoxLayout(editor_wrap);editor_lay.setContentsMargins(6,0,0,0)
        expr=QtWidgets.QPlainTextEdit();expr.setPlainText(str(current.get('expression','') or ''));expr.setPlaceholderText('Double-click channels on the left or type a formula.\nPortable example: (@engine_rpm / @driveshaft_rpm)\nRaw-source example: smooth(`Engine RPM`, 0.10)')
        mono=QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont);expr.setFont(mono);editor_lay.addWidget(QtWidgets.QLabel('Expression'));editor_lay.addWidget(expr,1)
        ops=QtWidgets.QHBoxLayout();
        for token in (' + ',' - ',' * ',' / ',' ** ','(',')'):
            b=QtWidgets.QPushButton(token.strip() or token);b.setMaximumWidth(48);b.clicked.connect(lambda _checked=False,t=token: expr.insertPlainText(t));ops.addWidget(b)
        ops.addStretch(1);editor_lay.addLayout(ops)
        funcs=QtWidgets.QHBoxLayout()
        for label,fn in [('abs','abs'),('sqrt','sqrt'),('smooth','smooth'),('d/dt','derivative'),('∫','integral'),('LPF','lowpass'),('HPF','highpass'),('Mean','rollingmean'),('RMS','rollingrms'),('Min','rollingmin'),('Max','rollingmax'),('σ','rollingstd')]:
            b=QtWidgets.QPushButton(label);b.setToolTip(fn);b.clicked.connect(lambda _checked=False,f=fn:self._insert_math_function(expr,f));funcs.addWidget(b)
        funcs.addStretch(1);editor_lay.addLayout(funcs)
        help_label=QtWidgets.QLabel('Tip: use @common_channel references whenever possible. They follow the engineering role when the next data log uses different vendor/channel names. Backticks address one raw source channel by name or display alias.')
        help_label.setWordWrap(True);help_label.setStyleSheet('color:#aeb4bb');editor_lay.addWidget(help_label)
        preview=QtWidgets.QLabel('Preview not run.');preview.setWordWrap(True);preview.setStyleSheet('padding:6px;border:1px solid #444;background:#202225');editor_lay.addWidget(preview)
        preview_btn=QtWidgets.QPushButton('Validate / Preview');editor_lay.addWidget(preview_btn,0,QtCore.Qt.AlignLeft)
        split.addWidget(editor_wrap);split.setStretchFactor(0,0);split.setStretchFactor(1,1);split.setSizes([330,600]);main.addWidget(split,1)

        save_template=QtWidgets.QCheckBox('Save this formula as a reusable template');template_name=QtWidgets.QLineEdit();template_name.setPlaceholderText('Template name');template_name.setEnabled(False);save_template.toggled.connect(template_name.setEnabled)
        save_row=QtWidgets.QHBoxLayout();save_row.addWidget(save_template);save_row.addWidget(template_name,1);main.addLayout(save_row)

        def insert_reference(item,_column=0):
            text=str(item.data(0,QtCore.Qt.UserRole) or '')
            if text:expr.insertPlainText(text)
        refs.itemDoubleClicked.connect(insert_reference)

        def apply_template(index):
            key=str(template.itemData(index) or '')
            if not key:return
            rec=templates.get(key,{})
            expr.setPlainText(str(rec.get('expression','') or ''))
            u=str(rec.get('unit','') or '');idx=unit.findData(u)
            if idx>=0:unit.setCurrentIndex(idx)
            if not name.text().strip():name.setText(key)
        template.currentIndexChanged.connect(apply_template)

        def do_preview():
            formula=expr.toPlainText().strip()
            if not formula:
                preview.setText('Enter an expression first.');return
            try:
                values=evaluate_run_expression(run,formula);finite=values[np.isfinite(values)]
                inferred=infer_expression_dimension(run,formula)
                if len(finite):
                    preview.setText(f'VALID — {len(finite):,}/{len(values):,} finite samples • dimension: {inferred} • min {np.nanmin(finite):.6g} • max {np.nanmax(finite):.6g} • mean {np.nanmean(finite):.6g}')
                else:preview.setText(f'VALID expression, but no finite output samples • dimension: {inferred}')
                preview.setStyleSheet('padding:6px;border:1px solid #366b3c;background:#1f2b22')
            except Exception as exc:
                preview.setText(f'NOT VALID — {exc}');preview.setStyleSheet('padding:6px;border:1px solid #7b3636;background:#2d2020')
        preview_btn.clicked.connect(do_preview)

        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel);buttons.accepted.connect(dlg.accept);buttons.rejected.connect(dlg.reject);main.addWidget(buttons)
        if dlg.exec()!=QtWidgets.QDialog.Accepted:return
        cname=name.text().strip();formula=expr.toPlainText().strip();unit_key=str(unit.currentData() or normalize_unit(unit.currentText()) or unit.currentText()).strip()
        if not cname or not formula:
            QtWidgets.QMessageBox.warning(self,'Math Channel Builder','Output name and expression are required.');return
        math_defs=[dict(d) for d in run.metadata.get('math_channels',[]) if isinstance(d,dict) and str(d.get('name','')).strip()]
        math_names={str(d.get('name','')).strip() for d in math_defs}
        if cname in run.data.columns and cname not in math_names and cname!=existing_channel:
            QtWidgets.QMessageBox.warning(self,'Math Channel Builder',f'{cname!r} is a source/common data channel. Math channels cannot overwrite source evidence; choose a different output name.')
            return
        if cname in math_names and cname!=existing_channel:
            answer=QtWidgets.QMessageBox.question(self,'Replace calculated channel?',f'A math channel named {cname!r} already exists. Replace that calculated definition?')
            if answer!=QtWidgets.QMessageBox.Yes:return
        try:
            # Build the complete proposed definition set first, then validate it
            # on a private copy. This catches dependency cycles and missing
            # references without partially mutating the engineer's active Run.
            proposed=[]
            for rec in math_defs:
                rec_name=str(rec.get('name','')).strip()
                if rec_name in {existing_channel,cname}:
                    continue
                rec2=dict(rec)
                if existing_channel and existing_channel!=cname:
                    rec2['expression']=re.sub(r'`'+re.escape(existing_channel)+r'`',f'`{cname}`',str(rec2.get('expression','')))
                proposed.append(rec2)
            proposed.append({'name':cname,'expression':formula,'unit':unit_key})
            trial=copy.deepcopy(run)
            if existing_channel and existing_channel!=cname:
                trial.data.drop(columns=[existing_channel],inplace=True,errors='ignore');trial.units.pop(existing_channel,None)
            trial.metadata['math_channels']=list(proposed)
            reapply_math_channels(trial,proposed)

            # The trial succeeded: commit the same definition set atomically to
            # the active Run. Dependent math expressions are renamed with it.
            if existing_channel and existing_channel!=cname:
                run.data.drop(columns=[existing_channel],inplace=True,errors='ignore');run.units.pop(existing_channel,None)
                aliases=run.metadata.get('channel_aliases',{})
                if isinstance(aliases,dict) and existing_channel in aliases:
                    aliases[cname]=aliases.pop(existing_channel)
            run.metadata['math_channels']=list(proposed)
            reapply_math_channels(run,proposed)
            if existing_channel and existing_channel!=cname:
                for i in range(self.worksheets.count()):
                    ws=self.worksheets.widget(i)
                    for wave in ws.waveforms:
                        if existing_channel in wave.channels:
                            wave.channels=[cname if ch==existing_channel else ch for ch in wave.channels]
                            if existing_channel in wave.channel_styles:
                                wave.channel_styles[cname]=wave.channel_styles.pop(existing_channel)
                            wave.refresh()
            if save_template.isChecked():
                tname=template_name.text().strip() or cname
                save_math_channel_template(tname,formula,unit_key)
            self.store.changed.emit();self.store.activeChanged.emit(h)
            self.statusBar().showMessage(f'Math channel ready: {cname}',5000)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self,'Math Channel Rejected',str(exc))

    def _insert_math_function(self, editor, function_name):
        cursor=editor.textCursor();selected=cursor.selectedText().replace('\u2029',' ').strip()
        templates={
            'abs':lambda x:f'abs({x})','sqrt':lambda x:f'sqrt({x})',
            'smooth':lambda x:f'smooth({x}, 0.10)','derivative':lambda x:f'derivative({x})',
            'integral':lambda x:f'integral({x})','lowpass':lambda x:f'lowpass({x}, 20)',
            'highpass':lambda x:f'highpass({x}, 2)','rollingmean':lambda x:f'rollingmean({x}, 0.10)','rollingrms':lambda x:f'rollingrms({x}, 0.10)','rollingmin':lambda x:f'rollingmin({x}, 0.10)','rollingmax':lambda x:f'rollingmax({x}, 0.10)','rollingstd':lambda x:f'rollingstd({x}, 0.10)',
        }
        seed=selected or '@engine_rpm';text=templates.get(function_name,lambda x:f'{function_name}({x})')(seed)
        cursor.insertText(text);editor.setTextCursor(cursor);editor.setFocus()

    def _require_access(self, scope='desktop.access', *, allow_offline=True):
        if not self.auth_required:
            return True
        try:
            self.auth.require(scope,allow_offline=allow_offline);return True
        except AccessDenied as exc:
            QtWidgets.QMessageBox.warning(self,'NHRA Tech Services access required',str(exc));return False

    def _refresh_account_actions(self):
        status=self.auth.status()
        # Only show the action that makes sense for the current state.  The
        # account detail action remains available in either state.
        self.a_signin.setVisible(not status.signed_in)
        self.a_signin.setEnabled(not status.signed_in)
        self.a_signout.setVisible(status.signed_in)
        self.a_signout.setEnabled(status.signed_in)
        ident=status.identity
        if status.signed_in and ident:
            label=ident.display_name or ident.email or 'Signed in'
            self.a_account.setText(f'NHRA Tech Services Account — {label}…')
        else:
            self.a_account.setText('NHRA Tech Services Account…')

    def _show_account_access(self):
        status=self.auth.status();ident=status.identity
        lines=[
            f"Protection mode: {'REQUIRED' if self.auth_required else 'development / not enforced'}",
            f"Provider: {self.auth.provider.provider_name}",
            f"Signed in: {'Yes' if status.signed_in else 'No'}",
            f"Online access: {'Valid' if status.online_access_valid else 'Not valid'}",
            f"Offline entitlement: {'Valid' if status.offline_access_valid else 'Not available'}",
        ]
        if ident:
            lines += [f"User: {ident.display_name or ident.email or ident.user_id}",f"Roles: {', '.join(ident.roles) or '—'}",f"Capabilities/scopes: {', '.join(ident.scopes) or '—'}"]
        if status.reason:lines.append(f"Status: {status.reason}")
        lines += ['', 'Velocity uses the existing NHRA Tech Services login API over HTTPS. Your password exists only long enough to perform the login request and is never saved. The returned Bearer token is stored in the operating-system credential vault.', 'The current website does not issue a signed offline entitlement, so a fresh application start still requires the cached token to be validated with Tech Services.']
        QtWidgets.QMessageBox.information(self,'NHRA Tech Services Account','\n'.join(lines))

    def _sign_in(self):
        dlg=QtWidgets.QDialog(self);dlg.setWindowTitle('Sign in to NHRA Tech Services');dlg.resize(470,220)
        form=QtWidgets.QFormLayout(dlg)
        email=QtWidgets.QLineEdit();email.setPlaceholderText('name@example.com')
        password=QtWidgets.QLineEdit();password.setEchoMode(QtWidgets.QLineEdit.Password)
        note=QtWidgets.QLabel('Uses your existing nhratechservices.com account. Credentials are sent directly to the existing HTTPS login API. The password is never stored; only the seven-day Bearer token is kept in your OS credential vault.')
        note.setWordWrap(True)
        form.addRow('Email',email);form.addRow('Password',password);form.addRow(note)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel);buttons.accepted.connect(dlg.accept);buttons.rejected.connect(dlg.reject);form.addRow(buttons)
        email.setFocus()
        if dlg.exec()!=QtWidgets.QDialog.Accepted:return False
        user=email.text().strip();secret=password.text()
        if not user or not secret:
            QtWidgets.QMessageBox.warning(self,'Tech Services sign-in','Email and password are required.');return False
        persistence_error=None
        try:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            session=self.auth_provider.sign_in(email=user,password=secret)
            try:
                self.auth.set_session(session,persist=True)
            except Exception as exc:
                # Authentication already succeeded.  A credential-vault
                # problem must not masquerade as a bad username/password or
                # throw away the valid in-memory session.  Continue for this
                # launch and tell the user that sign-in could not be remembered.
                persistence_error=exc
                logging.exception('Tech Services session persistence failed')
                self.auth.set_session(session,persist=False)
        except Exception as exc:
            logging.exception('Tech Services sign-in failed')
            QtWidgets.QMessageBox.warning(self,'Tech Services sign-in',str(exc));return False
        finally:
            # Drop the UI's reference to the password as soon as possible.
            password.clear();secret=''
            QtWidgets.QApplication.restoreOverrideCursor()
        if not self.auth.status().online_access_valid:
            QtWidgets.QMessageBox.warning(self,'Tech Services sign-in','The account authenticated, but its current Tech Services capabilities do not include NHRA Velocity desktop access.')
            return False
        self.statusBar().showMessage(f'Signed in to NHRA Tech Services as {session.identity.display_name or session.identity.email}.',5000)
        if persistence_error is not None:
            QtWidgets.QMessageBox.information(
                self,
                'Tech Services sign-in',
                'Sign-in succeeded, but Windows could not securely remember this session.\n\n'
                'You can continue using NHRA Velocity now, but you may need to sign in again the next time the app starts.\n\n'
                f'Detail: {persistence_error}',
            )
        self._refresh_account_actions()
        QtCore.QTimer.singleShot(0,self._maybe_start_initial_sync)
        return True

    def _sign_out(self):
        self.auth.sign_out();self._refresh_account_actions();self.statusBar().showMessage('Signed out of NHRA Tech Services.',4000)

    def _sync_tech_services_data(self):
        if not self.auth.status().online_access_valid:
            if not self._sign_in():return
        if self._tech_sync_thread is not None:
            self.statusBar().showMessage('NHRA Tech Services sync is already running in the background.',5000)
            return
        dlg=QtWidgets.QDialog(self);dlg.setWindowTitle('Sync NHRA Tech Services Data');dlg.resize(500,255)
        form=QtWidgets.QFormLayout(dlg)
        year=QtWidgets.QSpinBox();year.setRange(2000,2100);year.setValue(time.gmtime().tm_year)
        entries=QtWidgets.QCheckBox('Tech Master event entries / roster');entries.setChecked(True)
        runs=QtWidgets.QCheckBox('Official timing runs + canonical weather');runs.setChecked(True)
        note=QtWidgets.QLabel(
            "Velocity now syncs the current or most recently completed event first. "
            "As soon as that event is ready, its Runs appear in the browser and you can keep working while the rest of the season fills in quietly in the background. "
            "This remains a read-only pull from nhratechservices.com."
        )
        note.setWordWrap(True)
        form.addRow('Season',year);form.addRow('',entries);form.addRow('',runs);form.addRow(note)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel);buttons.accepted.connect(dlg.accept);buttons.rejected.connect(dlg.reject);form.addRow(buttons)
        if dlg.exec()!=QtWidgets.QDialog.Accepted:return
        self._start_tech_services_sync(year.value(),include_entries=entries.isChecked(),include_runs=runs.isChecked(),user_initiated=True)

    def _maybe_start_initial_sync(self):
        if self._tech_sync_thread is not None:return
        if not self.auth.status().online_access_valid:return
        try:
            has_runs=bool(self.catalog.list_runs(limit=1))
        except Exception:
            has_runs=True
        if has_runs:return
        year=time.gmtime().tm_year
        self.statusBar().showMessage('First launch: loading the most useful NHRA Tech Services event…')
        self._start_tech_services_sync(year,include_entries=True,include_runs=True,user_initiated=False)

    def _start_tech_services_sync(self,season_year:int,*,include_entries=True,include_runs=True,user_initiated=False):
        if self._tech_sync_thread is not None:return
        if not self.auth.status().online_access_valid:
            return
        client=self.auth_provider.client_for_session(self.auth.session)
        thread=QtCore.QThread(self)
        worker=TechServicesSeasonSyncWorker(
            self.catalog,client,int(season_year),include_entries=include_entries,include_runs=include_runs
        )
        worker.moveToThread(thread)
        self._tech_sync_thread=thread;self._tech_sync_worker=worker;self._tech_sync_user_initiated=bool(user_initiated)
        self.a_site_sync.setEnabled(False)
        worker.firstEventReady.connect(self._tech_sync_first_event_ready)
        worker.progress.connect(self._tech_sync_progress)
        worker.finished.connect(self._tech_sync_finished)
        worker.failed.connect(self._tech_sync_failed)
        worker.finished.connect(thread.quit);worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater);worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater);thread.finished.connect(self._tech_sync_cleanup)
        thread.started.connect(worker.run)
        self.statusBar().showMessage(f'Syncing {season_year}: loading current/latest event first…')
        thread.start()

    def _refresh_catalog_browsers(self):
        self.run_browser.refresh();self.asset_browser.refresh();self.case_browser.refresh();self.case_timeline.refresh();self.case_review.refresh()

    @QtCore.Slot(object,str)
    def _tech_sync_first_event_ready(self,result,event_name):
        self._refresh_catalog_browsers()
        run_count=int(getattr(result,'run_count',0))
        self.statusBar().showMessage(
            f'{event_name} ready ({run_count:,} Runs). You can work now; the rest of the season is syncing in the background.',
            12000,
        )

    @QtCore.Slot(int,int,str)
    def _tech_sync_progress(self,current,total,event_name):
        if current<=1:return
        self.statusBar().showMessage(f'Background Tech Services sync: {current}/{total} events — {event_name}')

    @QtCore.Slot(object)
    def _tech_sync_finished(self,result):
        self._refresh_catalog_browsers()
        summary=(
            f'Tech Services sync complete for {result.season_year}: '
            f'{result.run_count:,} Runs processed, {result.runs_with_weather:,} with canonical weather.'
        )
        if result.warnings:
            summary+=f' {len(result.warnings)} warning(s); see diagnostic log.'
            for warning in result.warnings:
                logging.warning('Tech Services sync: %s',warning)
        self.statusBar().showMessage(summary,15000)

    @QtCore.Slot(str)
    def _tech_sync_failed(self,message):
        QtWidgets.QMessageBox.critical(self,'Tech Services Sync',message)
        self.statusBar().showMessage('NHRA Tech Services sync failed. See diagnostic log.',10000)

    @QtCore.Slot()
    def _tech_sync_cleanup(self):
        self._tech_sync_thread=None;self._tech_sync_worker=None;self._tech_sync_user_initiated=False
        self.a_site_sync.setEnabled(True)


    def _attach_rsa_model_channels(self):
        if not self._require_access('simulation.use'):return
        h=self.store.active
        if not h:
            QtWidgets.QMessageBox.information(self,'RSA Model Channels','Open a measured Run first.');return
        missing=self._critical_model_missing(h.run,'compare')
        if missing:
            QtWidgets.QMessageBox.warning(self,'RSA Model Channels','A trustworthy model baseline is required.\n\nMissing: '+', '.join(missing));return
        try: vehicle,_=vehicle_from_run(h.run,require_explicit=False)
        except Exception as exc: QtWidgets.QMessageBox.warning(self,'RSA Model Channels',str(exc));return
        engine,ok=QtWidgets.QInputDialog.getItem(self,'RSA Model Channels','Model engine:',['reference — Quarter Pro source-faithful','smooth — optimizer engine'],0,False)
        if not ok:return
        mode='reference' if engine.startswith('reference') else 'smooth'
        try:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            info=run_rsa_model_enrichment(h.run,vehicle,environment=h.run.environment,engine=mode,include_residuals=True,persist=True)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self,'RSA Model Channels',str(exc));return
        finally:QtWidgets.QApplication.restoreOverrideCursor()
        self.store.changed.emit();self.store.activeChanged.emit(h)
        QtWidgets.QMessageBox.information(self,'RSA Model Channels',f"Attached {len(info['model_channels'])} Model.* channels and {len(info['residual_channels'])} Residual.* channels.\n\nThey retain the RSA model Run-time grid; residuals are model-minus-measured using explicit alignment.")

    def _simulation_study_center(self):
        if not self._require_access('simulation.use'):return
        h=self.store.active
        if not h:
            QtWidgets.QMessageBox.information(self,'Simulation Study Center','Open a measured Run first.');return
        missing=self._critical_model_missing(h.run,'compare')
        if missing:
            QtWidgets.QMessageBox.warning(self,'Simulation Study Center','A trustworthy simulation baseline needs the vehicle/setup model first.\n\nMissing: '+', '.join(missing));return
        vehicle,_=vehicle_from_run(h.run,require_explicit=False)
        dlg=QtWidgets.QDialog(self);dlg.setWindowTitle('Simulation Study Center — RSA / Quarter Pro');dlg.resize(900,560)
        lay=QtWidgets.QVBoxLayout(dlg)
        intro=QtWidgets.QLabel('Build repeatable forward studies with the same vehicle physics used by inverse fitting. Reference = source-faithful Quarter Pro port; Smooth = optimizer-oriented engine. Axis values may be absolute, delta from baseline, or scale factors.');intro.setWordWrap(True);lay.addWidget(intro)
        top=QtWidgets.QHBoxLayout();top.addWidget(QtWidgets.QLabel('Engine'));engine=QtWidgets.QComboBox();engine.addItems(['reference','smooth']);top.addWidget(engine);top.addWidget(QtWidgets.QLabel('Max cases'));maxcases=QtWidgets.QSpinBox();maxcases.setRange(1,1000);maxcases.setValue(100);top.addWidget(maxcases);top.addStretch(1);lay.addLayout(top)
        table=QtWidgets.QTableWidget(2,3);table.setHorizontalHeaderLabels(['Parameter','Mode','Values (comma-separated)']);table.horizontalHeader().setSectionResizeMode(2,QtWidgets.QHeaderView.Stretch);lay.addWidget(table,1)
        params=['power_scale','weight_lb','cda_ft2','cla_ft2','traction_index','final_drive_ratio','final_drive_efficiency','tire_diameter_in','tire_growth_scale','efficiency_scale','shift_rpm_offset']+[f'gear_ratio_{i+1}' for i in range(vehicle.n_gears)]+[f'shift_rpm_{i+1}' for i in range(max(0,vehicle.n_gears-1))]
        def make_row(r,param,mode,values):
            pc=QtWidgets.QComboBox();pc.addItems(params);pc.setCurrentText(param);table.setCellWidget(r,0,pc)
            mc=QtWidgets.QComboBox();mc.addItems(['absolute','delta','scale']);mc.setCurrentText(mode);table.setCellWidget(r,1,mc)
            table.setItem(r,2,QtWidgets.QTableWidgetItem(values))
        make_row(0,'power_scale','absolute','0.98, 1.00, 1.02');make_row(1,'weight_lb','delta','-10, 0, 10')
        rowbuttons=QtWidgets.QHBoxLayout();addrow=QtWidgets.QPushButton('Add Axis');delrow=QtWidgets.QPushButton('Remove Axis');rowbuttons.addWidget(addrow);rowbuttons.addWidget(delrow);rowbuttons.addStretch(1);lay.addLayout(rowbuttons)
        def add_axis():
            r=table.rowCount();table.insertRow(r);make_row(r,'shift_rpm_offset','delta','-100, 0, 100')
        addrow.clicked.connect(add_axis);delrow.clicked.connect(lambda: table.removeRow(table.currentRow()) if table.currentRow()>=0 else None)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel);buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('Run Study');buttons.accepted.connect(dlg.accept);buttons.rejected.connect(dlg.reject);lay.addWidget(buttons)
        if dlg.exec()!=QtWidgets.QDialog.Accepted:return
        axes=[]
        try:
            for r in range(table.rowCount()):
                p=str(table.cellWidget(r,0).currentText());m=str(table.cellWidget(r,1).currentText());text=str(table.item(r,2).text() if table.item(r,2) else '')
                vals=tuple(float(x.strip()) for x in text.replace(';',',').split(',') if x.strip())
                axes.append(ScenarioAxis(p,vals,mode=m))
            study=SimulationStudyDefinition(name=f'{h.label} Study',engine=engine.currentText(),axes=axes,include_baseline=True,max_cases=maxcases.value())
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor);result=run_scenario_sweep(vehicle,h.run.environment,study)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self,'Simulation Study rejected',str(exc));return
        finally:QtWidgets.QApplication.restoreOverrideCursor()
        package=package_study_result(result,vehicle,h.run.environment,source_run_id=h.catalog_run_id,source_run_name=h.label)
        self.simulation_studies.append(package.to_dict())
        out=QtWidgets.QDialog(self);out.setWindowTitle(f'Simulation Study Results — {study.name}');out.resize(1200,650);v=QtWidgets.QVBoxLayout(out)
        summary=QtWidgets.QLabel(f'{len(result.table)} cases • {study.engine} engine • baseline {result.baseline_result.timing.quarter_mile_s:.4f} s / {result.baseline_result.timing.quarter_mile_mph:.2f} mph');v.addWidget(summary)
        view=QtWidgets.QTableWidget(len(result.table),len(result.table.columns));view.setHorizontalHeaderLabels([str(c) for c in result.table.columns]);view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows);view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        for rr,(_,row) in enumerate(result.table.iterrows()):
            for cc,col in enumerate(result.table.columns):
                val=row[col];view.setItem(rr,cc,QtWidgets.QTableWidgetItem('' if pd.isna(val) else (f'{float(val):.6g}' if isinstance(val,(int,float,np.number)) else str(val))))
        view.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents);v.addWidget(view,1)
        actions=QtWidgets.QHBoxLayout();export=QtWidgets.QPushButton('Export Table…');savepkg=QtWidgets.QPushButton('Save Study Package…');addcompare=QtWidgets.QPushButton('Add Selected as Compare Session');close=QtWidgets.QPushButton('Close');actions.addWidget(export);actions.addWidget(savepkg);actions.addWidget(addcompare);actions.addStretch(1);actions.addWidget(close);v.addLayout(actions)
        def do_export():
            path,_=QtWidgets.QFileDialog.getSaveFileName(out,'Export simulation study',f'{h.label}_simulation_study.xlsx','Excel (*.xlsx);;CSV (*.csv);;JSON (*.json)')
            if path:
                try:export_study_table(result.table,path)
                except Exception as exc:QtWidgets.QMessageBox.critical(out,'Export failed',str(exc))
        def save_package():
            path,_=QtWidgets.QFileDialog.getSaveFileName(out,'Save simulation study package',f'{h.label}_simulation_study.nhrastudy','NHRA Simulation Study (*.nhrastudy);;JSON (*.json)')
            if path:
                if not path.lower().endswith(('.nhrastudy','.json')):path+='.nhrastudy'
                try:package.save(path)
                except Exception as exc:QtWidgets.QMessageBox.critical(out,'Study package save failed',str(exc))
        def add_selected():
            r=view.currentRow()
            if r<0:QtWidgets.QMessageBox.information(out,'Simulation Study','Select a study row first.');return
            rec=result.table.iloc[r];assign={str(c)[6:]:float(rec[c]) for c in result.table.columns if str(c).startswith('input.') and not pd.isna(rec[c])}
            try:run=create_scenario_run(h.label,vehicle,h.run.environment,assign,engine=study.engine,smooth_dt_s=study.smooth_dt_s,name=str(rec['case']))
            except Exception as exc:QtWidgets.QMessageBox.critical(out,'Scenario generation failed',str(exc));return
            path=str(Path(QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.TempLocation) or '.').joinpath('nhra-velocity-simulation.csv'));run.data.to_csv(path,index=False)
            nh=self.store.add(path,run);nh.role='reference';nh.display_name=run.name;self.store.changed.emit();self.statusBar().showMessage(f'Added simulated compare session: {run.name}',6000)
        export.clicked.connect(do_export);savepkg.clicked.connect(save_package);addcompare.clicked.connect(add_selected);close.clicked.connect(out.accept);out.exec()

    def _critical_model_missing(self, run, purpose='analysis'):
        _, missing = vehicle_from_run(run, require_explicit=False)
        required = {
            'reconstruct': {'weight_lb','final_drive_ratio','final_drive_efficiency','tire_diameter_in','gear_ratios','gear_efficiencies','engine_pmi','transmission_pmi','tires_pmi','frontal_area_ft2','drag_coefficient','lift_coefficient','transmission_type'},
            'inverse': {'weight_lb','final_drive_ratio','tire_diameter_in','gear_ratios','shift_rpms','dyno_curve'},
            'compare': {'weight_lb','wheelbase_in','final_drive_ratio','tire_diameter_in','gear_ratios','shift_rpms','launch_rpm','dyno_curve'},
        }.get(purpose,set())
        return sorted(required.intersection(missing))

    def _reconstruct_power(self):
        h=self.store.active
        if not h:return
        missing=self._critical_model_missing(h.run,'reconstruct')
        if missing:
            QtWidgets.QMessageBox.warning(self,'Reconstruct Delivered Power',
                'The run does not yet contain enough vehicle/setup information for a trustworthy power reconstruction.\n\nMissing: '+', '.join(missing)+
                '\n\nFill these values in Run Details / Setup first. The application will not substitute hidden defaults for derivative-based horsepower.')
            return
        try:
            vehicle,_=vehicle_from_run(h.run,require_explicit=False)
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            result=attach_delivered_power_reconstruction(h.run,vehicle,h.run.environment,persist=True,run_label=h.label)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self,'Power reconstruction rejected',str(exc)); return
        finally:QtWidgets.QApplication.restoreOverrideCursor()
        self.store.changed.emit();self.store.activeChanged.emit(h)
        # Show the inferred power immediately in a dedicated waveform. Measured
        # canonical power, when present, remains untouched.
        ws=self.current_sheet(); w=ws.add_waveform('Reconstructed Power')
        rpm_source=_source_for_canonical(h.run,'engine_rpm')
        w.channels=['Reconstructed Engine HP']+([rpm_source] if rpm_source else [])
        w.refresh()
        msg=f"Reconstruction complete: {result.diagnostics.get('usable_dyno_samples',0)} usable dyno samples"
        self.statusBar().showMessage(msg,7000)

    def _inference_center(self):
        h=self.store.active
        if not h:return
        critical=self._critical_model_missing(h.run,'inverse')
        if critical:
            QtWidgets.QMessageBox.warning(self,'Inference Center',
                'Inverse fitting needs a reasonable baseline model before estimating unknowns.\n\nMissing: '+', '.join(critical)+
                '\n\nA reconstructed power curve may satisfy the power-curve requirement.')
            return
        vehicle,_=vehicle_from_run(h.run,require_explicit=False)
        handles=[x for x in self.store.runs if x is h or x.role in ('reference','overlay')]
        runs=[FitRun(x.label,x.run.environment,x.run.timing,x.run) for x in handles]
        candidates=['power_scale','cda_ft2','cla_ft2','traction_index','final_drive_ratio','final_drive_efficiency','tire_diameter_in','tire_growth_scale','weight_lb','cg_height_in','static_front_weight_lb','efficiency_scale','shift_rpm_offset','front_overhang_in','rollout_in']
        try: obs=assess_observability(vehicle,runs,candidates)
        except Exception as exc: QtWidgets.QMessageBox.warning(self,'Inference Center',str(exc)); return
        dlg=QtWidgets.QDialog(self);dlg.setWindowTitle('Inference Center');dlg.resize(920,620)
        lay=QtWidgets.QVBoxLayout(dlg)
        intro=QtWidgets.QLabel('Select only the unknowns you actually want estimated. The observability grade is a preflight, not a promise of uniqueness. Main + Reference/Overlay sessions are used together.');intro.setWordWrap(True);lay.addWidget(intro)
        table=QtWidgets.QTableWidget(len(obs),5);table.setHorizontalHeaderLabels(['Estimate','Observability','Evidence','Major confounds','Best next measurement']);table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows);table.verticalHeader().setVisible(False)
        checks=[]
        for r,row in obs.reset_index(drop=True).iterrows():
            name=str(row['parameter']) if 'parameter' in row else candidates[r]
            cb=QtWidgets.QCheckBox(name); checks.append(cb);table.setCellWidget(r,0,cb)
            for c,key in enumerate(['preflight','evidence_present','important_confounds','best_next_measurement'],1):
                val=row.get(key,'')
                if isinstance(val,(list,tuple,set)):val=', '.join(map(str,val))
                table.setItem(r,c,QtWidgets.QTableWidgetItem(str(val)))
        table.horizontalHeader().setSectionResizeMode(0,QtWidgets.QHeaderView.ResizeToContents);table.horizontalHeader().setSectionResizeMode(1,QtWidgets.QHeaderView.ResizeToContents);table.horizontalHeader().setSectionResizeMode(2,QtWidgets.QHeaderView.Stretch);table.horizontalHeader().setSectionResizeMode(3,QtWidgets.QHeaderView.Stretch);table.horizontalHeader().setSectionResizeMode(4,QtWidgets.QHeaderView.Stretch)
        lay.addWidget(table,1)
        evidence_box=QtWidgets.QGroupBox('Fit Evidence Policy'); evidence_layout=QtWidgets.QGridLayout(evidence_box)
        evidence_domain=QtWidgets.QComboBox(); evidence_domain.addItems(['Time-domain telemetry','Downtrack distance'])
        distance_start=QtWidgets.QDoubleSpinBox();distance_start.setRange(0,1320);distance_start.setValue(330);distance_start.setSuffix(' ft')
        distance_end=QtWidgets.QDoubleSpinBox();distance_end.setRange(1,2000);distance_end.setValue(1320);distance_end.setSuffix(' ft')
        use_speed=QtWidgets.QCheckBox('Speed');use_speed.setChecked(True);use_rpm=QtWidgets.QCheckBox('Engine RPM');use_rpm.setChecked(True);use_ds=QtWidgets.QCheckBox('Driveshaft RPM');use_ds.setChecked(True);use_g=QtWidgets.QCheckBox('Longitudinal G');use_g.setChecked(True)
        use_et=QtWidgets.QCheckBox('Official ET incrementals');use_et.setChecked(True);use_trap=QtWidgets.QCheckBox('Official trap MPH');use_trap.setChecked(True)
        max_points=QtWidgets.QSpinBox();max_points.setRange(10,500);max_points.setValue(90)
        evidence_layout.addWidget(QtWidgets.QLabel('Telemetry domain'),0,0);evidence_layout.addWidget(evidence_domain,0,1);evidence_layout.addWidget(QtWidgets.QLabel('Window'),0,2);evidence_layout.addWidget(distance_start,0,3);evidence_layout.addWidget(distance_end,0,4)
        evidence_layout.addWidget(QtWidgets.QLabel('Telemetry'),1,0);evidence_layout.addWidget(use_speed,1,1);evidence_layout.addWidget(use_rpm,1,2);evidence_layout.addWidget(use_ds,1,3);evidence_layout.addWidget(use_g,1,4)
        evidence_layout.addWidget(QtWidgets.QLabel('Timing'),2,0);evidence_layout.addWidget(use_et,2,1,1,2);evidence_layout.addWidget(use_trap,2,3);evidence_layout.addWidget(QtWidgets.QLabel('Max samples/channel'),3,0);evidence_layout.addWidget(max_points,3,1)
        evidence_help=QtWidgets.QLabel('Distance mode lets you exclude launch/shake or other untrusted regions without deleting data. Residuals remain model − measured and are normalized by engineering uncertainty.');evidence_help.setWordWrap(True);evidence_layout.addWidget(evidence_help,4,0,1,5)
        lay.addWidget(evidence_box)
        run_box=QtWidgets.QGroupBox('Run Participation / Local Corrections'); run_lay=QtWidgets.QVBoxLayout(run_box)
        run_table=QtWidgets.QTableWidget(len(handles),7);run_table.setHorizontalHeaderLabels(['Run','Role','Use telemetry','Use timing','Power corr','Traction corr','Rollout corr']);run_table.verticalHeader().setVisible(False)
        run_controls=[]
        for rr,x in enumerate(handles):
            role='Main' if x is h else (x.role or 'overlay').title()
            run_table.setItem(rr,0,QtWidgets.QTableWidgetItem(x.label));run_table.setItem(rr,1,QtWidgets.QTableWidgetItem(role))
            cb_tel=QtWidgets.QCheckBox();cb_tel.setChecked(True);cb_time=QtWidgets.QCheckBox();cb_time.setChecked(True);cb_pow=QtWidgets.QCheckBox();cb_tr=QtWidgets.QCheckBox();cb_roll=QtWidgets.QCheckBox()
            for cc,cb in enumerate((cb_tel,cb_time,cb_pow,cb_tr,cb_roll),2):run_table.setCellWidget(rr,cc,cb)
            run_controls.append((x,cb_tel,cb_time,cb_pow,cb_tr,cb_roll))
        run_table.horizontalHeader().setSectionResizeMode(0,QtWidgets.QHeaderView.Stretch)
        for cc in range(1,7):run_table.horizontalHeader().setSectionResizeMode(cc,QtWidgets.QHeaderView.ResizeToContents)
        run_table.setMaximumHeight(150+28*len(handles));run_lay.addWidget(run_table)
        run_help=QtWidgets.QLabel('Local corrections are tightly regularized nuisance terms. Leave the baseline Run with none whenever possible; only allow a correction when that pass may legitimately differ in track/rollout/power state.');run_help.setWordWrap(True);run_lay.addWidget(run_help);lay.addWidget(run_box)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel);buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('Run Inference');buttons.accepted.connect(dlg.accept);buttons.rejected.connect(dlg.reject);lay.addWidget(buttons)
        if dlg.exec()!=QtWidgets.QDialog.Accepted:return
        selected=[cb.text() for cb in checks if cb.isChecked()]
        if not selected:QtWidgets.QMessageBox.information(self,'Inference Center','Select at least one unknown.');return
        timing_weights={}
        if not use_et.isChecked():
            timing_weights.update({k:0.0 for k in ('sixty_ft_s','three_thirty_ft_s','eighth_mile_s','thousand_ft_s','quarter_mile_s')})
        if not use_trap.isChecked():
            timing_weights.update({'eighth_mile_mph':0.0,'quarter_mile_mph':0.0})
        telemetry_weights={'speed_mph':1.0 if use_speed.isChecked() else 0.0,'engine_rpm':1.0 if use_rpm.isChecked() else 0.0,'driveshaft_rpm':1.0 if use_ds.isChecked() else 0.0,'longitudinal_g':1.0 if use_g.isChecked() else 0.0}
        domain='distance' if evidence_domain.currentIndex()==1 else 'time'
        windows=[]
        if domain=='distance':
            if distance_end.value()<=distance_start.value():QtWidgets.QMessageBox.warning(self,'Inference Center','Downtrack window end must exceed start.');return
            windows=[FitDistanceWindow('Selected downtrack',float(distance_start.value()),float(distance_end.value()),1.0)]
        evidence=FitEvidencePolicy(telemetry_domain=domain,timing_weights=timing_weights,telemetry_weights=telemetry_weights,distance_windows=windows,max_points=int(max_points.value()),distance_step_ft=5.0)
        runs=[]; nuisance=[]; run_policy_meta=[]
        all_timing_fields=('sixty_ft_s','three_thirty_ft_s','eighth_mile_s','eighth_mile_mph','thousand_ft_s','quarter_mile_s','quarter_mile_mph')
        for x,cb_tel,cb_time,cb_pow,cb_tr,cb_roll in run_controls:
            ev=FitEvidencePolicy.from_dict(evidence.to_dict())
            if not cb_tel.isChecked():ev.telemetry_weights={k:0.0 for k in ('speed_mph','engine_rpm','driveshaft_rpm','longitudinal_g')}
            if not cb_time.isChecked():ev.timing_weights={**ev.timing_weights,**{k:0.0 for k in all_timing_fields}}
            local=[]
            if cb_pow.isChecked():local.append('power_scale')
            if cb_tr.isChecked():local.append('traction_delta')
            if cb_roll.isChecked():local.append('rollout_delta_in')
            nuisance.extend(local)
            role='primary' if x is h else (x.role or 'comparison')
            runs.append(FitRun(x.label,x.run.environment,x.run.timing,x.run,evidence=ev,nuisance_terms=local,source_run_id=str(x.catalog_run_id or ''),role=role))
            run_policy_meta.append({'name':x.label,'source_run_id':str(x.catalog_run_id or ''),'role':role,'nuisance_terms':local,'evidence':ev.to_dict()})
        nuisance=list(dict.fromkeys(nuisance))
        definition=FitStudyDefinition(name=f'{h.label} joint reconstruction',shared_unknowns=list(selected),nuisance_terms=nuisance,max_nfev=90,fit_dt_s=.010,final_dt_s=.0025)
        try:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            fit,fit_package=run_joint_fit_study(vehicle,runs,definition)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self,'Inference failed',str(exc));return
        finally:QtWidgets.QApplication.restoreOverrideCursor()
        # Persist the calibrated portable model and parameter-level provenance.
        ov=fit.optimized_vehicle
        direct={'traction_index':'traction_index','final_drive_ratio':'final_drive_ratio','final_drive_efficiency':'final_drive_efficiency','tire_diameter_in':'tire_diameter_in','tire_growth_scale':'tire_growth_scale','weight_lb':'weight_lb','cg_height_in':'cg_height_in','static_front_weight_lb':'static_front_weight_lb','front_overhang_in':'front_overhang_in','rollout_in':'rollout_in'}
        est=fit.estimates
        for _,row in est.iterrows():
            internal=str(row.get('internal_name',''))
            ident=str(row.get('identifiability','Weak'))
            conf={'Good':0.9,'Moderate':0.65,'Weak':0.3}.get(ident,0.5)
            if internal in direct:
                val=getattr(ov,direct[internal])
                set_vehicle_input(h.run,direct[internal],val,'','inferred',confidence=conf,lower=row.get('95%_low'),upper=row.get('95%_high'),method='multi-run nonlinear inverse fit',runs=[x.label for x in handles],notes=ident)
            else:
                set_parameter(h.run,f'inference.{internal}',float(row.get('estimate',np.nan)),'','inferred',confidence=conf,lower=row.get('95%_low'),upper=row.get('95%_high'),method='multi-run nonlinear inverse fit',runs=[x.label for x in handles],notes=ident)
        if any(x=='power_scale' or x.startswith('curve_node_') for x in selected):
            set_vehicle_input(h.run,'dyno_rpm',list(ov.dyno.rpm),'rpm','inferred',method='multi-run nonlinear inverse fit',runs=[x.label for x in handles])
            set_vehicle_input(h.run,'dyno_hp',list(ov.dyno.hp),'hp','inferred',method='multi-run nonlinear inverse fit',runs=[x.label for x in handles])
            h.run.metadata['inferred_dyno_curve']={'rpm':list(ov.dyno.rpm),'hp':list(ov.dyno.hp)}
        h.run.metadata['last_inference_notes']=list(fit.identifiability_notes)
        h.run.metadata['last_fit_evidence_policy']=evidence.to_dict(); h.run.metadata['last_fit_run_policies']=run_policy_meta; h.run.metadata['last_fit_unknowns']=list(selected); h.run.metadata['last_fit_nuisance_terms']=list(nuisance)
        self.store.changed.emit();self.store.activeChanged.emit(h)
        out=QtWidgets.QDialog(self);out.setWindowTitle('Inference Results');out.resize(900,580);ol=QtWidgets.QVBoxLayout(out)
        label=QtWidgets.QLabel(('Fit completed successfully. ' if fit.success else 'Fit returned a provisional result. ')+fit.message);label.setWordWrap(True);ol.addWidget(label)
        rt=QtWidgets.QTableWidget(len(est),6);rt.setHorizontalHeaderLabels(['Parameter','Estimate','95% low','95% high','Correlation','Identifiability'])
        for r,row in est.reset_index(drop=True).iterrows():
            vals=[row.get('parameter',''),row.get('estimate',''),row.get('95%_low',''),row.get('95%_high',''),row.get('max_abs_correlation',''),row.get('identifiability','')]
            for c,v in enumerate(vals):rt.setItem(r,c,QtWidgets.QTableWidgetItem(str(v)))
        rt.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch);ol.addWidget(rt,1)
        quality=fit_package.residual_summary.get('by_run',[])
        if quality:
            qbox=QtWidgets.QGroupBox('Fit Quality by Run');ql=QtWidgets.QVBoxLayout(qbox)
            qt=QtWidgets.QTableWidget(len(quality),5);qt.setHorizontalHeaderLabels(['Run','Evidence','RMS normalized error','Mean |error|','Objective share'])
            for rr,row in enumerate(quality):
                vals=[row.get('run',''),row.get('count',''),f"{float(row.get('rms_normalized_residual',0)):.3f}",f"{float(row.get('mean_abs_normalized_residual',0)):.3f}",f"{100*float(row.get('objective_fraction',0)):.1f}%"]
                for cc,v in enumerate(vals):qt.setItem(rr,cc,QtWidgets.QTableWidgetItem(str(v)))
            qt.horizontalHeader().setSectionResizeMode(0,QtWidgets.QHeaderView.Stretch)
            for cc in range(1,5):qt.horizontalHeader().setSectionResizeMode(cc,QtWidgets.QHeaderView.ResizeToContents)
            qt.setMaximumHeight(95+26*len(quality));ql.addWidget(qt);ol.addWidget(qbox)
        if fit.identifiability_notes:
            notes=QtWidgets.QPlainTextEdit('\n'.join('• '+x for x in fit.identifiability_notes));notes.setReadOnly(True);notes.setMaximumHeight(150);ol.addWidget(notes)
        profilefit=QtWidgets.QPushButton('Profile Shared Parameter…');ol.addWidget(profilefit)
        def profile_shared_parameter():
            choices=[str(x) for x in definition.shared_unknowns]
            if not choices:return
            name,ok=QtWidgets.QInputDialog.getItem(out,'Profile Shared Parameter','Parameter',choices,0,False)
            if not ok or not name:return
            try:
                QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
                prof=profile_parameter(vehicle,runs,definition,fit,str(name),points=7,span_fraction=.12)
                fit_package.profiles[str(name)]=prof.to_dict()
            except Exception as exc:
                QtWidgets.QMessageBox.warning(out,'Profile Shared Parameter',str(exc));return
            finally:QtWidgets.QApplication.restoreOverrideCursor()
            pdialog=QtWidgets.QDialog(out);pdialog.setWindowTitle(f'Profile Objective — {name}');pdialog.resize(720,420);pl=QtWidgets.QVBoxLayout(pdialog)
            info=QtWidgets.QLabel(f"Status: {prof.status}   Practical interval in scan: {prof.practical_low} to {prof.practical_high}   Threshold Δobjective: {prof.threshold_delta_objective:g}");info.setWordWrap(True);pl.addWidget(info)
            pt=QtWidgets.QTableWidget(len(prof.rows),4);pt.setHorizontalHeaderLabels(['Value','Objective','Δ objective','Success'])
            for rr,row in enumerate(prof.rows):
                vals=[row.get('value',''),row.get('objective',''),row.get('delta_objective',''),row.get('success','')]
                for cc,v in enumerate(vals):pt.setItem(rr,cc,QtWidgets.QTableWidgetItem(str(v)))
            pt.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch);pl.addWidget(pt,1)
            note=QtWidgets.QLabel(prof.note);note.setWordWrap(True);pl.addWidget(note)
            close=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close);close.rejected.connect(pdialog.reject);close.clicked.connect(pdialog.accept);pl.addWidget(close);pdialog.exec()
        profilefit.clicked.connect(profile_shared_parameter)
        influencefit=QtWidgets.QPushButton('Run Influence (Leave-One-Out)…');influencefit.setEnabled(len(runs)>=2);ol.addWidget(influencefit)
        def run_influence_analysis():
            try:
                QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
                influence=leave_one_run_out_influence(vehicle,runs,definition,fit)
                fit_package.run_influence=influence
            except Exception as exc:
                QtWidgets.QMessageBox.warning(out,'Run Influence',str(exc));return
            finally:QtWidgets.QApplication.restoreOverrideCursor()
            rows=influence.get('runs',[])
            idlg=QtWidgets.QDialog(out);idlg.setWindowTitle('Leave-One-Run-Out Influence');idlg.resize(820,420);il=QtWidgets.QVBoxLayout(idlg)
            info=QtWidgets.QLabel(influence.get('note',''));info.setWordWrap(True);il.addWidget(info)
            it=QtWidgets.QTableWidget(len(rows),5);it.setHorizontalHeaderLabels(['Omitted Run','Status','Dominant parameter','Max bound-span shift','Largest parameter Δ'])
            for rr,row in enumerate(rows):
                shifts=row.get('parameter_shifts') or [];largest=max(shifts,key=lambda x:float(x.get('abs_delta',0)),default={})
                frac=row.get('max_bound_span_fraction');frac_text='' if frac is None else f"{100*float(frac):.2f}%"
                delta=largest.get('delta','') if largest else ''
                vals=[row.get('omitted_run',''),row.get('status',''),row.get('dominant_parameter',''),frac_text,delta]
                for cc,v in enumerate(vals):it.setItem(rr,cc,QtWidgets.QTableWidgetItem(str(v)))
            it.horizontalHeader().setSectionResizeMode(0,QtWidgets.QHeaderView.Stretch)
            for cc in range(1,5):it.horizontalHeader().setSectionResizeMode(cc,QtWidgets.QHeaderView.ResizeToContents)
            il.addWidget(it,1);bb2=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close);bb2.rejected.connect(idlg.reject);bb2.clicked.connect(idlg.accept);il.addWidget(bb2);idlg.exec()
        influencefit.clicked.connect(run_influence_analysis)
        savefit=QtWidgets.QPushButton('Save Joint Fit Study…');ol.addWidget(savefit)
        def save_joint_fit():
            path,_=QtWidgets.QFileDialog.getSaveFileName(out,'Save Joint Fit Study',f'{h.label}_joint_fit.nhrafit','NHRA Fit Study (*.nhrafit);;JSON (*.json)')
            if path:
                try:save_fit_study_package(path,fit_package);self.statusBar().showMessage(f'Saved fit study: {path}',6000)
                except Exception as exc:QtWidgets.QMessageBox.warning(out,'Save Joint Fit Study',str(exc))
        savefit.clicked.connect(save_joint_fit)
        bb=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close);bb.rejected.connect(out.reject);bb.clicked.connect(out.accept);ol.addWidget(bb);out.exec()

    def _create_compare_run(self):
        h=self.store.active
        if not h:return
        critical=self._critical_model_missing(h.run,'compare')
        if critical:
            QtWidgets.QMessageBox.warning(self,'Create Compare Run','A generated compare run requires a calibrated model.\n\nMissing: '+', '.join(critical));return
        vehicle,_=vehicle_from_run(h.run,require_explicit=False)
        env=Environment.from_dict(h.run.environment.to_dict())
        dlg=QtWidgets.QDialog(self);dlg.setWindowTitle('Create Compare Run');dlg.resize(560,560);form=QtWidgets.QFormLayout(dlg)
        name=QtWidgets.QLineEdit(f'{h.label} — Compare')
        power=QtWidgets.QDoubleSpinBox();power.setRange(.25,3.0);power.setDecimals(4);power.setValue(1.0)
        weight=QtWidgets.QDoubleSpinBox();weight.setRange(100,20000);weight.setDecimals(1);weight.setValue(vehicle.weight_lb)
        final=QtWidgets.QDoubleSpinBox();final.setRange(.5,15);final.setDecimals(4);final.setValue(vehicle.final_drive_ratio)
        tire=QtWidgets.QDoubleSpinBox();tire.setRange(5,100);tire.setDecimals(3);tire.setValue(vehicle.tire_diameter_in)
        traction=QtWidgets.QDoubleSpinBox();traction.setRange(1,10);traction.setDecimals(3);traction.setValue(vehicle.traction_index)
        gears=QtWidgets.QLineEdit(', '.join(f'{x:g}' for x in vehicle.gear_ratios));shifts=QtWidgets.QLineEdit(', '.join(f'{x:g}' for x in vehicle.shift_rpms))
        temp=QtWidgets.QDoubleSpinBox();temp.setRange(-50,180);temp.setValue(env.temperature_f)
        baro=QtWidgets.QDoubleSpinBox();baro.setRange(20,35);baro.setDecimals(3);baro.setValue(env.barometer_inhg)
        humidity=QtWidgets.QDoubleSpinBox();humidity.setRange(0,100);humidity.setValue(env.humidity_pct)
        wind=QtWidgets.QDoubleSpinBox();wind.setRange(-100,100);wind.setValue(env.wind_mph)
        track=QtWidgets.QDoubleSpinBox();track.setRange(0,220);track.setValue(env.track_temperature_f)
        rows=[('Session name',name),('Power multiplier',power),('Race weight [lb]',weight),('Final drive ratio',final),('Tire diameter [in]',tire),('Traction index',traction),('Gear ratios',gears),('Shift RPMs',shifts),('Air temperature [°F]',temp),('Barometer [inHg]',baro),('Humidity [%]',humidity),('Wind [mph]',wind),('Track temperature [°F]',track)]
        for label,w in rows:form.addRow(label,w)
        note=QtWidgets.QLabel('The generated pass is a normal telemetry session and can be overlaid, aligned, plotted and analyzed exactly like a measured run.');note.setWordWrap(True);form.addRow(note)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel);buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('Generate');buttons.accepted.connect(dlg.accept);buttons.rejected.connect(dlg.reject);form.addRow(buttons)
        if dlg.exec()!=QtWidgets.QDialog.Accepted:return
        try:
            changes={'power_scale':power.value(),'weight_lb':weight.value(),'final_drive_ratio':final.value(),'tire_diameter_in':tire.value(),'traction_index':traction.value(),'gear_ratios':gears.text(),'shift_rpms':shifts.text()}
            env.temperature_f=temp.value();env.barometer_inhg=baro.value();env.humidity_pct=humidity.value();env.wind_mph=wind.value();env.track_temperature_f=track.value()
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            scenario=create_compare_run(h.label,vehicle,env,changes,name=name.text().strip() or None)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self,'Compare run generation failed',str(exc));return
        finally:QtWidgets.QApplication.restoreOverrideCursor()
        default_dir=str(Path(h.path).parent) if h.path and not h.path.startswith('generated:') else str(Path.home())
        safe=''.join(c if c.isalnum() or c in (' ','-','_') else '_' for c in scenario.run.name).strip().replace(' ','_')
        outpath,_=QtWidgets.QFileDialog.getSaveFileName(self,'Save generated compare telemetry',str(Path(default_dir)/(safe+'.csv')),'CSV telemetry (*.csv)')
        if not outpath:return
        if not outpath.lower().endswith('.csv'):outpath+='.csv'
        scenario.run.data.to_csv(outpath,index=False)
        nh=self.store.add(outpath,scenario.run);nh.role='reference';nh.display_name=scenario.run.name
        self.store.changed.emit();self.statusBar().showMessage(f'Generated scratch compare session: {scenario.run.name}',7000)

    @staticmethod
    def _catalog_session_display_name(record: Dict[str, Any], asset_filename: str = '', *, multiple: bool = False) -> str:
        parts=[]
        driver=str(record.get('driver_name') or '').strip()
        round_name=str(record.get('round') or '').strip()
        if driver:parts.append(driver)
        if round_name:parts.append(round_name)
        if multiple and asset_filename:
            parts.append(Path(asset_filename).stem)
        return ' — '.join(parts) or Path(asset_filename).stem or str(record.get('run_key') or 'Run')

    def _restore_catalog_launch_zero(self, handle: RunHandle) -> None:
        if not handle.catalog_asset_id:
            return
        mapping=self.catalog.get_time_mapping(handle.catalog_asset_id)
        if not mapping:
            return
        method=str(mapping.get('method') or '').lower()
        scale=float(mapping.get('scale') or 1.0)
        if method.startswith('manual launch zero') and abs(scale) > 1e-12:
            set_launch_time_override(handle.run, -float(mapping.get('offset_s') or 0.0)/scale)

    def _attach_local_telemetry_to_selected_run(self):
        run_id=self.run_browser.selected_run_id() if hasattr(self,'run_browser') else ''
        if not run_id:
            QtWidgets.QMessageBox.information(self,'Attach Data Log','Select an authoritative Run in the NHRA Tech Services Runs browser first.')
            return
        self._attach_local_telemetry_to_run(run_id)

    def _attach_local_telemetry_to_run(self, run_id: str):
        """Explicitly associate local telemetry with one authoritative Run.

        This is a local workstation bridge only. It intentionally performs no
        Tech Services write and never chooses a Run from a filename. The user
        must select the canonical Run first.
        """
        record=self.catalog.get_run(run_id)
        if record is None:
            QtWidgets.QMessageBox.warning(self,'Attach Data Log',f'Run {run_id} was not found in the local catalog.')
            return
        files,_=QtWidgets.QFileDialog.getOpenFileNames(
            self,
            f"Attach data log — {record.get('driver_name') or ''} {record.get('round') or ''}".strip(),
            '',
            qt_file_dialog_filter()
        )
        files=[str(Path(x)) for x in files if x and Path(x).is_file()]
        if not files:return
        opened=0;existing_count=0;errors=[]
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            for path in files:
                try:
                    racepak_cfg_path=''
                    racepak_cfg_source=''
                    profile={}
                    if Path(path).suffix.lower()=='.ddf':
                        profile=matching_racepak_config_profile(record)
                        racepak_cfg_path=racepak_config_path_from_profile(profile) if profile else ''
                        if racepak_cfg_path:
                            racepak_cfg_source='context_profile'
                    run=load_telemetry(path, racepak_config_path=racepak_cfg_path or None)
                    _rid,asset_id,session_id=register_opened_telemetry(
                        self.catalog,path,run,run_id=run_id,managed=True,local_attachment=True
                    )
                    if str(run.metadata.get('source_format') or '').lower().startswith('racepak raw ddf') and run.metadata.get('ddf_config_path'):
                        cfg_record=profile.get('config') if racepak_cfg_source=='context_profile' and isinstance(profile,dict) else str(run.metadata['ddf_config_path'])
                        binding=racepak_exact_config_record(cfg_record, source=racepak_cfg_source or 'sibling_discovery')
                        self.catalog.update_telemetry_session_settings(asset_id,{'racepak_ddf_config':binding})
                    asset=self.catalog.get_asset(asset_id) or {}
                    stored_path=self.catalog.local_asset_read_path(asset_id) or str(asset.get('local_path') or path)
                    already=next((h for h in self.store.runs if str(h.catalog_asset_id or '')==str(asset_id)),None)
                    if already is not None:
                        existing_count+=1
                        try:self.store.set_active(self.store.runs.index(already))
                        except ValueError:pass
                        continue
                    h=self.store.add(stored_path,run,activate=(opened==0))
                    h.catalog_run_id=run_id;h.catalog_asset_id=asset_id;h.catalog_session_id=session_id
                    h.display_name=self._catalog_session_display_name(record,str(asset.get('filename') or Path(path).name),multiple=(len(files)>1));self._restore_catalog_launch_zero(h)
                    opened+=1
                except Exception as exc:
                    logging.exception('Could not attach telemetry %s to catalog run %s',path,run_id)
                    errors.append(f'{Path(path).name}: {exc}')
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.run_browser.refresh();self.asset_browser.set_run(run_id);self.catalog_run_details.set_run(run_id)
        if hasattr(self,'run_workspace'):self.run_workspace.set_run(run_id)
        if opened or existing_count:
            timing=record.get('timing') or {}
            inherited=[]
            if timing:inherited.append('official timing')
            if record.get('weather'):inherited.append('official weather')
            context=', '.join(inherited) if inherited else 'canonical Run identity'
            self.statusBar().showMessage(f'Attached {opened} data log(s) to selected Run; inherited {context}. The association is stored locally.',8000)
        if errors:
            QtWidgets.QMessageBox.warning(self,'Attach Data Log','Some files could not be attached:\n\n'+'\n'.join(errors))

    def _catalog_run_selected(self, run_id: str):
        """Keep the waveform/session context aligned with the selected canonical Run.

        Selection never performs a heavy disk decode on its own. If a data log
        for that Run is already loaded, it is reactivated immediately. If the
        association only exists in the persistent local catalog, the Run
        Workspace exposes it and Open Data loads it on demand.
        """
        rid=str(run_id or '')
        if not rid:
            return
        handle=next((h for h in self.store.runs if str(h.catalog_run_id or '')==rid),None)
        if handle is not None and handle is not self.store.active:
            try:self.store.set_active(self.store.runs.index(handle))
            except ValueError:pass
            return
        if handle is None:
            logs=[a for a in self.catalog.list_assets(rid) if a.get('asset_type')=='telemetry']
            local_logs=[a for a in logs if self.catalog.local_asset_read_path(str(a.get('id') or ''))]
            if local_logs:
                # An attached local data log should behave as part of the Run,
                # not as a separate file the user must remember to reopen. Delay
                # slightly so arrowing/searching through the list does not decode
                # every transient selection. The selected Run is re-checked before
                # any file is opened.
                self.statusBar().showMessage(f"{len(local_logs)} attached data log(s) available locally — loading selected Run…",2500)
                QtCore.QTimer.singleShot(300, lambda run_id=rid: self._auto_open_selected_run_data(run_id))
            elif logs:
                self.statusBar().showMessage(f"{len(logs)} data log(s) attached to this Run — choose Open Data to cache/load.",3500)

    def _auto_open_selected_run_data(self, run_id: str):
        rid=str(run_id or '')
        if not rid or self.run_browser.selected_run_id()!=rid:
            return
        if self._active_handle_for_catalog_run(rid) is not None:
            return
        local_logs=[a for a in self.catalog.list_assets(rid) if a.get('asset_type')=='telemetry' and self.catalog.local_asset_read_path(str(a.get('id') or ''))]
        if local_logs:
            self._open_catalog_run(rid, local_only=True, quiet=True)

    def _active_handle_for_catalog_run(self, run_id: str) -> Optional[RunHandle]:
        rid=str(run_id or '')
        active=self.store.active
        if active is not None and str(active.catalog_run_id or '')==rid:
            return active
        return next((h for h in self.store.runs if str(h.catalog_run_id or '')==rid),None)

    def _apply_profile_to_catalog_run(self, run_id: str, profile_key: str):
        h=self._active_handle_for_catalog_run(run_id)
        if h is None:
            self._open_catalog_run(run_id);h=self._active_handle_for_catalog_run(run_id)
        if h is None:
            QtWidgets.QMessageBox.information(self,'Run Workspace','Attach or open a data log for this Run before applying a waveform layout.');return
        try:self.store.set_active(self.store.runs.index(h))
        except Exception:pass
        self._apply_standard_profile_layout(profile_key)
        if hasattr(self,'run_workspace'):self.run_workspace.set_run(run_id)

    def _generate_standard_run_report(self, run_id: str, report_type: str):
        h=self._active_handle_for_catalog_run(run_id)
        if h is None:
            self._open_catalog_run(run_id);h=self._active_handle_for_catalog_run(run_id)
        if h is None:
            QtWidgets.QMessageBox.information(self,'Run Report','Attach or open a data log for this Run before generating a report.');return
        try:self.store.set_active(self.store.runs.index(h))
        except Exception:pass
        try:
            if report_type=='pro_stock_shift':
                report=attach_shift_report(h.run,profile='pro_stock')
                report_id,created=self.catalog.save_run_report(str(run_id),report,source_asset_id=h.catalog_asset_id or None,label='Pro Stock Shift Report')
                self.store.changed.emit()
                if hasattr(self,'run_workspace'):self.run_workspace.set_run(run_id)
                self.statusBar().showMessage(('Generated' if created else 'Reused existing')+f' Pro Stock shift report for Run {run_id}.',7000)
                return
            raise ValueError(f'Unsupported standardized report type: {report_type}')
        except Exception as exc:
            logging.exception('Standard Run report generation failed');QtWidgets.QMessageBox.warning(self,'Run Report',str(exc))

    def _open_catalog_run(self, run_id: str, *, local_only: bool = False, quiet: bool = False):
        record=self.catalog.get_run(run_id)
        if record is None:
            QtWidgets.QMessageBox.warning(self,'Run Browser',f'Run {run_id} was not found in the local catalog.');return
        assets=[a for a in self.catalog.list_assets(run_id) if a.get('asset_type')=='telemetry']
        if local_only:
            assets=[a for a in assets if self.catalog.local_asset_read_path(str(a.get('id') or ''))]
        if not assets:
            QtWidgets.QMessageBox.information(self,'Run Browser','This Run does not yet have a data log attached.');return
        errors=[];opened=0;existing_count=0
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            for asset in assets:
                path=self.catalog.local_asset_read_path(str(asset.get('id') or ''))
                try:
                    existing=next((h for h in self.store.runs if str(h.catalog_asset_id or '')==str(asset['id'])),None)
                    if existing is not None:
                        existing_count+=1
                        if opened==0:
                            try:self.store.set_active(self.store.runs.index(existing))
                            except ValueError:pass
                        continue
                    if not path or not Path(path).is_file():
                        ensure_asset_cached(self.catalog,self.tech_services,str(asset['id']))
                        path=self.catalog.local_asset_read_path(str(asset['id']))
                    if not path or not Path(path).is_file():
                        raise FileNotFoundError(asset.get('filename') or asset.get('id'))
                    existing_session=self.catalog.get_telemetry_session(str(asset['id'])) or {}
                    existing_settings=existing_session.get('settings') or {}
                    racepak_cfg_path=''
                    racepak_cfg_source=''
                    _cfg_rec={}
                    if Path(str(asset.get('filename') or path)).suffix.lower()=='.ddf':
                        racepak_cfg_path,racepak_cfg_source,_cfg_rec=resolve_racepak_config_path(record,session_settings=existing_settings)
                    run=load_telemetry(path, racepak_config_path=racepak_cfg_path or None)
                    session_id=self.catalog.ensure_telemetry_session(str(asset['id']),display_name=str(asset.get('filename') or Path(path).stem),vendor=run.vendor,channel_summary={'channels':len(run.data.columns),'canonical_roles':sorted(run.channel_map.keys())})
                    if str(run.metadata.get('source_format') or '').lower().startswith('racepak raw ddf') and run.metadata.get('ddf_config_path') and not racepak_exact_config_binding(existing_settings):
                        cfg_record=_cfg_rec.get('config') if racepak_cfg_source=='context_profile' and isinstance(_cfg_rec,dict) else str(run.metadata['ddf_config_path'])
                        binding=racepak_exact_config_record(cfg_record, source=racepak_cfg_source or 'sibling_discovery')
                        self.catalog.update_telemetry_session_settings(str(asset['id']),{'racepak_ddf_config':binding})
                    apply_catalog_run_authority(self.catalog,run_id,run)
                    # Mapping precedence is deliberate and conservative:
                    # importer auto < exact context profile < this exact data log.
                    profile_overrides=learned_common_channel_overrides(run)
                    if profile_overrides:
                        run=apply_channel_overrides(run,profile_overrides,{})
                    session=self.catalog.get_telemetry_session(str(asset['id'])) or {}
                    settings=session.get('settings') or {}
                    asset_overrides=dict(settings.get('common_channel_overrides') or {}) if isinstance(settings,dict) else {}
                    unit_overrides=dict(settings.get('unit_overrides') or {}) if isinstance(settings,dict) else {}
                    if asset_overrides or unit_overrides:
                        run=apply_channel_overrides(run,asset_overrides,unit_overrides)
                    run.metadata['catalog_asset_id']=asset['id'];run.metadata['catalog_telemetry_session_id']=session_id
                    h=self.store.add(path,run,activate=(opened==0 and existing_count==0),apply_preferences=False)
                    h.channel_overrides={**profile_overrides,**asset_overrides};h.unit_overrides=unit_overrides
                    h.catalog_run_id=run_id;h.catalog_asset_id=str(asset['id']);h.catalog_session_id=session_id;h.display_name=self._catalog_session_display_name(record,str(asset.get('filename') or Path(path).name),multiple=(len(assets)>1));self._restore_catalog_launch_zero(h)
                    opened+=1
                except Exception as exc:
                    logging.exception('Could not open catalog asset %s',asset.get('id'));errors.append(f"{asset.get('filename')}: {exc}")
        finally:QtWidgets.QApplication.restoreOverrideCursor()
        if hasattr(self,'run_workspace'):self.run_workspace.set_run(run_id)
        if opened or existing_count:
            self.statusBar().showMessage(f"Opened catalog run: {record.get('event_name') or 'Local'} — {opened} opened, {existing_count} already loaded",7000)
        if errors and not quiet:QtWidgets.QMessageBox.warning(self,'Run Browser','Some assets were unavailable:\n\n'+'\n'.join(errors))

    def _case_review_time_changed(self, case_id: str, case_time_s: float):
        """Drive the active telemetry cursor from the shared AnalysisCase clock."""
        h=self.store.active
        if h is None or not h.catalog_run_id:return
        try:
            if not any(str(r['id'])==str(h.catalog_run_id) for r in self.catalog.list_case_runs(case_id)):return
            mode=self.xmode.currentText().strip().lower()
            if mode.startswith('distance') or mode.startswith('sample'):
                return
            asset_time=None
            if h.catalog_asset_id and self.catalog.get_time_mapping(h.catalog_asset_id) is not None:
                asset_time=self.catalog.map_case_time_to_asset(case_id,h.catalog_asset_id,float(case_time_s))
            if mode.startswith('logger') and asset_time is not None:
                x=float(asset_time)
            elif asset_time is not None:
                try:launch=float(detect_drag_pass_window(h.run).launch_time_s)
                except Exception:launch=0.0
                x=float(asset_time)-launch+float(h.time_alignment_s)
            else:
                x=self.catalog.map_case_time_to_run(case_id,h.catalog_run_id,float(case_time_s))+float(h.time_alignment_s)
            self.cursors.x=float(x);self.cursors.moved.emit(float(x))
        except Exception:
            logging.debug('Could not map Case cursor to active telemetry session',exc_info=True)

    def _keep_asset_offline(self, asset_id: str):
        try:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            path=ensure_asset_cached(self.catalog,self.tech_services,str(asset_id))
            self.asset_browser.refresh();self.run_browser.refresh();self.case_timeline.refresh();self.case_review.refresh()
            self.statusBar().showMessage(f'Cached synchronized source: {Path(path).name}',7000)
        except Exception as exc:
            logging.exception('Cache synchronized source failed');QtWidgets.QMessageBox.critical(self,'Cache Source',str(exc))
        finally:QtWidgets.QApplication.restoreOverrideCursor()

    def _keep_active_offline(self):
        h=self.store.active
        if not h:return
        if not h.catalog_asset_id:
            QtWidgets.QMessageBox.information(self,'Cache Offline','This is a scratch session with no catalog attachment. Attach it manually to an authoritative Run first, or open a mirrored Tech Services asset.');return
        try:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            path=ensure_asset_cached(self.catalog,self.tech_services,h.catalog_asset_id);h.path=path
            asset=self.catalog.get_asset(h.catalog_asset_id) or {};label='Tech Services asset' if asset.get('source_kind')=='tech_services' else 'local Run attachment';self.run_browser.refresh();self.asset_browser.refresh();self.statusBar().showMessage(f'Active {label} is stored locally and SHA-256 verified.',7000)
        except Exception as exc:
            logging.exception('Keep offline failed');QtWidgets.QMessageBox.critical(self,'Cache Offline',str(exc))
        finally:QtWidgets.QApplication.restoreOverrideCursor()

    def _keep_run_offline(self, run_id: str):
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try: result=cache_run(self.catalog,self.tech_services,run_id)
        except Exception as exc:
            logging.exception('Cache run failed');QtWidgets.QMessageBox.critical(self,'Cache Run',str(exc));return
        finally: QtWidgets.QApplication.restoreOverrideCursor()
        self.run_browser.refresh();self.asset_browser.refresh();self.statusBar().showMessage(f"Run cache: {result.cached} downloaded, {result.already_cached} already cached.",6000)
        if result.errors: QtWidgets.QMessageBox.warning(self,'Cache Run','Some assets could not be cached:\n\n'+'\n'.join(f"{e['filename']}: {e['error']}" for e in result.errors[:30]))

    def _keep_event_offline(self, event_id: str):
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try: result=cache_event(self.catalog,self.tech_services,event_id)
        except Exception as exc:
            logging.exception('Cache event failed');QtWidgets.QMessageBox.critical(self,'Cache Event',str(exc));return
        finally: QtWidgets.QApplication.restoreOverrideCursor()
        self.run_browser.refresh();self.asset_browser.refresh();self.statusBar().showMessage(f"Event cache: {result.cached} downloaded, {result.already_cached} already cached.",7000)
        if result.errors: QtWidgets.QMessageBox.warning(self,'Cache Event','Some assets could not be cached:\n\n'+'\n'.join(f"{e['filename']}: {e['error']}" for e in result.errors[:30]))

    def _apply_sync_snapshot(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Apply Tech Services Snapshot','','JSON (*.json);;All Files (*)')
        if not path:return
        try:
            payload=json.loads(Path(path).read_text(encoding='utf-8'))
            result=apply_tech_services_snapshot(self.catalog,payload)
            self.run_browser.refresh();self.case_browser.refresh();self.case_timeline.refresh();self.case_review.refresh()
            QtWidgets.QMessageBox.information(self,'Tech Services Sync',f"Tech Services snapshot applied.\n\nEvents: +{result.events_created} / {result.events_updated} updated\nRuns: +{result.runs_created} / {result.runs_updated} updated\nAssets: +{result.assets_created} / {result.assets_updated} updated\nCursor: {result.cursor or '(none)'}")
        except Exception as exc:
            logging.exception('Tech Services snapshot apply failed');QtWidgets.QMessageBox.critical(self,'Tech Services Sync',str(exc))

    def _create_analysis_case(self, run_id: str):
        record=self.catalog.get_run(run_id) or {}
        choices=['Incident','Performance / Reconstruction','Parity','Development','Aerodynamics','General Engineering']
        display,ok=QtWidgets.QInputDialog.getItem(self,'New Analysis Case','Case type:',choices,0,False)
        if not ok:return
        kind_map={'Incident':'incident','Performance / Reconstruction':'performance','Parity':'parity','Development':'development','Aerodynamics':'aero','General Engineering':'engineering'};kind=kind_map.get(display,'engineering')
        stem=record.get('run_key') or record.get('run_datetime') or 'run';default=f"{display} — {stem}"
        title,ok=QtWidgets.QInputDialog.getText(self,'New Analysis Case','Case title:',text=default)
        if not ok or not title.strip():return
        case_id=self.catalog.create_analysis_case(title.strip(),case_type=kind,primary_run_id=run_id)
        self.run_browser.refresh();self.case_browser.refresh();self.case_timeline.refresh();QtWidgets.QMessageBox.information(self,'Analysis Case',f'Created {display.lower()} case {case_id}.\n\nThis Run is the primary pass. You can add baseline, comparison, or reference Runs without changing permanent Run/Asset ownership.')

    def _add_selected_run_to_case(self, case_id: str):
        run_id=self.run_browser.selected_run_id()
        if not run_id:
            QtWidgets.QMessageBox.information(self,'Add Run to Case','Select the Run you want to add in the NHRA Tech Services Runs browser first.');return
        roles=['Comparison','Baseline','Reference','Primary']
        display,ok=QtWidgets.QInputDialog.getItem(self,'Add Run to Analysis Case','Run role:',roles,0,False)
        if not ok:return
        role=display.lower()
        try:
            self.catalog.add_run_to_case(case_id,run_id,role=role);self.case_browser.refresh();self.statusBar().showMessage(f'Added selected Run to analysis case as {role}.',6000)
        except Exception as exc:QtWidgets.QMessageBox.critical(self,'Add Run to Case',str(exc))

    def _cache_analysis_case(self, case_id: str):
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:result=cache_case(self.catalog,self.tech_services,case_id)
        except Exception as exc:
            logging.exception('Cache analysis case failed');QtWidgets.QMessageBox.critical(self,'Cache Analysis Case',str(exc));return
        finally:QtWidgets.QApplication.restoreOverrideCursor()
        self.run_browser.refresh();self.case_browser.refresh();self.case_timeline.refresh();self.case_review.refresh();self.asset_browser.refresh();self.statusBar().showMessage(f"Case cache: {result.cached} downloaded, {result.already_cached} already cached.",7000)
        if result.errors:QtWidgets.QMessageBox.warning(self,'Cache Analysis Case','Some assets could not be cached:\n\n'+'\n'.join(f"{e['filename']}: {e['error']}" for e in result.errors[:30]))

    def _capture_model_snapshot(self):
        h=self.store.active
        if not h:return
        if not h.catalog_run_id:
            QtWidgets.QMessageBox.information(self,'Model Snapshot','Open the run from NHRA Tech Services first. Scratch/local sessions do not create permanent catalog runs.');return
        name,ok=QtWidgets.QInputDialog.getText(self,'Capture Vehicle Model Snapshot','Snapshot name:',text=f'{h.label} — model')
        if not ok:return
        try:
            sync_run_state(self.catalog,h.catalog_run_id,h.run)
            sid=capture_model_snapshot(self.catalog,h.catalog_run_id,h.run,name=name.strip() or 'Vehicle model snapshot')
            self.run_browser.refresh();self.case_browser.refresh();self.case_timeline.refresh();self.statusBar().showMessage(f'Captured vehicle model snapshot {sid}',7000)
        except Exception as exc:
            logging.exception('Model snapshot failed');QtWidgets.QMessageBox.critical(self,'Model Snapshot',str(exc))

    def _engineering_history(self):
        key,ok=QtWidgets.QInputDialog.getText(self,'Engineering History','Engineering value key:',text='model.peak_hp')
        if not ok or not key.strip():return
        active_record=self.catalog.get_run(self.store.active.catalog_run_id) if self.store.active and self.store.active.catalog_run_id else None
        driver_id=(active_record or {}).get('driver_id') or None
        rows=self.catalog.engineering_history(key.strip(),driver_id=driver_id)
        dlg=QtWidgets.QDialog(self);dlg.setWindowTitle(f'Engineering History — {key.strip()}');dlg.resize(1100,580);lay=QtWidgets.QVBoxLayout(dlg)
        scope=f"Active driver: {(active_record or {}).get('driver_name')}" if driver_id else 'Scope: all catalog runs'
        note=QtWidgets.QLabel('Historical engineering values are append-only observations tied to a specific run/model snapshot. '+scope+'. Descriptive season changes do not yet apply comparable-run/uncertainty normalization.');note.setWordWrap(True);lay.addWidget(note)
        seasons=sorted({int(r['season']) for r in rows if r.get('season') is not None})
        if len(seasons)>=2:
            try:
                comp=compare_seasons(self.catalog,key.strip(),seasons[-2],seasons[-1],driver_id=driver_id)
                summary=QtWidgets.QLabel(f"{comp.season_a} → {comp.season_b}: mean {comp.percent_change_mean:+.2f}% (n={comp.count_a} → {comp.count_b}); median {comp.percent_change_median:+.2f}% — descriptive only")
                summary.setStyleSheet('font-weight:bold;padding:4px');lay.addWidget(summary)
            except Exception:pass
        table=QtWidgets.QTableWidget(len(rows),10);table.setHorizontalHeaderLabels(['Season','Date','Event','Driver','Class','Car','Value','Unit','Provenance','Method'])
        for r,row in enumerate(rows):
            vals=[row.get('season',''),row.get('run_datetime',''),row.get('event_name',''),row.get('driver_name',''),row.get('category',''),row.get('car_number',''),row.get('value',''),row.get('unit',''),row.get('provenance',''),row.get('method','')]
            for c,v in enumerate(vals):table.setItem(r,c,QtWidgets.QTableWidgetItem(str(v if v is not None else '')))
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch);lay.addWidget(table,1)
        bb=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close);bb.rejected.connect(dlg.reject);bb.clicked.connect(dlg.accept);lay.addWidget(bb);dlg.exec()

    def _channel_properties(self, channel):
        h=self.store.active
        if not h:return
        run=h.run
        dlg=QtWidgets.QDialog(self); dlg.setWindowTitle(f'Channel Properties — {channel}'); dlg.resize(560,340)
        form=QtWidgets.QFormLayout(dlg)
        form.addRow('Source channel',QtWidgets.QLabel(channel))
        unit=QtWidgets.QComboBox(); unit.setEditable(True)
        unit_keys=['']+sorted(k for k in UNITS if k)
        for key in unit_keys: unit.addItem(display_label(key) or key,key)
        current=normalize_unit(run.units.get(channel,'')); idx=unit.findData(current)
        if idx>=0:unit.setCurrentIndex(idx)
        else:unit.setEditText(run.units.get(channel,''))
        form.addRow('Engineering unit',unit)
        role=QtWidgets.QComboBox(); role.addItem('No common-channel assignment','')
        for spec in common_channel_specs():
            suffix=f' [{spec.unit_label}]' if spec.unit_label else ''
            role.addItem(f'{spec.label}{suffix}',spec.key)
        current_role=next((k for k,v in run.metadata.get('original_channel_map',{}).items() if v==channel),'')
        idx=role.findData(current_role); role.setCurrentIndex(max(0,idx))
        form.addRow('Common channel',role)
        profile=matching_common_channel_profile(run);profile_scope=str(profile.get('scope') or '') if profile else ''
        scope=self._common_channel_scope_combo(run,current_scope=profile_scope);form.addRow('Reusable profile',scope)
        prov=run.metadata.get('unit_provenance',{}).get(channel,'native / inferred source unit')
        form.addRow('Current provenance',QtWidgets.QLabel(str(prov)))
        note=QtWidgets.QLabel(
            'The assignment above is always stored for this exact data log when it is attached to a Tech Services Run. '
            'A reusable profile is optional and is narrowly scoped to the selected driver/category or vehicle/category plus logger. '
            'Display Alias is cosmetic and separate. Raw source data is never overwritten.'
        ); note.setWordWrap(True); form.addRow(note)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel); buttons.accepted.connect(dlg.accept);buttons.rejected.connect(dlg.reject);form.addRow(buttons)
        if dlg.exec()!=QtWidgets.QDialog.Accepted:return
        unit_key=str(unit.currentData() or normalize_unit(unit.currentText()) or unit.currentText()).strip()
        chosen=str(role.currentData() or '')
        scope_key=str(scope.currentData() or '')
        try:
            if chosen:
                target=next((spec.unit for spec in common_channel_specs() if spec.key==chosen),'')
                effective_unit=normalize_unit(unit_key or run.units.get(channel,''))
                if target and effective_unit and not compatible(effective_unit,target):
                    raise ValueError(f'{channel} is {display_label(effective_unit) or effective_unit}; {common_channel_label(chosen)} expects {display_label(target) or target}.')
            if unit_key: h.unit_overrides[channel]=unit_key
            if current_role and current_role!=chosen:h.channel_overrides[current_role]=''
            if chosen:h.channel_overrides[chosen]=channel
            elif current_role:h.channel_overrides[current_role]=''
            h.run=apply_channel_overrides(h.run,h.channel_overrides,h.unit_overrides)
            if h.run.metadata.get('math_channels'):reapply_math_channels(h.run,list(h.run.metadata.get('math_channels',[])))
            self._persist_exact_channel_settings(h)
            if scope_key and chosen:remember_common_channel_mapping(h.run,channel,chosen,scope=scope_key)
            self.store.changed.emit(); self.store.activeChanged.emit(h)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self,'Channel mapping rejected',str(exc))

    def _show_audit(self):
        for d in self.findChildren(QtWidgets.QDockWidget):
            if d.objectName()=='AuditDock':d.show();d.raise_();break

    def _active_changed(self,handle):
        run=handle.run if handle else None; self._refresh_channel_explorer(); self.metadata.refresh(); self.audit.refresh()
        if hasattr(self,'run_browser'): self.run_browser.refresh()
        if hasattr(self,'case_browser'): self.case_browser.refresh()
        if hasattr(self,'case_timeline'): self.case_timeline.refresh()
        if hasattr(self,'case_review'): self.case_review.refresh()
        if handle and handle.catalog_run_id:
            if hasattr(self,'asset_browser'):self.asset_browser.set_run(handle.catalog_run_id)
            if hasattr(self,'catalog_run_details'):self.catalog_run_details.set_run(handle.catalog_run_id)
            if hasattr(self,'run_workspace'):self.run_workspace.set_run(handle.catalog_run_id)
        if handle:
            report=assess_plotability(run)
            ws=self.current_sheet()
            if ws.waveforms:
                w=ws.waveforms[0]
                available=set(_visible_channel_names(run))
                if not w.channels or not any(c in available for c in w.channels):
                    p=infer_profile(run)
                    preferred=resolve_profile_channels(run,p.key,limit=8) if p.key!='generic_drag' else []
                    w.channels=list(preferred or report.default_channels)
                    w.refresh()
                    QtCore.QTimer.singleShot(0,w._fit_run)
            self._refresh_profile_selector()
            warning_count=len(run.metadata.get('data_warnings',[])); msg=f"{Path(handle.path).name} — {run.vendor} — {len(run.native_channels) or len(run.data.columns)} channels"
            if report.default_channels: msg+=f" — plotting {len(report.default_channels)} default channel(s)"
            if warning_count:msg+=f" — {warning_count} import warning(s)"
            self.statusBar().showMessage(msg)

    def _open_log_folder(self):
        folder=log_dir()
        try:
            if sys.platform.startswith('win'):
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif sys.platform=='darwin':
                subprocess.Popen(['open',str(folder)])
            else:
                subprocess.Popen(['xdg-open',str(folder)])
        except Exception as exc:
            QtWidgets.QMessageBox.information(self,'Diagnostic log folder',f'{folder}\n\nCould not open the folder automatically: {exc}')

    def _run_data_selftest(self):
        root=bundled_examples_dir()
        rows=run_data_pipeline_selftest(root)
        text=format_selftest(rows)
        dlg=QtWidgets.QDialog(self); dlg.setWindowTitle('Import / Plot Data Self-Test'); dlg.resize(860,600)
        lay=QtWidgets.QVBoxLayout(dlg); box=QtWidgets.QPlainTextEdit(); box.setReadOnly(True); box.setPlainText(text); lay.addWidget(box)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close); buttons.rejected.connect(dlg.reject); buttons.clicked.connect(dlg.accept); lay.addWidget(buttons); dlg.exec()

    def _show_import_support(self):
        text=(
            'NHRA Velocity import status\n\n'
            'Native / direct:\n'
            '  • RacePak/DataLink .rpk — validated legacy/current DataLink run families.\n'
            '  • RacePak raw .ddf — direct SD-card/logger decode; matching .rcg/prior .rpk config adds names and units but is not required for raw samples.\n'
            '  • MoTeC .ld — native parser for currently validated LD/M1 families; additional real-log qualification remains in progress.\n'
            '  • MaxxECU .maxxlog / .MaxxECU-log — native text log; supported zip packages are also decoded.\n\n'
            'Delimited:\n'
            '  • CSV / TSV / TXT / LOG exports.\n\n'
            'Authoritative Run workflow:\n'
            '  • Sync Tech Services Events/Runs, select the exact Run, then use Attach Data Log… to bind the local run data explicitly.\n'
            '  • Attachments are copied into Velocity managed storage, inherit official timing/weather when available, and are never uploaded or matched by filename.\n\n'
            'Recognized but intentionally not decoded yet:\n'
            '  • FuelTech .ftlog / .ftml — use CSV or MoTeC .ld export until a native decoder is validated.\n\n'
            'Import rules:\n'
            '  • Binary files are never silently sent to the CSV parser.\n'
            '  • Successful imports must contain plotable numeric data before they are accepted.\n'
            '  • Missing semantic time falls back to Sample Index for viewing; derivative/physics tools still require a valid timebase.\n'
            '  • Open Help → Open Bundled Native Demos to verify the viewer and three import paths independently of your own files.'
        )
        dlg=QtWidgets.QDialog(self); dlg.setWindowTitle('Import Support / Diagnostics'); dlg.resize(720,500)
        lay=QtWidgets.QVBoxLayout(dlg); box=QtWidgets.QPlainTextEdit(); box.setReadOnly(True); box.setPlainText(text); lay.addWidget(box)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close); buttons.rejected.connect(dlg.reject); buttons.clicked.connect(dlg.accept); lay.addWidget(buttons); dlg.exec()

    def _open_paths(self, paths):
        files=[str(Path(p)) for p in paths if p and Path(p).is_file()]
        if not files:return
        errors=[]; opened=0
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            for path in files:
                try:
                    # Every explicitly opened log becomes the active/Main session
                    # as it is decoded. This guarantees the final selected file is
                    # the one visible on the primary waveform.
                    run=load_telemetry(path)
                    h=self.store.add(path,run,activate=True)
                    # Direct file opens are scratch sessions only. Permanent Run→Asset
                    # ownership comes exclusively from NHRA Tech Services.
                    opened+=1
                except Exception as exc:
                    logging.exception('Telemetry import failed: %s', path)
                    errors.append(f'{Path(path).name}: {exc}')
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if errors:
            title='Log import failed' if not opened else 'Some logs could not be opened'
            detail='\n\n'.join(errors)
            detail+='\n\nRaw data is never silently treated as CSV when the file appears binary. The message above identifies the decoder stage that failed.'
            QtWidgets.QMessageBox.warning(self,title,detail)
        if opened:
            h=self.store.active
            if h:
                report=assess_plotability(h.run)
                self.statusBar().showMessage(f'Opened {opened} log(s) — {Path(h.path).name} — {len(report.default_channels)} default trace(s) selected',8000)

    def open_logs(self):
        files,_=QtWidgets.QFileDialog.getOpenFileNames(self,'Open data logs','', qt_file_dialog_filter())
        self._open_paths(files)

    def _open_bundled_demos(self):
        root=bundled_examples_dir()
        demos=[root/'native_demo_racepak.rpk',root/'native_demo_motec.ld',root/'native_demo_maxxecu.MaxxECU-log']
        missing=[p.name for p in demos if not p.exists()]
        if missing:
            QtWidgets.QMessageBox.warning(self,'Demo files missing','Bundled native demo files are missing: '+', '.join(missing))
            return
        self._open_paths([str(p) for p in demos])

    def open_log_folder(self):
        folder=QtWidgets.QFileDialog.getExistingDirectory(self,'Open folder of data logs')
        if not folder:return
        root=Path(folder)
        files=sorted((p for p in root.rglob('*') if p.is_file() and telemetry_file_candidate(p)), key=lambda p:str(p).lower())
        if not files:
            QtWidgets.QMessageBox.information(self,'No data logs found',f'No recognized data-log files were found under:\n{root}')
            return
        if len(files)>1:
            answer=QtWidgets.QMessageBox.question(self,'Open data-log folder',f'Found {len(files)} candidate data-log files under:\n{root}\n\nOpen them now?')
            if answer!=QtWidgets.QMessageBox.Yes:return
        self._open_paths([str(p) for p in files])

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction(); return
        super().dragEnterEvent(event)

    def dropEvent(self,event):
        if event.mimeData().hasUrls():
            paths=[u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            if paths:
                self._open_paths(paths); event.acceptProposedAction(); return
        super().dropEvent(event)

    def _library_changed(self):
        self.store.analysis_library=self.analysis_library; self.store.changed.emit(); self.statusBar().showMessage(f'Analysis library: {self.analysis_library.name}',4000)
    def _import_analysis_library(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Import analysis library','','NHRA Analysis Library (*.nhralib);;JSON (*.json)')
        if not path:return
        try:self.analysis_library=DefinitionLibrary.load(path);self._library_changed()
        except Exception as exc:QtWidgets.QMessageBox.critical(self,'Import analysis library',str(exc))
    def _export_analysis_library(self):
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Export analysis library','analysis.nhralib','NHRA Analysis Library (*.nhralib)')
        if not path:return
        try:self.analysis_library.save(path);self.statusBar().showMessage(f'Exported analysis library {path}',5000)
        except Exception as exc:QtWidgets.QMessageBox.critical(self,'Export analysis library',str(exc))
    def _capture_analysis_library(self):
        h=self.store.active
        if not h:QtWidgets.QMessageBox.information(self,'Analysis Library','Open a telemetry session first.');return
        captured=capture_from_run(h.run,name=self.analysis_library.name)
        self.analysis_library.calculated_channels.update(captured.calculated_channels);self.analysis_library.gates.update(captured.gates);self._library_changed()
    def _new_library_constant(self):
        name,ok=QtWidgets.QInputDialog.getText(self,'Library Constant','Name:');
        if not ok or not name.strip():return
        value,ok=QtWidgets.QInputDialog.getDouble(self,'Library Constant',f'{name} value:',0.0,-1e12,1e12,6);
        if not ok:return
        unit,ok=QtWidgets.QInputDialog.getText(self,'Library Constant','Engineering unit (optional):');
        if not ok:return
        self.analysis_library.constants[name.strip()]=ConstantDefinition(name.strip(),value,unit.strip());self._library_changed()
    def _new_library_metric(self):
        name,ok=QtWidgets.QInputDialog.getText(self,'Saved Metric','Metric name:');
        if not ok or not name.strip():return
        channel,ok=QtWidgets.QInputDialog.getText(self,'Saved Metric','Channel / common-channel key (for example engine_rpm):');
        if not ok or not channel.strip():return
        stats=['mean','min','max','median','std','rms','range','start','end','delta','integral','slope','p05','p95'];stat,ok=QtWidgets.QInputDialog.getItem(self,'Saved Metric','Statistic:',stats,2,False)
        if not ok:return
        self.analysis_library.metrics[name.strip()]=PortableMetricDefinition(name.strip(),channel.strip(),stat);self._library_changed()
    def _new_library_segment(self):
        name,ok=QtWidgets.QInputDialog.getText(self,'Saved Segment','Segment name:');
        if not ok or not name.strip():return
        kind,ok=QtWidgets.QInputDialog.getItem(self,'Saved Segment','Type:',['Official timing boundaries','Manual time window'],0,False)
        if not ok:return
        if kind.startswith('Official'):
            a,ok=QtWidgets.QInputDialog.getItem(self,'Saved Segment','Start:',['launch','60','330','660','1000'],0,False);
            if not ok:return
            b,ok=QtWidgets.QInputDialog.getItem(self,'Saved Segment','End:',['60','330','660','1000','finish'],4,False);
            if not ok:return
            rec=SegmentTemplate(name.strip(),source='official',start_ref=a,end_ref=b)
        else:
            a,ok=QtWidgets.QInputDialog.getDouble(self,'Saved Segment','Start time (s):',0,-10000,10000,5);
            if not ok:return
            b,ok=QtWidgets.QInputDialog.getDouble(self,'Saved Segment','End time (s):',1,-10000,10000,5);
            if not ok:return
            rec=SegmentTemplate(name.strip(),source='manual',start=a,end=b)
        self.analysis_library.segments[rec.name]=rec;self._library_changed()
    def _new_library_condition(self):
        if not self.analysis_library.metrics:QtWidgets.QMessageBox.information(self,'Conditional Rule','Create a saved metric first.');return
        name,ok=QtWidgets.QInputDialog.getText(self,'Conditional Rule','Rule name:');
        if not ok or not name.strip():return
        metric,ok=QtWidgets.QInputDialog.getItem(self,'Conditional Rule','Metric:',sorted(self.analysis_library.metrics),0,False);
        if not ok:return
        op,ok=QtWidgets.QInputDialog.getItem(self,'Conditional Rule','Condition:',['>','>=','<','<=','==','!='],0,False);
        if not ok:return
        threshold,ok=QtWidgets.QInputDialog.getDouble(self,'Conditional Rule','Threshold:',0,-1e12,1e12,6);
        if not ok:return
        self.analysis_library.conditions[name.strip()]=ConditionalRule(name.strip(),metric,operator=op,threshold=threshold);self._library_changed()
    def _new_library_event_rule(self):
        name,ok=QtWidgets.QInputDialog.getText(self,'Event / Alarm Rule','Rule name:');
        if not ok or not name.strip():return
        expression,ok=QtWidgets.QInputDialog.getText(self,'Event / Alarm Rule','Portable condition (for example engine_rpm > 9500):');
        if not ok or not expression.strip():return
        trigger,ok=QtWidgets.QInputDialog.getItem(self,'Event / Alarm Rule','Trigger:',['interval','rising','falling'],0,False);
        if not ok:return
        severity,ok=QtWidgets.QInputDialog.getItem(self,'Event / Alarm Rule','Severity:',['info','warning','high','critical'],1,False);
        if not ok:return
        duration,ok=QtWidgets.QInputDialog.getDouble(self,'Event / Alarm Rule','Minimum true duration (s):',0.0,0,1000,4);
        if not ok:return
        rec=EventRuleDefinition(name.strip(),expression.strip(),severity=severity,trigger=trigger,min_duration_s=duration)
        self.analysis_library.event_rules[rec.name]=rec;self._library_changed()

    def _new_library_report(self):
        if not self.analysis_library.metrics or not self.analysis_library.segments:QtWidgets.QMessageBox.information(self,'Saved Report','Create at least one saved metric and segment first.');return
        name,ok=QtWidgets.QInputDialog.getText(self,'Saved Report','Report name:');
        if not ok or not name.strip():return
        metrics,ok=QtWidgets.QInputDialog.getText(self,'Saved Report','Metrics (comma-separated):',text=', '.join(self.analysis_library.metrics));
        if not ok:return
        segments,ok=QtWidgets.QInputDialog.getText(self,'Saved Report','Segments (comma-separated):',text=', '.join(self.analysis_library.segments));
        if not ok:return
        m=[x.strip() for x in metrics.split(',') if x.strip() in self.analysis_library.metrics];sg=[x.strip() for x in segments.split(',') if x.strip() in self.analysis_library.segments]
        self.analysis_library.reports[name.strip()]=ReportDefinition(name.strip(),metrics=m,segments=sg,conditions=list(self.analysis_library.conditions));self._library_changed()

    def _project_dict(self):
        sheets=[]
        for i in range(self.worksheets.count()):
            ws=self.worksheets.widget(i)
            sheets.append({'name':self.worksheets.tabText(i),'x_mode':self.xmode.currentText(),'displays':ws.display_specs(),'dock_state':bytes(ws.saveState()).hex()})
        sessions=[]
        for h in self.store.runs:
            if h.catalog_run_id:
                try:sync_run_state(self.catalog,h.catalog_run_id,h.run)
                except Exception:logging.exception('Could not sync run state to local catalog before project save')
            sessions.append({
                'path':h.path,'display_name':h.display_name,'role':h.role,
                'catalog_run_id':h.catalog_run_id,'catalog_asset_id':h.catalog_asset_id,'catalog_session_id':h.catalog_session_id,
                'channel_overrides':h.channel_overrides,'unit_overrides':h.unit_overrides,'time_alignment_s':h.time_alignment_s,'launch_time_override_s':launch_time_override(h.run),
                # Compatibility shadow. Durable values are moving to the
                # catalog but retains them so pre-catalog workbooks remain portable.
                'environment':h.run.environment.to_dict(),'timing':h.run.timing.to_dict(),
                'vehicle_inputs':h.run.metadata.get('vehicle_inputs',{}),'parameter_knowledge':h.run.metadata.get('parameter_knowledge',{}),
                'user_notes':h.run.metadata.get('user_notes',''),'math_channels':h.run.metadata.get('math_channels',[]),'channel_aliases':h.run.metadata.get('channel_aliases',{}),'gates':h.run.metadata.get('gates',[]),
                'annotations':h.run.metadata.get('annotations',[]),'derived_analyses':h.run.metadata.get('derived_analyses',{}),'analysis_profile':h.run.metadata.get('analysis_profile',''),'rsa_profile_defaults':h.run.metadata.get('rsa_profile_defaults',{})
            })
        return {
            'version':WORKBOOK_FORMAT_VERSION,'application':'NHRA Velocity','catalog_path':str(self.catalog.path),'analysis_library':self.analysis_library.to_dict(),'simulation_studies':list(self.simulation_studies),'compare_sets':self.compare_sets.to_dict(),
            'sessions':sessions,'active_index':self.store.active_index,'worksheets':sheets,
            'x_mode':self.xmode.currentText(),'compare_enabled':self.compare_box.isChecked(),
            'cursors':{'x':self.cursors.x,'a':self.cursors.a,'b':self.cursors.b},
            'main_geometry':bytes(self.saveGeometry()).hex(),'main_state':bytes(self.saveState()).hex()
        }

    def _write_project_path(self,path:str, *, recovery:bool=False):
        obj=self._project_dict()
        obj['saved_at_utc']=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
        obj['source_project_path']=self.project_path
        atomic_write_json(path,obj)
        if not recovery:
            self.project_path=str(path)
        return path

    def _write_recovery_snapshot(self):
        # Do not create noisy recovery files for an untouched empty shell.
        if not self.store.runs and self.worksheets.count()<=1:
            return
        try:
            current=self._project_dict()
            # If an explicit saved project is byte-for-content equivalent, no
            # recovery image is needed and should not trigger a false prompt.
            if self.project_path and Path(self.project_path).exists():
                try:
                    if projects_equivalent(current,read_project_json(self.project_path)):
                        self._recovery_path.unlink(missing_ok=True); return
                except Exception:
                    logging.exception('Could not compare project with autosave state')
            self._write_project_path(str(self._recovery_path),recovery=True)
        except Exception:
            logging.exception('Autosave recovery snapshot failed')

    def _offer_recovery(self):
        if not getattr(self,'_recovery_path',None) or not self._recovery_path.exists():
            return
        try:
            obj=read_project_json(self._recovery_path)
            source=obj.get('source_project_path')
            if not is_recovery_newer(self._recovery_path,source):
                return
        except Exception:
            logging.exception('Could not inspect autosave recovery file')
            return
        answer=QtWidgets.QMessageBox.question(self,'Recover autosaved workspace?',
            'NHRA Velocity found a newer recovery snapshot from a previous session.\n\nRecover it now?')
        if answer==QtWidgets.QMessageBox.Yes:
            self._recover_snapshot(force=True)

    def _recover_snapshot(self, force=False):
        path=getattr(self,'_recovery_path',None)
        if not path or not Path(path).exists():
            if force: QtWidgets.QMessageBox.information(self,'No recovery snapshot','No autosave recovery snapshot is available.')
            return
        try:
            obj=read_project_json(path)
            self._load_project_object(obj,source_path=None)
            self.project_path=obj.get('source_project_path') or None
            self.statusBar().showMessage('Recovered autosaved workspace. Save Workbook to preserve it.',10000)
        except Exception as exc:
            logging.exception('Recovery failed')
            QtWidgets.QMessageBox.critical(self,'Recovery failed',str(exc))

    def save_project(self):
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Save NHRA Velocity workbook',self.project_path or f'analysis{PROJECT_EXT}',f'NHRA Velocity Workbook (*{PROJECT_EXT})')
        if not path:return
        if not path.lower().endswith(PROJECT_EXT):path+=PROJECT_EXT
        try:
            self._write_project_path(path)
            # A successful explicit save supersedes the crash-recovery snapshot.
            try:self._recovery_path.unlink(missing_ok=True)
            except Exception:pass
            self.statusBar().showMessage(f'Saved {path}',5000)
        except Exception as exc:
            logging.exception('Project save failed')
            QtWidgets.QMessageBox.critical(self,'Project save failed',str(exc))

    def _load_project_object(self,obj,source_path=None):
        if source_path is not None:self.project_path=str(source_path)
        # Restore global viewer state before recreating displays.
        desired_x=str(obj.get('x_mode') or ((obj.get('worksheets') or [{}])[0].get('x_mode') if obj.get('worksheets') else '') or 'Time from Launch')
        i=self.xmode.findText(desired_x); self.xmode.blockSignals(True); self.xmode.setCurrentIndex(i if i>=0 else 0); self.xmode.blockSignals(False)
        self.compare_box.blockSignals(True); self.compare_box.setChecked(bool(obj.get('compare_enabled',True))); self.compare_box.blockSignals(False)
        cur=obj.get('cursors',{}) or {}; self.cursors.x=float(cur.get('x',0.0)); self.cursors.a=float(cur.get('a',0.0)); self.cursors.b=float(cur.get('b',1.0))
        self.analysis_library=DefinitionLibrary.from_dict(obj.get('analysis_library',{})); self.store.analysis_library=self.analysis_library
        self.simulation_studies=list(obj.get('simulation_studies',[]) or [])
        self.compare_sets=CompareSetLibrary.from_dict(obj.get('compare_sets',{}) or {})
        # Fresh session store, keeping signal connections by mutating existing object.
        self.store.runs.clear();self.store.active_index=-1
        errors=[]
        for rec in obj.get('sessions',[]):
            p=str(rec.get('path','') or '')
            catalog_asset_id=str(rec.get('catalog_asset_id','') or '')
            catalog_run_id=str(rec.get('catalog_run_id','') or '')
            if catalog_asset_id:
                asset=self.catalog.get_asset(catalog_asset_id)
                if asset:
                    # Prefer the catalog's filename-preserving managed alias even
                    # when an older workbook remembered the extensionless CAS path.
                    managed_path=self.catalog.local_asset_read_path(catalog_asset_id)
                    if managed_path:
                        p=managed_path
                    elif not p or not Path(p).is_file():
                        try:
                            ensure_asset_cached(self.catalog,self.tech_services,catalog_asset_id)
                            p=self.catalog.local_asset_read_path(catalog_asset_id)
                        except Exception:pass
            try:
                h=self.store.add(p,load_telemetry(p),apply_preferences=False);h.role=rec.get('role','available'); h.time_alignment_s=float(rec.get('time_alignment_s',0.0) or 0.0); h.display_name=str(rec.get('display_name') or Path(p).stem)
                h.catalog_run_id=catalog_run_id;h.catalog_asset_id=catalog_asset_id;h.catalog_session_id=str(rec.get('catalog_session_id','') or '')
                h.channel_overrides=dict(rec.get('channel_overrides',{})); h.unit_overrides=dict(rec.get('unit_overrides',{}))
                if h.channel_overrides or h.unit_overrides:
                    h.run=apply_channel_overrides(h.run,h.channel_overrides,h.unit_overrides)
                # Portable @common-channel math definitions must be evaluated
                # only after the workbook's source-role overrides are restored.
                if rec.get('math_channels'):
                    reapply_math_channels(h.run, rec.get('math_channels'))
                if rec.get('environment'): h.run.environment=Environment.from_dict(rec['environment'])
                if rec.get('timing'): h.run.timing=TimingData.from_dict(rec['timing'])
                h.run.metadata['vehicle_inputs']=dict(rec.get('vehicle_inputs', rec.get('quarterpro_inputs',{})))
                restore_knowledge_snapshot(h.run, rec.get('parameter_knowledge',{}))
                h.run.metadata['user_notes']=rec.get('user_notes',''); h.run.metadata['annotations']=list(rec.get('annotations',[])); h.run.metadata['channel_aliases']=dict(rec.get('channel_aliases',{})); h.run.metadata['gates']=list(rec.get('gates',[]))
                h.run.metadata['analysis_profile']=str(rec.get('analysis_profile','') or '')
                h.run.metadata['rsa_profile_defaults']=dict(rec.get('rsa_profile_defaults',{}) or {})
                if rec.get('launch_time_override_s') is not None:
                    try:set_launch_time_override(h.run,float(rec.get('launch_time_override_s')))
                    except Exception:logging.exception('Could not restore workbook launch zero')
                elif h.catalog_asset_id:
                    try:self._restore_catalog_launch_zero(h)
                    except Exception:logging.exception('Could not restore catalog launch zero')
                h.run.metadata['derived_analyses']=dict(rec.get('derived_analyses',{}))
                dp=h.run.metadata.get('derived_analyses',{}).get('delivered_power',{})
                if isinstance(dp,dict) and dp.get('enabled'):
                    try:
                        vehicle,_missing=vehicle_from_run(h.run,require_explicit=False)
                        attach_delivered_power_reconstruction(h.run,vehicle,h.run.environment,smoothing_s=float(dp.get('smoothing_s',0.12)),rpm_bin=float(dp.get('rpm_bin',250.0)),min_throttle_pct=float(dp.get('min_throttle_pct',80.0)),persist=True,run_label=h.label)
                    except Exception as deriv_exc:
                        logging.exception('Could not rebuild delivered-power derivation for %s',p); errors.append(f'{p}: derived power not rebuilt: {deriv_exc}')
                model_cfg=h.run.metadata.get('derived_analyses',{}).get('rsa_model_enrichment',{})
                if isinstance(model_cfg,dict) and model_cfg.get('enabled'):
                    try:
                        vehicle,_missing=vehicle_from_run(h.run,require_explicit=False)
                        rebuild_rsa_model_enrichment(h.run,vehicle)
                    except Exception as model_exc:
                        logging.exception('Could not rebuild RSA model enrichment for %s',p); errors.append(f'{p}: RSA model channels not rebuilt: {model_exc}')
            except Exception as exc:errors.append(f'{p}: {exc}')
        idx=int(obj.get('active_index',0));
        if self.store.runs:self.store.set_active(max(0,min(idx,len(self.store.runs)-1)))
        while self.worksheets.count():self.worksheets.removeTab(0)
        for spec in obj.get('worksheets',[]) or [{'name':'Data'}]:
            ws=self.add_worksheet(spec.get('name','Data'))
            if spec.get('displays'):
                ws.restore_display_specs(spec.get('displays'))
            elif ws.waveforms:
                # Backwards compatibility with earlier development project files.
                ws.waveforms[0].channels=list(spec.get('channels',[])); ws.waveforms[0].refresh()
            state=spec.get('dock_state');
            if state:
                try:ws.restoreState(QtCore.QByteArray.fromHex(state.encode()))
                except Exception:pass
        self._xmode_changed(self.xmode.currentText()); self._compare_changed(1 if self.compare_box.isChecked() else 0)
        self.cursors.moved.emit(self.cursors.x); self.cursors.cursorAMoved.emit(self.cursors.a); self.cursors.cursorBMoved.emit(self.cursors.b)
        try:
            if obj.get('main_geometry'):self.restoreGeometry(QtCore.QByteArray.fromHex(obj['main_geometry'].encode()))
            if obj.get('main_state'):self.restoreState(QtCore.QByteArray.fromHex(obj['main_state'].encode()))
        except Exception:pass
        self.run_browser.refresh()
        if errors:QtWidgets.QMessageBox.warning(self,'Project opened with missing sessions','\n'.join(errors))

    def open_project(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Open NHRA Velocity workbook','',f'NHRA Velocity Workbook (*{PROJECT_EXT});;All files (*.*)')
        if not path:return
        try:
            obj=read_project_json(path)
            self._load_project_object(obj,source_path=path)
            self.statusBar().showMessage(f'Opened project {path}',5000)
        except Exception as exc:
            logging.exception('Project open failed')
            QtWidgets.QMessageBox.critical(self,'Project open failed',str(exc))

    def closeEvent(self,event):
        # Recovery is for abnormal termination. A clean shutdown removes the
        # snapshot so the next launch is not asked to recover a session that
        # was intentionally closed.
        try:self._recovery_path.unlink(missing_ok=True)
        except Exception:pass
        super().closeEvent(event)


def _style(app):
    app.setStyle('Fusion')
    palette=QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window,QtGui.QColor(33,35,38));palette.setColor(QtGui.QPalette.WindowText,QtGui.QColor(225,225,225))
    palette.setColor(QtGui.QPalette.Base,QtGui.QColor(24,26,29));palette.setColor(QtGui.QPalette.AlternateBase,QtGui.QColor(31,33,36))
    palette.setColor(QtGui.QPalette.Text,QtGui.QColor(225,225,225));palette.setColor(QtGui.QPalette.Button,QtGui.QColor(45,48,52));palette.setColor(QtGui.QPalette.ButtonText,QtGui.QColor(230,230,230))
    palette.setColor(QtGui.QPalette.Highlight,QtGui.QColor(55,115,170));palette.setColor(QtGui.QPalette.HighlightedText,QtGui.QColor(255,255,255))
    app.setPalette(palette)
    app.setStyleSheet('''
        QMainWindow::separator { background:#24272b; width:2px; height:2px; }
        QDockWidget::title { background:#25282c; padding:4px 6px; border-bottom:1px solid #34383d; }
        QToolBar { spacing:3px; padding:2px; border-bottom:1px solid #34383d; background:#25282c; }
        QTreeWidget,QTableWidget { gridline-color:#34383d; alternate-background-color:#1d2024; }
        QHeaderView::section { background:#2b2e33; color:#d8d8d8; padding:3px 5px; border:0; border-right:1px solid #3a3e43; border-bottom:1px solid #3a3e43; }
        QTabWidget::pane { border:0; border-top:1px solid #34383d; }
        QTabBar::tab { padding:5px 12px; margin-right:1px; background:#25282c; border:0; border-bottom:2px solid transparent; }
        QTabBar::tab:selected { background:#30343a; border-bottom:2px solid #5b9bd5; color:#ffffff; }
        QTabBar::tab:hover { background:#2d3136; }
        QPushButton,QToolButton { min-height:20px; padding:2px 7px; }
        QComboBox,QLineEdit { min-height:20px; }
        QScrollBar:vertical { width:11px; }
        QScrollBar:horizontal { height:11px; }
    ''')


_FAULT_LOG_HANDLE = None


def _desktop_smoke_requested() -> bool:
    return '--smoke-test' in sys.argv or os.environ.get('NHRA_VELOCITY_SMOKE_TEST','').strip() == '1'


def _run_desktop_smoke_scenario(win, app) -> None:
    """Exercise the packaged Qt/runtime path without external data or network.

    This intentionally lives in the desktop entry point so the PyInstaller and
    installed-executable smoke gate validates the same imports, MainWindow,
    pyqtgraph rendering and common analysis widgets that normal users run.
    """
    t=np.arange(0.0, 3.01, 0.01)
    speed=np.maximum(0.0,(t-0.35)*70.0)
    throttle=np.where((t>=0.15)&(t<2.8),100.0,0.0)
    rpm=np.where(t<0.35,5500.0,7200.0+speed*11.0)
    driveshaft=speed*30.0
    run=TelemetryRun(
        name='packaged-smoke',
        data=pd.DataFrame({'Time':t,'RPM':rpm,'Speed':speed,'Driveshaft':driveshaft,'Throttle':throttle}),
        channel_map={'time_s':'Time','engine_rpm':'RPM','speed_mph':'Speed','driveshaft_rpm':'Driveshaft','throttle_pct':'Throttle'},
        units={'Time':'s','RPM':'rpm','Speed':'mph','Driveshaft':'rpm','Throttle':'%'},
        timing=TimingData(sixty_ft_s=1.05,three_thirty_ft_s=2.75,eighth_mile_s=4.20,quarter_mile_s=6.55),
        environment=Environment(),
    )
    run=apply_channel_overrides(run,{
        'time_s':'Time','engine_rpm':'RPM','speed_mph':'Speed','driveshaft_rpm':'Driveshaft','throttle_pct':'Throttle'
    },{})
    add_math_channel(run,'Overall Ratio','@engine_rpm / @driveshaft_rpm','ratio',persist=True)
    if not np.isfinite(pd.to_numeric(run.data['Overall Ratio'],errors='coerce')).any():
        raise RuntimeError('Desktop smoke test portable math channel produced no finite samples')
    win.store.add('__velocity_smoke__.csv',run,activate=True)
    sheet=win.current_sheet()
    if sheet is None or not sheet.waveforms:
        raise RuntimeError('Desktop smoke test could not create the default worksheet/waveform')
    wave=sheet.waveforms[0]
    wave.channels=['RPM','Speed','Throttle']
    wave.refresh();app.processEvents()
    if len(wave.plots) != 3:
        raise RuntimeError(f'Desktop smoke test rendered {len(wave.plots)} waveform bands; expected 3')
    win.cursors.x=1.25;win.cursors.a=0.55;wave.reference_visible=True
    wave._set_readout_stat('show_stat_min',True);wave._set_readout_stat('show_stat_max',True);wave._refresh_readout();app.processEvents()
    for factory in (sheet.add_region_stats,sheet.add_histogram,sheet.add_scatter,sheet.add_spectrum,sheet.add_sensor_health):
        dock=factory();widget=dock.widget()
        if hasattr(widget,'refresh'):widget.refresh()
        app.processEvents()
    logging.info('PACKAGED_DESKTOP_SMOKE_PASS version=%s plots=%s',PRODUCT_VERSION,len(wave.plots))


def main():
    global _FAULT_LOG_HANDLE
    log_path=configure_logging()
    logging.info('Starting %s %s; log=%s', PRODUCT_NAME, PRODUCT_VERSION, log_path)
    smoke_test=_desktop_smoke_requested()
    if smoke_test:
        # Packaged/CI smoke tests must be network-free and must not require a
        # developer machine credential vault or Tech Services session.
        os.environ['NHRA_TECH_DEV_UNAUTHENTICATED']='1'
        logging.info('Packaged desktop smoke test requested')
    # Install native/Python crash capture before any Qt widget is constructed.
    # pythonw.exe has no console, so startup exceptions must never disappear.
    try:
        fault_path=log_dir()/'nhra-velocity-fault.log'
        _FAULT_LOG_HANDLE=open(fault_path,'a',encoding='utf-8',buffering=1)
        faulthandler.enable(file=_FAULT_LOG_HANDLE, all_threads=True)
    except Exception:
        logging.exception('Could not enable native fault logging')

    pg.setConfigOptions(antialias=False, background=(20,22,25), foreground=(215,215,215))
    app=QtWidgets.QApplication(sys.argv);app.setOrganizationName(APP_ORG);app.setApplicationName(APP_ID);icon=_application_icon();
    if not icon.isNull(): app.setWindowIcon(icon)
    _style(app)
    win_ref={'win':None}

    def _unhandled(exc_type, exc_value, exc_tb):
        logging.critical('Unhandled application exception', exc_info=(exc_type,exc_value,exc_tb))
        text=''.join(traceback.format_exception(exc_type,exc_value,exc_tb))
        parent=win_ref.get('win')
        try:
            QtWidgets.QMessageBox.critical(parent,'Unexpected application error',
                f'{exc_value}\n\nA diagnostic log was written to:\n{log_path}\n\n{text[-2500:]}')
        except Exception:
            pass
    sys.excepthook=_unhandled

    try:
        win=MainWindow()
        win_ref['win']=win
        if not smoke_test:
            try:
                win.auth.restore()
            except Exception:
                logging.exception('Could not restore secure Tech Services session')
        win._refresh_account_actions()
        if win.auth_required and not smoke_test:
            status=win.auth.status()
            if not (status.online_access_valid or status.offline_access_valid):
                if not win._sign_in():
                    QtWidgets.QMessageBox.critical(win,'NHRA Tech Services sign-in required',
                        'This protected NHRA Velocity build requires an authorized NHRA Tech Services account.\n\n'
                        'Sign-in was not completed, so the application will remain closed.')
                    return 4
        win.show()
        if smoke_test:
            try:
                _run_desktop_smoke_scenario(win,app)
            except Exception:
                logging.exception('PACKAGED_DESKTOP_SMOKE_FAIL')
                return 6
            QtCore.QTimer.singleShot(150,app.quit)
        else:
            QtCore.QTimer.singleShot(250,win._maybe_start_initial_sync)
            if len(sys.argv)>1:
                paths=[p for p in sys.argv[1:] if p != '--smoke-test' and Path(p).is_file()]
                win._open_paths(paths)
        return app.exec()
    except Exception:
        exc_type,exc_value,exc_tb=sys.exc_info()
        _unhandled(exc_type,exc_value,exc_tb)
        return 1


if __name__=='__main__': sys.exit(main())
