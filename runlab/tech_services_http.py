from __future__ import annotations

"""Hardened read-only HTTP boundary for NHRA Tech Services.

The nhratechservices repository was audited read-only at commit
77eb280fe94825f93f2cdfdd3ab2568851aa6a19.

The current site exposes several *real* protected read surfaces that matter to
the workstation:

- ``auth.php?action=me`` for the authenticated identity;
- Tech Master Events through ``tm-events.php``;
- Tech Master Event Entries through ``tm-entries.php``;
- normalized NHRA timing Runs through ``parity.php?action=runs``;
- the older ``runs.php`` saved-simulation history (kept deliberately separate).

The database also contains ``parity_runs.event_entry_id`` as the intended
Entry -> Run bridge, but the audited parity ``runs`` response does not expose
that field. No Run -> permanent telemetry/supporting-file Asset API is present
either. Therefore this module binds the verified metadata reads exactly as
implemented while the canonical Event -> Entry -> Run -> Asset sync contract
continues to fail closed rather than guessing relationships.
"""

from dataclasses import dataclass
import json
import os
import re
from typing import Any, Mapping, MutableMapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .transport import ProviderCapabilities
from .version import __version__


DEFAULT_TECH_SERVICES_BASE_URL = "https://nhratechservices.com"
TECH_SERVICES_AUDITED_SHA = "77eb280fe94825f93f2cdfdd3ab2568851aa6a19"


class TechServicesHttpError(RuntimeError):
    """A safe, secret-free representation of a Tech Services HTTP failure."""

    def __init__(self, message: str, *, status: int | None = None, url: str = ""):
        super().__init__(message)
        self.status = status
        self.url = url


@dataclass(frozen=True)
class TechServicesHttpConfig:
    base_url: str = DEFAULT_TECH_SERVICES_BASE_URL
    bearer_token: str = ""
    catalog_path: str = ""
    asset_path_template: str = ""
    timeout_s: float = 20.0
    max_json_bytes: int = 8 * 1024 * 1024
    max_asset_bytes: int = 1024 * 1024 * 1024
    allow_insecure_localhost: bool = True

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "TechServicesHttpConfig":
        values = os.environ if env is None else env

        def _float(name: str, default: float) -> float:
            raw = str(values.get(name, "") or "").strip()
            return float(raw) if raw else default

        def _int(name: str, default: int) -> int:
            raw = str(values.get(name, "") or "").strip()
            return int(raw) if raw else default

        return cls(
            base_url=str(values.get("NHRA_TECH_SERVICES_BASE_URL", DEFAULT_TECH_SERVICES_BASE_URL) or DEFAULT_TECH_SERVICES_BASE_URL).strip(),
            bearer_token=str(values.get("NHRA_TECH_SERVICES_TOKEN", "") or "").strip(),
            catalog_path=str(values.get("NHRA_TECH_SERVICES_CATALOG_PATH", "") or "").strip(),
            asset_path_template=str(values.get("NHRA_TECH_SERVICES_ASSET_PATH_TEMPLATE", "") or "").strip(),
            timeout_s=max(1.0, _float("NHRA_TECH_SERVICES_TIMEOUT_S", 20.0)),
            max_json_bytes=max(1024, _int("NHRA_TECH_SERVICES_MAX_JSON_BYTES", 8 * 1024 * 1024)),
            max_asset_bytes=max(1024, _int("NHRA_TECH_SERVICES_MAX_ASSET_BYTES", 1024 * 1024 * 1024)),
        )


class _SameOriginRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_origin: tuple[str, str, int | None]):
        super().__init__()
        self.allowed_origin = allowed_origin

    @staticmethod
    def _origin(url: str) -> tuple[str, str, int | None]:
        p = urlparse(url)
        port = p.port
        if port is None:
            port = 443 if p.scheme.lower() == "https" else 80 if p.scheme.lower() == "http" else None
        return p.scheme.lower(), (p.hostname or "").lower(), port

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if self._origin(newurl) != self.allowed_origin:
            raise TechServicesHttpError("Tech Services refused a cross-origin redirect", status=int(code), url=newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class TechServicesHttpClient:
    """Small GET-only client for the existing nhratechservices Bearer API."""

    user_agent = f"NHRA-Velocity/{__version__}"

    def __init__(self, config: TechServicesHttpConfig):
        self.config = config
        self.base_url = self._validate_base_url(config.base_url, config.allow_insecure_localhost)
        self._origin = self._url_origin(self.base_url)
        self._opener = build_opener(_SameOriginRedirectHandler(self._origin))

    @staticmethod
    def _url_origin(url: str) -> tuple[str, str, int | None]:
        p = urlparse(url)
        port = p.port
        if port is None:
            port = 443 if p.scheme.lower() == "https" else 80 if p.scheme.lower() == "http" else None
        return p.scheme.lower(), (p.hostname or "").lower(), port

    @staticmethod
    def _validate_base_url(value: str, allow_insecure_localhost: bool) -> str:
        raw = str(value or "").strip().rstrip("/") + "/"
        p = urlparse(raw)
        if p.scheme not in {"http", "https"} or not p.hostname:
            raise ValueError("Tech Services base URL must be an absolute http(s) URL")
        local = p.hostname.lower() in {"127.0.0.1", "localhost", "::1"}
        if p.scheme != "https" and not (allow_insecure_localhost and local):
            raise ValueError("Tech Services requires HTTPS; plain HTTP is allowed only for localhost development")
        if p.username or p.password:
            raise ValueError("Tech Services credentials must not be embedded in the base URL")
        if p.query or p.fragment:
            raise ValueError("Tech Services base URL must not contain a query string or fragment")
        return raw

    def _resolve(self, path: str) -> str:
        candidate = str(path or "").strip()
        if not candidate:
            raise ValueError("Tech Services route is not configured")
        if candidate.startswith("//"):
            raise ValueError("Scheme-relative Tech Services routes are not allowed")
        url = urljoin(self.base_url, candidate.lstrip("/"))
        if self._url_origin(url) != self._origin:
            raise ValueError("Tech Services route must remain on the configured origin")
        return url

    @staticmethod
    def _redacted_message(status: int, body: bytes) -> str:
        # Return a useful server message without ever reflecting tokens/headers.
        try:
            data = json.loads(body.decode("utf-8", errors="replace"))
            if isinstance(data, Mapping) and data.get("error"):
                return f"Tech Services HTTP {status}: {str(data['error'])[:240]}"
        except Exception:
            pass
        return f"Tech Services HTTP {status}"

    def _read_limited(self, response, limit: int) -> bytes:  # noqa: ANN001
        length = response.headers.get("Content-Length")
        if length:
            try:
                if int(length) > limit:
                    raise TechServicesHttpError(f"Tech Services response exceeds configured size limit ({limit} bytes)", url=response.geturl())
            except ValueError:
                pass
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(min(1024 * 1024, limit - total + 1))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > limit:
                raise TechServicesHttpError(f"Tech Services response exceeds configured size limit ({limit} bytes)", url=response.geturl())
        return b"".join(chunks)

    def _get(self, path: str, *, query: Optional[Mapping[str, Any]] = None, limit: int) -> bytes:
        url = self._resolve(path)
        if query:
            clean = {str(k): str(v) for k, v in query.items() if v not in (None, "")}
            if clean:
                url += ("&" if "?" in url else "?") + urlencode(clean)
        headers: MutableMapping[str, str] = {
            "Accept": "application/json, application/octet-stream;q=0.9",
            "User-Agent": self.user_agent,
            "Cache-Control": "no-cache",
        }
        if self.config.bearer_token:
            headers["Authorization"] = f"Bearer {self.config.bearer_token}"
        req = Request(url, headers=dict(headers), method="GET")
        try:
            with self._opener.open(req, timeout=float(self.config.timeout_s)) as response:
                final_url = response.geturl()
                if self._url_origin(final_url) != self._origin:
                    raise TechServicesHttpError("Tech Services response escaped the configured origin", url=final_url)
                return self._read_limited(response, int(limit))
        except TechServicesHttpError:
            raise
        except HTTPError as exc:
            try:
                body = exc.read(64 * 1024)
            except Exception:
                body = b""
            raise TechServicesHttpError(self._redacted_message(int(exc.code), body), status=int(exc.code), url=url) from exc
        except URLError as exc:
            raise TechServicesHttpError(f"Tech Services connection failed: {getattr(exc, 'reason', exc)}", url=url) from exc

    def get_json(self, path: str, *, query: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        raw = self._get(path, query=query, limit=int(self.config.max_json_bytes))
        try:
            value = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise TechServicesHttpError("Tech Services returned invalid JSON", url=self._resolve(path)) from exc
        if not isinstance(value, Mapping):
            raise TechServicesHttpError("Tech Services JSON response must be an object", url=self._resolve(path))
        return value

    def get_bytes(self, path: str) -> bytes:
        return self._get(path, limit=int(self.config.max_asset_bytes))

    # Routes below are verified in nhratechservices at TECH_SERVICES_AUDITED_SHA.
    def current_user(self) -> Mapping[str, Any]:
        return self.get_json("api/auth.php", query={"action": "me"})

    def simulation_run_history(self, *, limit: int = 50) -> Mapping[str, Any]:
        # This is the website's saved *simulation* run_history API. It is
        # deliberately not translated into the workstation Event/Run catalog.
        return self.get_json("api/runs.php", query={"limit": max(1, min(int(limit), 100))})

    def parity_runs(
        self,
        *,
        race_lookup: str,
        category: str = "",
        class_index: str = "",
        driver_name: str = "",
        lane: str = "",
        round_name: str = "",
        dq: str = "",
        include_bad: bool = False,
        limit: int = 500,
        offset: int = 0,
    ) -> Mapping[str, Any]:
        """Read normalized NHRA timing Runs from the verified parity API.

        The audited response does not currently expose the database's
        ``event_entry_id`` bridge. Callers must not infer Entry ownership from
        names, car numbers, ordering or filenames.
        """
        lookup = str(race_lookup or "").strip()
        if not re.fullmatch(r"\d{8}", lookup):
            raise ValueError("race_lookup must be YYYYMMDD")
        query: dict[str, Any] = {
            "action": "runs",
            "raceLookup": lookup,
            "limit": max(1, min(int(limit), 5000)),
            "offset": max(0, int(offset)),
        }
        if category:
            query["category"] = str(category).strip()
        elif class_index:
            query["classIndex"] = str(class_index).strip()
        if driver_name:
            query["driverName"] = str(driver_name).strip()
        if lane != "":
            query["lane"] = str(lane).strip()
        if round_name != "":
            query["round"] = str(round_name).strip()
        if dq:
            value = str(dq).strip().lower()
            if value not in {"exclude", "only", "include"}:
                raise ValueError("dq must be exclude, only, or include")
            query["dq"] = value
        if include_bad:
            query["includeBad"] = 1
        return self.get_json("api/parity.php", query=query)

    def tech_master_events(
        self,
        *,
        season_id: int | None = None,
        season_year: int | None = None,
        limit: int = 100,
    ) -> Mapping[str, Any]:
        """List Tech Master event instances using the verified read API."""
        query: dict[str, Any] = {
            "action": "listEvents",
            "limit": max(1, min(int(limit), 500)),
        }
        if season_id is not None:
            query["seasonId"] = max(1, int(season_id))
        elif season_year is not None:
            query["seasonYear"] = int(season_year)
        return self.get_json("api/tm-events.php", query=query)

    def tech_master_event(self, event_id: int) -> Mapping[str, Any]:
        eid = int(event_id)
        if eid <= 0:
            raise ValueError("event_id must be positive")
        return self.get_json("api/tm-events.php", query={"action": "getEvent", "id": eid})

    def tech_master_entries(
        self,
        *,
        event_instance_id: int,
        class_index: str = "",
    ) -> Mapping[str, Any]:
        """List authoritative Event Entries for one Tech Master event."""
        eid = int(event_instance_id)
        if eid <= 0:
            raise ValueError("event_instance_id must be positive")
        query: dict[str, Any] = {"action": "listForEvent", "eventInstanceId": eid}
        if class_index:
            query["classIndex"] = str(class_index).strip()
        return self.get_json("api/tm-entries.php", query=query)

    def tech_master_entry(self, entry_id: int) -> Mapping[str, Any]:
        entry = int(entry_id)
        if entry <= 0:
            raise ValueError("entry_id must be positive")
        return self.get_json("api/tm-entries.php", query={"action": "get", "id": entry})


class HttpTechServicesTransport:
    """Contract-v4 transport using explicitly configured server routes.

    Route names are intentionally *not* defaulted for the canonical sync
    contract. The audited site now has verified Event, Entry and normalized
    Run read APIs, but the parity Run response omits its database
    ``event_entry_id`` bridge and no permanent Asset manifest/download API is
    exposed. Once those exact links exist, this class can bind them without
    changing the catalog/cache layer.
    """

    def __init__(self, client: TechServicesHttpClient):
        self.client = client
        self.catalog_path = client.config.catalog_path.strip()
        self.asset_path_template = client.config.asset_path_template.strip()
        if self.asset_path_template and "{asset_id}" not in self.asset_path_template:
            raise ValueError("Tech Services asset path template must contain {asset_id}")

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider="nhra-tech-services",
            catalog_pull=bool(self.catalog_path),
            asset_fetch=bool(self.asset_path_template),
            analysis_push=False,
            asset_upload=False,
            incremental_cursor=bool(self.catalog_path),
        )

    def pull_catalog_snapshot(self, *, cursor: str = "") -> Mapping[str, Any]:
        if not self.catalog_path:
            raise TechServicesHttpError(
                "Authoritative Tech Services catalog route is not configured. "
                "The audited site exposes Event/Entry/Run metadata reads, but not the complete "
                "Entry→Run→Asset linkage required by sync contract v4."
            )
        payload = self.client.get_json(self.catalog_path, query={"cursor": cursor} if cursor else None)
        version = int(payload.get("contract_version") or 0)
        if version != 4:
            raise TechServicesHttpError(f"Unsupported Tech Services catalog contract {version}; expected 4")
        events = payload.get("events")
        if events is None or not isinstance(events, list):
            raise TechServicesHttpError("Tech Services catalog response must contain an events array")
        return payload

    def fetch_asset(self, remote_asset_id: str) -> bytes:
        if not self.asset_path_template:
            raise TechServicesHttpError(
                "Authoritative Tech Services asset-download route is not configured. "
                "No filename/path guessing is permitted."
            )
        rid = str(remote_asset_id or "").strip()
        if not rid:
            raise ValueError("remote_asset_id is required")
        path = self.asset_path_template.replace("{asset_id}", quote(rid, safe=""))
        return self.client.get_bytes(path)

    def push_analysis_bundle(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        raise TechServicesHttpError("v0.32 Tech Services transport is read-only; analysis write-back is not bound")


def build_http_transport_from_env(env: Optional[Mapping[str, str]] = None) -> HttpTechServicesTransport:
    """Construct the audited read-only provider without inventing route names."""
    return HttpTechServicesTransport(TechServicesHttpClient(TechServicesHttpConfig.from_env(env)))
