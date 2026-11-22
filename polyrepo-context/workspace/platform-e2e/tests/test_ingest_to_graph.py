def test_discovered_schema_appears_in_graph(int_env):
    int_env.ingest_table("crm", "customers")
    cols = int_env.metadata.get_columns("urn:ds:crm.customers")
    assert {c.name for c in cols} >= {"id", "email"}
