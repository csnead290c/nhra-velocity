from __future__ import annotations

"""Authentication and desktop-access boundary for NHRA Tech Services.

The desktop must never embed or persist the Tech Services user's password,
scrape browser cookies, or ship a client secret that is assumed confidential.
A read-only source audit in v0.32 confirmed that the current website API issues
a seven-day Bearer token from its direct login endpoint, but it does not expose
a native-app authorization-code/PKCE or refresh-token flow.

The generic PKCE/session primitives remain here as the preferred future native
handoff boundary. Production desktop sign-in remains fail-closed until Tech
Services adds a safe browser/device handoff; HTTP transport mechanics are bound
separately in ``tech_services_http``.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import base64
import hashlib
import json
import secrets
from typing import Any, Mapping, Optional, Protocol, Sequence, runtime_checkable


def utc_now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


@dataclass(frozen=True)
class PkceMaterial:
    verifier: str
    challenge: str
    method: str = "S256"
    state: str = ""


def create_pkce_material() -> PkceMaterial:
    # 64 bytes gives a verifier comfortably inside RFC 7636's 43-128 character
    # range once URL-safe base64 encoded without padding.
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode("ascii").rstrip("=")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return PkceMaterial(verifier=verifier, challenge=challenge, state=secrets.token_urlsafe(32))


@dataclass(frozen=True)
class Identity:
    user_id: str
    display_name: str = ""
    email: str = ""
    roles: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Identity":
        return cls(
            user_id=str(value.get("user_id") or value.get("sub") or value.get("id") or ""),
            display_name=str(value.get("display_name") or value.get("name") or ""),
            email=str(value.get("email") or ""),
            roles=tuple(str(x) for x in (value.get("roles") or ())),
            scopes=tuple(str(x) for x in (value.get("scopes") or ())),
        )


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    expires_at_utc: float
    refresh_token: str = ""
    token_type: str = "Bearer"
    scopes: tuple[str, ...] = ()

    @property
    def expired(self) -> bool:
        return self.expires_at_utc <= utc_now_ts()


@dataclass(frozen=True)
class AuthSession:
    identity: Identity
    tokens: TokenSet
    issued_at_utc: float = field(default_factory=utc_now_ts)
    # A production server may issue a signed offline entitlement/grant so a
    # track-side laptop can keep working for a bounded period without network.
    # The desktop treats it as opaque; verification belongs to the bound
    # provider/JWS verifier, not to this generic model.
    offline_grant: str = ""
    offline_valid_until_utc: float = 0.0

    def allows(self, scope: str) -> bool:
        wanted = str(scope or "").strip()
        if not wanted:
            return True
        available = set(self.identity.scopes) | set(self.tokens.scopes)
        return wanted in available or "*" in available

    def to_secret_payload(self) -> dict[str, Any]:
        """Serialize only values appropriate for OS credential storage."""
        return {
            "refresh_token": self.tokens.refresh_token,
            "offline_grant": self.offline_grant,
            "offline_valid_until_utc": float(self.offline_valid_until_utc or 0.0),
            "identity": asdict(self.identity),
        }


@dataclass(frozen=True)
class AuthStatus:
    signed_in: bool
    online_access_valid: bool
    offline_access_valid: bool
    identity: Optional[Identity] = None
    reason: str = ""


@runtime_checkable
class TechServicesAuthProvider(Protocol):
    provider_name: str

    def authorization_url(self, *, redirect_uri: str, state: str, code_challenge: str) -> str: ...
    def exchange_authorization_code(self, *, code: str, code_verifier: str, redirect_uri: str) -> AuthSession: ...
    def refresh(self, refresh_token: str) -> AuthSession: ...
    def revoke(self, refresh_token: str) -> None: ...
    def restore_offline_session(self, payload: Mapping[str, Any]) -> Optional[AuthSession]: ...


class UnboundTechServicesAuthProvider:
    """Fail-closed native sign-in provider until the site exposes a safe desktop handoff."""

    provider_name = "nhra-tech-services"

    @staticmethod
    def _unbound() -> RuntimeError:
        return RuntimeError(
            "NHRA Tech Services authentication is not bound. The desktop intentionally does not guess "
            "login URLs, token endpoints, cookie/session formats, JWT keys, or role names."
        )

    def authorization_url(self, *, redirect_uri: str, state: str, code_challenge: str) -> str:
        raise self._unbound()

    def exchange_authorization_code(self, *, code: str, code_verifier: str, redirect_uri: str) -> AuthSession:
        raise self._unbound()

    def refresh(self, refresh_token: str) -> AuthSession:
        raise self._unbound()

    def revoke(self, refresh_token: str) -> None:
        raise self._unbound()

    def restore_offline_session(self, payload: Mapping[str, Any]) -> Optional[AuthSession]:
        # Never trust a cached identity/grant unless the real provider can
        # cryptographically validate whatever the server issued.
        return None


@runtime_checkable
class CredentialStore(Protocol):
    def save(self, provider: str, account: str, payload: Mapping[str, Any]) -> None: ...
    def load(self, provider: str, account: str) -> Optional[dict[str, Any]]: ...
    def clear(self, provider: str, account: str) -> None: ...


class MemoryCredentialStore:
    """Tests/development only. Never use this as a persistence fallback."""

    def __init__(self):
        self._items: dict[tuple[str, str], str] = {}

    def save(self, provider: str, account: str, payload: Mapping[str, Any]) -> None:
        self._items[(provider, account)] = json.dumps(dict(payload))

    def load(self, provider: str, account: str) -> Optional[dict[str, Any]]:
        value = self._items.get((provider, account))
        return json.loads(value) if value else None

    def clear(self, provider: str, account: str) -> None:
        self._items.pop((provider, account), None)


class KeyringCredentialStore:
    """OS credential-vault storage (Credential Manager/Keychain/etc.).

    There is intentionally no plaintext-file fallback.  If keyring is not
    available/configured, production refresh-token persistence must fail rather
    than quietly writing a credential into the workbook or app-data directory.
    """

    service_prefix = "NHRA.TechData"

    @staticmethod
    def _keyring():
        try:
            import keyring  # type: ignore
        except Exception as exc:  # pragma: no cover - platform/env dependent
            raise RuntimeError(
                "Secure OS credential storage is unavailable. Install/configure the 'keyring' package; "
                "NHRA Tech Data will not store refresh tokens in plaintext."
            ) from exc
        return keyring

    def _service(self, provider: str) -> str:
        return f"{self.service_prefix}.{provider}"

    def save(self, provider: str, account: str, payload: Mapping[str, Any]) -> None:
        self._keyring().set_password(self._service(provider), account, json.dumps(dict(payload), separators=(",", ":")))

    def load(self, provider: str, account: str) -> Optional[dict[str, Any]]:
        raw = self._keyring().get_password(self._service(provider), account)
        return json.loads(raw) if raw else None

    def clear(self, provider: str, account: str) -> None:
        try:
            self._keyring().delete_password(self._service(provider), account)
        except Exception:
            # Deleting a missing credential should behave idempotently across
            # keyring backends.
            pass


class AccessDenied(PermissionError):
    pass


class AuthManager:
    """Small state machine shared by UI, transport and future headless clients."""

    def __init__(
        self,
        provider: TechServicesAuthProvider,
        credential_store: Optional[CredentialStore] = None,
        *,
        required_scope: str = "desktop.access",
        credential_account: str = "default",
    ):
        self.provider = provider
        self.credential_store = credential_store
        self.required_scope = required_scope
        self.credential_account = credential_account
        self.session: Optional[AuthSession] = None

    def set_session(self, session: AuthSession, *, persist: bool = True) -> None:
        if not session.identity.user_id:
            raise ValueError("Authenticated session must contain a stable user identity")
        self.session = session
        if persist and self.credential_store and session.tokens.refresh_token:
            self.credential_store.save(
                self.provider.provider_name,
                self.credential_account,
                session.to_secret_payload(),
            )

    def restore(self) -> bool:
        if not self.credential_store:
            return False
        payload = self.credential_store.load(self.provider.provider_name, self.credential_account)
        if not payload:
            return False
        restored = self.provider.restore_offline_session(payload)
        if restored is None:
            return False
        self.session = restored
        return True

    def sign_out(self) -> None:
        current = self.session
        self.session = None
        if current and current.tokens.refresh_token:
            try:
                self.provider.revoke(current.tokens.refresh_token)
            except Exception:
                # Local sign-out should still remove the local credential even
                # if the server is unreachable. A production adapter can queue
                # revocation or expose that status separately.
                pass
        if self.credential_store:
            self.credential_store.clear(self.provider.provider_name, self.credential_account)

    def refresh_if_needed(self, *, skew_s: float = 60.0) -> Optional[AuthSession]:
        current = self.session
        if current is None:
            return None
        if current.tokens.expires_at_utc > utc_now_ts() + max(0.0, skew_s):
            return current
        if not current.tokens.refresh_token:
            return current
        updated = self.provider.refresh(current.tokens.refresh_token)
        self.set_session(updated, persist=True)
        return updated

    def status(self, *, now_utc: Optional[float] = None) -> AuthStatus:
        now = utc_now_ts() if now_utc is None else float(now_utc)
        if self.session is None:
            return AuthStatus(False, False, False, reason="not signed in")
        online = self.session.tokens.expires_at_utc > now and self.session.allows(self.required_scope)
        offline = bool(
            self.session.offline_grant
            and self.session.offline_valid_until_utc > now
            and self.session.allows(self.required_scope)
        )
        reason = ""
        if not self.session.allows(self.required_scope):
            reason = f"missing required scope: {self.required_scope}"
        elif not online and not offline:
            reason = "access token/offline entitlement expired"
        return AuthStatus(True, online, offline, self.session.identity, reason)

    def require(self, scope: str = "", *, allow_offline: bool = True, now_utc: Optional[float] = None) -> Identity:
        wanted = scope or self.required_scope
        status = self.status(now_utc=now_utc)
        if self.session is None:
            raise AccessDenied("Sign in to NHRA Tech Services is required")
        if not self.session.allows(wanted):
            raise AccessDenied(f"Your NHRA Tech Services account is not entitled to '{wanted}'")
        now = utc_now_ts() if now_utc is None else float(now_utc)
        if self.session.tokens.expires_at_utc > now:
            return self.session.identity
        if allow_offline and self.session.offline_grant and self.session.offline_valid_until_utc > now:
            return self.session.identity
        raise AccessDenied("NHRA Tech Services authorization has expired; reconnect and sign in again")
