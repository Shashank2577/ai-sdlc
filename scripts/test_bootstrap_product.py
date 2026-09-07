#!/usr/bin/env python3
"""Tests for the product-repo bootstrapper.

Fakes only — an in-memory fake of the four `gh api` calls the world layer
makes, never a real `gh` invocation — so this suite runs offline and
cannot be broken by rate limits or a real repo's drift. The four scenarios
the work item names each get their own test: a clean repo, an
already-bootstrapped one, one with a conflicting file, and one where the
credential lacks admin.

    python3 scripts/test_bootstrap_product.py
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent

spec = importlib.util.spec_from_file_location("bootstrap_product", HERE / "bootstrap-product.py")
B = importlib.util.module_from_spec(spec)
sys.modules["bootstrap_product"] = B
spec.loader.exec_module(B)


REPO = "acme/widgets"


class FakeGitHub:
    """An in-memory stand-in for the target repo's API surface.

    `files`: path -> content (absence means the file does not exist).
    `protection`: the branch-protection object, or None.
    `is_admin`: whether the credential has admin on the repo.
    """

    def __init__(self, files: dict[str, str] | None = None, protection: dict | None = None,
                 is_admin: bool = True, default_branch: str = "main"):
        self.files = dict(files or {})
        self.protection = protection
        self.is_admin = is_admin
        self.default_branch = default_branch
        self.put_files: dict[str, str] = {}
        self.protection_puts = 0

    # -- world callables, matching bootstrap_product's Callable signatures --

    def get_file(self, repo: str, path: str):
        assert repo == REPO
        return self.files.get(path)

    def put_file(self, repo: str, path: str, content: str, message: str) -> None:
        assert repo == REPO
        self.files[path] = content
        self.put_files[path] = content

    def get_protection(self, repo: str, branch: str):
        assert repo == REPO
        assert branch == self.default_branch
        return self.protection

    def put_protection(self, repo: str, branch: str, context: str, existing: dict | None = None) -> None:
        assert repo == REPO
        assert branch == self.default_branch
        self.protection_puts += 1
        contexts = list(((existing or {}).get("required_status_checks") or {}).get("contexts") or [])
        if context not in contexts:
            contexts.append(context)
        self.protection = {
            "required_status_checks": {"strict": False, "contexts": contexts},
            "enforce_admins": {"enabled": True},
            "required_conversation_resolution": {"enabled": True},
        }

    def get_repo_meta(self, repo: str) -> dict:
        assert repo == REPO
        return {"default_branch": self.default_branch, "is_admin": self.is_admin}

    def check_world(self) -> dict:
        return dict(
            get_file=self.get_file,
            get_protection=self.get_protection,
            get_repo_meta=self.get_repo_meta,
        )

    def install_world(self) -> dict:
        return dict(
            get_file=self.get_file,
            put_file=self.put_file,
            get_protection=self.get_protection,
            put_protection=self.put_protection,
            get_repo_meta=self.get_repo_meta,
        )


def bootstrapped_files() -> dict[str, str]:
    return {
        "CONVENTIONS.md": B.conventions_md(),
        ".github/CODEOWNERS": B.codeowners("acme"),
        B.CANONICAL_PR_TEMPLATE: B.pull_request_template(),
    }


def bootstrapped_protection(context: str = "dod", conversation_resolution: bool = True) -> dict:
    return {
        "required_status_checks": {"strict": False, "contexts": [context]},
        "enforce_admins": {"enabled": True},
        "required_conversation_resolution": {"enabled": conversation_resolution},
    }


# --------------------------------------------------------------------------
# Pure planning functions
# --------------------------------------------------------------------------

class TestPlanFileInstall(unittest.TestCase):
    def test_missing_file_is_created(self):
        r = B.plan_file_install("x", None, "desired")
        self.assertEqual(r.status, "created")

    def test_identical_file_is_unchanged(self):
        r = B.plan_file_install("x", "same", "same")
        self.assertEqual(r.status, "unchanged")

    def test_differing_file_is_a_conflict_not_overwritten(self):
        r = B.plan_file_install("x", "custom stuff", "our template")
        self.assertEqual(r.status, "conflict")


class TestCheckBranchProtection(unittest.TestCase):
    def test_no_protection_is_missing(self):
        r = B.check_branch_protection(None, "dod")
        self.assertEqual(r.status, "missing")

    def test_check_present_but_admins_exempt_is_missing(self):
        protection = {"required_status_checks": {"contexts": ["dod"]}, "enforce_admins": {"enabled": False}}
        r = B.check_branch_protection(protection, "dod")
        self.assertEqual(r.status, "missing")
        self.assertIn("enforce_admins", r.detail)

    def test_admins_enforced_but_wrong_context_is_missing(self):
        protection = {"required_status_checks": {"contexts": ["other-check"]}, "enforce_admins": {"enabled": True}}
        r = B.check_branch_protection(protection, "dod")
        self.assertEqual(r.status, "missing")

    def test_both_present_is_satisfied(self):
        r = B.check_branch_protection(bootstrapped_protection(), "dod")
        self.assertEqual(r.status, "present")


class TestPlanBranchProtection(unittest.TestCase):
    def test_already_satisfied_is_unchanged(self):
        r = B.plan_branch_protection(bootstrapped_protection(), "dod", is_admin=True)
        self.assertEqual(r.status, "unchanged")

    def test_missing_with_admin_is_created(self):
        r = B.plan_branch_protection(None, "dod", is_admin=True)
        self.assertEqual(r.status, "created")

    def test_missing_without_admin_is_reported_not_swallowed(self):
        r = B.plan_branch_protection(None, "dod", is_admin=False)
        self.assertEqual(r.status, "no_admin")
        self.assertIn("admin", r.detail)


class TestCheckConversationResolution(unittest.TestCase):
    def test_no_protection_is_missing(self):
        r = B.check_conversation_resolution(None)
        self.assertEqual(r.status, "missing")

    def test_disabled_is_missing(self):
        protection = bootstrapped_protection(conversation_resolution=False)
        r = B.check_conversation_resolution(protection)
        self.assertEqual(r.status, "missing")

    def test_enabled_is_present(self):
        r = B.check_conversation_resolution(bootstrapped_protection())
        self.assertEqual(r.status, "present")

    def test_a_repo_with_correct_branch_protection_but_loosened_conversation_resolution_is_caught(self):
        # #227's exact failure shape: the `dod` status check and
        # enforce_admins are both still correct, so `check_branch_protection`
        # alone would call this repo fully bootstrapped — this is the
        # separate, independently-checked item that catches the loosening.
        protection = bootstrapped_protection(conversation_resolution=False)
        self.assertEqual(B.check_branch_protection(protection, "dod").status, "present")
        self.assertEqual(B.check_conversation_resolution(protection).status, "missing")


class TestPlanConversationResolution(unittest.TestCase):
    def test_already_satisfied_is_unchanged(self):
        r = B.plan_conversation_resolution(bootstrapped_protection(), is_admin=True)
        self.assertEqual(r.status, "unchanged")

    def test_missing_with_admin_is_created(self):
        r = B.plan_conversation_resolution(None, is_admin=True)
        self.assertEqual(r.status, "created")

    def test_missing_without_admin_is_reported_not_swallowed(self):
        r = B.plan_conversation_resolution(None, is_admin=False)
        self.assertEqual(r.status, "no_admin")
        self.assertIn("admin", r.detail)

    def test_loosened_with_admin_is_created(self):
        protection = bootstrapped_protection(conversation_resolution=False)
        r = B.plan_conversation_resolution(protection, is_admin=True)
        self.assertEqual(r.status, "created")

    def test_loosened_without_admin_is_reported_not_swallowed(self):
        protection = bootstrapped_protection(conversation_resolution=False)
        r = B.plan_conversation_resolution(protection, is_admin=False)
        self.assertEqual(r.status, "no_admin")
        self.assertIn("admin", r.detail)


class TestPrTemplatePlanning(unittest.TestCase):
    def test_missing_everywhere_is_created_at_canonical_path(self):
        r = B.plan_pr_template_install({p: None for p in B.PR_TEMPLATE_VARIANTS}, "desired")
        self.assertEqual(r.status, "created")

    def test_present_at_alternate_location_is_left_alone(self):
        existing = {p: None for p in B.PR_TEMPLATE_VARIANTS}
        existing[".github/PULL_REQUEST_TEMPLATE.md"] = "their own template"
        r = B.plan_pr_template_install(existing, "desired")
        self.assertEqual(r.status, "present_elsewhere")

    def test_canonical_path_identical_is_unchanged(self):
        existing = {p: None for p in B.PR_TEMPLATE_VARIANTS}
        existing[B.CANONICAL_PR_TEMPLATE] = "desired"
        r = B.plan_pr_template_install(existing, "desired")
        self.assertEqual(r.status, "unchanged")

    def test_canonical_path_differs_is_a_conflict(self):
        existing = {p: None for p in B.PR_TEMPLATE_VARIANTS}
        existing[B.CANONICAL_PR_TEMPLATE] = "their own template"
        r = B.plan_pr_template_install(existing, "desired")
        self.assertEqual(r.status, "conflict")


# --------------------------------------------------------------------------
# The four scenarios the work item names, end to end through do_check /
# do_install with a fake world.
# --------------------------------------------------------------------------

class TestScenarios(unittest.TestCase):
    def test_clean_repo_check_reports_everything_missing(self):
        fake = FakeGitHub()
        results = B.do_check(REPO, "dod", **fake.check_world())
        self.assertFalse(B.is_ok(results))
        self.assertTrue(all(r.status == "missing" for r in results))

    def test_clean_repo_install_creates_everything(self):
        fake = FakeGitHub()
        results = B.do_install(REPO, "dod", **fake.install_world())
        self.assertTrue(B.is_ok(results))
        self.assertEqual(set(fake.put_files), {"CONVENTIONS.md", ".github/CODEOWNERS", B.CANONICAL_PR_TEMPLATE})
        self.assertEqual(fake.protection_puts, 1)

    def test_install_twice_is_a_no_op_the_second_time(self):
        fake = FakeGitHub()
        B.do_install(REPO, "dod", **fake.install_world())
        fake.put_files.clear()
        fake.protection_puts = 0
        results = B.do_install(REPO, "dod", **fake.install_world())
        self.assertTrue(B.is_ok(results))
        self.assertEqual(fake.put_files, {})
        self.assertEqual(fake.protection_puts, 0)
        self.assertTrue(all(r.status in ("unchanged",) for r in results))

    def test_already_bootstrapped_repo_check_reports_all_present(self):
        fake = FakeGitHub(files=bootstrapped_files(), protection=bootstrapped_protection())
        results = B.do_check(REPO, "dod", **fake.check_world())
        self.assertTrue(B.is_ok(results))
        self.assertTrue(all(r.status == "present" for r in results))

    def test_conflicting_file_is_reported_and_never_overwritten(self):
        files = {"CONVENTIONS.md": "# This product's own conventions\n\nDo it our way.\n"}
        fake = FakeGitHub(files=files)
        results = B.do_install(REPO, "dod", **fake.install_world())
        self.assertFalse(B.is_ok(results))
        conflict = next(r for r in results if r.name == "CONVENTIONS.md")
        self.assertEqual(conflict.status, "conflict")
        self.assertEqual(fake.files["CONVENTIONS.md"], "# This product's own conventions\n\nDo it our way.\n")
        self.assertNotIn("CONVENTIONS.md", fake.put_files)
        # the other, non-conflicting items still install
        self.assertIn(".github/CODEOWNERS", fake.put_files)

    def test_no_admin_installs_files_but_not_protection_and_says_so(self):
        fake = FakeGitHub(is_admin=False)
        results = B.do_install(REPO, "dod", **fake.install_world())
        self.assertFalse(B.is_ok(results))
        protection_result = next(r for r in results if r.name == "branch protection")
        self.assertEqual(protection_result.status, "no_admin")
        self.assertIn("admin", protection_result.detail)
        conversation_result = next(r for r in results if r.name == "required conversation resolution")
        self.assertEqual(conversation_result.status, "no_admin")
        self.assertIn("admin", conversation_result.detail)
        self.assertEqual(fake.protection_puts, 0)
        # files were installed regardless
        self.assertEqual(set(fake.put_files), {"CONVENTIONS.md", ".github/CODEOWNERS", B.CANONICAL_PR_TEMPLATE})

    def test_loosened_repo_check_catches_it_without_touching_files(self):
        # #227's acceptance criterion: a repo bootstrapped, then loosened
        # by hand (here, required_conversation_resolution turned back off
        # while everything else stays correct), is caught by --check.
        fake = FakeGitHub(files=bootstrapped_files(), protection=bootstrapped_protection(conversation_resolution=False))
        results = B.do_check(REPO, "dod", **fake.check_world())
        self.assertFalse(B.is_ok(results))
        conversation_result = next(r for r in results if r.name == "required conversation resolution")
        self.assertEqual(conversation_result.status, "missing")
        branch_protection_result = next(r for r in results if r.name == "branch protection")
        self.assertEqual(branch_protection_result.status, "present")

    def test_loosened_repo_install_fixes_it_without_dropping_other_contexts(self):
        # The fix must not clobber a status-check context this product
        # added on top of `dod` after bootstrap — the PUT this call makes
        # replaces the whole protection resource, so anything already
        # required has to be carried forward, not just the context this
        # script itself cares about.
        protection = bootstrapped_protection(conversation_resolution=False)
        protection["required_status_checks"]["contexts"].append("qa-gate")
        fake = FakeGitHub(files=bootstrapped_files(), protection=protection)
        results = B.do_install(REPO, "dod", **fake.install_world())
        self.assertTrue(B.is_ok(results))
        self.assertEqual(fake.protection_puts, 1)
        self.assertTrue(fake.protection["required_conversation_resolution"]["enabled"])
        self.assertEqual(set(fake.protection["required_status_checks"]["contexts"]), {"dod", "qa-gate"})
        # no file was touched — this was purely a protection fix
        self.assertEqual(fake.put_files, {})


# --------------------------------------------------------------------------
# The registry gate — a product not declared is refused, not guessed at.
# --------------------------------------------------------------------------

class TestRegistry(unittest.TestCase):
    def test_unknown_product_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            policy = Path(d) / "products.yaml"
            policy.write_text("products:\n  known-product:\n    repo: acme/widgets\n")
            products = B.load_products(policy)
            with self.assertRaises(SystemExit):
                B.resolve_repo(products, "unknown-product")

    def test_known_product_resolves_its_repo(self):
        with tempfile.TemporaryDirectory() as d:
            policy = Path(d) / "products.yaml"
            policy.write_text("products:\n  known-product:\n    repo: acme/widgets\n")
            products = B.load_products(policy)
            self.assertEqual(B.resolve_repo(products, "known-product"), "acme/widgets")


if __name__ == "__main__":
    unittest.main()
