#!/usr/bin/env python3
"""Tests for the traceability generator.

The parsing and the join are pure functions, so they are tested with
fixtures rather than against a live repository — the tests have to hold
for histories this repo has not reached yet (merged PRs, orphan REQs,
several commits per requirement).

    python3 dashboards/test_build.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

spec = importlib.util.spec_from_file_location("dash_build", HERE / "build.py")
B = importlib.util.module_from_spec(spec)
# Register before exec: @dataclass resolves annotations through
# sys.modules[cls.__module__], which is None for an unregistered module.
sys.modules["dash_build"] = B
spec.loader.exec_module(B)


REQ_MD = """
# Foundry — Requirement Index (REQ v0)

| ID | Requirement | PRD § |
|---|---|---|
| REQ-001 | All agent coordination happens through the tracker. | §1 P1–P2 |
| REQ-002 | Roles are harness-neutral packs. | §3 |
| REQ-003 | Harness adapter: Claude Code, Codex, DeepSeek interchangeable. | §11.2 |

## Traceability convention

Branch: `story/FDY-<issue#>-<slug>`
"""


def log(*records: tuple[str, str, str, str]) -> str:
    """Build a `git log` payload in the exact format collect_commits emits."""
    return "\x01".join(
        f"{sha}\x00{subject}\x00{date}\x00{trailers}" for sha, subject, date, trailers in records
    ) + "\x01"


TRAILERS_DEV = ("Work-Item: acme/widgets#3\nRequirement: REQ-002, REQ-003\n"
                "Agent-Role: developer\nHarness: claude-code/2.1.220\n")
TRAILERS_HUMAN = ("Work-Item: acme/widgets#1\nRequirement: REQ-001\n"
                  "Agent-Role: human\nHarness: manual\n")


class TestParseRequirements(unittest.TestCase):
    def test_extracts_every_row(self):
        reqs = B.parse_requirements(REQ_MD)
        self.assertEqual([r[0] for r in reqs], ["REQ-001", "REQ-002", "REQ-003"])
        self.assertEqual(reqs[1][1], "Roles are harness-neutral packs.")
        self.assertEqual(reqs[2][2], "§11.2")

    def test_ignores_prose_and_the_convention_section(self):
        # `REQ-0XX` in the convention block is not a requirement row.
        self.assertEqual(len(B.parse_requirements(REQ_MD)), 3)

    def test_empty_input(self):
        self.assertEqual(B.parse_requirements("# nothing here\n"), [])


class TestParseCommits(unittest.TestCase):
    def test_trailers_are_split_out(self):
        commits = B.parse_commits(log(("abc123", "feat: thing", "2026-09-01T00:00:00Z",
                                       TRAILERS_DEV)))
        self.assertEqual(len(commits), 1)
        c = commits[0]
        self.assertEqual(c.sha, "abc123")
        self.assertEqual(c.role, "developer")
        self.assertEqual(c.harness, "claude-code/2.1.220")
        self.assertEqual(c.requirements, ["REQ-002", "REQ-003"])

    def test_commit_without_trailers(self):
        c = B.parse_commits(log(("abc", "chore: no trailers", "2026-09-01T00:00:00Z", "")))[0]
        self.assertEqual(c.requirements, [])
        self.assertEqual(c.role, "unknown")

    def test_subject_containing_a_colon_is_not_read_as_a_trailer(self):
        c = B.parse_commits(log(("abc", "feat(x): y: z", "2026-09-01T00:00:00Z",
                                 TRAILERS_HUMAN)))[0]
        self.assertEqual(c.subject, "feat(x): y: z")
        self.assertEqual(c.requirements, ["REQ-001"])

    def test_empty_log(self):
        self.assertEqual(B.parse_commits(""), [])


class TestBuildMatrix(unittest.TestCase):
    def setUp(self):
        self.reqs = B.parse_requirements(REQ_MD)

    def test_every_requirement_appears_even_with_no_commits(self):
        rows = B.build_matrix(self.reqs, [], {})
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r.status == B.RED for r in rows))

    def test_commit_without_a_merged_pr_is_amber(self):
        commits = B.parse_commits(log(("abc", "s", "2026-09-01T00:00:00Z", TRAILERS_HUMAN)))
        rows = {r.req: r for r in B.build_matrix(self.reqs, commits, {})}
        self.assertEqual(rows["REQ-001"].status, B.AMBER)
        self.assertEqual(rows["REQ-002"].status, B.RED)

    def test_commit_in_a_merged_pr_is_green(self):
        commits = B.parse_commits(log(("abc", "s", "2026-09-01T00:00:00Z", TRAILERS_DEV)))
        pulls = {"abc": [{"number": 11, "url": "u", "title": "t", "merged_at": "x"}]}
        rows = {r.req: r for r in B.build_matrix(self.reqs, commits, pulls)}
        self.assertEqual(rows["REQ-002"].status, B.GREEN)
        self.assertEqual(rows["REQ-003"].status, B.GREEN)   # one commit, two REQs
        self.assertEqual(rows["REQ-001"].status, B.RED)

    def test_a_pr_is_listed_once_per_requirement(self):
        pr = {"number": 11, "url": "u", "title": "t", "merged_at": "x"}
        commits = B.parse_commits(log(
            ("abc", "one", "2026-09-01T00:00:00Z", TRAILERS_DEV),
            ("def", "two", "2026-09-02T00:00:00Z", TRAILERS_DEV),
        ))
        rows = {r.req: r for r in
                B.build_matrix(self.reqs, commits, {"abc": [pr], "def": [pr]})}
        self.assertEqual(len(rows["REQ-002"].commits), 2)
        self.assertEqual(len(rows["REQ-002"].pulls), 1)

    def test_requirement_not_in_the_index_is_surfaced_not_dropped(self):
        trailers = "Requirement: REQ-999\nAgent-Role: developer\nHarness: manual\n"
        commits = B.parse_commits(log(("abc", "s", "2026-09-01T00:00:00Z", trailers)))
        rows = B.build_matrix(self.reqs, commits, {})
        orphan = [r for r in rows if r.req == "REQ-999"]
        self.assertEqual(len(orphan), 1, "an unknown REQ trailer must still appear")
        self.assertIn("not in requirements/index.md", orphan[0].text)

    def test_roles_are_collected_per_requirement(self):
        commits = B.parse_commits(log(
            ("abc", "one", "2026-09-01T00:00:00Z", TRAILERS_DEV),
            ("def", "two", "2026-09-02T00:00:00Z",
             "Requirement: REQ-002\nAgent-Role: qa\nHarness: manual\n"),
        ))
        rows = {r.req: r for r in B.build_matrix(self.reqs, commits, {})}
        self.assertEqual(sorted(rows["REQ-002"].roles), ["developer", "qa"])


class TestRender(unittest.TestCase):
    def test_html_is_self_contained_and_escapes_input(self):
        reqs = [("REQ-001", "Text with <script>alert(1)</script> & an ampersand", "§1")]
        html = B.render_html(B.build_matrix(reqs, [], {}), {"repo": "a/b"})
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("http://", html.split("<style>")[1].split("</style>")[0])
        self.assertIn("untraced", html)

    def test_counts_render(self):
        commits = B.parse_commits(log(("abc", "s", "2026-09-01T00:00:00Z", TRAILERS_DEV)))
        rows = B.build_matrix(B.parse_requirements(REQ_MD), commits,
                              {"abc": [{"number": 1, "url": "u", "title": "t",
                                        "merged_at": "x"}]})
        html = B.render_html(rows, {"repo": "a/b"})
        self.assertIn(">2<", html)   # two green
        self.assertIn(">3<", html)   # three requirements


class TestPageDiscovery(unittest.TestCase):
    """Generators declare their own index entry; build.py only discovers.

    Covers dashboards#127: three consecutive merge conflicts on a
    hardcoded page list in build.py, and an index that silently omitted a
    page whose `append` a branch forgot.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name)

    def test_no_pages(self):
        pages, orphans = B.discover_pages(self.out)
        self.assertEqual(pages, [])
        self.assertEqual(orphans, [])

    def test_one_page(self):
        (self.out / "standup.html").write_text("<html></html>")
        B.write_page(self.out, "standup.html", "Standup digest", "desc")
        pages, orphans = B.discover_pages(self.out)
        self.assertEqual(pages, [("standup.html", "Standup digest", "desc")])
        self.assertEqual(orphans, [])

    def test_all_pages_sorted_deterministically_regardless_of_write_order(self):
        entries = [
            ("traceability.html", "Traceability matrix", "d1"),
            ("standup.html", "Standup digest", "d2"),
            ("burndown.html", "Burndown & velocity", "d3"),
            ("qa.html", "QA verdicts", "d4"),
            ("decisions.html", "Decisions", "d5"),
            ("status.html", "Programme status", "d6"),
        ]
        for href, title, desc in entries:
            (self.out / href).write_text("<html></html>")
            B.write_page(self.out, href, title, desc)

        pages, orphans = B.discover_pages(self.out)
        self.assertEqual(orphans, [])
        self.assertEqual([p[0] for p in pages], sorted(e[0] for e in entries))
        # Order must not depend on write order or filesystem listing order.
        self.assertEqual(pages, sorted(entries, key=lambda e: e[0]))

    def test_page_on_disk_with_no_declared_entry_is_reported_not_skipped(self):
        (self.out / "standup.html").write_text("<html></html>")
        B.write_page(self.out, "standup.html", "Standup digest", "desc")
        # A generator that forgot to call write_page().
        (self.out / "forgotten.html").write_text("<html></html>")

        pages, orphans = B.discover_pages(self.out)
        self.assertEqual(pages, [("standup.html", "Standup digest", "desc")])
        self.assertEqual(orphans, ["forgotten.html"])

    def test_index_html_itself_is_never_treated_as_an_orphan(self):
        (self.out / "index.html").write_text("<html></html>")
        pages, orphans = B.discover_pages(self.out)
        self.assertEqual(pages, [])
        self.assertEqual(orphans, [])


class TestAgainstThisRepo(unittest.TestCase):
    """The generator must work on the real requirement index, not just fixtures."""

    def test_real_index_parses_and_every_req_appears(self):
        text = (REPO_ROOT / "requirements" / "index.md").read_text()
        reqs = B.parse_requirements(text)
        self.assertGreaterEqual(len(reqs), 14)
        ids = [r[0] for r in reqs]
        self.assertEqual(ids, sorted(ids), "REQ ids should be in order in the index")
        rows = B.build_matrix(reqs, [], {})
        self.assertEqual(len(rows), len(reqs),
                         "every requirement in the index must appear in the matrix")

    def test_real_history_produces_valid_json(self):
        commits = B.collect_commits("HEAD")
        rows = B.build_matrix(B.parse_requirements(
            (REPO_ROOT / "requirements" / "index.md").read_text()), commits, {})
        payload = json.dumps({"rows": [B.asdict(r) for r in rows]})
        self.assertGreater(len(payload), 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
