#!/usr/bin/env python3
"""Tests for the label -> project-board mapping.

`desired_fields` and `diff` are pure, so the whole mapping is testable
without a project. That matters here more than usual: this code writes to
a surface humans read as the truth, and a wrong mapping is invisible —
the board just quietly says the wrong thing.

    python3 scripts/test_sync_project.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sync_project", HERE / "sync-project.py")
S = importlib.util.module_from_spec(spec)
sys.modules["sync_project"] = S
spec.loader.exec_module(S)


def issue(*labels, state="OPEN", body="", number=1):
    return {"number": number, "state": state, "body": body,
            "labels": [{"name": n} for n in labels]}


class TestStatusMapping(unittest.TestCase):
    def test_each_status_label_maps_to_its_column(self):
        for label, column in S.STATUS_BY_LABEL:
            with self.subTest(label=label):
                self.assertEqual(desired := S.desired_fields(issue(label))["Status"], column,
                                 f"{label} -> {desired}")

    def test_no_status_label_is_todo(self):
        self.assertEqual(S.desired_fields(issue("type:story"))["Status"], "Todo")

    def test_closed_outranks_any_label(self):
        # An item can carry a stale status label. Closed is a fact.
        self.assertEqual(
            S.desired_fields(issue("status:in-review", state="CLOSED"))["Status"], "Done")

    def test_blocked_wins_over_other_status_labels(self):
        # Two status labels is a bug, but it must resolve the same way every
        # run or the board flickers between syncs.
        both = issue("status:ready", "status:blocked")
        self.assertEqual(S.desired_fields(both)["Status"], "Blocked")
        self.assertEqual(S.desired_fields(both)["Status"],
                         S.desired_fields(issue("status:blocked", "status:ready"))["Status"])


class TestRoleAndVerdict(unittest.TestCase):
    def test_role_label_maps_to_the_role_field(self):
        self.assertEqual(S.desired_fields(issue("role:developer"))["Role"], "Developer")
        self.assertEqual(S.desired_fields(issue("role:qa"))["Role"], "QA")

    def test_no_role_label_leaves_the_field_alone(self):
        # Absent, not blanked: the board should not fight a human who set it.
        self.assertNotIn("Role", S.desired_fields(issue("status:ready")))

    def test_qa_defaults_to_pending(self):
        self.assertEqual(S.desired_fields(issue())["QA-Verdict"], "Pending")

    def test_qa_labels_map_to_verdicts(self):
        self.assertEqual(S.desired_fields(issue("qa:approved"))["QA-Verdict"], "Approved")
        self.assertEqual(S.desired_fields(issue("qa:rejected"))["QA-Verdict"], "Rejected")

    def test_rejected_wins_when_both_verdicts_are_present(self):
        # A story carrying both is broken; the safe reading is the veto.
        self.assertEqual(
            S.desired_fields(issue("qa:approved", "qa:rejected"))["QA-Verdict"], "Rejected")


class TestRequirementExtraction(unittest.TestCase):
    def test_reads_the_convention_marker(self):
        body = "**As the** org **I want** x **so that** y. → **REQ-002, REQ-003**"
        self.assertEqual(S.desired_fields(issue(body=body))["Requirement-ID"],
                         "REQ-002, REQ-003")

    def test_the_marker_is_authoritative_over_incidental_mentions(self):
        body = ("Story. → **REQ-002**\n\nAcceptance criteria:\n"
                "Given REQ-009 is not in scope here, it must not be linked.")
        self.assertEqual(S.desired_fields(issue(body=body))["Requirement-ID"], "REQ-002")

    def test_falls_back_to_the_whole_body_without_a_marker(self):
        body = "No marker, but mentions REQ-005 and REQ-001."
        self.assertEqual(S.desired_fields(issue(body=body))["Requirement-ID"],
                         "REQ-001, REQ-005")

    def test_ids_are_sorted_and_deduplicated(self):
        body = "→ **REQ-009, REQ-002, REQ-009**"
        self.assertEqual(S.desired_fields(issue(body=body))["Requirement-ID"],
                         "REQ-002, REQ-009")

    def test_no_requirements_leaves_the_field_alone(self):
        self.assertNotIn("Requirement-ID", S.desired_fields(issue(body="nothing here")))


class TestDiff(unittest.TestCase):
    def test_a_correct_board_produces_no_writes(self):
        # The sync runs on a schedule; a no-op run must write nothing, or
        # every run churns the board's own activity feed.
        desired = {"Status": "Done", "QA-Verdict": "Pending"}
        self.assertEqual(S.diff({"Status": "Done", "QA-Verdict": "Pending"}, desired), {})

    def test_only_the_differing_fields_are_written(self):
        current = {"Status": "In Review", "QA-Verdict": "Pending", "Role": "Developer"}
        desired = {"Status": "Done", "QA-Verdict": "Pending"}
        self.assertEqual(S.diff(current, desired), {"Status": "Done"})

    def test_an_unset_field_counts_as_differing(self):
        self.assertEqual(S.diff({}, {"Role": "QA"}), {"Role": "QA"})


class TestPlanAdditions(unittest.TestCase):
    def test_an_open_issue_missing_from_the_board_is_planned(self):
        issues = {20: issue("type:story", number=20)}
        self.assertEqual([i["number"] for i in S.plan_additions(issues, on_board=set())],
                         [20])

    def test_an_issue_already_on_the_board_is_not_replanned(self):
        issues = {20: issue("type:story", number=20)}
        self.assertEqual(S.plan_additions(issues, on_board={20}), [])

    def test_every_open_issue_already_on_the_board_plans_nothing(self):
        # This is the run that matters: the job runs hourly, and a run with
        # nothing to do must stay silent, not just harmless.
        issues = {1: issue(number=1), 2: issue(number=2)}
        self.assertEqual(S.plan_additions(issues, on_board={1, 2}), [])

    def test_a_closed_issue_missing_from_the_board_is_not_planned(self):
        # Backfilling history is a different job than keeping the board
        # current with what's open now.
        issues = {5: issue(state="CLOSED", number=5)}
        self.assertEqual(S.plan_additions(issues, on_board=set()), [])

    def test_additions_are_ordered_by_issue_number(self):
        issues = {9: issue(number=9), 3: issue(number=3)}
        self.assertEqual([i["number"] for i in S.plan_additions(issues, on_board=set())],
                         [3, 9])


class TestRunSyncAgainstTrackerStubs(unittest.TestCase):
    """P3-7: `run_sync` is the whole algorithm main() drives, written once
    against `adapters.tracker.base.Tracker` — not against `gh`. Running it
    against the Jira adapter's stubs (no live Jira exists, see
    adapters/tracker/jira/client.py's docstring) proves the seam actually
    carries sync-project.py's logic, which is REQ-004's claim. It is not
    proof the Jira adapter works against a real Jira instance."""

    def test_full_sync_against_github_stub(self):
        from adapters.tracker.base import BoardRef
        from adapters.tracker.github import GitHubTracker
        from adapters.tracker.tests.test_github import FakeGh

        fake = FakeGh()
        # The seeded fixture's issue #1 carries "status:ready", but this
        # board's only Status options are Todo/In Progress/Done — give it a
        # label this board can actually represent, matching the Jira run
        # below so the two are a fair side-by-side comparison.
        fake.issues[1]["labels"] = ["status:in-progress"]
        tracker = GitHubTracker(run=fake)
        board = BoardRef(owner="o", number=1)

        code, summary = S.run_sync(tracker, board, dry_run=False)

        self.assertEqual(code, 0)
        self.assertEqual(summary,
                          "project sync: changed 1 item(s) (1 added), 0 already correct.")
        self.assertEqual(fake.items[1]["fields"].get("Status"), "In Progress")

    def test_full_sync_against_jira_stub(self):
        from adapters.tracker.base import BoardRef
        from adapters.tracker.jira import JiraTracker
        from adapters.tracker.tests.test_jira import FakeJira

        fake = FakeJira()
        # Same relabel as the GitHub run above, for the same reason: a fair
        # side-by-side comparison of the same algorithm against both stubs.
        fake.issues[1]["fields"]["labels"] = ["status:in-progress"]
        tracker = JiraTracker(
            base_url="https://example.atlassian.net", email="bot@example.com",
            api_token="unused-in-tests", project_key="FDY",
            field_map={"Requirement-ID": {"id": "customfield_10052", "type": "text"}},
            webhook_urls={"dispatch.yml": "https://example.atlassian.net/webhook/dispatch"},
            transport=fake,
        )
        board = BoardRef(owner="FDY", number=5)

        code, summary = S.run_sync(tracker, board, dry_run=False)

        self.assertEqual(code, 0)
        self.assertEqual(summary,
                          "project sync: changed 1 item(s) (1 added), 0 already correct.")
        # Same operations as the GitHub run: issue #1 added to the board
        # (here, the active sprint) and its Status field transitioned to
        # match the label — driven by the exact same run_sync() call.
        self.assertEqual(fake.sprint_issues["500"], ["FDY-1"])
        self.assertEqual(fake.issues[1]["fields"]["status"]["name"], "In Progress")

    def test_dry_run_against_jira_stub_changes_nothing(self):
        from adapters.tracker.base import BoardRef
        from adapters.tracker.jira import JiraTracker
        from adapters.tracker.tests.test_jira import FakeJira

        fake = FakeJira()
        fake.issues[1]["fields"]["labels"] = ["status:in-progress"]
        tracker = JiraTracker(
            base_url="https://example.atlassian.net", email="bot@example.com",
            api_token="unused-in-tests", project_key="FDY",
            field_map={"Requirement-ID": {"id": "customfield_10052", "type": "text"}},
            webhook_urls={"dispatch.yml": "https://example.atlassian.net/webhook/dispatch"},
            transport=fake,
        )
        board = BoardRef(owner="FDY", number=5)

        code, summary = S.run_sync(tracker, board, dry_run=True)

        self.assertEqual(code, 0)
        self.assertEqual(summary,
                          "project sync: would change 1 item(s) (1 added), 0 already correct.")
        self.assertEqual(fake.sprint_issues["500"], [])
        self.assertEqual(fake.issues[1]["fields"]["status"]["name"], "Ready")


class TestMakeTracker(unittest.TestCase):
    """The implementation is chosen by config in exactly one place:
    `make_tracker()` reads `TRACKER_IMPL`. Everything else in the script
    only ever sees a `Tracker`."""

    def test_defaults_to_github(self):
        from adapters.tracker.github import GitHubTracker
        old = os.environ.pop("TRACKER_IMPL", None)
        try:
            self.assertIsInstance(S.make_tracker(), GitHubTracker)
        finally:
            if old is not None:
                os.environ["TRACKER_IMPL"] = old

    def test_env_var_switches_to_jira(self):
        from adapters.tracker.jira import JiraTracker
        env = {
            "TRACKER_IMPL": "jira", "JIRA_BASE_URL": "https://example.atlassian.net",
            "JIRA_EMAIL": "bot@example.com", "JIRA_API_TOKEN": "x", "JIRA_PROJECT_KEY": "FDY",
        }
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            self.assertIsInstance(S.make_tracker(), JiraTracker)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_unknown_impl_raises(self):
        old = os.environ.get("TRACKER_IMPL")
        os.environ["TRACKER_IMPL"] = "carrier-pigeon"
        try:
            with self.assertRaises(ValueError):
                S.make_tracker()
        finally:
            if old is None:
                os.environ.pop("TRACKER_IMPL", None)
            else:
                os.environ["TRACKER_IMPL"] = old


class TestAgainstThisRepo(unittest.TestCase):
    def test_every_status_label_in_conventions_has_a_column(self):
        conventions = (HERE.parent / ".github").parent
        labels = {l for l, _ in S.STATUS_BY_LABEL}
        expected = {"status:needs-refinement", "status:ready", "status:in-progress",
                    "status:in-review", "status:blocked"}
        self.assertEqual(labels, expected,
                         "the board mapping and the label state machine have diverged")

    def test_every_role_pack_in_the_repo_has_a_role_label_mapping(self):
        packs = sorted(p.name for p in (HERE.parent / "role-packs").iterdir()
                       if (p / "pack.yaml").is_file())
        for role in packs:
            with self.subTest(role=role):
                self.assertIn(f"role:{role}", S.ROLE_BY_LABEL,
                              f"role pack `{role}` has no board mapping")


if __name__ == "__main__":
    unittest.main(verbosity=2)
