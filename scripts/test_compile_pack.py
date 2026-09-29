#!/usr/bin/env python3
"""Tests for compiler/compile-pack.py: write_scope rendering, --check discovery.

    python3 scripts/test_compile_pack.py
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("compile_pack", ROOT / "compiler" / "compile-pack.py")
CP = importlib.util.module_from_spec(spec)
sys.modules["compile_pack"] = CP
spec.loader.exec_module(CP)


class WriteScope(unittest.TestCase):
    def test_rendered(self):
        pack = CP.read_pack("developer")
        doc = CP.render_role_doc(pack)
        self.assertIn("# Write scope", doc)
        self.assertIn("`prds/**`", doc)
        self.assertIn("`src/**`", doc)


class CheckDiscovery(unittest.TestCase):
    def test_dir_without_pack_yaml_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            packs = Path(tmp)
            (packs / "broken").mkdir()
            old, CP.PACKS_DIR = CP.PACKS_DIR, packs
            argv, sys.argv = sys.argv, ["compile-pack.py", "--check"]
            try:
                err = StringIO()
                with redirect_stderr(err), redirect_stdout(StringIO()):
                    rc = CP.main()
            finally:
                CP.PACKS_DIR, sys.argv = old, argv
            self.assertEqual(rc, 1)
            self.assertIn("broken", err.getvalue())


if __name__ == "__main__":
    unittest.main()
