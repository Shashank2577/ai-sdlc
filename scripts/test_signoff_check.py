#!/usr/bin/env python3
"""Tests for the sign-off validator and classifier.

Fixtures only — an in-line policy dict, and in-line label/event lists —
never a live issue or the real `policies/signoff.yaml`, so this suite
runs offline. `is_human()` is exercised as imported from `gate-check.py`,
not reimplemented, so a future change to what counts as a bot is caught
here too.

    python3 scripts/test_signoff_check.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

spec = importlib.util.spec_from_file_location("signoff_check", HERE / "signoff-check.py")
S = importlib.util.module_from_spec(spec)
sys.modules["signoff_check"] = S
spec.loader.exec_module(S)


def make_scope(**overrides) -> dict:
    scope = {
        "question": "Does the client accept this?",
        "owner": "client",
        "granted_by": "a person applying `signoff:approved`",
        "evidence_required": ["qa:approved label present"],
        "default_if_unanswered": "remains unsigned",
        "sla_hours": 72,
        "escalates_after_sla": True,
        "enforced_by": ["signoff_check"],
    }
    scope.update(overrides)
    return scope


def make_policy(**overrides) -> dict:
    policy = {
        "version": 0,
        "signoffs": {
            "story": make_scope(),
            "sprint": make_scope(sla_hours=120),
            "release": make_scope(sla_hours=48),
        },
        "change_request": {
            "question": "What happens when signed-off work needs to change?",
            "owner": "client + human account lead",
            "granted_by": "both the human account lead and the client approving",
            "requires": ["an impact analysis"],
            "default_if_unanswered": "the signed record stands",
            "sla_hours": 120,
            "escalates_after_sla": True,
            "enforced_by": ["signoff_check"],
        },
        "not_gated": ["engineering work continuing on a story pending sign-off"],
        "limits": "Classification reads labels, so it is best-effort by construction.",
    }
    policy.update(overrides)
    return policy


def event(label: str, actor: str, created_at: str = "2026-01-01T00:00:00Z") -> dict:
    return {"label": label, "actor": actor, "created_at": created_at}


class TestPolicyHappyPath(unittest.TestCase):
    def test_a_well_formed_policy_is_clean(self):
        self.assertEqual(S.validate_structure(make_policy()), [])

    def test_the_live_signoff_policy_is_clean(self):
        import yaml

        policy = yaml.safe_load((REPO_ROOT / "policies" / "signoff.yaml").read_text())
        self.assertEqual(S.validate_structure(policy), [])


class TestPolicyMissingFields(unittest.TestCase):
    def test_missing_owner_is_reported(self):
        policy = make_policy()
        del policy["signoffs"]["story"]["owner"]
        violations = S.validate_structure(policy)
        self.assertTrue(any("signoffs.story" in v and "owner" in v for v in violations))

    def test_missing_sla_hours_is_reported(self):
        policy = make_policy()
        del policy["signoffs"]["release"]["sla_hours"]
        violations = S.validate_structure(policy)
        self.assertTrue(any("signoffs.release" in v and "sla_hours" in v for v in violations))

    def test_empty_evidence_required_is_reported(self):
        policy = make_policy()
        policy["signoffs"]["sprint"]["evidence_required"] = []
        violations = S.validate_structure(policy)
        self.assertTrue(any("signoffs.sprint" in v and "evidence_required" in v for v in violations))

    def test_missing_not_gated_is_reported(self):
        policy = make_policy()
        del policy["not_gated"]
        violations = S.validate_structure(policy)
        self.assertTrue(any("not_gated" in v for v in violations))

    def test_change_request_missing_requires_is_reported(self):
        policy = make_policy()
        policy["change_request"]["requires"] = []
        violations = S.validate_structure(policy)
        self.assertTrue(any("change_request" in v and "requires" in v for v in violations))


class TestPolicyEnforcedBy(unittest.TestCase):
    def test_enforced_by_not_naming_signoff_check_is_reported(self):
        policy = make_policy()
        policy["signoffs"]["story"]["enforced_by"] = ["something_else"]
        violations = S.validate_structure(policy)
        self.assertTrue(any("signoffs.story" in v and "enforced_by" in v for v in violations))


class TestPolicyOwnerCannotBeAnAgentRole(unittest.TestCase):
    def test_owner_naming_an_agent_role_is_reported(self):
        policy = make_policy()
        policy["signoffs"]["story"]["owner"] = "role:developer"
        violations = S.validate_structure(policy)
        self.assertTrue(any("agent role" in v for v in violations))

    def test_owner_client_is_fine(self):
        policy = make_policy()
        self.assertEqual(S.validate_structure(policy), [])

    def test_change_request_owner_naming_both_humans_is_fine(self):
        policy = make_policy()
        self.assertEqual(
            [v for v in S.validate_structure(policy) if "change_request" in v], []
        )


class TestReportsEveryViolation(unittest.TestCase):
    def test_multiple_independent_problems_are_all_reported(self):
        policy = make_policy()
        del policy["signoffs"]["story"]["owner"]
        policy["signoffs"]["release"]["evidence_required"] = []
        del policy["not_gated"]
        violations = S.validate_structure(policy)
        self.assertGreaterEqual(len(violations), 3)


class TestClassifyHappyPath(unittest.TestCase):
    def test_approved_by_a_person_is_signed(self):
        state, detail = S.classify(
            ["signoff:approved"], [event("signoff:approved", "a-human")]
        )
        self.assertEqual(state, S.STATE_SIGNED)
        self.assertIn("a-human", detail)

    def test_no_relevant_label_is_unsigned(self):
        state, _ = S.classify(["status:in-review"], [])
        self.assertEqual(state, S.STATE_UNSIGNED)

    def test_change_requested_label_wins(self):
        state, _ = S.classify(
            ["signoff:change-requested"],
            [event("signoff:approved", "a-human", "2026-01-01T00:00:00Z")],
        )
        self.assertEqual(state, S.STATE_CHANGE_REQUESTED)


class TestClassifyRejectsBotActors(unittest.TestCase):
    def test_signoff_applied_by_a_bot_suffix_is_unsigned_not_signed(self):
        state, detail = S.classify(
            ["signoff:approved"], [event("signoff:approved", "some-app[bot]")]
        )
        self.assertEqual(state, S.STATE_UNSIGNED)
        self.assertIn("bot actor", detail)

    def test_signoff_applied_by_github_actions_is_unsigned(self):
        state, _ = S.classify(
            ["signoff:approved"], [event("signoff:approved", "github-actions")]
        )
        self.assertEqual(state, S.STATE_UNSIGNED)

    def test_reuses_gate_check_is_human_rather_than_a_second_rule(self):
        # If gate-check.py's deny-list grows, signoff-check inherits it —
        # proven here by comparing bytecode against a fresh load of
        # gate-check.py, not a copy of its logic.
        gate_check = S._load_gate_check()
        self.assertEqual(S.is_human.__code__, gate_check.is_human.__code__)


class TestClassifyUndeterminedNeverReadsAsAccepted(unittest.TestCase):
    def test_label_present_with_no_matching_event_is_undetermined(self):
        state, detail = S.classify(["signoff:approved"], [])
        self.assertEqual(state, S.STATE_UNDETERMINED)
        self.assertNotEqual(state, S.STATE_SIGNED)

    def test_label_present_with_only_unrelated_events_is_undetermined(self):
        state, _ = S.classify(
            ["signoff:approved"], [event("status:ready", "a-human")]
        )
        self.assertEqual(state, S.STATE_UNDETERMINED)

    def test_most_recent_relabeling_actor_is_the_one_that_counts(self):
        # Applied by a bot, removed, then applied again by a person —
        # the most recent event should win, not the first.
        events = [
            event("signoff:approved", "some-app[bot]", "2026-01-01T00:00:00Z"),
            event("signoff:approved", "a-human", "2026-02-01T00:00:00Z"),
        ]
        state, detail = S.classify(["signoff:approved"], events)
        self.assertEqual(state, S.STATE_SIGNED)
        self.assertIn("a-human", detail)


class TestCLI(unittest.TestCase):
    def test_main_returns_zero_on_a_clean_policy(self):
        import tempfile

        import yaml

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "signoff.yaml"
            path.write_text(yaml.safe_dump(make_policy()))
            self.assertEqual(S.main(["--policy", str(path)]), 0)

    def test_main_returns_nonzero_on_a_policy_violation(self):
        import tempfile

        import yaml

        policy = make_policy()
        del policy["signoffs"]["story"]["owner"]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "signoff.yaml"
            path.write_text(yaml.safe_dump(policy))
            self.assertEqual(S.main(["--policy", str(path)]), 1)

    def test_classify_without_issue_or_scope_errors(self):
        with self.assertRaises(SystemExit):
            S.main(["--classify"])


if __name__ == "__main__":
    unittest.main()
