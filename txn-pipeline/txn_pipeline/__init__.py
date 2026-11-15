"""Shim so ``python -m txn_pipeline`` works from the project root uninstalled.

The real package lives in ``src/txn_pipeline``; this module redirects the
package search path there and runs the real ``__init__``.
"""

from pathlib import Path

_SRC_PACKAGE = Path(__file__).resolve().parent.parent / "src" / "txn_pipeline"
__path__ = [str(_SRC_PACKAGE)]
_init = _SRC_PACKAGE / "__init__.py"
exec(compile(_init.read_text(encoding="utf-8"), str(_init), "exec"))
