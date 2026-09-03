"""Runs the shared contract suite against JiraTracker, against a stubbed
transport. There is no live Jira behind this — see the module docstring in
`adapters/tracker/jira/client.py` and the PR for #123. This only proves the
adapter's internal request/response handling is self-consistent, not that
the request shapes match a real Jira Cloud instance.
"""

from __future__ import annotations

import re
import unittest

from adapters.tracker.base import BoardRef
from adapters.tracker.jira import JiraTracker
from adapters.tracker.jira.client import _Response, _adf_text
from adapters.tracker.tests.contract import TrackerContractTests


class FakeJira:
    STATUS_CATEGORY = {"Ready": "new", "In Progress": "indeterminate", "Done": "done"}

    def __init__(self):
        def status(name):
            return {"name": name, "statusCategory": {"key": self.STATUS_CATEGORY[name]}}

        self.issues = {
            1: {"id": "10001", "key": "FDY-1", "fields": {
                "summary": "Wire the seam", "description": "hello",
                "status": status("Ready"), "labels": ["status:ready"],
                "customfield_10052": None,
            }},
            2: {"id": "10002", "key": "FDY-2", "fields": {
                "summary": "Old work", "description": "",
                "status": status("Done"), "labels": [],
                "customfield_10052": None,
            }},
        }
        self.comments = {1: [], 2: []}
        self.dev_status = {
            "10001": [{"url": "https://github.com/o/r/pull/10", "status": "OPEN",
                       "source": {"branch": "story/FDY-1-tracker"}}],
            "10002": [{"url": "https://github.com/o/r/pull/11", "status": "MERGED",
                       "source": {"branch": "story/FDY-9-other"}}],
        }
        self.statuses = ["Ready", "In Progress", "Done"]
        self.transitions = {"Ready": [("31", "In Progress"), ("41", "Done")],
                             "In Progress": [("21", "Ready"), ("41", "Done")],
                             "Done": [("11", "Ready"), ("21", "In Progress")]}
        self.field_options = ["REQ-000"]  # unused: Requirement-ID is free text
        self.sprints = {"5": [{"id": "500"}]}
        self.sprint_issues: dict[str, list[str]] = {"500": []}
        self.triggered: list = []

    def _done(self, status):
        return 200 if status is not None else 204

    def __call__(self, method, url, *, params=None, json=None) -> _Response:
        path = re.sub(r"^https?://[^/]+", "", url)

        m = re.match(r"^/rest/api/3/issue/(FDY-\d+)/comment$", path)
        if m and method == "POST":
            number = int(m.group(1).split("-")[1])
            self.comments[number].append({"body": json["body"]})
            return _Response(201, {"id": "c1"})
        if m and method == "GET":
            number = int(m.group(1).split("-")[1])
            return _Response(200, {"comments": self.comments[number]})

        m = re.match(r"^/rest/api/3/issue/(FDY-\d+)/transitions$", path)
        if m and method == "GET":
            number = int(m.group(1).split("-")[1])
            current = self.issues[number]["fields"]["status"]["name"]
            opts = self.transitions[current]
            return _Response(200, {"transitions": [{"id": i, "to": {"name": n}} for i, n in opts]})
        if m and method == "POST":
            number = int(m.group(1).split("-")[1])
            current = self.issues[number]["fields"]["status"]["name"]
            tid = json["transition"]["id"]
            target = next(n for i, n in self.transitions[current] if i == tid)
            self.issues[number]["fields"]["status"] = {
                "name": target, "statusCategory": {"key": self.STATUS_CATEGORY[target]}}
            return _Response(204, None)

        m = re.match(r"^/rest/api/3/issue/(FDY-\d+)$", path)
        if m and method == "GET":
            return _Response(200, self.issues[int(m.group(1).split("-")[1])])
        if m and method == "PUT":
            number = int(m.group(1).split("-")[1])
            for k, v in json.get("fields", {}).items():
                self.issues[number]["fields"][k] = v
            if "update" in json:
                labels = set(self.issues[number]["fields"]["labels"])
                for change in json["update"].get("labels", []):
                    if "add" in change:
                        labels.add(change["add"])
                    if "remove" in change:
                        labels.discard(change["remove"])
                self.issues[number]["fields"]["labels"] = sorted(labels)
            return _Response(200, None)

        if path == "/rest/api/3/search" and method == "GET":
            want_open = "statusCategory != Done" in params["jql"]
            out = [i for n, i in self.issues.items()
                   if not want_open or i["fields"]["status"]["name"] != "Done"]
            return _Response(200, {"issues": out})

        if path == "/rest/dev-status/1.0/issue/detail" and method == "GET":
            prs = self.dev_status.get(params["issueId"], [])
            return _Response(200, {"detail": [{"pullRequests": prs}]})

        if path == "/rest/api/3/project/FDY/statuses" and method == "GET":
            return _Response(200, [{"statuses": [{"name": s} for s in self.statuses]}])

        if path == "/rest/api/3/field/customfield_10052/context" and method == "GET":
            return _Response(200, {"values": []})

        m = re.match(r"^/rest/agile/1.0/board/(\d+)/sprint$", path)
        if m and method == "GET":
            return _Response(200, {"values": self.sprints.get(m.group(1), [])})

        m = re.match(r"^/rest/agile/1.0/sprint/(\d+)/issue$", path)
        if m and method == "POST":
            self.sprint_issues.setdefault(m.group(1), []).extend(json["issues"])
            return _Response(204, None)
        if m and method == "GET":
            wanted_key = params["jql"].split("=")[-1].strip()
            members = self.sprint_issues.get(m.group(1), [])
            issues = [self.issues[int(k.split("-")[1])] for k in members if k == wanted_key]
            return _Response(200, {"issues": issues})

        if path == "/webhook/dispatch" and method == "POST":
            self.triggered.append((json["workflow"], {k: v for k, v in json.items()
                                                        if k != "workflow"}))
            return _Response(200, None)

        raise AssertionError(f"FakeJira got an unexpected request: {method} {path} {params!r}")


class TestJiraTrackerContract(TrackerContractTests, unittest.TestCase):
    def make_tracker(self):
        self.fake = FakeJira()
        return JiraTracker(
            base_url="https://example.atlassian.net", email="bot@example.com",
            api_token="unused-in-tests", project_key="FDY",
            field_map={"Requirement-ID": {"id": "customfield_10052", "type": "text"}},
            webhook_urls={"dispatch.yml": "https://example.atlassian.net/webhook/dispatch"},
            transport=self.fake,
        )

    def board_ref(self):
        return BoardRef(owner="FDY", number=5)

    def triggered(self):
        return self.fake.triggered

    def test_adf_helpers_round_trip_plain_text(self):
        # Not part of the shared contract — this is Jira-specific plumbing
        # (issue bodies and comments must be sent as ADF) with no GitHub
        # equivalent to test it against.
        from adapters.tracker.jira.client import _plain_text
        self.assertEqual(_plain_text(_adf_text("hello world")), "hello world")


if __name__ == "__main__":
    unittest.main(verbosity=2)
