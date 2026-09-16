from runlab.security import desktop_auth_required

def test_source_development_requires_auth_by_default():
    assert desktop_auth_required(frozen=False,env={}) is True

def test_frozen_distribution_requires_auth_by_default():
    assert desktop_auth_required(frozen=True,env={}) is True

def test_explicit_auth_and_development_overrides():
    assert desktop_auth_required(frozen=False,env={'NHRA_TECH_AUTH_REQUIRED':'1'}) is True
    assert desktop_auth_required(frozen=True,env={'NHRA_TECH_DEV_UNAUTHENTICATED':'1'}) is False
    assert desktop_auth_required(frozen=True,env={'NHRA_TECH_AUTH_REQUIRED':'0'}) is False
