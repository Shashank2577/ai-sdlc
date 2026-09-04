#!/usr/bin/env python3
"""Tests for the client portal generator.

The property this page exists to hold: a paying, non-engineer reader must
never be shown an optimistic guess dressed up as a fact. Every test here is
either a way that could leak (a label name, a branch name, a bare REQ id,
a state this cannot confirm rendered as accepted) or one of the four
scenarios the work item names explicitly: nothing delivered, an item
awaiting sign-off, an open change request, and an item whose sign-off
state cannot be determined.

    python3 portal/test_build.py
"""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

spec = importlib.util.spec_from_file_location("portal_build_under_test", HERE / "build.py")
P = importlib.util.module_from_spec(spec)
sys.modules["portal_build_under_test"] = P
spec.loader.exec_module(P)


def commit(sha: str, work_item: str) -> P.B.Commit:
    return P.B.Commit(sha=sha, subject="s", date="2026-09-01",
                       trailers={"Work-Item": work_item})


class TestPlainLanguage(unittest.TestCase):
    def test_ticket_prefix_is_stripped(self):
        self.assertEqual(P.plain_title("P2-5: Client portal"), "Client portal")

    def test_bug_prefix_is_stripped(self):
        self.assertEqual(P.plain_title("BUG: DoD reports trailers missing"),
                         "DoD reports trailers missing")

    def test_a_title_with_no_prefix_is_unchanged(self):
        self.assertEqual(P.plain_title("Nothing to strip here"), "Nothing to strip here")

    def test_a_label_name_mentioned_inline_is_redacted(self):
        # A real issue title in this repo: "the QA role cannot be
        # dispatched — the guard requires status:ready" — a label name
        # used in prose, not applied as metadata.
        out = P.plain_title("the guard requires status:ready")
        self.assertNotIn("status:ready", out)

    def test_a_req_id_mentioned_inline_is_redacted_not_just_the_prefix(self):
        # A real issue title in this repo: "...give ceremonies an owner,
        # settle REQ-002" — the bare id is in the middle, not a prefix.
        out = P.plain_title("Raise WIP, give ceremonies an owner, settle REQ-002")
        self.assertNotIn("REQ-002", out)
        self.assertIn("a requirement", out)

    def test_every_evidence_line_in_the_real_policy_has_a_plain_translation(self):
        # A drift regression: if policies/signoff.yaml's story evidence
        # changes wording, this must fail loudly rather than start
        # showing "an internal check" on a real client's page.
        import yaml
        policy = yaml.safe_load(P.SC.SIGNOFF_POLICY.read_text())
        for raw in policy["signoffs"]["story"]["evidence_required"]:
            with self.subTest(raw=raw):
                self.assertNotEqual(P.plain_evidence(raw), "an internal check")

    def test_an_evidence_line_the_policy_does_not_say_falls_back_generically(self):
        self.assertEqual(P.plain_evidence("something nobody wrote yet"), "an internal check")


class TestParseWorkItem(unittest.TestCase):
    def test_extracts_the_issue_number_regardless_of_repo(self):
        self.assertEqual(P.parse_work_item_issue("Shashank2577/foundry-program#42"), 42)

    def test_a_malformed_trailer_is_none_not_a_crash(self):
        self.assertIsNone(P.parse_work_item_issue(""))
        self.assertIsNone(P.parse_work_item_issue("not a trailer"))


class TestDeliveredIssueNumbers(unittest.TestCase):
    def test_a_work_item_trailer_alone_proves_nothing(self):
        # Scenario: nothing delivered. A commit names a Work-Item but no
        # merged PR carried it — the honesty rule this whole page exists
        # for: a trailer trace is not delivered work.
        commits = [commit("abc123", "org/repo#7")]
        delivered = P.delivered_issue_numbers(commits, {})
        self.assertEqual(delivered, {})

    def test_a_merged_pr_behind_the_trailer_counts_as_delivered(self):
        commits = [commit("abc123", "org/repo#7")]
        pulls = {"abc123": [{"number": 99, "url": "https://x/99"}]}
        delivered = P.delivered_issue_numbers(commits, pulls)
        self.assertEqual(delivered, {7: {"pr_number": 99, "pr_url": "https://x/99"}})


class TestSignoffDisplay(unittest.TestCase):
    POLICY = {"signoffs": {"story": {
        "evidence_required": ["the linked work item is closed"],
    }}}

    def test_signed_reads_as_accepted(self):
        text, _ = P.signoff_display(P.SC.STATE_SIGNED, self.POLICY)
        self.assertIn("signed off", text)

    def test_unsigned_reads_as_awaiting_action_not_rejection(self):
        text, _ = P.signoff_display(P.SC.STATE_UNSIGNED, self.POLICY)
        self.assertEqual(text, "awaiting your sign-off")

    def test_change_requested_says_reopened(self):
        text, _ = P.signoff_display(P.SC.STATE_CHANGE_REQUESTED, self.POLICY)
        self.assertIn("change request", text)

    def test_undetermined_never_implies_acceptance(self):
        # Scenario: an item whose sign-off state cannot be determined —
        # signoff:approved is present but no labeling event names who
        # applied it. The only honest thing to say is "not yet reviewed".
        text, _ = P.signoff_display(P.SC.STATE_UNDETERMINED, self.POLICY)
        self.assertEqual(text, "not yet reviewed")

    def test_evidence_is_read_from_the_policy_not_hardcoded(self):
        _, evidence = P.signoff_display(P.SC.STATE_UNSIGNED, self.POLICY)
        self.assertEqual(evidence, ["the task tracking it is finished"])


class TestBuildDelivered(unittest.TestCase):
    def _issue(self, number, title, body, labels):
        return {"number": number, "title": title, "body": body,
                "labels": [{"name": l} for l in labels]}

    def test_an_item_awaiting_sign_off(self):
        issues = {5: self._issue(5, "P2-1: Ship the thing",
                                  "→ **REQ-008**", [])}
        delivered_map = {5: {"pr_number": 12, "pr_url": "https://x/12"}}
        coverage = {"REQ-008": {"summary": "Client layer", "pct": 50, "passed": 1, "total": 2}}
        policy = {"signoffs": {"story": {"evidence_required": ["the linked work item is closed"]}}}

        def no_events(_issue_no):
            return []  # no signoff:approved label -> unsigned

        out = P.build_delivered(issues, delivered_map, coverage, policy, no_events)
        self.assertEqual(len(out), 1)
        item = out[0]
        self.assertEqual(item.title, "Ship the thing")
        self.assertTrue(item.needs_signoff)
        self.assertEqual(item.signoff_text, "awaiting your sign-off")
        self.assertEqual(item.requirement_label, "Client layer")
        # Never a bare REQ id in anything reader-facing.
        self.assertNotIn("REQ-008", item.title)

    def test_an_item_whose_sign_off_state_cannot_be_determined(self):
        issues = {6: self._issue(6, "Some story", "→ **REQ-008**",
                                  ["signoff:approved"])}
        delivered_map = {6: {"pr_number": 13, "pr_url": "https://x/13"}}
        policy = {"signoffs": {"story": {"evidence_required": []}}}

        def events_with_no_actor(_issue_no):
            return []  # label present, but no labeled event names who applied it

        out = P.build_delivered(issues, delivered_map, {}, policy, events_with_no_actor)
        self.assertEqual(out[0].signoff_text, "not yet reviewed")
        self.assertTrue(out[0].needs_signoff)

    def test_a_signed_item_does_not_need_signoff(self):
        issues = {7: self._issue(7, "Signed story", "→ **REQ-008**",
                                  ["signoff:approved"])}
        delivered_map = {7: {"pr_number": 14, "pr_url": "https://x/14"}}
        policy = {"signoffs": {"story": {"evidence_required": []}}}

        def events_with_human_actor(_issue_no):
            return [{"label": "signoff:approved", "actor": "a-human", "created_at": "2026-01-01T00:00:00Z"}]

        out = P.build_delivered(issues, delivered_map, {}, policy, events_with_human_actor)
        self.assertFalse(out[0].needs_signoff)
        self.assertIn("signed off", out[0].signoff_text)

    def test_nothing_delivered_yields_an_empty_list(self):
        out = P.build_delivered({}, {}, {}, {"signoffs": {"story": {}}}, lambda n: [])
        self.assertEqual(out, [])


class TestChangeRequests(unittest.TestCase):
    def test_an_open_change_request_is_included(self):
        issues = [{"number": 20, "state": "OPEN", "title": "Change the thing",
                  "labels": [{"name": "type:change-request"}]}]
        out = P.build_change_requests(issues)
        self.assertEqual([c.issue for c in out], [20])

    def test_a_closed_change_request_is_not_open(self):
        issues = [{"number": 21, "state": "CLOSED", "title": "Old CR",
                  "labels": [{"name": "type:change-request"}]}]
        self.assertEqual(P.build_change_requests(issues), [])

    def test_an_issue_without_the_label_is_not_a_change_request(self):
        issues = [{"number": 22, "state": "OPEN", "title": "Just a story", "labels": []}]
        self.assertEqual(P.build_change_requests(issues), [])


class TestInProgress(unittest.TestCase):
    def test_a_status_label_translates_to_plain_language(self):
        issues = [{"number": 30, "state": "OPEN", "title": "Working on it",
                  "labels": [{"name": "status:in-progress"}]}]
        out = P.build_in_progress(issues, exclude=set())
        self.assertEqual(out[0].plain_status, "being worked on right now")
        # No engineering label name in the plain phrase.
        self.assertNotIn("status:", out[0].plain_status)

    def test_delivered_issues_are_excluded(self):
        issues = [{"number": 31, "state": "OPEN", "title": "Already delivered",
                  "labels": [{"name": "status:in-progress"}]}]
        self.assertEqual(P.build_in_progress(issues, exclude={31}), [])

    def test_change_requests_are_excluded_from_in_progress(self):
        issues = [{"number": 32, "state": "OPEN", "title": "A CR",
                  "labels": [{"name": "type:change-request"}]}]
        self.assertEqual(P.build_in_progress(issues, exclude=set()), [])

    def test_closed_issues_are_not_in_progress(self):
        issues = [{"number": 33, "state": "CLOSED", "title": "Done",
                  "labels": [{"name": "status:in-progress"}]}]
        self.assertEqual(P.build_in_progress(issues, exclude=set()), [])


class TestRenderHonesty(unittest.TestCase):
    def _meta(self):
        return {"repo": "a/b", "repo_url": "https://github.com/a/b",
                "generated_at": "2026-09-04 00:00 UTC"}

    def test_nothing_delivered_says_so_plainly(self):
        html = P.render_html([], [], [], {}, self._meta(), "")
        self.assertIn("Nothing has been delivered yet.", html)

    def test_no_label_names_reach_the_page(self):
        item = P.Delivered(issue=1, title="Thing", pr_number=1, pr_url="https://x/1",
                           requirements=["REQ-008"], requirement_label="Client layer",
                           signoff_text="awaiting your sign-off",
                           evidence=["it passed quality review"], needs_signoff=True)
        html = P.render_html([item], [], [], {}, self._meta(), "")
        for label in ("signoff:approved", "signoff:change-requested", "type:change-request",
                     "status:in-progress", "qa:approved"):
            self.assertNotIn(label, html)

    def test_no_bare_req_id_reaches_the_page(self):
        item = P.Delivered(issue=1, title="Thing", pr_number=1, pr_url="https://x/1",
                           requirements=["REQ-008"], requirement_label="Client layer",
                           signoff_text="signed off — you accepted this as delivered",
                           evidence=[], needs_signoff=False)
        html = P.render_html([item], [], [], {}, self._meta(), "")
        self.assertNotIn("REQ-008", html)

    def test_no_branch_name_reaches_the_page(self):
        item = P.Delivered(issue=1, title="Thing", pr_number=1, pr_url="https://x/1",
                           requirement_label="General delivery",
                           signoff_text="signed off — you accepted this as delivered")
        html = P.render_html([item], [], [], {}, self._meta(), "")
        self.assertNotIn("story/FDY-", html)

    def test_an_undetermined_item_never_renders_as_accepted(self):
        item = P.Delivered(issue=1, title="Thing", pr_number=1, pr_url="https://x/1",
                           requirement_label="General delivery",
                           signoff_text="not yet reviewed", needs_signoff=True)
        html = P.render_html([item], [], [], {}, self._meta(), "")
        self.assertIn("not yet reviewed", html)
        self.assertNotIn("accepted this as delivered", html)

    def test_an_open_change_request_appears_in_its_own_section(self):
        cr = P.ChangeRequest(issue=9, title="Change the scope")
        html = P.render_html([], [cr], [], {}, self._meta(), "")
        self.assertIn("Change the scope", html)
        self.assertNotIn("No open change requests", html)

    def test_the_page_states_a_source_and_date_for_its_figures(self):
        html = P.render_html([], [], [], {}, self._meta(), "")
        self.assertIn("requirements/coverage.yaml", html)
        self.assertIn("policies/signoff.yaml", html)
        self.assertIn("2026-09-04 00:00 UTC", html)

    def test_self_contained_and_escaped(self):
        item = P.Delivered(issue=1, title="<script>x</script>", pr_number=1,
                           pr_url="https://x/1", requirement_label="General delivery",
                           signoff_text="signed off — you accepted this as delivered")
        html = P.render_html([item], [], [], {}, self._meta(), "")
        self.assertNotIn("<script>x", html)
        self.assertNotIn("http://fonts", html)
        self.assertNotIn("cdn.", html)

    def test_a_note_is_shown_when_github_data_is_unavailable(self):
        html = P.render_html([], [], [], {}, self._meta(), "gh unavailable (--no-github)")
        self.assertIn("gh unavailable", html)


class TestAgainstThisRepo(unittest.TestCase):
    def test_the_policy_and_coverage_files_load_cleanly(self):
        policy = P.SC.load_policy(P.SC.SIGNOFF_POLICY)
        self.assertIn("signoffs", policy)
        cov = P.STATUS.load_coverage()
        self.assertIn("REQ-008", cov)


if __name__ == "__main__":
    unittest.main(verbosity=2)
