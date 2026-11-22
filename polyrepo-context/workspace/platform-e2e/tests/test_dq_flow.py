def test_dq_score_attached(int_env):
    int_env.land_batch("urn:ds:crm.customers")
    assert int_env.metadata_raw("urn:ds:crm.customers")["quality_score"] is not None
