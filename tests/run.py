"""Run the Quant OS test suite: python tests/run.py [pattern]

Runs from any directory. The repository root is kept off sys.path on purpose (see tests/support.py).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
sys.path[:] = [str(TESTS)] + [p for p in sys.path if Path(p or ".").resolve() not in (ROOT, TESTS)]

pattern = sys.argv[1] if len(sys.argv) > 1 else "test_*.py"
suite = unittest.defaultTestLoader.discover(str(TESTS), pattern=pattern, top_level_dir=str(TESTS))
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
