from runlab.auth import AuthManager, AuthSession, Identity, MemoryCredentialStore, TokenSet, UnboundTechServicesAuthProvider, AccessDenied
from runlab.transport import AuthorizedTechServicesTransport, ProviderCapabilities

class FakeTransport:
    capabilities=ProviderCapabilities(provider='fake',catalog_pull=True,asset_fetch=True,analysis_push=True)
    def pull_catalog_snapshot(self,*,cursor=''):return {'cursor':'n','events':[]}
    def fetch_asset(self,remote_asset_id):return b'data'
    def push_analysis_bundle(self,payload):return {'ok':True}

def manager(scopes):
    m=AuthManager(UnboundTechServicesAuthProvider(),MemoryCredentialStore())
    m.set_session(AuthSession(Identity('u',scopes=tuple(scopes)),TokenSet('a',9e12,scopes=tuple(scopes))),persist=False)
    return m

def test_transport_scopes_are_operation_specific():
    t=AuthorizedTechServicesTransport(FakeTransport(),manager(['desktop.access','runs.read','assets.read']))
    assert t.pull_catalog_snapshot()['events']==[]
    assert t.fetch_asset('x')==b'data'
    try:t.push_analysis_bundle({})
    except AccessDenied:pass
    else:raise AssertionError('analysis.write should be required')

def test_development_wrapper_can_be_non_enforcing():
    t=AuthorizedTechServicesTransport(FakeTransport(),manager([]),enforce=False)
    assert t.fetch_asset('x')==b'data'
