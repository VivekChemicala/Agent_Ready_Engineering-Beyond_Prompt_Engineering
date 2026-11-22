def test_domain_grant_can_query(int_env):
    int_env.grant("bob", "domain:crm:read")
    status, body = int_env.query("bob", "urn:ds:crm.customers", "select * from customers")
    assert status == 200 and body["rows"]


def test_no_grant_is_forbidden(int_env):
    status, _ = int_env.query("eve", "urn:ds:crm.customers", "select 1")
    assert status == 403
