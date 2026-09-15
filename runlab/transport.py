from __future__ import annotations

"""Read-mostly transport boundary for nhratechservices.com.

Tech Services is the authoritative system of record for Events, Entries, Runs,
and every file permanently attached to a Run. The desktop mirrors metadata and caches immutable asset bytes for
analysis/offline use. The live backend has now been inspected read-only.
Known auth plus Event/Entry/normalized-Run read APIs are bound in
``tech_services_http``. Canonical sync still fails closed because the public
Run response omits the existing Entry bridge and no permanent Run→Asset API is
exposed.
"""

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from .auth import AuthManager


@dataclass(frozen=True)
class ProviderCapabilities:
    provider: str
    catalog_pull: bool = False
    asset_fetch: bool = False
    analysis_push: bool = False
    asset_upload: bool = False
    incremental_cursor: bool = False


@runtime_checkable
class TechServicesTransport(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def pull_catalog_snapshot(self, *, cursor: str = "") -> Mapping[str, Any]: ...
    def fetch_asset(self, remote_asset_id: str) -> bytes: ...
    def push_analysis_bundle(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...


class UnboundTechServicesTransport:
    """Safe placeholder for canonical sync operations the audited site does not yet fully expose."""
    capabilities=ProviderCapabilities(provider="nhra-tech-services")

    @staticmethod
    def _unbound() -> RuntimeError:
        return RuntimeError(
            "NHRA Tech Services canonical Run/Asset sync is not bound. The audited site exposes "
            "Bearer authentication plus Event/Entry/normalized-Run read APIs, but it does not expose "
            "the complete Entry→Run→Asset relationship required by the workstation. The desktop will not "
            "infer ownership, invent download URLs, or assume write permissions."
        )

    def pull_catalog_snapshot(self, *, cursor: str = "") -> Mapping[str, Any]:
        raise self._unbound()

    def fetch_asset(self, remote_asset_id: str) -> bytes:
        raise self._unbound()

    def push_analysis_bundle(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        raise self._unbound()


class AuthorizedTechServicesTransport:
    """Entitlement gate around any concrete Tech Services transport.

    Authentication stays independent of HTTP route details. A future PHP/API
    adapter can focus on server mechanics while this wrapper consistently
    enforces desktop scopes before catalog/data/write operations leave the app.
    """
    def __init__(self, inner: TechServicesTransport, auth: AuthManager, *, enforce: bool = True):
        self.inner=inner;self.auth=auth;self.enforce=bool(enforce)

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self.inner.capabilities

    def _require(self, scope: str) -> None:
        if self.enforce:self.auth.require(scope)

    def pull_catalog_snapshot(self, *, cursor: str = "") -> Mapping[str, Any]:
        self._require("runs.read");return self.inner.pull_catalog_snapshot(cursor=cursor)

    def fetch_asset(self, remote_asset_id: str) -> bytes:
        self._require("assets.read");return self.inner.fetch_asset(remote_asset_id)

    def push_analysis_bundle(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        self._require("analysis.write");return self.inner.push_analysis_bundle(payload)
