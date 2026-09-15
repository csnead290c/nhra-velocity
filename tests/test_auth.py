from runlab.auth import (
    AccessDenied,
    AuthManager,
    AuthSession,
    Identity,
    MemoryCredentialStore,
    TokenSet,
    UnboundTechServicesAuthProvider,
    create_pkce_material,
)


def session(*, exp=2000.0, offline=0.0, scopes=("desktop.access", "simulation.use"), refresh="r"):
    return AuthSession(
        Identity("u1", "Engineer", "eng@example.com", roles=("engineering",), scopes=scopes),
        TokenSet("a", exp, refresh_token=refresh, scopes=scopes),
        issued_at_utc=1000.0,
        offline_grant="signed-grant" if offline else "",
        offline_valid_until_utc=offline,
    )


def test_pkce_s256_shape_and_state_are_generated():
    p=create_pkce_material()
    assert 43 <= len(p.verifier) <= 128
    assert p.method == "S256"
    assert p.challenge and "=" not in p.challenge
    assert p.state


def test_auth_manager_scope_and_offline_access():
    mgr=AuthManager(UnboundTechServicesAuthProvider(), MemoryCredentialStore())
    mgr.set_session(session(exp=1100.0, offline=1500.0), persist=False)
    assert mgr.status(now_utc=1050.0).online_access_valid
    assert mgr.require("simulation.use", now_utc=1200.0).user_id == "u1"
    try:
        mgr.require("admin", now_utc=1200.0)
    except AccessDenied:
        pass
    else:
        raise AssertionError("missing entitlement should fail closed")
    try:
        mgr.require("simulation.use", now_utc=1600.0)
    except AccessDenied:
        pass
    else:
        raise AssertionError("expired offline entitlement should fail closed")


def test_refresh_secret_persists_only_to_credential_store():
    store=MemoryCredentialStore();mgr=AuthManager(UnboundTechServicesAuthProvider(),store)
    s=session(exp=2000.0,offline=3000.0)
    mgr.set_session(s)
    payload=store.load("nhra-tech-services","default")
    assert payload["refresh_token"] == "r"
    assert payload["offline_grant"] == "signed-grant"
    assert "access_token" not in payload
    mgr.sign_out()
    assert store.load("nhra-tech-services","default") is None


def test_unbound_provider_never_restores_cached_identity():
    store=MemoryCredentialStore();store.save("nhra-tech-services","default",session().to_secret_payload())
    mgr=AuthManager(UnboundTechServicesAuthProvider(),store)
    assert mgr.restore() is False
    assert mgr.session is None


def test_access_token_can_be_persisted_only_for_opt_in_provider():
    class AccessTokenProvider(UnboundTechServicesAuthProvider):
        persist_access_token = True

        def restore_offline_session(self, payload):
            return None

    store=MemoryCredentialStore();mgr=AuthManager(AccessTokenProvider(),store)
    s=session(exp=2000.0, refresh="")
    mgr.set_session(s)
    payload=store.load("nhra-tech-services","default")
    assert payload["access_token"] == "a"
    assert payload["expires_at_utc"] == 2000.0
    assert "password" not in payload
