from types import SimpleNamespace

from entitlements.policies import PolicyEngine


class FakeMeta:
    def get_dataset(self, urn):
        return SimpleNamespace(urn=urn, domain="crm", owner="alice")


def test_domain_grant_allows():
    e = PolicyEngine({"bob": {"domain:crm:read"}}, FakeMeta())
    assert e.decide("bob", "urn:ds:crm.customers", "read").allow
