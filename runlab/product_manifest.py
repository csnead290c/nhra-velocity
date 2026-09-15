from __future__ import annotations

"""Canonical product/release manifest.

This module is intentionally small and dependency-free.  It is the one place
that defines NHRA Tech Data's product version and portable/persistent format
versions.  Release tooling and tests use it to catch copy-forward drift before
an archive is frozen.
"""

from dataclasses import dataclass, asdict
import os
from typing import Any, Mapping

from .version import __version__, __channel__

PRODUCT_NAME = "NHRA Tech Data"
PRODUCT_TAGLINE = "Technical Data, Analysis & Vehicle Performance"
PRODUCT_VERSION = __version__
PRODUCT_CHANNEL = __channel__

CATALOG_SCHEMA_VERSION = 7
WORKBOOK_FORMAT_VERSION = 8
ANALYSIS_LIBRARY_FORMAT_VERSION = 2
SIMULATION_STUDY_FORMAT_VERSION = 2
FIT_STUDY_FORMAT_VERSION = 5
SYNC_CONTRACT_VERSION = 4

RSA_REFERENCE_REPOSITORY = "https://github.com/csnead290c/RacingSystemsAnalysis"
TECH_SERVICES_REFERENCE_REPOSITORY = "https://github.com/csnead290c/nhratechservices"

# Build/release jobs may set these after a read-only upstream audit.  Empty
# means deliberately unverified, never "latest main" by assumption.
RSA_REFERENCE_SHA_ENV = "NHRA_RSA_REFERENCE_SHA"
TECH_SERVICES_REFERENCE_SHA_ENV = "NHRA_TECH_SERVICES_REFERENCE_SHA"


@dataclass(frozen=True)
class UpstreamReference:
    name: str
    repository: str
    role: str
    commit_sha: str = ""

    @property
    def verified(self) -> bool:
        return bool(self.commit_sha.strip())

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["verified"] = self.verified
        out["commit_sha"] = self.commit_sha.strip() or "unverified"
        return out


def upstream_references(env: Mapping[str, str] | None = None) -> tuple[UpstreamReference, UpstreamReference]:
    values = os.environ if env is None else env
    return (
        UpstreamReference(
            "RacingSystemsAnalysis",
            RSA_REFERENCE_REPOSITORY,
            "physics/source-fidelity reference",
            str(values.get(RSA_REFERENCE_SHA_ENV, "")),
        ),
        UpstreamReference(
            "nhratechservices",
            TECH_SERVICES_REFERENCE_REPOSITORY,
            "production identity/auth/data/API reference",
            str(values.get(TECH_SERVICES_REFERENCE_SHA_ENV, "")),
        ),
    )


def manifest_dict(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    return {
        "product": PRODUCT_NAME,
        "tagline": PRODUCT_TAGLINE,
        "product_version": PRODUCT_VERSION,
        "update_channel": PRODUCT_CHANNEL,
        "formats": {
            "catalog_schema": CATALOG_SCHEMA_VERSION,
            "workbook": WORKBOOK_FORMAT_VERSION,
            "analysis_library": ANALYSIS_LIBRARY_FORMAT_VERSION,
            "simulation_study": SIMULATION_STUDY_FORMAT_VERSION,
            "fit_study": FIT_STUDY_FORMAT_VERSION,
            "tech_services_sync_contract": SYNC_CONTRACT_VERSION,
        },
        "upstream_references": [r.to_dict() for r in upstream_references(env)],
    }
