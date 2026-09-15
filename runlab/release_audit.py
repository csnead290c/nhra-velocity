from __future__ import annotations

"""Release consistency checks used before freezing an NHRA Tech Data archive."""

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Mapping
import re

from .product_manifest import manifest_dict, PRODUCT_VERSION


@dataclass(frozen=True)
class AuditFinding:
    level: str
    check: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def audit_release_tree(root: str | Path, *, env: Mapping[str,str] | None = None) -> dict[str, Any]:
    root=Path(root)
    findings: list[AuditFinding]=[]
    manifest=manifest_dict(env)
    expected_short=PRODUCT_VERSION.split("-",1)[0]
    expected_v="v"+".".join(expected_short.split(".")[:2])

    # Runtime constant checks are imports rather than duplicated regex guesses.
    from .catalog import SCHEMA_VERSION
    from .definition_library import LIBRARY_VERSION
    from .fit_study import FIT_STUDY_FORMAT_VERSION
    from .simulation_study import SIMULATION_STUDY_FORMAT_VERSION
    from .sync_contract import SYNC_CONTRACT_VERSION
    from .product_manifest import CATALOG_SCHEMA_VERSION, ANALYSIS_LIBRARY_FORMAT_VERSION, FIT_STUDY_FORMAT_VERSION as MFIT, SIMULATION_STUDY_FORMAT_VERSION as MSIM, SYNC_CONTRACT_VERSION as MSYNC
    runtime={"catalog_schema":SCHEMA_VERSION,"analysis_library":LIBRARY_VERSION,"fit_study":FIT_STUDY_FORMAT_VERSION,"simulation_study":SIMULATION_STUDY_FORMAT_VERSION,"tech_services_sync_contract":SYNC_CONTRACT_VERSION}
    expected={"catalog_schema":CATALOG_SCHEMA_VERSION,"analysis_library":ANALYSIS_LIBRARY_FORMAT_VERSION,"fit_study":MFIT,"simulation_study":MSIM,"tech_services_sync_contract":MSYNC}
    for key,val in runtime.items():
        if val != expected[key]:findings.append(AuditFinding("error",f"runtime.{key}",f"runtime={val} manifest={expected[key]}"))

    docs={"README.md":r"^# NHRA Tech Data .*v(\d+\.\d+)","ARCHITECTURE.md":r"^# NHRA Tech Data Architecture — v(\d+\.\d+)","PRODUCT_ARCHITECTURE.md":r"^# NHRA Technical Data Platform — Product Architecture v(\d+\.\d+)"}
    for rel,pattern in docs.items():
        path=root/rel
        if not path.exists():
            findings.append(AuditFinding("error",f"doc.{rel}","missing"));continue
        text=path.read_text(encoding="utf-8",errors="replace")
        m=re.search(pattern,text,re.M)
        if not m:
            findings.append(AuditFinding("warning",f"doc.{rel}","version heading not found"))
        elif "v"+m.group(1) != expected_v:
            findings.append(AuditFinding("error",f"doc.{rel}",f"heading v{m.group(1)} != {expected_v}"))


    manifest_file=root/"PRODUCT_MANIFEST.json"
    if not manifest_file.exists():
        findings.append(AuditFinding("error","product_manifest.file","PRODUCT_MANIFEST.json missing"))
    else:
        try:
            import json
            stored=json.loads(manifest_file.read_text(encoding="utf-8"))
            if stored.get("product_version") != manifest.get("product_version"):
                findings.append(AuditFinding("error","product_manifest.version",f"file={stored.get('product_version')} runtime={manifest.get('product_version')}"))
            if stored.get("formats") != manifest.get("formats"):
                findings.append(AuditFinding("error","product_manifest.formats","PRODUCT_MANIFEST.json format versions differ from runtime manifest"))
        except Exception as exc:
            findings.append(AuditFinding("error","product_manifest.file",f"invalid JSON: {exc}"))

    refs=manifest["upstream_references"]
    for ref in refs:
        if not ref.get("verified"):
            findings.append(AuditFinding("warning",f"upstream.{ref['name']}","commit SHA unverified for this release"))

    errors=sum(f.level=="error" for f in findings)
    warnings=sum(f.level=="warning" for f in findings)
    return {"ok":errors==0,"errors":errors,"warnings":warnings,"manifest":manifest,"findings":[f.to_dict() for f in findings]}
