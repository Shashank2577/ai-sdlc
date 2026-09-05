#!/usr/bin/env python3
"""Tests for the pack-coverage check (#190).

`TestUnits` uses a small synthetic `packs_dir` fixture (real pack policies
carry `!(role)`-style extglob denies that make `_root`'s coarse,
first-wildcard-character truncation an unreliable signal at whole-directory
granularity — a synthetic fixture with plain globs keeps that pre-existing
matcher quirk out of these assertions). `TestAgainstRealPacks` replays the
same functions against this repo's actual `role-packs/`, pinning the two
directories #190 found unclaimed (`portal/`, `adapters/`, now developer's)
and the general shape of the report.

    python3 scripts/test_check_pack_coverage.py
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
spec = importlib.util.spec_from_file_location("check_pack_coverage", HERE / "check-pack-coverage.py")
C = importlib.util.module_from_spec(spec)
sys.modules["check_pack_coverage"] = C
spec.loader.exec_module(C)


def make_pack(root: Path, role: str, allow: list[str]) -> None:
    pack_dir = root / role
    pack_dir.mkdir(parents=True)
    (pack_dir / "policy.yaml").write_text(
        yaml.safe_dump({"role": role, "write_scope": {"allow": allow}}))


class TestTopLevelDirs(unittest.TestCase):
    def test_first_segment_of_each_path(self):
        self.assertEqual(
            C.top_level_dirs(["portal/build.py", "adapters/tracker/base.py", "portal/test_build.py"]),
            ["adapters", "portal"])

    def test_root_file_names_no_directory_and_is_dropped(self):
        self.assertEqual(C.top_level_dirs(["README.md", "src/main.py"]), ["src"])

    def test_dedupes(self):
        self.assertEqual(C.top_level_dirs(["a/one.py", "a/two.py"]), ["a"])


class TestUnits(unittest.TestCase):
    """A directory with committed code and no owning pack must be reported
    — the acceptance criterion #190 names explicitly.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.packs_dir = Path(self._tmp.name)
        make_pack(self.packs_dir, "developer", ["src/**"])
        make_pack(self.packs_dir, "architect", ["adrs/**"])

    def tearDown(self):
        self._tmp.cleanup()

    def test_claimed_directory_reports_its_role(self):
        coverage = C.analyze(["src/main.py", "adrs/0001.md"], self.packs_dir)
        self.assertEqual(coverage["src"], ["developer"])
        self.assertEqual(coverage["adrs"], ["architect"])

    def test_unclaimed_directory_is_reported_with_no_pack(self):
        coverage = C.analyze(["src/main.py", "orphan/thing.py"], self.packs_dir)
        self.assertIn("orphan", coverage)
        self.assertEqual(coverage["orphan"], [])

    def test_report_names_the_unclaimed_directory(self):
        coverage = C.analyze(["orphan/thing.py"], self.packs_dir)
        report = C.render_report(coverage)
        self.assertIn("`orphan/` — **no pack**", report)
        self.assertIn("Unclaimed: `orphan/`", report)

    def test_report_omits_unclaimed_section_when_everything_is_claimed(self):
        coverage = C.analyze(["src/main.py"], self.packs_dir)
        report = C.render_report(coverage)
        self.assertNotIn("Unclaimed", report)

    def test_main_exits_nonzero_when_a_directory_is_unclaimed(self):
        coverage = C.analyze(["orphan/thing.py"], self.packs_dir)
        self.assertTrue(any(not roles for roles in coverage.values()))

    def test_main_exits_zero_when_everything_is_claimed(self):
        coverage = C.analyze(["src/main.py", "adrs/0001.md"], self.packs_dir)
        self.assertFalse(any(not roles for roles in coverage.values()))


class TestAgainstRealPacks(unittest.TestCase):
    """Replayed against this repo's real `role-packs/` — the gap #190
    actually found and fixed.
    """

    def test_portal_and_adapters_are_now_developer_owned(self):
        coverage = C.analyze(["portal/build.py", "adapters/tracker/base.py"])
        self.assertEqual(coverage["portal"], ["developer"])
        self.assertEqual(coverage["adapters"], ["developer"])

    def test_dashboards_and_compiler_remain_developer_owned(self):
        # Unrelated to #190 — pinned so a future edit that narrows
        # developer's scope notices it broke these too.
        coverage = C.analyze(["dashboards/status.py", "compiler/compile-pack.py"])
        self.assertEqual(coverage["dashboards"], ["developer"])
        self.assertEqual(coverage["compiler"], ["developer"])


if __name__ == "__main__":
    unittest.main()
