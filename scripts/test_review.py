#!/usr/bin/env python3
"""Tests for the sprint review ceremony generator.

`build_review` is pure — closed stories and PRs in, the review out — so
the window boundary, verdict mapping and the "nothing shipped is still a
signal" rule are all testable without a repository, the same style as
`scripts/test_retro.py`.

    python3 scripts/test_review.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("review", HERE / "review.py")
R = importlib.util.module_from_spec(spec)
sys.modules["review"] = R
spec.loader.exec_module(R)

NOW = datetime(2026, 9, 3, 9, 0, 0, tzinfo=timezone.utc)
START = NOW - timedelta(days=7)


def ago(hours: float) -> str:
    return (NOW - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def story(number, *labels, closed_hours=24, body=""):
    return {"number": number, "title": f"Story {number}",
            "url": f"https://x/{number}", "closedAt": ago(closed_hours),
            "labels": [{"name": lbl} for lbl in labels], "body": body}


def pr(number, branch, state="MERGED", merged=True):
    return {"number": number, "url": f"https://x/pr/{number}", "headRefName": branch,
            "state": state, "mergedAt": ago(20) if merged else None,
            "closedAt": ago(20)}


class TestVerdict(unittest.TestCase):
    def test_rejected_outranks_approved(self):
        self.assertEqual(R.verdict(story(1, "qa:approved", "qa:rejected")), R.REJECTED)

    def test_approved_alone(self):
        self.assertEqual(R.verdict(story(1, "qa:approved")), R.APPROVED)

    def test_no_label_is_pending(self):
        self.assertEqual(R.verdict(story(1)), R.PENDING)


class TestFindPrForIssue(unittest.TestCase):
    def test_matches_story_branch_convention(self):
        prs = [pr(5, "story/FDY-7-slug")]
        found = R.find_pr_for_issue(prs, 7)
        self.assertEqual(found["number"], 5)

    def test_no_match_returns_none(self):
        self.assertIsNone(R.find_pr_for_issue([pr(5, "story/FDY-7-slug")], 8))

    def test_does_not_confuse_issue_7_with_issue_70(self):
        prs = [pr(5, "story/FDY-70-slug")]
        self.assertIsNone(R.find_pr_for_issue(prs, 7))


class TestAcceptanceCriteria(unittest.TestCase):
    def test_extracts_gherkin_lines_only(self):
        body = "Some prose.\nGiven a thing\nWhen it happens\nThen it works\nMore prose."
        ac = R.acceptance_criteria(body)
        self.assertEqual(ac, ["Given a thing", "When it happens", "Then it works"])

    def test_empty_body_returns_empty_list(self):
        self.assertEqual(R.acceptance_criteria(None), [])
        self.assertEqual(R.acceptance_criteria(""), [])


class TestBuildReview(unittest.TestCase):
    def test_empty_window_is_a_real_result_not_skipped(self):
        review = R.build_review(START, NOW, [], [])
        self.assertEqual(review["items"], [])
        self.assertEqual(review["totals"]["shipped"], 0)

    def test_only_includes_stories_closed_in_window(self):
        stories = [story(1, "qa:approved", closed_hours=24),
                   story(2, "qa:approved", closed_hours=24 * 30)]  # outside window
        review = R.build_review(START, NOW, stories, [])
        self.assertEqual([i["number"] for i in review["items"]], [1])

    def test_pending_verdicts_are_flagged_separately(self):
        stories = [story(1, "qa:approved"), story(2)]  # no verdict label
        review = R.build_review(START, NOW, stories, [])
        self.assertEqual([i["number"] for i in review["no_verdict"]], [2])
        self.assertEqual(review["totals"]["pending"], 1)

    def test_totals_split_approved_and_rejected(self):
        stories = [story(1, "qa:approved"), story(2, "qa:rejected"), story(3, "qa:approved")]
        review = R.build_review(START, NOW, stories, [])
        t = review["totals"]
        self.assertEqual((t["shipped"], t["approved"], t["rejected"]), (3, 2, 1))

    def test_pr_is_attached_when_the_branch_matches(self):
        stories = [story(1, "qa:approved")]
        prs = [pr(9, "story/FDY-1-slug")]
        review = R.build_review(START, NOW, stories, prs)
        self.assertEqual(review["items"][0]["pr"]["number"], 9)

    def test_missing_pr_is_none_not_an_error(self):
        review = R.build_review(START, NOW, [story(1, "qa:approved")], [])
        self.assertIsNone(review["items"][0]["pr"])


class TestRenderIssueBody(unittest.TestCase):
    def test_empty_window_says_nothing_shipped(self):
        review = R.build_review(START, NOW, [], [])
        body = R.render_issue_body(review, {"role": "techwriter", "run_url": "n/a"})
        self.assertIn("Nothing closed in this window", body)

    def test_pending_verdict_note_appears_only_when_present(self):
        review = R.build_review(START, NOW, [story(1, "qa:approved")], [])
        body = R.render_issue_body(review, {"role": "techwriter", "run_url": "n/a"})
        self.assertNotIn("REQ-009", body)

        review2 = R.build_review(START, NOW, [story(2)], [])
        body2 = R.render_issue_body(review2, {"role": "techwriter", "run_url": "n/a"})
        self.assertIn("REQ-009", body2)


class TestLoadCeremonyRole(unittest.TestCase):
    def test_reads_the_real_declaration_file(self):
        role = R.load_ceremony_role()
        self.assertEqual(role, "techwriter")


if __name__ == "__main__":
    unittest.main()
