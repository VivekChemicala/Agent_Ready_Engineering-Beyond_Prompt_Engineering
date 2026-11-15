import txn_pipeline


def test_package_exposes_run_pipeline():
    assert callable(txn_pipeline.run_pipeline)
