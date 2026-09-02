#!/usr/bin/env python3
"""Tests for the dispatch-approval gate.

Two failure modes matter, and they pull in opposite directions. A gate
that catches everything is the gate nobody reads. A gate that misses the
governance cases is not a gate. Most tests here pin one side or the other.

    python3 scripts/test_gate_check.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
spec = importlib.util.spec_from_file_location("gate_check", HERE / "gate-check.py")
G = importlib.util.module_from_spec(spec)
sys.modules["gate_check"] = G
spec.loader.exec_module(G)

GATE = G.load_gate()


def classify(title="a story", body="", labels=()):
    return G.matched_rules(title, body, list(labels), GATE)


def rules(*args, **kw):
    return sorted(m["rule"] for m in classify(*args, **kw))


class TestNotTooBroad(unittest.TestCase):
    """The first version of this policy classified the entire backlog
    critical, because it matched substrings and `PAT` appears inside
    "dispatch"."""

    def test_dispatch_does_not_match_PAT(self):
        self.assertEqual(rules(body="The dispatcher dispatches a session."), [])

    def test_patch_and_path_do_not_match_PAT(self):
        self.assertEqual(rules(body="Apply the patch at that path."), [])

    def test_citing_a_REQ_is_not_critical(self):
        # Every story in this repo cites a REQ. If that were the signal,
        # nothing would ever be routine.
        self.assertEqual(rules(body="→ **REQ-002, REQ-011**"), [])

    def test_an_ordinary_story_is_routine(self):
        body = ("**As a** user **I want** the digest sorted by date **so that** "
                "the newest entry is first. → **REQ-011**\n\n"
                "Extend `dashboards/standup.py` and its tests. Estimate: S")
        self.assertEqual(rules("P1-9: sort the digest", body), [])

    def test_the_word_reproduction_does_not_match_prod(self):
        self.assertEqual(rules(body="Add a reproduction case to the tests."), [])


class TestCatchesGovernance(unittest.TestCase):
    def test_devops_role_is_critical_by_label_alone(self):
        self.assertIn("pipeline_role", rules(body="tidy a comment",
                                             labels=["role:devops"]))

    def test_touching_workflows_is_critical(self):
        self.assertIn("touches_governance",
                      rules(body="Edit `.github/workflows/dod-check.yml`."))

    def test_touching_policies_is_critical(self):
        self.assertIn("touches_governance", rules(body="Update `policies/dod.yaml`."))

    def test_branch_protection_is_critical(self):
        self.assertIn("touches_governance",
                      rules(body="Add a required check to branch protection."))

    def test_credentials_are_critical(self):
        for phrase in ("gh secret set X", "mint a PAT", "a new token_secret",
                       "FOUNDRY_DEV_TOKEN"):
            with self.subTest(phrase=phrase):
                self.assertIn("touches_credentials", rules(body=phrase))

    def test_production_is_critical(self):
        for phrase in ("deploy to staging", "the production ladder",
                       "a rollback plan", "sign a release tag"):
            with self.subTest(phrase=phrase):
                self.assertIn("production_or_release", rules(body=phrase))

    def test_a_large_estimate_is_critical(self):
        self.assertIn("large_estimate", rules(body="Estimate: L"))
        self.assertEqual(rules(body="Estimate: S"), [])

    def test_every_matching_rule_is_reported_not_just_the_first(self):
        # The comment should tell a human every reason it was held.
        matched = classify(body="Change `policies/gates.yaml` and mint a PAT.",
                           labels=["role:devops"])
        self.assertEqual(len(matched), 3)
        self.assertTrue(all(m["because"] for m in matched),
                        "every rule states why, or the comment cannot explain itself")


class TestWhoApproves(unittest.TestCase):
    def test_a_bot_cannot_approve(self):
        for actor in ("github-actions[bot]", "github-actions", "foundry-dev-bot[bot]",
                      "dependabot[bot]", "Copilot"):
            with self.subTest(actor=actor):
                self.assertFalse(G.is_human(actor))

    def test_a_person_can(self):
        self.assertTrue(G.is_human("Shashank2577"))

    def test_an_empty_actor_is_not_a_person(self):
        # Erring toward "approved" on missing data would defeat the gate.
        self.assertFalse(G.is_human(""))
        self.assertFalse(G.is_human("   "))


class TestPolicyShape(unittest.TestCase):
    def test_every_rule_has_a_name_and_a_reason(self):
        for rule in GATE["critical_when"]:
            with self.subTest(rule=rule.get("rule")):
                self.assertTrue(rule.get("rule"))
                self.assertTrue(rule.get("because"),
                               "a rule that cannot say why it fired is not reviewable")
                self.assertTrue(rule.get("match"))

    def test_the_gate_has_an_owner_and_a_default(self):
        # PRD §7: few gates, each with an SLA and a default, so a silent
        # gate cannot stall work forever without anyone deciding anything.
        self.assertEqual(GATE["owner"], "human")
        self.assertTrue(GATE["default_if_unanswered"])
        self.assertIsInstance(GATE["sla_hours"], int)

    def test_the_policy_admits_its_own_limits(self):
        self.assertIn("best-effort", GATE["limits"])

    def test_no_role_pack_may_write_the_gate_policy(self):
        import yaml
        packs = sorted(p for p in (REPO_ROOT / "role-packs").iterdir()
                       if (p / "policy.yaml").is_file())
        self.assertTrue(packs)
        for pack in packs:
            with self.subTest(role=pack.name):
                scope = (yaml.safe_load((pack / "policy.yaml").read_text())
                         or {}).get("write_scope", {})
                self.assertIn("policies/**", scope.get("deny") or [],
                              f"{pack.name} must not be able to move its own gates")


class TestHeldComment(unittest.TestCase):
    def test_it_says_how_to_approve_and_what_happens_otherwise(self):
        matched = classify(body="Update `policies/gates.yaml`.")
        note = G.render_held(42, matched, GATE)
        self.assertIn("apply `status:ready` yourself", note)
        self.assertIn("If you do nothing", note)
        self.assertIn("touches_governance", note)
        self.assertIn("best-effort", note)


if __name__ == "__main__":
    unittest.main(verbosity=2)
