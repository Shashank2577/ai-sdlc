#!/usr/bin/env python3
"""Tests for the product registry validator.

Fixtures only — a products policy dict, a ladder policy dict, and fake
role-pack budgets/platform responses, all built in-line. Never the live
`policies/products.yaml` or a real `gh api` call for the platform-facing
rules, so this suite runs offline and cannot be broken by a future entry
added to the real registry (or a rate-limited API). One test does read
the live `policies/products.yaml` structurally, the same way
`test_check_environments.py` does for its policy.

    python3 scripts/test_check_products.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

spec = importlib.util.spec_from_file_location("check_products", HERE / "check-products.py")
C = importlib.util.module_from_spec(spec)
sys.modules["check_products"] = C
spec.loader.exec_module(C)


LADDER_ENVIRONMENTS = {
    "preview": {"human_reviewer_required": False},
    "dev": {"human_reviewer_required": False},
    "staging": {"human_reviewer_required": False},
    "prod": {"human_reviewer_required": True},
}

ROLE_PACK_NAMES = {"product-manager", "architect", "developer", "qa", "devops", "techwriter"}

ROLE_PACK_BUDGETS = {
    "developer": {"turns": 90, "cost_usd": 5.00, "tokens": 400000, "wall_clock_minutes": 45},
    "qa": {"turns": 40, "cost_usd": 3.00, "tokens": 250000, "wall_clock_minutes": 30},
    "architect": {"turns": 60, "cost_usd": 4.00, "tokens": 300000, "wall_clock_minutes": 40},
    "devops": {"turns": 60, "cost_usd": 4.00, "tokens": 300000, "wall_clock_minutes": 40},
    "product-manager": {"turns": 60, "cost_usd": 4.00, "tokens": 300000, "wall_clock_minutes": 40},
    "techwriter": {"turns": 60, "cost_usd": 4.00, "tokens": 300000, "wall_clock_minutes": 40},
}


def make_products(**overrides) -> dict:
    """A single clean entry, the shape of a real one."""
    products = {
        "acme-widgets": {
            "repo": "acme/widgets",
            "project": {"owner": "acme", "number": 1},
            "environments": [
                {"name": "preview", "human_reviewer_required": False},
                {"name": "prod", "human_reviewer_required": True},
            ],
            "roles": ["developer", "qa"],
            "budget_overrides": {"developer": {"cost_usd": 3.00}},
            "bootstrapped": True,
        },
    }
    products.update(overrides)
    return products


class TestEnvironmentsKnown(unittest.TestCase):
    def test_known_environments_are_clean(self):
        self.assertEqual(
            C.validate_environments_known(make_products(), set(LADDER_ENVIRONMENTS)), []
        )

    def test_unknown_environment_is_reported(self):
        products = make_products()
        products["acme-widgets"]["environments"].append({"name": "canary", "human_reviewer_required": False})
        violations = C.validate_environments_known(products, set(LADDER_ENVIRONMENTS))
        self.assertTrue(any("acme-widgets" in v and "canary" in v for v in violations))


class TestEnvironmentsNotWeakened(unittest.TestCase):
    def test_tightening_is_allowed(self):
        products = make_products()
        products["acme-widgets"]["environments"][0]["human_reviewer_required"] = True  # preview, tightened
        self.assertEqual(
            C.validate_environments_not_weakened(products, LADDER_ENVIRONMENTS), []
        )

    def test_weakening_a_required_rung_is_reported(self):
        products = make_products()
        products["acme-widgets"]["environments"][1]["human_reviewer_required"] = False  # prod, weakened
        violations = C.validate_environments_not_weakened(products, LADDER_ENVIRONMENTS)
        self.assertTrue(any("acme-widgets" in v and "prod" in v for v in violations))

    def test_an_unknown_environment_is_not_double_reported_here(self):
        products = make_products()
        products["acme-widgets"]["environments"].append({"name": "canary", "human_reviewer_required": False})
        self.assertEqual(
            C.validate_environments_not_weakened(products, LADDER_ENVIRONMENTS), []
        )


class TestRolesHavePacks(unittest.TestCase):
    def test_known_roles_are_clean(self):
        self.assertEqual(C.validate_roles_have_packs(make_products(), ROLE_PACK_NAMES), [])

    def test_unknown_role_is_reported(self):
        products = make_products()
        products["acme-widgets"]["roles"].append("security-champion")
        violations = C.validate_roles_have_packs(products, ROLE_PACK_NAMES)
        self.assertTrue(any("acme-widgets" in v and "security-champion" in v for v in violations))


class TestBudgetOverridesOnlyTighten(unittest.TestCase):
    def test_a_tighter_override_is_clean(self):
        self.assertEqual(
            C.validate_budget_overrides(make_products(), ROLE_PACK_BUDGETS), []
        )

    def test_a_looser_override_is_reported(self):
        products = make_products()
        products["acme-widgets"]["budget_overrides"]["developer"]["cost_usd"] = 9.00
        violations = C.validate_budget_overrides(products, ROLE_PACK_BUDGETS)
        self.assertTrue(any("acme-widgets" in v and "cost_usd" in v for v in violations))

    def test_an_equal_override_is_not_a_violation(self):
        products = make_products()
        products["acme-widgets"]["budget_overrides"]["developer"]["cost_usd"] = 5.00
        self.assertEqual(C.validate_budget_overrides(products, ROLE_PACK_BUDGETS), [])

    def test_a_role_not_in_the_roles_list_is_reported(self):
        products = make_products()
        products["acme-widgets"]["budget_overrides"]["architect"] = {"cost_usd": 1.00}
        violations = C.validate_budget_overrides(products, ROLE_PACK_BUDGETS)
        self.assertTrue(any("architect" in v and "roles" in v for v in violations))

    def test_an_empty_roles_list_permits_any_role(self):
        products = make_products()
        products["acme-widgets"]["roles"] = []
        products["acme-widgets"]["budget_overrides"]["architect"] = {"cost_usd": 1.00}
        self.assertEqual(C.validate_budget_overrides(products, ROLE_PACK_BUDGETS), [])

    def test_a_role_with_no_pack_is_reported(self):
        products = make_products()
        products["acme-widgets"]["roles"] = []
        products["acme-widgets"]["budget_overrides"] = {"ghost-role": {"cost_usd": 1.00}}
        violations = C.validate_budget_overrides(products, ROLE_PACK_BUDGETS)
        self.assertTrue(any("ghost-role" in v for v in violations))

    def test_an_unknown_field_is_reported(self):
        products = make_products()
        products["acme-widgets"]["budget_overrides"]["developer"]["frobs"] = 1
        violations = C.validate_budget_overrides(products, ROLE_PACK_BUDGETS)
        self.assertTrue(any("frobs" in v for v in violations))


class TestNoDuplicateProjects(unittest.TestCase):
    def test_distinct_projects_are_clean(self):
        self.assertEqual(C.validate_no_duplicate_projects(make_products()), [])

    def test_shared_project_is_reported(self):
        products = make_products()
        products["other-widgets"] = {
            "repo": "acme/other-widgets",
            "project": {"owner": "acme", "number": 1},  # same board as acme-widgets
            "bootstrapped": False,
        }
        violations = C.validate_no_duplicate_projects(products)
        self.assertTrue(
            any("acme-widgets" in v and "other-widgets" in v for v in violations)
        )


class TestRepoResolves(unittest.TestCase):
    def test_a_matching_repo_is_clean(self):
        fetch = lambda repo: {"full_name": repo, "default_branch": "main"}
        self.assertEqual(C.validate_repo_resolves(make_products(), fetch), [])

    def test_a_missing_repo_is_reported(self):
        fetch = lambda repo: None
        violations = C.validate_repo_resolves(make_products(), fetch)
        self.assertTrue(any("acme-widgets" in v and "does not resolve" in v for v in violations))

    def test_a_renamed_repo_is_reported(self):
        fetch = lambda repo: {"full_name": "acme/widgets-renamed", "default_branch": "main"}
        violations = C.validate_repo_resolves(make_products(), fetch)
        self.assertTrue(any("acme-widgets" in v and "widgets-renamed" in v for v in violations))


class TestProjectResolves(unittest.TestCase):
    def test_a_resolving_project_is_clean(self):
        fetch = lambda owner, number: {"id": "PVT_1"}
        self.assertEqual(C.validate_project_resolves(make_products(), fetch), [])

    def test_a_non_resolving_project_is_reported(self):
        fetch = lambda owner, number: None
        violations = C.validate_project_resolves(make_products(), fetch)
        self.assertTrue(any("acme-widgets" in v and "does not resolve" in v for v in violations))


class TestBootstrappedIsVerified(unittest.TestCase):
    def _fetchers(self, *, present: set | None = None, contexts=("dod",)):
        present = present if present is not None else {
            "CONVENTIONS.md", ".github/CODEOWNERS", ".github/pull_request_template.md",
        }
        fetch_repo = lambda repo: {"full_name": repo, "default_branch": "main"}
        fetch_exists = lambda repo, path: path in present
        fetch_protection = lambda repo, branch: {"required_status_checks": {"contexts": list(contexts)}}
        return fetch_repo, fetch_exists, fetch_protection

    def test_a_fully_bootstrapped_repo_is_clean(self):
        fetch_repo, fetch_exists, fetch_protection = self._fetchers()
        self.assertEqual(
            C.validate_bootstrapped(make_products(), fetch_repo, fetch_exists, fetch_protection), []
        )

    def test_a_non_bootstrapped_entry_is_never_checked(self):
        products = make_products()
        products["acme-widgets"]["bootstrapped"] = False
        fetch_repo, fetch_exists, fetch_protection = self._fetchers(present=set())
        self.assertEqual(
            C.validate_bootstrapped(products, fetch_repo, fetch_exists, fetch_protection), []
        )

    def test_missing_conventions_is_reported(self):
        fetch_repo, fetch_exists, fetch_protection = self._fetchers(
            present={".github/CODEOWNERS", ".github/pull_request_template.md"}
        )
        violations = C.validate_bootstrapped(make_products(), fetch_repo, fetch_exists, fetch_protection)
        self.assertTrue(any("CONVENTIONS.md" in v for v in violations))

    def test_missing_codeowners_is_reported(self):
        fetch_repo, fetch_exists, fetch_protection = self._fetchers(
            present={"CONVENTIONS.md", ".github/pull_request_template.md"}
        )
        violations = C.validate_bootstrapped(make_products(), fetch_repo, fetch_exists, fetch_protection)
        self.assertTrue(any("CODEOWNERS" in v for v in violations))

    def test_pr_template_accepts_any_of_the_three_locations(self):
        for path in (".github/pull_request_template.md", "PULL_REQUEST_TEMPLATE.md", ".github/PULL_REQUEST_TEMPLATE"):
            with self.subTest(path=path):
                fetch_repo, fetch_exists, fetch_protection = self._fetchers(
                    present={"CONVENTIONS.md", ".github/CODEOWNERS", path}
                )
                self.assertEqual(
                    C.validate_bootstrapped(make_products(), fetch_repo, fetch_exists, fetch_protection), []
                )

    def test_missing_pr_template_is_reported(self):
        fetch_repo, fetch_exists, fetch_protection = self._fetchers(
            present={"CONVENTIONS.md", ".github/CODEOWNERS"}
        )
        violations = C.validate_bootstrapped(make_products(), fetch_repo, fetch_exists, fetch_protection)
        self.assertTrue(any("pull request template" in v for v in violations))

    def test_missing_dod_context_is_reported(self):
        fetch_repo, fetch_exists, fetch_protection = self._fetchers(contexts=("some-other-check",))
        violations = C.validate_bootstrapped(make_products(), fetch_repo, fetch_exists, fetch_protection)
        self.assertTrue(any("dod" in v for v in violations))

    def test_a_custom_dod_check_context_is_honoured(self):
        products = make_products()
        products["acme-widgets"]["dod_check_context"] = "ci/dod"
        fetch_repo, fetch_exists, fetch_protection = self._fetchers(contexts=("ci/dod",))
        self.assertEqual(
            C.validate_bootstrapped(products, fetch_repo, fetch_exists, fetch_protection), []
        )

    def test_repo_that_does_not_resolve_is_reported_without_crashing(self):
        fetch_repo = lambda repo: None
        fetch_exists = lambda repo, path: True
        fetch_protection = lambda repo, branch: {"required_status_checks": {"contexts": ["dod"]}}
        violations = C.validate_bootstrapped(make_products(), fetch_repo, fetch_exists, fetch_protection)
        self.assertTrue(any("acme-widgets" in v and "does not resolve" in v for v in violations))

    def test_multiple_missing_pieces_are_all_reported(self):
        fetch_repo, fetch_exists, fetch_protection = self._fetchers(present=set(), contexts=())
        violations = C.validate_bootstrapped(make_products(), fetch_repo, fetch_exists, fetch_protection)
        self.assertEqual(len(violations), 1)  # one entry, one combined message...
        self.assertIn("CONVENTIONS.md", violations[0])
        self.assertIn("CODEOWNERS", violations[0])
        self.assertIn("pull request template", violations[0])
        self.assertIn("dod", violations[0])


class TestReportsEveryViolation(unittest.TestCase):
    def test_multiple_independent_structural_problems_are_all_reported(self):
        products = make_products()
        products["acme-widgets"]["environments"].append({"name": "canary", "human_reviewer_required": False})
        products["acme-widgets"]["roles"].append("security-champion")
        violations = C.validate_structure(products, LADDER_ENVIRONMENTS, ROLE_PACK_NAMES, ROLE_PACK_BUDGETS)
        self.assertTrue(any("canary" in v for v in violations))
        self.assertTrue(any("security-champion" in v for v in violations))


class TestLivePolicyStructure(unittest.TestCase):
    """The real policies/products.yaml, structurally — no network.

    `no_duplicate_projects` is deliberately not folded into a single
    "the whole file is clean" assertion here: as of this writing the live
    registry itself fails that one rule (`ai-sdlc-pilot` and
    `foundry-program` both resolve to `{Shashank2577, 2}` — see the PR this
    test suite shipped in). That is a real, pre-existing defect in a file
    outside this role's write scope (`policies/**` is delivery-lead's, not
    developer's), not a bug in the checker. A blanket cleanliness
    assertion here would fail every future PR's CI — unrelated to whatever
    that PR touches — until someone else fixes the registry. Each rule
    that the live file does satisfy today is still checked individually,
    so a regression in any of *those* is still caught.
    """

    def _load(self):
        import yaml

        policy = yaml.safe_load((REPO_ROOT / "policies" / "products.yaml").read_text())
        env_policy = yaml.safe_load((REPO_ROOT / "policies" / "environments.yaml").read_text())
        names = C.role_pack_names(REPO_ROOT / "role-packs")
        budgets = C.load_role_pack_budgets(REPO_ROOT / "role-packs", names)
        return policy.get("products") or {}, env_policy.get("environments") or {}, names, budgets

    def test_environments_roles_and_budgets_are_clean(self):
        products, ladder_environments, names, budgets = self._load()
        violations = []
        violations += C.validate_environments_known(products, set(ladder_environments))
        violations += C.validate_environments_not_weakened(products, ladder_environments)
        violations += C.validate_roles_have_packs(products, names)
        violations += C.validate_budget_overrides(products, budgets)
        self.assertEqual(violations, [])

    def test_product_template_is_not_iterated(self):
        import yaml

        policy = yaml.safe_load((REPO_ROOT / "policies" / "products.yaml").read_text())
        self.assertNotIn("product_template", policy.get("products") or {})


class TestRolePackDiscovery(unittest.TestCase):
    def test_every_declared_role_pack_directory_is_found(self):
        names = C.role_pack_names(REPO_ROOT / "role-packs")
        self.assertIn("developer", names)
        self.assertIn("qa", names)
        self.assertNotIn("README.md", names)

    def test_budgets_are_loaded_per_pack(self):
        names = C.role_pack_names(REPO_ROOT / "role-packs")
        budgets = C.load_role_pack_budgets(REPO_ROOT / "role-packs", names)
        self.assertIn("turns", budgets["developer"])


class TestCLI(unittest.TestCase):
    def _write(self, tmp_path: Path, name: str, data: dict) -> Path:
        import yaml

        p = tmp_path / name
        p.write_text(yaml.safe_dump(data))
        return p

    def _write_ladder(self, tmp_path: Path) -> Path:
        return self._write(tmp_path, "environments.yaml", {"environments": LADDER_ENVIRONMENTS})

    def _write_role_packs(self, tmp_path: Path) -> Path:
        packs_dir = tmp_path / "role-packs"
        for name, budgets in ROLE_PACK_BUDGETS.items():
            d = packs_dir / name
            d.mkdir(parents=True)
            import yaml
            (d / "policy.yaml").write_text(yaml.safe_dump({"budgets": budgets}))
        return packs_dir

    def test_main_returns_zero_on_a_clean_policy_and_matching_platform(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            products_path = self._write(tmp, "products.yaml", {"products": make_products()})
            ladder_path = self._write_ladder(tmp)
            packs_dir = self._write_role_packs(tmp)
            rc = C.main(
                ["--policy", str(products_path), "--environments-policy", str(ladder_path),
                 "--role-packs-dir", str(packs_dir)],
                fetch_repo=lambda repo: {"full_name": repo, "default_branch": "main"},
                fetch_project=lambda owner, number: {"id": "PVT_1"},
                fetch_exists=lambda repo, path: True,
                fetch_protection=lambda repo, branch: {"required_status_checks": {"contexts": ["dod"]}},
            )
        self.assertEqual(rc, 0)

    def test_main_returns_nonzero_on_a_structural_violation_without_calling_fetchers(self):
        import tempfile

        products = make_products()
        products["acme-widgets"]["roles"].append("no-such-role")
        calls = []

        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            products_path = self._write(tmp, "products.yaml", {"products": products})
            ladder_path = self._write_ladder(tmp)
            packs_dir = self._write_role_packs(tmp)
            rc = C.main(
                ["--policy", str(products_path), "--environments-policy", str(ladder_path),
                 "--role-packs-dir", str(packs_dir)],
                fetch_repo=lambda repo: calls.append(repo) or {"full_name": repo, "default_branch": "main"},
                fetch_project=lambda owner, number: calls.append((owner, number)) or {"id": "PVT_1"},
                fetch_exists=lambda repo, path: True,
                fetch_protection=lambda repo, branch: {"required_status_checks": {"contexts": ["dod"]}},
            )
        self.assertEqual(rc, 1)
        self.assertEqual(calls, [], "a structural violation must not reach the API")

    def test_main_returns_nonzero_on_a_platform_violation(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            products_path = self._write(tmp, "products.yaml", {"products": make_products()})
            ladder_path = self._write_ladder(tmp)
            packs_dir = self._write_role_packs(tmp)
            rc = C.main(
                ["--policy", str(products_path), "--environments-policy", str(ladder_path),
                 "--role-packs-dir", str(packs_dir)],
                fetch_repo=lambda repo: None,
                fetch_project=lambda owner, number: {"id": "PVT_1"},
                fetch_exists=lambda repo, path: True,
                fetch_protection=lambda repo, branch: {"required_status_checks": {"contexts": ["dod"]}},
            )
        self.assertEqual(rc, 1)

    def test_main_returns_nonzero_on_an_empty_registry(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            products_path = self._write(tmp, "products.yaml", {"products": {}})
            ladder_path = self._write_ladder(tmp)
            packs_dir = self._write_role_packs(tmp)
            rc = C.main(
                ["--policy", str(products_path), "--environments-policy", str(ladder_path),
                 "--role-packs-dir", str(packs_dir)],
            )
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
