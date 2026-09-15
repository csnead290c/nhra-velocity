from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import parse_qs, urlparse

import pytest

from runlab.tech_services_http import (
    HttpTechServicesTransport,
    TechServicesHttpClient,
    TechServicesHttpConfig,
    TechServicesHttpError,
    build_http_transport_from_env,
)


@contextmanager
def api_server():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            seen.append({
                "path": parsed.path,
                "query": parse_qs(parsed.query),
                "authorization": self.headers.get("Authorization", ""),
                "method": "GET",
            })
            if parsed.path == "/api/auth.php":
                if self.headers.get("Authorization") != "Bearer test-token":
                    self._json({"error": "Unauthorized"}, 401)
                else:
                    self._json({"user": {"id": "7", "email": "engineer@example.com", "name": "Engineer", "role": "admin"}})
            elif parsed.path == "/api/capabilities-endpoint.php":
                if self.headers.get("Authorization") != "Bearer test-token":
                    self._json({"error": "Unauthorized"}, 401)
                else:
                    self._json({"plan": "nhra", "role": "admin", "capabilities": ["nhra.tech.read", "nhra.parity", "sim.basic"], "version": "test"})
            elif parsed.path == "/api/runs.php":
                self._json({"runs": [{"id": "sim-1", "vehicle_name": "Test"}]})
            elif parsed.path == "/api/parity.php":
                q = parse_qs(parsed.query)
                if q.get("action") == ["runs"]:
                    self._json({
                        "runs": [{
                            "id": 101, "uuid": "run-uuid-1", "race_lookup": q.get("raceLookup", [""])[0],
                            "driver_name": "Test Rider", "car_number": "7", "ft1320": 6.75, "mph1320": 200.0
                        }],
                        "total": 1, "limit": int(q.get("limit", [500])[0]),
                        "offset": int(q.get("offset", [0])[0]),
                        "raceLookup": q.get("raceLookup", [""])[0],
                    })
                else:
                    self._json({"error": "unknown parity action"}, 400)
            elif parsed.path == "/api/tm-events.php":
                q = parse_qs(parsed.query)
                if q.get("action") == ["listEvents"]:
                    self._json({"events": [{"id": 12, "uuid": "evt-uuid-12", "race_lookup": "20260908", "name": "PSM Indianapolis Test"}], "count": 1})
                elif q.get("action") == ["getEvent"]:
                    self._json({"event": {"id": int(q.get("id", [0])[0]), "uuid": "evt-uuid-12", "race_lookup": "20260908"}})
                else:
                    self._json({"error": "unknown event action"}, 400)
            elif parsed.path == "/api/tm-entries.php":
                q = parse_qs(parsed.query)
                if q.get("action") == ["listForEvent"]:
                    eid = int(q.get("eventInstanceId", [0])[0])
                    self._json({"entries": [{"id": 44, "uuid": "entry-uuid-44", "event_instance_id": eid, "competition_number": "7"}], "count": 1, "eventInstanceId": eid})
                elif q.get("action") == ["get"]:
                    self._json({"entry": {"id": int(q.get("id", [0])[0]), "uuid": "entry-uuid-44"}})
                else:
                    self._json({"error": "unknown entry action"}, 400)
            elif parsed.path == "/tech-data/catalog":
                self._json({
                    "contract_version": 4,
                    "cursor": "next:2",
                    "events": [{"remote_id": "evt-1", "event_code": "II1", "name": "US Nationals", "runs": []}],
                })
            elif parsed.path == "/tech-data/bad-catalog":
                self._json({"contract_version": 4, "events": {}})
            elif parsed.path.startswith("/tech-data/assets/"):
                body = b"telemetry-bytes"
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif parsed.path == "/too-big":
                body = b"1234567890"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif parsed.path == "/bad-json":
                body = b"not-json"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):  # noqa: N802
            parsed = urlparse(self.path)
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length)
            body = json.loads(raw.decode("utf-8")) if raw else {}
            seen.append({
                "path": parsed.path,
                "query": parse_qs(parsed.query),
                "authorization": self.headers.get("Authorization", ""),
                "method": "POST",
                "body": body,
            })
            if parsed.path == "/api/auth.php" and parse_qs(parsed.query).get("action") == ["login"]:
                if body.get("email") == "engineer@example.com" and body.get("password") == "correct-horse":
                    self._json({"success": True, "token": "test-token", "user": {"id": "7", "email": body["email"], "name": "Engineer", "role": "admin"}})
                else:
                    self._json({"error": "Invalid credentials"}, 401)
            else:
                self._json({"error": "not found"}, 404)

        def _json(self, value, code=200):
            body = json.dumps(value).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", seen
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_production_http_requires_tls_and_disallows_url_credentials():
    with pytest.raises(ValueError, match="requires HTTPS"):
        TechServicesHttpClient(TechServicesHttpConfig(base_url="http://example.com"))
    with pytest.raises(ValueError, match="credentials"):
        TechServicesHttpClient(TechServicesHttpConfig(base_url="https://user:pass@example.com"))


def test_existing_login_exchange_posts_json_without_bearer_and_capabilities_are_protected():
    with api_server() as (base, seen):
        anonymous = TechServicesHttpClient(TechServicesHttpConfig(base_url=base, bearer_token="stale-token"))
        login = anonymous.login(email="engineer@example.com", password="correct-horse")
        assert login["token"] == "test-token"
        assert seen[-1]["method"] == "POST"
        assert seen[-1]["query"]["action"] == ["login"]
        assert seen[-1]["authorization"] == ""
        assert seen[-1]["body"] == {"email": "engineer@example.com", "password": "correct-horse"}

        protected = TechServicesHttpClient(TechServicesHttpConfig(base_url=base, bearer_token=login["token"]))
        caps = protected.capabilities()
        assert "nhra.tech.read" in caps["capabilities"]
        assert seen[-1]["authorization"] == "Bearer test-token"


def test_verified_existing_api_uses_bearer_get_without_translating_sim_runs():
    with api_server() as (base, seen):
        client = TechServicesHttpClient(TechServicesHttpConfig(base_url=base, bearer_token="test-token"))
        me = client.current_user()
        history = client.simulation_run_history(limit=999)
        assert me["user"]["id"] == "7"
        assert history["runs"][0]["id"] == "sim-1"
        assert seen[0]["authorization"] == "Bearer test-token"
        assert seen[0]["method"] == "GET"
        assert seen[1]["query"]["limit"] == ["100"]



def test_verified_tech_master_and_parity_metadata_reads_do_not_infer_entry_links():
    with api_server() as (base, seen):
        client = TechServicesHttpClient(TechServicesHttpConfig(base_url=base, bearer_token="test-token"))

        events = client.tech_master_events(season_year=2026, limit=999)
        assert events["events"][0]["uuid"] == "evt-uuid-12"
        assert seen[-1]["path"] == "/api/tm-events.php"
        assert seen[-1]["query"]["action"] == ["listEvents"]
        assert seen[-1]["query"]["seasonYear"] == ["2026"]
        assert seen[-1]["query"]["limit"] == ["500"]

        event = client.tech_master_event(12)
        assert event["event"]["id"] == 12

        entries = client.tech_master_entries(event_instance_id=12, class_index="PRO STOCK MOTORCYCLE")
        assert entries["entries"][0]["event_instance_id"] == 12
        assert seen[-1]["query"]["classIndex"] == ["PRO STOCK MOTORCYCLE"]

        entry = client.tech_master_entry(44)
        assert entry["entry"]["uuid"] == "entry-uuid-44"

        runs = client.parity_runs(
            race_lookup="20260908", category="PRO STOCK MOTORCYCLE", driver_name="Test",
            lane="1", round_name="T1", dq="exclude", include_bad=True, limit=99999, offset=-5,
        )
        assert runs["runs"][0]["uuid"] == "run-uuid-1"
        assert "event_entry_id" not in runs["runs"][0]
        q = seen[-1]["query"]
        assert q["action"] == ["runs"]
        assert q["raceLookup"] == ["20260908"]
        assert q["category"] == ["PRO STOCK MOTORCYCLE"]
        assert q["limit"] == ["5000"]
        assert q["offset"] == ["0"]
        assert q["includeBad"] == ["1"]


def test_verified_metadata_read_argument_validation():
    with api_server() as (base, _seen):
        client = TechServicesHttpClient(TechServicesHttpConfig(base_url=base))
        with pytest.raises(ValueError, match="YYYYMMDD"):
            client.parity_runs(race_lookup="Indy")
        with pytest.raises(ValueError, match="dq must"):
            client.parity_runs(race_lookup="20260908", dq="maybe")
        with pytest.raises(ValueError, match="event_id"):
            client.tech_master_event(0)
        with pytest.raises(ValueError, match="event_instance_id"):
            client.tech_master_entries(event_instance_id=0)
        with pytest.raises(ValueError, match="entry_id"):
            client.tech_master_entry(-1)

def test_authoritative_catalog_and_asset_routes_are_explicit_and_read_only():
    with api_server() as (base, seen):
        cfg = TechServicesHttpConfig(
            base_url=base,
            bearer_token="test-token",
            catalog_path="tech-data/catalog",
            asset_path_template="tech-data/assets/{asset_id}",
        )
        transport = HttpTechServicesTransport(TechServicesHttpClient(cfg))
        assert transport.capabilities.catalog_pull
        assert transport.capabilities.asset_fetch
        assert not transport.capabilities.analysis_push
        snapshot = transport.pull_catalog_snapshot(cursor="cursor:1")
        assert snapshot["contract_version"] == 4
        assert seen[-1]["query"]["cursor"] == ["cursor:1"]
        assert transport.fetch_asset("asset / 1") == b"telemetry-bytes"
        # Quoting must prevent an asset ID from becoming a path segment.
        assert seen[-1]["path"].endswith("/asset%20%2F%201")
        with pytest.raises(TechServicesHttpError, match="read-only"):
            transport.push_analysis_bundle({"anything": True})


def test_missing_authoritative_routes_fail_closed_even_though_site_api_exists():
    with api_server() as (base, _seen):
        transport = HttpTechServicesTransport(TechServicesHttpClient(TechServicesHttpConfig(base_url=base)))
        assert not transport.capabilities.catalog_pull
        assert not transport.capabilities.asset_fetch
        with pytest.raises(TechServicesHttpError, match="catalog route is not configured"):
            transport.pull_catalog_snapshot()
        with pytest.raises(TechServicesHttpError, match="asset-download route is not configured"):
            transport.fetch_asset("asset-1")


def test_catalog_contract_is_validated_before_local_sync_sees_it():
    with api_server() as (base, _seen):
        cfg = TechServicesHttpConfig(base_url=base, catalog_path="tech-data/bad-catalog")
        transport = HttpTechServicesTransport(TechServicesHttpClient(cfg))
        with pytest.raises(TechServicesHttpError, match="events array"):
            transport.pull_catalog_snapshot()


def test_response_limits_invalid_json_and_http_errors_are_safe():
    with api_server() as (base, _seen):
        client = TechServicesHttpClient(TechServicesHttpConfig(base_url=base, max_json_bytes=5))
        with pytest.raises(TechServicesHttpError, match="size limit"):
            client.get_json("too-big")

        client = TechServicesHttpClient(TechServicesHttpConfig(base_url=base))
        with pytest.raises(TechServicesHttpError, match="invalid JSON"):
            client.get_json("bad-json")
        with pytest.raises(TechServicesHttpError, match="HTTP 404: not found"):
            client.get_json("missing")


def test_env_factory_never_invents_catalog_or_asset_paths():
    t = build_http_transport_from_env({
        "NHRA_TECH_SERVICES_BASE_URL": "https://nhratechservices.com",
        "NHRA_TECH_SERVICES_TOKEN": "secret",
    })
    assert not t.capabilities.catalog_pull
    assert not t.capabilities.asset_fetch
    assert t.client.config.bearer_token == "secret"
