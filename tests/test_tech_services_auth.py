from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import json
import threading
import time
from urllib.parse import parse_qs, urlparse

from runlab.auth import AuthManager, MemoryCredentialStore
from runlab.tech_services_auth import WebsiteTechServicesAuthProvider


def _token(exp: float) -> str:
    def enc(value):
        return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"{enc({'alg':'HS256','typ':'JWT'})}.{enc({'user_id':7,'exp':exp})}.signature"


@contextmanager
def auth_server():
    token = _token(time.time() + 3600)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def _json(self, payload, code=200):
            raw=json.dumps(payload).encode()
            self.send_response(code);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)

        def do_POST(self):  # noqa: N802
            parsed=urlparse(self.path);body=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))).decode())
            if parsed.path=="/api/auth.php" and parse_qs(parsed.query).get("action")==["login"] and body=={"email":"eng@example.com","password":"pw"}:
                self._json({"success":True,"token":token,"user":{"id":7,"email":"eng@example.com","name":"Engineer","role":"admin"}});return
            self._json({"error":"Invalid credentials"},401)

        def do_GET(self):  # noqa: N802
            if self.headers.get("Authorization") != f"Bearer {token}":
                self._json({"error":"Unauthorized"},401);return
            parsed=urlparse(self.path)
            if parsed.path=="/api/auth.php":
                self._json({"user":{"id":7,"email":"eng@example.com","name":"Engineer","role":"admin"}})
            elif parsed.path=="/api/capabilities-endpoint.php":
                self._json({"plan":"nhra","role":"admin","capabilities":["nhra.tech.read","nhra.parity","sim.basic"],"version":"v"})
            else:self._json({"error":"not found"},404)

    server=ThreadingHTTPServer(("127.0.0.1",0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield f"http://127.0.0.1:{server.server_port}"
    finally:server.shutdown();thread.join(timeout=2);server.server_close()


def test_website_provider_login_maps_server_capabilities_and_securely_restores_token():
    with auth_server() as base:
        provider=WebsiteTechServicesAuthProvider(base_url=base)
        store=MemoryCredentialStore();mgr=AuthManager(provider,store)
        signed=provider.sign_in(email="eng@example.com",password="pw")
        assert signed.identity.user_id == "7"
        assert "desktop.access" in signed.identity.scopes
        assert "runs.read" in signed.identity.scopes
        assert "simulation.use" in signed.identity.scopes
        mgr.set_session(signed)
        payload=store.load(provider.provider_name,"default")
        assert payload["access_token"]
        assert payload["schema"] == 1
        assert "password" not in payload
        assert "identity" not in payload
        assert "token_scopes" not in payload
        # Owner/admin accounts can carry a long capability list.  The vault
        # payload must stay compact because Windows Credential Manager has a
        # small generic-credential blob limit.
        assert len(json.dumps(payload,separators=(",", ":")).encode("utf-16-le")) < 2560

        restored=AuthManager(provider,store)
        assert restored.restore()
        assert restored.status().online_access_valid
        restored.sign_out()
        assert store.load(provider.provider_name,"default") is None
