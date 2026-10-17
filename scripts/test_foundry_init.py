#!/usr/bin/env python3
"""Tests for foundry-init (#323), against a fake GitHub that keeps state, so
"apply, then plan again" really shows whether the second run plans nothing.

    python3 scripts/test_foundry_init.py
"""

from __future__ import annotations

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("foundry_init", HERE / "foundry-init.py")
F = importlib.util.module_from_spec(spec)
sys.modules["foundry_init"] = F
spec.loader.exec_module(F)

CP, PRODUCT, KEY = "acme/ai-sdlc", "acme/widget", "widget"
REGISTRY = """\
products:
  foundry-program:
    repo: acme/ai-sdlc
    project: {owner: acme, number: 2}
    environments:
      - {name: prod, human_reviewer_required: true}
    bootstrapped: true
"""
SEVEN = {"role:security", "role:operations", "security:approved", "security:rejected",
         "signoff:approved", "signoff:change-requested", "type:change-request"}


class FakeGitHub:
    """Just enough GitHub. Every write changes what later reads return."""

    def __init__(self, product_exists=True, admin=True):
        self.repos = {CP: {"admin": True, "owner_type": "User"}}
        if product_exists:
            self.repos[PRODUCT] = {"admin": admin, "owner_type": "User"}
        self.files = {CP: {"policies/products.yaml": REGISTRY}, PRODUCT: {}}
        self.labels = {CP: {"status:ready", "qa:approved"}}
        self.secrets = {CP: {"CLAUDE_CODE_OAUTH_TOKEN", F.APP_SECRET}}
        self.variables = {CP: {F.APP_VAR: "Iv1.x", F.APP_SLUG_VAR: "foundry-acme"}, PRODUCT: {}}
        self.envs, self.protections, self.alerts, self.codeql = {}, {}, set(), {}
        self.projects = {"acme": {2: "foundry-program Delivery"}}
        self.links, self.issues, self.prs, self.dispatches = [], {}, {}, []
        self.writes = []

    def whoami(self):
        return "acme"

    def repo(self, repo):
        r = self.repos.get(repo)
        if r is None:
            return None
        return {"default_branch": "main", "admin": r["admin"], "is_admin": r["admin"],
                "empty": not self.files.get(repo), "owner_type": r["owner_type"], "private": True}

    def secret_names(self, repo):
        return set(self.secrets.get(repo, set()))

    def variable(self, repo, name):
        return self.variables.get(repo, {}).get(name)

    def set_variable(self, repo, name, value):
        self.writes.append(("variable", repo, name))
        self.variables.setdefault(repo, {})[name] = value

    def label_names(self, repo):
        return set(self.labels.get(repo, set()))

    def create_label(self, repo, name, color, description):
        self.writes.append(("label", repo, name))
        self.labels.setdefault(repo, set()).add(name)

    def get_file(self, repo, path):
        return self.files.get(repo, {}).get(path)

    def put_file(self, repo, path, content, message):
        self.writes.append(("file", repo, path))
        self.files.setdefault(repo, {})[path] = content

    def root_files(self, repo):
        return {p.split("/")[0] for p in self.files.get(repo, {})}

    def environments(self, repo):
        return dict(self.envs.get(repo, {}))

    def put_environment(self, repo, name, reviewers):
        self.writes.append(("environment", repo, name))
        self.envs.setdefault(repo, {})[name] = list(reviewers)

    def vulnerability_alerts(self, repo):
        return repo in self.alerts

    def enable_security(self, repo):
        self.writes.append(("security", repo))
        self.alerts.add(repo)

    def codeql_state(self, repo):
        return self.codeql.get(repo, "not-configured")

    def enable_codeql(self, repo):
        self.writes.append(("codeql", repo))
        self.codeql[repo] = "configured"
        return "default setup configured"

    def protection(self, repo, branch):
        return self.protections.get(repo)

    def put_protection(self, repo, contexts):
        self.writes.append(("protection", repo))
        self.protections[repo] = {"required_status_checks": {"contexts": list(contexts)},
                                  "enforce_admins": {"enabled": True},
                                  "required_conversation_resolution": {"enabled": True}}
        return "ok"

    def control_plane_key(self, cp, products):
        return F.GitHub.control_plane_key(self, cp, products)

    def find_project(self, owner, title):
        for n, t in self.projects.get(owner, {}).items():
            if t == title:
                return n
        return None

    def copy_project(self, src_owner, src_number, owner, title):
        self.writes.append(("project", owner, title))
        n = max(self.projects.get(owner, {0: ""})) + 1
        self.projects.setdefault(owner, {})[n] = title
        return n

    def link_project(self, owner, number, repo):
        self.links.append((owner, number, repo))

    def find_issue(self, repo, label, title):
        for n, i in self.issues.items():
            if i["title"] == title and label in i["labels"]:
                return {"number": n, "labels": list(i["labels"]), "dispatched": n in self.dispatches}
        return None

    def create_issue(self, repo, title, body, labels):
        self.writes.append(("issue", repo, title))
        n = 400 + len(self.issues)
        self.issues[n] = {"title": title, "body": body, "labels": set(labels)}
        return n

    def registry(self, cp):
        return yaml.safe_load(self.files[cp]["policies/products.yaml"]) or {}

    def registry_text(self, cp):
        return self.files[cp]["policies/products.yaml"]

    def find_pr(self, repo, head):
        return self.prs.get(head, {}).get("url")

    def open_registry_pr(self, cp, key, repo, text, interview):
        self.writes.append(("pr", cp, key))
        self.prs[F.REGISTRY_BRANCH.format(key=key)] = {"url": "https://x/pull/9", "text": text,
                                                     "interview": interview}
        return "https://x/pull/9"

    def merge_registry_pr(self, key):
        self.files[CP]["policies/products.yaml"] = self.prs.pop(F.REGISTRY_BRANCH.format(key=key))["text"]

    def approve_and_dispatch(self, cp, number, key):
        self.writes.append(("dispatch", cp, number))
        self.issues[number]["labels"].add("status:ready")
        self.dispatches.append(number)
        return "dispatched"

    def app_installed(self, ctx, repo):
        return None


def ctx():
    return F.Ctx(control_plane=CP, repo=PRODUCT, key=KEY, login="acme", today="2026-10-17")


def apply_all(w, c):
    steps = F.plan(w, c)
    for s in steps:
        if s.status == "todo":
            s.apply()
    return F.plan(w, c)


def todo(steps):
    return [s.title for s in steps if s.status == "todo"]


class TestPlan(unittest.TestCase):
    def test_missing_repo_blocks_and_is_never_created(self):
        w = FakeGitHub(product_exists=False)
        steps = F.plan(w, ctx())
        self.assertEqual([s.status for s in steps], ["blocked"])
        self.assertIn("gh repo create", steps[0].detail)
        self.assertEqual(w.writes, [])

    def test_no_admin_blocks(self):
        steps = F.plan(FakeGitHub(admin=False), ctx())
        self.assertEqual(steps[0].status, "blocked")

    def test_planning_writes_nothing(self):
        w = FakeGitHub()
        F.plan(w, ctx())
        self.assertEqual(w.writes, [])

    def test_empty_repo_plans_every_setup_step(self):
        titles = todo(F.plan(FakeGitHub(), ctx()))
        for t in ("labels", "CONVENTIONS.md", ".github/CODEOWNERS", "PR template", "dod check workflow",
                  "scope check workflow", "CI workflow", "Dependabot config",
                  "FOUNDRY_CONTROL_PLANE variable", "environments",
                  "Dependabot alerts and security updates", "CodeQL", "branch protection", "board",
                  "interview issue", "products.yaml entry"):
            self.assertIn(t, titles)

    def test_labels_include_the_seven_missing_and_the_product_label(self):
        step = next(s for s in F.plan(FakeGitHub(), ctx()) if s.title == "labels")
        for name in SEVEN | {"product:widget"}:
            self.assertIn(name, step.detail)

    def test_second_run_plans_nothing(self):
        w = FakeGitHub()
        after = apply_all(w, ctx())
        self.assertEqual(todo(after), [])
        before = len(w.writes)
        self.assertEqual(todo(F.plan(w, ctx())), [])
        self.assertEqual(len(w.writes), before)

    def test_protection_is_applied_after_the_files_that_produce_its_checks(self):
        w = FakeGitHub()
        apply_all(w, ctx())
        kinds = [x[0] + ":" + (x[2] if len(x) > 2 else "") for x in w.writes]
        scope_at = kinds.index("file:.github/workflows/scope-check.yml")
        self.assertLess(scope_at, [k.split(":")[0] for k in kinds].index("protection"))
        self.assertEqual(w.protections[PRODUCT]["required_status_checks"]["contexts"], ["dod", "scope"])

    def test_a_differing_file_is_left_alone(self):
        w = FakeGitHub()
        w.files[PRODUCT]["CONVENTIONS.md"] = "our own conventions\n"
        apply_all(w, ctx())
        self.assertEqual(w.files[PRODUCT]["CONVENTIONS.md"], "our own conventions\n")

    def test_prod_gets_a_human_reviewer(self):
        w = FakeGitHub()
        apply_all(w, ctx())
        self.assertEqual(w.envs[PRODUCT]["prod"], ["acme"])
        self.assertEqual(w.envs[PRODUCT]["preview"], [])
        self.assertEqual(set(w.envs[PRODUCT]), {"preview", "dev", "staging", "prod"})

    def test_board_is_copied_from_the_control_planes_and_linked(self):
        w = FakeGitHub()
        apply_all(w, ctx())
        self.assertEqual(w.projects["acme"][3], "widget Delivery")
        self.assertEqual(w.links, [("acme", 3, PRODUCT)])

    def test_interview_is_not_ready_until_the_product_is_registered(self):
        w = FakeGitHub()
        steps = apply_all(w, ctx())
        issue = w.issues[400]
        self.assertNotIn("status:ready", issue["labels"])
        self.assertEqual({"product:widget", "role:product-manager", "type:story"}, issue["labels"])
        self.assertEqual(next(s for s in steps if s.title == "products.yaml entry").status, "waiting")
        self.assertEqual(next(s for s in steps if s.title == "first dispatch").status, "waiting")
        self.assertEqual(w.dispatches, [])

    def test_registry_pr_entry_is_valid_and_cites_the_interview(self):
        w = FakeGitHub()
        apply_all(w, ctx())
        pr = w.prs["foundry-init/widget"]
        self.assertEqual(pr["interview"], 400)
        entry = yaml.safe_load(pr["text"])["products"]["widget"]
        self.assertEqual(entry["repo"], PRODUCT)
        self.assertEqual(entry["project"], {"owner": "acme", "number": 3})
        self.assertEqual(entry["write_scope_extra"], {"developer": ["*"]})
        self.assertIn("foundry-program", yaml.safe_load(pr["text"])["products"])
        self.assertIn("#", pr["text"])  # the registry's comments survive (appended, not re-dumped)

    def test_after_merge_a_rerun_dispatches_the_interview_once(self):
        w = FakeGitHub()
        apply_all(w, ctx())
        w.merge_registry_pr(KEY)
        reg = w.registry(CP)["products"][KEY]
        reg["bootstrapped"] = True  # the floor verified (the fake has no bootstrap API)
        w.files[CP]["policies/products.yaml"] = yaml.safe_dump(w.registry(CP) | {
            "products": {**w.registry(CP)["products"], KEY: reg}})
        steps = apply_all(w, ctx())
        self.assertEqual(w.dispatches, [400])
        self.assertIn("status:ready", w.issues[400]["labels"])
        self.assertEqual(next(s for s in steps if s.title == "first dispatch").status, "ok")
        apply_all(w, ctx())
        self.assertEqual(w.dispatches, [400])

    def test_missing_app_is_manual_without_create_app(self):
        w = FakeGitHub()
        del w.variables[CP][F.APP_VAR]
        step = next(s for s in F.plan(w, ctx()) if s.title == "Foundry GitHub App")
        self.assertEqual(step.status, "manual")
        c = ctx()
        c.create_app = True
        step = next(s for s in F.plan(w, c) if s.title == "Foundry GitHub App")
        self.assertEqual(step.status, "todo")

    def test_missing_llm_secret_is_reported(self):
        w = FakeGitHub()
        w.secrets[CP] = {F.APP_SECRET}
        step = next(s for s in F.plan(w, ctx()) if s.title == "LLM credential")
        self.assertEqual(step.status, "manual")
        self.assertIn("gh secret set", step.detail)


    def test_an_already_registered_product_is_dispatched_in_the_same_run(self):
        w = FakeGitHub()
        w.files[CP]["policies/products.yaml"] = REGISTRY + (
            "  widget:\n    repo: acme/widget\n    project: {owner: acme, number: 7}\n"
            "    environments:\n      - {name: prod, human_reviewer_required: true}\n    bootstrapped: true\n")
        steps = apply_all(w, ctx())
        self.assertEqual(w.dispatches, [400])
        self.assertEqual(todo(steps), [])
        self.assertNotIn(("pr", CP, KEY), w.writes)


class TestPieces(unittest.TestCase):
    def test_dependabot_adds_detected_ecosystems_once(self):
        text = F.dependabot_config({"package.json", "requirements.txt", "pyproject.toml"})
        cfg = yaml.safe_load(text)
        self.assertEqual([u["package-ecosystem"] for u in cfg["updates"]], ["github-actions", "npm", "pip"])

    def test_ci_and_scope_workflows_parse(self):
        self.assertEqual(yaml.safe_load(F.CI_WORKFLOW)["jobs"]["test"]["name"], "test")
        self.assertEqual(yaml.safe_load(F.SCOPE_WORKFLOW.read_text())["jobs"]["scope"]["name"], "scope")

    def test_readiness_names_the_missing_build(self):
        w = FakeGitHub()
        steps = apply_all(w, ctx())
        score = F.readiness(w, ctx(), steps)
        build = score[-1]
        self.assertFalse(build[1])
        self.assertIn("no code yet", build[2])
        w.files[PRODUCT]["package.json"] = "{}"
        w.files[PRODUCT]["tests/a.test.js"] = ""
        self.assertTrue(F.readiness(w, ctx(), steps)[-1][1])

    def test_main_prints_plan_and_applies_nothing_with_plan_flag(self):
        w = FakeGitHub()
        out = io.StringIO()
        with redirect_stdout(out):
            rc = F.main([PRODUCT, "--control-plane", CP, "--plan"], world=w)
        self.assertEqual(rc, 0)
        self.assertEqual(w.writes, [])
        self.assertIn("change(s) planned", out.getvalue())
        self.assertIn("Readiness", out.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=1)
