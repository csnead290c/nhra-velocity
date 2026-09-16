from __future__ import annotations

"""Bound authentication adapter for the existing NHRA Tech Services website.

The website already exposes a first-party JSON login route that accepts the
same email/password used by nhratechservices.com and returns a seven-day Bearer
token.  NHRA Velocity uses that route directly over HTTPS, keeps the password
only in memory for the request, and stores only the returned token in the OS
credential vault.

This is intentionally a compatibility bridge, not a new auth system.  A future
browser/device/PKCE handoff can replace this provider without changing the
catalog or UI ownership model.
"""

import base64
import json
from typing import Any, Mapping, Optional

from .auth import AuthSession, Identity, TokenSet, utc_now_ts
from .tech_services_http import (
    DEFAULT_TECH_SERVICES_BASE_URL,
    TechServicesHttpClient,
    TechServicesHttpConfig,
    TechServicesHttpError,
)


def _decode_unverified_exp(token: str) -> float:
    """Read the token's exp claim only as a local lifetime hint.

    Signature/capability enforcement remains server-side.  The returned value
    is capped to eight days so malformed/unexpected tokens cannot create an
    effectively permanent local session.
    """
    now = utc_now_ts()
    try:
        parts = str(token or "").split(".")
        if len(parts) != 3:
            raise ValueError("unexpected token shape")
        segment = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(segment.encode("ascii")).decode("utf-8"))
        exp = float(payload.get("exp") or 0.0)
        if exp <= now:
            return exp
        return min(exp, now + 8 * 24 * 3600)
    except Exception:
        # The audited website currently issues seven-day tokens.  If the token
        # shape ever changes, fail shorter rather than granting a long session.
        return now + 6 * 3600


def _desktop_scopes(site_capabilities: list[str] | tuple[str, ...] | set[str]) -> tuple[str, ...]:
    caps = {str(x) for x in site_capabilities if str(x).strip()}
    scopes = set(caps)

    # These are local workstation aliases only.  Every API request is still
    # checked by the site's authoritative capability enforcement.
    if caps & {"nhra.tech.read", "nhra.parity", "admin.access", "nhra.tech.admin"}:
        scopes.add("desktop.access")
    if "nhra.parity" in caps:
        scopes.add("runs.read")
    if caps & {"sim.basic", "sim.et", "sim.advanced", "nhra.tech.read", "nhra.tech.admin"}:
        scopes.add("simulation.use")
    if caps & {"nhra.tech.read", "nhra.tech.admin"}:
        scopes.add("assets.read")
    if "nhra.tech.admin" in caps:
        scopes.add("analysis.write")
    return tuple(sorted(scopes))


class WebsiteTechServicesAuthProvider:
    """Authenticate against the existing nhratechservices.com login API."""

    provider_name = "nhra-tech-services"
    persist_access_token = True

    def __init__(self, *, base_url: str = DEFAULT_TECH_SERVICES_BASE_URL, timeout_s: float = 20.0):
        self.base_url = str(base_url or DEFAULT_TECH_SERVICES_BASE_URL).strip()
        self.timeout_s = float(timeout_s)

    def _client(self, token: str = "") -> TechServicesHttpClient:
        return TechServicesHttpClient(TechServicesHttpConfig(
            base_url=self.base_url,
            bearer_token=str(token or ""),
            timeout_s=self.timeout_s,
        ))

    def client_for_session(self, session: AuthSession | None) -> TechServicesHttpClient:
        token = session.tokens.access_token if session is not None else ""
        return self._client(token)

    def credential_payload(self, session: AuthSession) -> dict[str, Any]:
        """Return the smallest restorable secret for the OS credential vault.

        Identity, role and capabilities are deliberately not persisted: they
        are refreshed from Tech Services whenever the token is restored.  This
        also keeps owner/admin sessions comfortably below the Windows
        Credential Manager generic-credential blob limit.
        """
        return {
            "schema": 1,
            "access_token": session.tokens.access_token,
            "expires_at_utc": float(session.tokens.expires_at_utc),
        }

    def sign_in(self, *, email: str, password: str) -> AuthSession:
        response = self._client().login(email=email, password=password)
        token = str(response.get("token") or "").strip()
        user = response.get("user") or {}
        if not token or not isinstance(user, Mapping):
            raise TechServicesHttpError("Tech Services login returned an incomplete authentication response")

        # Refresh server capabilities immediately rather than inventing desktop
        # permissions from the login response's plan/role labels.
        protected = self._client(token)
        caps_response = protected.capabilities()
        raw_caps = caps_response.get("capabilities") or []
        if not isinstance(raw_caps, (list, tuple, set)):
            raw_caps = []
        scopes = _desktop_scopes(raw_caps)
        role = str(caps_response.get("role") or user.get("role") or "").strip()
        identity = Identity(
            user_id=str(user.get("id") or user.get("user_id") or ""),
            display_name=str(user.get("name") or user.get("display_name") or ""),
            email=str(user.get("email") or email or ""),
            roles=(role,) if role else (),
            scopes=scopes,
        )
        if not identity.user_id:
            raise TechServicesHttpError("Tech Services login did not return a stable user id")
        return AuthSession(
            identity=identity,
            tokens=TokenSet(token, _decode_unverified_exp(token), scopes=scopes),
        )

    # PKCE-compatible protocol hooks are retained so this adapter can be
    # replaced cleanly when the site adds a native browser/device handoff.
    def authorization_url(self, *, redirect_uri: str, state: str, code_challenge: str) -> str:
        raise RuntimeError("The current Tech Services website uses direct first-party login; browser PKCE is not exposed yet")

    def exchange_authorization_code(self, *, code: str, code_verifier: str, redirect_uri: str) -> AuthSession:
        raise RuntimeError("Tech Services authorization-code exchange is not exposed yet")

    def refresh(self, refresh_token: str) -> AuthSession:
        raise RuntimeError("Tech Services does not currently issue refresh tokens; sign in again when the seven-day token expires")

    def revoke(self, refresh_token: str) -> None:
        # The audited site has no token-revocation endpoint. Local sign-out
        # clears the OS-vault copy. Server token expiry remains seven days.
        return None

    def restore_offline_session(self, payload: Mapping[str, Any]) -> Optional[AuthSession]:
        token = str(payload.get("access_token") or "").strip()
        expires = float(payload.get("expires_at_utc") or 0.0)
        if not token or expires <= utc_now_ts():
            return None
        try:
            client = self._client(token)
            me = client.current_user()
            caps_response = client.capabilities()
        except Exception:
            # No signed offline grant exists in the current website contract,
            # so a cached Bearer token is not treated as an offline entitlement.
            return None

        user = me.get("user") or {}
        if not isinstance(user, Mapping):
            return None
        raw_caps = caps_response.get("capabilities") or []
        if not isinstance(raw_caps, (list, tuple, set)):
            raw_caps = []
        scopes = _desktop_scopes(raw_caps)
        role = str(caps_response.get("role") or user.get("role") or "").strip()
        identity = Identity(
            user_id=str(user.get("id") or user.get("user_id") or ""),
            display_name=str(user.get("name") or user.get("display_name") or ""),
            email=str(user.get("email") or ""),
            roles=(role,) if role else (),
            scopes=scopes,
        )
        if not identity.user_id:
            return None
        return AuthSession(
            identity=identity,
            tokens=TokenSet(token, min(expires, _decode_unverified_exp(token)), scopes=scopes),
        )
