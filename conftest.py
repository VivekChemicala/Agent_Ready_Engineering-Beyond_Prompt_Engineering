"""Puts src/ and the pinned platform-contracts checkout on sys.path.

platform-contracts is resolved from $PLATFORM_CONTRACTS_PATH, else .deps/platform-contracts
(created by scripts/fetch_deps.sh). The checkout's version must equal the pin in requirements.txt.
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))
CONTRACTS = Path(os.environ.get("PLATFORM_CONTRACTS_PATH", ROOT / ".deps" / "platform-contracts"))
if not (CONTRACTS / "src" / "platform_contracts").is_dir():
    raise RuntimeError("platform-contracts not found: run scripts/fetch_deps.sh or set PLATFORM_CONTRACTS_PATH")
sys.path.insert(0, str(CONTRACTS / "src"))

import platform_contracts  # noqa: E402

PIN = re.search(r"platform-contracts==([\w.]+)", (ROOT / "requirements.txt").read_text()).group(1)
if platform_contracts.__version__ != PIN:
    raise RuntimeError(f"requirements.txt pins platform-contracts=={PIN} "
                       f"but {CONTRACTS} is {platform_contracts.__version__}")
