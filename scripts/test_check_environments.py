#!/usr/bin/env python3
"""Tests for the environment ladder validator.

Fixtures only — a policy dict built in-line, and a fake platform response
built in-line — never the live `policies/environments.yaml` or a real `gh
api` call, so this suite runs offline and cannot be broken by a future
edit to the real ladder (or a rate-limited API).

    python3 scripts/test_check_environments.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

spec = importlib.util.spec_from_file_location("check_environments", HERE / "check-environments.py")
C = importlib.util.module_from_spec(spec)
sys.modules["check_environments"] = C
spec.loader.exec_module(C)


def make_policy(**overrides) -> dict:
    """A clean four-rung ladder, the shape of the real policy."""
    policy = {
        "version": 0,
        "promotion_order": ["preview", "dev", "staging", "prod"],
        "environments": {
            "preview": {
                "promotes_from": None,
                "promotes_to": "dev",
                "human_reviewer_required": False,
                "rollback": {"owner": "role:devops"},
            },
            "dev": {
                "promotes_from": "preview",
                "promotes_to": "staging",
                "human_reviewer_required": False,
                "rollback": {"owner": "role:devops"},
            },
            "staging": {
                "promotes_from": "dev",
                "promotes_to": "prod",
                "human_reviewer_required": False,
                "rollback": {"owner": "role:devops"},
            },
            "prod": {
                "promotes_from": "staging",
                "promotes_to": None,
                "human_reviewer_required": True,
                "rollback": {"owner": "@Shashank2577 approves, role:devops executes"},
            },
        },
    }
    policy.update(overrides)
    return policy


def make_api(*, prod_has_reviewer: bool = True, names: tuple[str, ...] = ("preview", "dev", "staging", "prod")) -> dict:
    api = {}
    for name in names:
        env = {"name": name, "protection_rules": []}
        if name == "prod" and prod_has_reviewer:
            env["protection_rules"] = [
                {"type": "required_reviewers", "reviewers": [{"type": "User", "reviewer": {"login": "Shashank2577"}}]}
            ]
        api[name] = env
    return api


class TestHappyPath(unittest.TestCase):
    def test_a_well_formed_ladder_is_structurally_clean(self):
        self.assertEqual(C.validate_structure(make_policy()), [])

    def test_a_well_formed_ladder_matches_a_matching_platform(self):
        policy = make_policy()
        self.assertEqual(
            C.validate_platform(policy["environments"], make_api()), []
        )


class TestMissingRollbackOwner(unittest.TestCase):
    def test_missing_owner_is_reported(self):
        policy = make_policy()
        policy["environments"]["dev"]["rollback"] = {"owner": ""}
        violations = C.validate_structure(policy)
        self.assertTrue(any("dev" in v and "rollback.owner" in v for v in violations))

    def test_missing_rollback_block_entirely_is_reported(self):
        policy = make_policy()
        del policy["environments"]["dev"]["rollback"]
        violations = C.validate_structure(policy)
        self.assertTrue(any("dev" in v and "rollback.owner" in v for v in violations))


class TestPromotionOrderShape(unittest.TestCase):
    def test_duplicate_entry_is_reported(self):
        policy = make_policy(promotion_order=["preview", "dev", "dev", "staging", "prod"])
        violations = C.validate_structure(policy)
        self.assertTrue(any("duplicate" in v for v in violations))

    def test_missing_environment_from_order_is_reported(self):
        policy = make_policy(promotion_order=["preview", "dev", "staging"])
        violations = C.validate_structure(policy)
        self.assertTrue(any("missing environment" in v and "prod" in v for v in violations))

    def test_unknown_environment_in_order_is_reported(self):
        policy = make_policy(promotion_order=["preview", "dev", "staging", "prod", "canary"])
        violations = C.validate_structure(policy)
        self.assertTrue(any("not declared" in v and "canary" in v for v in violations))


class TestNotATotalOrder(unittest.TestCase):
    """promotes_from/promotes_to disagreeing with promotion_order — includes
    the cycle case, where a chain loops back into itself."""

    def test_a_cycle_is_reported(self):
        policy = make_policy()
        # prod points back at preview instead of terminating.
        policy["environments"]["prod"]["promotes_to"] = "preview"
        policy["environments"]["preview"]["promotes_from"] = "prod"
        violations = C.validate_structure(policy)
        self.assertTrue(any("prod" in v and "cycle" in v for v in violations))

    def test_a_branch_is_reported(self):
        policy = make_policy()
        # dev claims to promote from staging instead of preview: a branch,
        # not a line.
        policy["environments"]["dev"]["promotes_from"] = "staging"
        violations = C.validate_structure(policy)
        self.assertTrue(any("dev" in v and "promotes_from" in v for v in violations))

    def test_entry_point_with_a_promotes_from_is_reported(self):
        policy = make_policy()
        policy["environments"]["preview"]["promotes_from"] = "dev"
        violations = C.validate_structure(policy)
        self.assertTrue(any("preview" in v for v in violations))

    def test_terminus_with_a_promotes_to_is_reported(self):
        policy = make_policy()
        policy["environments"]["prod"]["promotes_to"] = "dev"
        violations = C.validate_structure(policy)
        self.assertTrue(any("prod" in v for v in violations))


class TestPlatformMismatch(unittest.TestCase):
    def test_environment_missing_from_the_repo_is_reported(self):
        policy = make_policy()
        api = make_api(names=("preview", "dev", "staging"))  # prod absent
        violations = C.validate_platform(policy["environments"], api)
        self.assertTrue(
            any("prod" in v and "does not exist" in v for v in violations)
        )

    def test_required_reviewer_env_with_no_reviewer_configured_is_reported(self):
        policy = make_policy()
        api = make_api(prod_has_reviewer=False)
        violations = C.validate_platform(policy["environments"], api)
        self.assertTrue(
            any("prod" in v and "no required-reviewers" in v for v in violations)
        )

    def test_an_env_not_requiring_a_reviewer_is_fine_without_one(self):
        policy = make_policy()
        api = make_api()  # dev/staging/preview never get a reviewer rule
        violations = C.validate_platform(policy["environments"], api)
        self.assertEqual(violations, [])

    def test_extra_platform_environments_are_not_a_violation(self):
        # github-pages exists on the real repo and is not in the ladder —
        # the policy only makes claims about what it declares.
        policy = make_policy()
        api = make_api()
        api["github-pages"] = {"name": "github-pages", "protection_rules": []}
        self.assertEqual(C.validate_platform(policy["environments"], api), [])


class TestReportsEveryViolation(unittest.TestCase):
    def test_multiple_independent_problems_are_all_reported(self):
        policy = make_policy()
        policy["environments"]["dev"]["rollback"] = {"owner": ""}
        policy["environments"]["prod"]["promotes_to"] = "dev"
        violations = C.validate_structure(policy)
        self.assertGreaterEqual(len(violations), 2)

    def test_multiple_platform_problems_are_all_reported(self):
        policy = make_policy()
        api = make_api(prod_has_reviewer=False, names=("preview", "dev"))
        violations = C.validate_platform(policy["environments"], api)
        # staging missing, prod missing, prod's reviewer requirement unmet
        # (though prod is already reported missing, staging is independent)
        self.assertTrue(any("staging" in v for v in violations))
        self.assertTrue(any("prod" in v for v in violations))


class TestLivePolicyStructure(unittest.TestCase):
    """The real policies/environments.yaml, structurally — no network."""

    def test_the_merged_ladder_is_structurally_clean(self):
        import yaml

        policy = yaml.safe_load((REPO_ROOT / "policies" / "environments.yaml").read_text())
        self.assertEqual(C.validate_structure(policy), [])


class TestCLI(unittest.TestCase):
    def _write(self, tmp_path: Path, policy: dict) -> Path:
        import yaml

        p = tmp_path / "environments.yaml"
        p.write_text(yaml.safe_dump(policy))
        return p

    def test_main_returns_zero_on_a_clean_policy_and_matching_platform(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = self._write(Path(d), make_policy())
            rc = C.main(
                ["--policy", str(path), "--repo", "owner/repo"],
                fetch=lambda repo: make_api(),
            )
        self.assertEqual(rc, 0)

    def test_main_returns_nonzero_on_a_structural_violation_without_calling_fetch(self):
        import tempfile

        policy = make_policy()
        policy["environments"]["dev"]["rollback"] = {"owner": ""}
        calls = []

        with tempfile.TemporaryDirectory() as d:
            path = self._write(Path(d), policy)
            rc = C.main(
                ["--policy", str(path), "--repo", "owner/repo"],
                fetch=lambda repo: calls.append(repo) or make_api(),
            )
        self.assertEqual(rc, 1)
        self.assertEqual(calls, [], "a structural violation must not reach the API")

    def test_main_returns_nonzero_on_a_platform_violation(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = self._write(Path(d), make_policy())
            rc = C.main(
                ["--policy", str(path), "--repo", "owner/repo"],
                fetch=lambda repo: make_api(names=("preview", "dev", "staging")),
            )
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
