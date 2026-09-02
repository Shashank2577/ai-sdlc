#!/usr/bin/env python3
"""Tests for the wiki generator.

The property that matters is that no published page can be a hand-edited
orphan: every page carries the "generated" banner, and every factual page
is computed rather than copied.

    python3 scripts/test_build_wiki.py
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

spec = importlib.util.spec_from_file_location("build_wiki", HERE / "build-wiki.py")
W = importlib.util.module_from_spec(spec)
sys.modules["build_wiki"] = W
spec.loader.exec_module(W)

TRACEABILITY = {
    "meta": {"commits_scanned": 25, "head": "abc1234def", "generated_at": "2026-09-02 01:00 UTC"},
    "rows": [
        {"req": "REQ-001", "status": "red", "pulls": []},
        {"req": "REQ-002", "status": "green",
         "pulls": [{"number": 11, "url": "https://x/11"}]},
        {"req": "REQ-014", "status": "amber", "pulls": []},
    ],
}


class TestGeneratedPages(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def build(self, traceability=TRACEABILITY):
        tf = self.out / "trace.json"
        if traceability is not None:
            tf.write_text(json.dumps(traceability))
        argv = sys.argv
        sys.argv = ["build-wiki.py", "--out", str(self.out / "wiki"),
                    "--traceability", str(tf)]
        try:
            W.main()
        finally:
            sys.argv = argv
        return self.out / "wiki"

    def test_every_published_page_says_it_is_generated(self):
        # The one property that keeps a wiki honest: nobody should think
        # editing it in the browser is how you change anything.
        wiki = self.build()
        pages = [p for p in wiki.glob("*.md") if p.name != "_Sidebar.md"]
        self.assertGreaterEqual(len(pages), 5)
        for page in pages:
            with self.subTest(page=page.name):
                self.assertIn("Generated from the repository", page.read_text())
                self.assertIn("do not edit this page", page.read_text())

    def test_the_banner_names_the_source_to_edit_instead(self):
        wiki = self.build()
        self.assertIn("role-packs/*/", (wiki / "Roles.md").read_text())
        self.assertIn("wiki/Conventions.md", (wiki / "Conventions.md").read_text())

    def test_roles_page_is_built_from_the_real_packs(self):
        wiki = self.build()
        text = (wiki / "Roles.md").read_text()
        packs = sorted(p.name for p in (REPO_ROOT / "role-packs").iterdir()
                       if (p / "pack.yaml").is_file())
        self.assertTrue(packs)
        for role in packs:
            with self.subTest(role=role):
                self.assertIn(f"`{role}`", text)

    def test_roles_page_reports_unprovisioned_identities_rather_than_hiding_them(self):
        text = self.build().joinpath("Roles.md").read_text()
        self.assertIn("not provisioned", text)

    def test_requirements_page_lists_every_req_in_the_index(self):
        text = self.build().joinpath("Requirements.md").read_text()
        index = (REPO_ROOT / "requirements" / "index.md").read_text()
        ids = [line.split("|")[1].strip().strip("`")
               for line in index.splitlines() if W.REQ_ROW.match(line.strip())]
        self.assertGreaterEqual(len(ids), 14)
        for req in ids:
            with self.subTest(req=req):
                self.assertIn(req, text)

    def test_requirements_page_shows_trace_status_and_pr_links(self):
        text = self.build().joinpath("Requirements.md").read_text()
        self.assertIn("traced", text)
        self.assertIn("untraced", text)
        self.assertIn("https://x/11", text)

    def test_a_requirement_with_no_traceability_data_reads_unknown_not_traced(self):
        # Missing data must never render as a green claim.
        text = self.build(traceability={"meta": {}, "rows": []}).joinpath(
            "Requirements.md").read_text()
        self.assertIn("unknown", text)
        self.assertNotIn("| traced |", text)

    def test_home_carries_the_live_counts(self):
        text = self.build().joinpath("Home.md").read_text()
        self.assertIn("25", text)          # commits scanned
        self.assertIn("abc1234", text)     # head sha, short
        self.assertIn("2026-09-02", text)  # generated at

    def test_sidebar_links_the_live_surfaces(self):
        text = self.build().joinpath("_Sidebar.md").read_text()
        for target in ("projects/2", "traceability.html", "standup.html"):
            with self.subTest(target=target):
                self.assertIn(target, text)

    def test_prose_pages_are_copied_from_the_repo_source(self):
        wiki = self.build()
        for name in ("Operating-the-System.md", "Conventions.md"):
            with self.subTest(page=name):
                src = (REPO_ROOT / "wiki" / name).read_text()
                self.assertIn(src.strip()[:60], (wiki / name).read_text())


class TestSourceTree(unittest.TestCase):
    def test_every_wiki_source_page_is_reachable_from_the_sidebar(self):
        # A page nobody can navigate to is a page nobody reads.
        sidebar = W.SIDEBAR
        for src in (REPO_ROOT / "wiki").glob("*.md"):
            with self.subTest(page=src.name):
                self.assertIn(f"[[{src.stem}]]", sidebar)


if __name__ == "__main__":
    unittest.main(verbosity=2)
