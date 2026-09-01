#!/usr/bin/env python3
"""Tests for the standup digest.

`build_digest` is pure — raw event data in, digest out — so the whole
computation is testable with fixtures at a fixed `now`. That matters more
here than elsewhere: every interesting case in this generator is a
time-window boundary, and a test that uses the real clock cannot pin one.

    python3 dashboards/test_standup.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

spec = importlib.util.spec_from_file_location("dash_standup", HERE / "standup.py")
S = importlib.util.module_from_spec(spec)
sys.modules["dash_standup"] = S
spec.loader.exec_module(S)

NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)


def ago(hours: float) -> str:
    return (NOW - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def commits(*specs):
    """specs: (sha, subject, role, harness, 'REQ-001, REQ-002')"""
    records = "\x01".join(
        f"{sha}\x00{subject}\x00{ago(1)}\x00"
        f"Requirement: {reqs}\nAgent-Role: {role}\nHarness: {harness}\n"
        for sha, subject, role, harness, reqs in specs
    ) + "\x01"
    return S.B.parse_commits(records)


def issue(number, *labels, state="OPEN", title="an item"):
    return {"number": number, "title": title, "state": state, "url": f"u/{number}",
            "labels": [{"name": n} for n in labels], "updatedAt": ago(1)}


def digest(**kw):
    base = dict(commits=[], pulls=[], runs=[], issues=[], blocked_since={},
                now=NOW, window_hours=24)
    base.update(kw)
    return S.build_digest(**base)


class TestPerRoleActivity(unittest.TestCase):
    def test_groups_by_agent_role_trailer(self):
        d = digest(commits=commits(
            ("a1", "feat: one", "developer", "claude-code/2.1", "REQ-002"),
            ("a2", "feat: two", "developer", "claude-code/2.1", "REQ-003"),
            ("a3", "test: three", "qa", "claude-code/2.1", "REQ-009"),
        ))
        self.assertEqual([r["role"] for r in d["roles"]], ["developer", "qa"])
        self.assertEqual(d["roles"][0]["commits"], 2)
        self.assertEqual(d["roles"][0]["requirements"], ["REQ-002", "REQ-003"])
        self.assertEqual(d["commits_total"], 3)

    def test_roles_are_ordered_by_volume(self):
        d = digest(commits=commits(
            ("a1", "s", "qa", "h", "REQ-009"),
            ("a2", "s", "developer", "h", "REQ-002"),
            ("a3", "s", "developer", "h", "REQ-002"),
        ))
        self.assertEqual([r["role"] for r in d["roles"]], ["developer", "qa"])

    def test_commit_without_a_role_trailer_lands_under_unknown(self):
        raw = "abc\x00no trailers\x00" + ago(1) + "\x00\x01"
        d = digest(commits=S.B.parse_commits(raw))
        self.assertEqual(d["roles"][0]["role"], "unknown")

    def test_harnesses_are_tracked_per_role(self):
        d = digest(commits=commits(
            ("a1", "s", "developer", "claude-code/2.1", "REQ-002"),
            ("a2", "s", "developer", "codex/1.0", "REQ-002"),
        ))
        self.assertEqual(d["roles"][0]["harnesses"], ["claude-code/2.1", "codex/1.0"])

    def test_no_activity_is_reported_as_no_activity(self):
        d = digest()
        self.assertEqual(d["roles"], [])
        self.assertEqual(d["commits_total"], 0)


class TestPullRequestWindow(unittest.TestCase):
    def setUp(self):
        self.pulls = [
            {"number": 1, "title": "in window, merged", "state": "MERGED",
             "createdAt": ago(30), "mergedAt": ago(2), "closedAt": ago(2),
             "url": "u1", "headRefName": "story/FDY-1-a"},
            {"number": 2, "title": "in window, opened", "state": "OPEN",
             "createdAt": ago(3), "mergedAt": None, "closedAt": None,
             "url": "u2", "headRefName": "story/FDY-2-b"},
            {"number": 3, "title": "closed unmerged", "state": "CLOSED",
             "createdAt": ago(40), "mergedAt": None, "closedAt": ago(5),
             "url": "u3", "headRefName": "story/FDY-3-c"},
            {"number": 4, "title": "outside the window", "state": "MERGED",
             "createdAt": ago(100), "mergedAt": ago(90), "closedAt": ago(90),
             "url": "u4", "headRefName": "story/FDY-4-d"},
        ]

    def test_transitions_are_bucketed_by_when_not_by_state(self):
        d = digest(pulls=self.pulls)
        self.assertEqual([p["number"] for p in d["pulls"]["merged"]], [1])
        self.assertEqual([p["number"] for p in d["pulls"]["opened"]], [2])
        self.assertEqual([p["number"] for p in d["pulls"]["closed_unmerged"]], [3])

    def test_a_merged_pr_is_not_also_counted_as_closed_unmerged(self):
        d = digest(pulls=self.pulls)
        self.assertNotIn(1, [p["number"] for p in d["pulls"]["closed_unmerged"]])

    def test_open_count_is_current_not_windowed(self):
        self.assertEqual(digest(pulls=self.pulls)["pulls"]["open_now"], 1)


class TestCheckFailures(unittest.TestCase):
    def test_only_failures_inside_the_window(self):
        runs = [
            {"name": "dod", "conclusion": "failure", "createdAt": ago(2),
             "headBranch": "story/x", "url": "r1"},
            {"name": "dod", "conclusion": "success", "createdAt": ago(2),
             "headBranch": "story/y", "url": "r2"},
            {"name": "dod", "conclusion": "failure", "createdAt": ago(48),
             "headBranch": "story/z", "url": "r3"},
        ]
        d = digest(runs=runs)
        self.assertEqual([f["url"] for f in d["check_failures"]], ["r1"])


class TestBoard(unittest.TestCase):
    def test_counts_open_issues_by_status_label(self):
        d = digest(issues=[
            issue(1, "status:ready"), issue(2, "status:ready"),
            issue(3, "status:in-review"),
            issue(4, "status:ready", state="CLOSED"),
            issue(5, "type:story"),
        ])
        self.assertEqual(d["board"]["status:ready"], 2)
        self.assertEqual(d["board"]["status:in-review"], 1)
        self.assertEqual(d["board"]["(no status)"], 1)

    def test_needs_human_items_are_surfaced(self):
        d = digest(issues=[issue(7, "needs-human", title="decide this"),
                           issue(8, "status:ready")])
        self.assertEqual([i["number"] for i in d["needs_human"]], [7])


class TestBlockedDetection(unittest.TestCase):
    """The >24h rule. Every case here is a boundary, which is why `now` is
    injected rather than read from the clock."""

    def test_blocked_beyond_the_window_is_flagged(self):
        d = digest(issues=[issue(9, "status:blocked")],
                   blocked_since={9: ago(30)})
        self.assertEqual(len(d["blocked_stale"]), 1)
        self.assertEqual(d["blocked_stale"][0]["number"], 9)
        self.assertAlmostEqual(d["blocked_stale"][0]["hours"], 30.0, places=1)

    def test_blocked_inside_the_window_is_not_flagged(self):
        d = digest(issues=[issue(9, "status:blocked")], blocked_since={9: ago(23)})
        self.assertEqual(d["blocked_stale"], [])

    def test_exactly_at_the_threshold_is_not_flagged(self):
        # "> 24h", not ">= 24h". A boundary either way; this one is stated.
        d = digest(issues=[issue(9, "status:blocked")], blocked_since={9: ago(24)})
        self.assertEqual(d["blocked_stale"], [])

    def test_an_item_already_flagged_is_reported_but_marked(self):
        d = digest(issues=[issue(9, "status:blocked", "needs-human")],
                   blocked_since={9: ago(48)})
        self.assertTrue(d["blocked_stale"][0]["already_flagged"])

    def test_ordered_worst_first(self):
        d = digest(issues=[issue(1, "status:blocked"), issue(2, "status:blocked")],
                   blocked_since={1: ago(30), 2: ago(90)})
        self.assertEqual([b["number"] for b in d["blocked_stale"]], [2, 1])

    def test_a_window_override_moves_the_threshold(self):
        d = digest(issues=[issue(9, "status:blocked")],
                   blocked_since={9: ago(30)}, window_hours=48)
        self.assertEqual(d["blocked_stale"], [])


class TestRender(unittest.TestCase):
    def test_renders_self_contained_html(self):
        d = digest(commits=commits(("a1", "feat: <b>x</b>", "developer", "h", "REQ-002")),
                   issues=[issue(9, "status:blocked")], blocked_since={9: ago(40)})
        html = S.render_digest_html(d, {"repo": "a/b", "generated_at": "now"})
        self.assertIn("&lt;b&gt;", html)
        self.assertNotIn("<b>x</b>", html)
        self.assertNotIn("http://", html.split("<style>")[1].split("</style>")[0])
        self.assertIn("blocked", html)

    def test_empty_digest_still_renders_a_page(self):
        html = S.render_digest_html(digest(), {"repo": "a/b"})
        self.assertIn("No commits in the window", html)
        self.assertIn("nothing blocked beyond 24h", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
