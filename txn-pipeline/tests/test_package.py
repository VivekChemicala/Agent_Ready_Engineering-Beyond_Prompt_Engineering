from pathlib import Path

import txn_pipeline
from txn_pipeline import pipeline


def test_package_exposes_run_pipeline():
    assert callable(txn_pipeline.run_pipeline)


def test_code_is_loaded_from_src():
    src = Path(__file__).resolve().parents[1] / "src" / "txn_pipeline"
    assert Path(pipeline.__file__).resolve().parent == src
