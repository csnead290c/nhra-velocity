from pathlib import Path

from runlab.product_manifest import (
    PRODUCT_VERSION, CATALOG_SCHEMA_VERSION, WORKBOOK_FORMAT_VERSION,
    ANALYSIS_LIBRARY_FORMAT_VERSION, FIT_STUDY_FORMAT_VERSION,
    SIMULATION_STUDY_FORMAT_VERSION, SYNC_CONTRACT_VERSION, manifest_dict,
)
from runlab.catalog import SCHEMA_VERSION
from runlab.definition_library import LIBRARY_VERSION
from runlab.release_audit import audit_release_tree


def test_manifest_runtime_versions_agree():
    assert PRODUCT_VERSION.startswith("0.37.")
    assert SCHEMA_VERSION == CATALOG_SCHEMA_VERSION == 7
    assert LIBRARY_VERSION == ANALYSIS_LIBRARY_FORMAT_VERSION == 2
    assert WORKBOOK_FORMAT_VERSION == 8
    assert FIT_STUDY_FORMAT_VERSION == 5
    assert SIMULATION_STUDY_FORMAT_VERSION == 2
    assert SYNC_CONTRACT_VERSION == 4


def test_manifest_upstreams_fail_explicitly_to_unverified_without_shas():
    payload=manifest_dict({})
    assert len(payload["upstream_references"]) == 2
    assert all(x["commit_sha"] == "unverified" for x in payload["upstream_references"])
    assert not any(x["verified"] for x in payload["upstream_references"])


def test_release_audit_catches_doc_version_drift(tmp_path: Path):
    (tmp_path/"README.md").write_text("# NHRA Tech Data — Development v0.30\n",encoding="utf-8")
    (tmp_path/"ARCHITECTURE.md").write_text("# NHRA Tech Data Architecture — v0.31\n",encoding="utf-8")
    result=audit_release_tree(tmp_path,env={})
    assert not result["ok"]
    assert any(x["check"]=="doc.README.md" and x["level"]=="error" for x in result["findings"])
