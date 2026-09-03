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


class TestScopedToWriteCapability(unittest.TestCase):
    """`guards_paths` rules fire only for a role that could make the change.

    Word boundaries fixed matching precision but not scope: the gate had
    drifted back to holding 41 of 53 issues, because in a
    workflow-and-policy repo half the stories name a governance path
    without proposing to touch it.
    """

    def test_a_developer_naming_a_workflow_is_not_held(self):
        # The developer pack denies `.github/**` and its token lacks
        # `workflow` scope — proved live when a push was rejected. Holding
        # it is a gate on something that cannot happen.
        body = "Wire the new suite into `.github/workflows/dod-check.yml`."
        self.assertNotIn("touches_governance", rules(body=body,
                                                     labels=["role:developer"]))

    def test_a_devops_story_naming_a_workflow_is_held(self):
        body = "Wire the new suite into `.github/workflows/dod-check.yml`."
        self.assertIn("touches_governance", rules(body=body, labels=["role:devops"]))

    def test_the_governance_owner_naming_policies_is_held(self):
        self.assertIn("touches_governance",
                      rules(body="Update `policies/dod.yaml`.",
                            labels=["role:delivery-lead"]))

    def test_a_developer_citing_coverage_yaml_is_not_held(self):
        # Every story that adds a capability updates coverage.yaml — that
        # is how satisfaction is computed. As a critical signal it is
        # universal, and universal is the same as absent.
        body = "Add the check to `requirements/coverage.yaml` once it passes."
        self.assertEqual(rules(body=body, labels=["role:developer"]), [])

    def test_a_product_manager_citing_coverage_yaml_is_held(self):
        # PM owns `requirements/**`, so for that role it is a real proposal.
        self.assertIn("changes_requirements",
                      rules(body="Add a check to `requirements/coverage.yaml`.",
                            labels=["role:product-manager"]))

    def test_an_unlabelled_story_is_still_held(self):
        # No role label means the story is unrefined — the moment least is
        # known about it. Scoping must not become a way past the gate.
        self.assertIn("touches_governance", rules(body="Update `policies/dod.yaml`."))

    def test_an_unrecognised_role_is_still_held(self):
        self.assertIn("touches_governance",
                      rules(body="Update `policies/dod.yaml`.",
                            labels=["role:nonexistent"]))

    def test_two_role_labels_are_still_held(self):
        # Ambiguous ownership resolves toward the gate, not past it.
        self.assertIn("touches_governance",
                      rules(body="Update `policies/dod.yaml`.",
                            labels=["role:developer", "role:devops"]))

    def test_unscoped_rules_are_unaffected_by_role(self):
        # credentials, production and estimate carry no guards_paths: a
        # story can describe any of them regardless of what it may write.
        self.assertIn("touches_credentials",
                      rules(body="mint a PAT", labels=["role:developer"]))
        self.assertIn("production_or_release",
                      rules(body="deploy to staging", labels=["role:qa"]))
        self.assertIn("large_estimate",
                      rules(body="Estimate: L", labels=["role:techwriter"]))

    def test_deny_beats_allow(self):
        self.assertFalse(G.role_can_write("developer", [".github/workflows/**"]))
        self.assertTrue(G.role_can_write("devops", [".github/workflows/**"]))

    def test_capability_is_true_when_it_cannot_be_established(self):
        for role in (None, "", "not-a-role"):
            with self.subTest(role=role):
                self.assertTrue(G.role_can_write(role, ["policies/**"]))

    def test_a_pattern_and_a_guarded_path_overlap_in_both_directions(self):
        self.assertTrue(G._covers("role-packs/**", "role-packs/delivery-lead/**"))
        self.assertTrue(G._covers("policies/**", "policies/gates.yaml"))
        self.assertTrue(G._covers("**", "anything/at/all"))
        self.assertFalse(G._covers("src/**", "policies/**"))
        self.assertFalse(G._covers("role-packs/devops/**", "role-packs/qa/**"))

    def test_every_guarded_path_names_a_real_scope_pattern(self):
        # A typo in guards_paths silently disables the rule for every role,
        # which is the quietest way this could fail.
        import yaml
        declared = set()
        for pack in (REPO_ROOT / "role-packs").iterdir():
            f = pack / "policy.yaml"
            if not f.is_file():
                continue
            scope = (yaml.safe_load(f.read_text()) or {}).get("write_scope", {})
            declared |= set(scope.get("allow") or []) | set(scope.get("deny") or [])
        guarded = [g for r in GATE["critical_when"] for g in (r.get("guards_paths") or [])]
        self.assertTrue(guarded, "scoping is declared; some rule must use it")
        for g in guarded:
            with self.subTest(path=g):
                self.assertTrue(any(G._covers(d, g) for d in declared),
                                f"no pack's write_scope mentions anything under "
                                f"`{g}` — likely a typo, which would disable the "
                                f"rule for every role")


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

    # The governance owner. Exactly one role may write `policies/**`,
    # because gates with no agent owner cannot be changed through the loop
    # at all. That exception is only safe under the two conditions below,
    # so they are asserted rather than described in a charter.
    GOVERNANCE_OWNER = "delivery-lead"

    def _packs(self):
        import yaml
        packs = sorted(p for p in (REPO_ROOT / "role-packs").iterdir()
                       if (p / "policy.yaml").is_file())
        self.assertTrue(packs)
        return [(p, yaml.safe_load((p / "policy.yaml").read_text()) or {})
                for p in packs]

    def test_only_the_governance_owner_may_write_the_gate_policy(self):
        for pack, policy in self._packs():
            scope = policy.get("write_scope", {})
            with self.subTest(role=pack.name):
                if pack.name == self.GOVERNANCE_OWNER:
                    self.assertIn("policies/**", scope.get("allow") or [],
                                  "the governance owner must own the gates, or "
                                  "no role can change them through the loop")
                else:
                    self.assertIn("policies/**", scope.get("deny") or [],
                                  f"{pack.name} must not be able to move its "
                                  "own gates")

    def test_the_governance_owner_is_gated_critical_by_its_label_alone(self):
        # Condition one. Owning `policies/**` is only safe while every one
        # of its stories is approved by a person first — and that must not
        # depend on the prose rules, which a story can simply not trip.
        self.assertIn("governance_role",
                      rules(body="tidy a comment",
                            labels=[f"role:{self.GOVERNANCE_OWNER}"]))

    def test_the_governance_owner_cannot_merge(self):
        # Condition two. A governance change reviewed by nobody is the
        # worst use of the role. `shell.allow` is an allowlist, so absence
        # is the enforcement.
        import yaml
        tools = yaml.safe_load(
            (REPO_ROOT / "role-packs" / self.GOVERNANCE_OWNER / "tools.yaml").read_text())
        allowed = " ".join((tools.get("shell") or {}).get("allow") or [])
        self.assertNotIn("gh pr merge", allowed)
        self.assertNotIn("gh pr review", allowed)

    def test_no_pack_may_write_another_packs_directory(self):
        # `role-packs/**` on the governance owner made two of its own
        # `forbidden` entries prose instead of scope: it could rewrite any
        # role's budget, tool denials and write_scope, including its own.
        for pack, policy in self._packs():
            scope = policy.get("write_scope", {})
            with self.subTest(role=pack.name):
                for pattern in scope.get("allow") or []:
                    if not pattern.startswith("role-packs/"):
                        continue
                    self.assertTrue(
                        pattern.startswith(f"role-packs/{pack.name}/"),
                        f"{pack.name} allows `{pattern}`, which reaches into "
                        "another role's pack — propose that as a pull request "
                        "instead")

    def test_a_pack_cannot_reach_its_own_gate_through_write_capability(self):
        # The same question asked through the code the gate uses, not the
        # YAML — these must agree, or the gate and the policy disagree
        # about who is dangerous.
        for role in ("developer", "qa", "architect", "techwriter",
                     "product-manager", "devops", "orchestrator"):
            with self.subTest(role=role):
                self.assertFalse(G.role_can_write(role, ["policies/**"]))
        self.assertTrue(G.role_can_write(self.GOVERNANCE_OWNER, ["policies/**"]))


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
