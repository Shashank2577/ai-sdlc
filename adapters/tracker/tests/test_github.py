"""Runs the shared contract suite against GitHubTracker.

`FakeGh` stands in for the `gh` CLI: it parses the exact argv
`GitHubTracker` builds (the same argv `sync-project.py`/`assign.py`/
`dispatch.yml` built before this seam existed) and answers from an
in-memory GitHub Projects v2 fixture. No network, no real repository.
"""

from __future__ import annotations

import json
import re
import unittest

from adapters.tracker.base import BoardRef
from adapters.tracker.github import GitHubTracker
from adapters.tracker.tests.contract import TrackerContractTests

_PR_STATE_FOR_ARG = {"open": "OPEN", "closed": "CLOSED", "merged": "MERGED"}


class FakeGh:
    def __init__(self):
        self.issues = {
            1: {"number": 1, "id": "I_1", "title": "Wire the seam", "body": "hello",
                "state": "OPEN", "labels": ["status:ready"],
                "url": "https://github.com/o/r/issues/1"},
            2: {"number": 2, "id": "I_2", "title": "Old work", "body": "",
                "state": "CLOSED", "labels": [], "url": "https://github.com/o/r/issues/2"},
        }
        self.comments = {1: [], 2: []}
        self.prs = [
            {"number": 10, "url": "https://github.com/o/r/pull/10",
             "headRefName": "story/FDY-1-tracker", "state": "OPEN"},
            {"number": 11, "url": "https://github.com/o/r/pull/11",
             "headRefName": "story/FDY-9-other", "state": "MERGED"},
        ]
        self.triggered: list = []
        self.project_id = "PVT_1"
        self.fields = [
            {"id": "F_STATUS", "name": "Status",
             "options": [{"id": "O_TODO", "name": "Todo"},
                         {"id": "O_PROG", "name": "In Progress"},
                         {"id": "O_DONE", "name": "Done"}]},
            {"id": "F_REQ", "name": "Requirement-ID", "options": []},
        ]
        self.items: dict[int, dict] = {}  # issue number -> item state
        self._next_item = 1
        # Issue numbers whose items the board *query* does not list yet, even
        # though the add mutation returned their id and the field mutation
        # accepts it. GitHub Projects v2 reads are eventually consistent:
        # PR #252's own sync run added #225, re-queried the board, and got a
        # page without it. Set by a test; empty means a consistent board.
        self.lagging: set[int] = set()

    # --- helpers ---------------------------------------------------------------

    def _kv_args(self, args: list[str]) -> dict:
        out = {}
        it = iter(args)
        for a in it:
            if a in ("-f", "-F"):
                k, _, v = next(it).partition("=")
                out[k] = v
        return out

    def _board_json(self) -> dict:
        items = []
        for number, item in self.items.items():
            if number in self.lagging:
                continue
            field_nodes = []
            for name, value in item["fields"].items():
                spec = next(f for f in self.fields if f["name"] == name)
                if spec["options"]:
                    field_nodes.append({"name": value, "field": {"name": name}})
                else:
                    field_nodes.append({"text": value, "field": {"name": name}})
            items.append({
                "id": item["id"],
                "content": {"number": number, "state": self.issues[number]["state"]},
                "fieldValues": {"nodes": field_nodes},
            })
        return {"data": {"user": {"projectV2": {
            "id": self.project_id,
            "fields": {"nodes": [{"id": f["id"], "name": f["name"], "options": f["options"]}
                                  for f in self.fields]},
            "items": {"nodes": items},
        }}}}

    # --- the entry point GitHubTracker calls ------------------------------------

    def __call__(self, args: list[str]) -> str:
        if args[:2] == ["issue", "list"]:
            state = args[args.index("--state") + 1]
            out = [i for i in self.issues.values() if state == "all" or i["state"] == "OPEN"]
            return json.dumps([{**i, "labels": [{"name": n} for n in i["labels"]]} for i in out])

        if args[:2] == ["issue", "view"]:
            number = int(args[2])
            i = self.issues[number]
            return json.dumps({**i, "labels": [{"name": n} for n in i["labels"]]})

        if args[:2] == ["issue", "comment"]:
            number = int(args[2])
            body = args[args.index("--body") + 1]
            self.comments[number].append({"body": body})
            return ""

        if args[:2] == ["issue", "edit"]:
            number = int(args[2])
            labels = set(self.issues[number]["labels"])
            rest = iter(args[3:])
            for a in rest:
                if a == "--add-label":
                    labels.add(next(rest))
                elif a == "--remove-label":
                    labels.discard(next(rest))
            self.issues[number]["labels"] = sorted(labels)
            return ""

        if args[:2] == ["api", "--paginate"]:
            number = int(re.search(r"issues/(\d+)/comments", args[2]).group(1))
            return json.dumps(self.comments[number])

        if args[:2] == ["pr", "list"]:
            state = args[args.index("--state") + 1]
            wanted = _PR_STATE_FOR_ARG.get(state)
            out = [p for p in self.prs if wanted is None or p["state"] == wanted]
            return json.dumps(out)

        if args[:2] == ["workflow", "run"]:
            workflow = args[2]
            inputs = self._kv_args(args[3:])
            self.triggered.append((workflow, inputs))
            return ""

        if args[:2] == ["api", "graphql"]:
            query = self._kv_args(args)["query"]
            if "updateProjectV2ItemFieldValue" in query:
                item_id = re.search(r'itemId:"([^"]+)"', query).group(1)
                field_id = re.search(r'fieldId:"([^"]+)"', query).group(1)
                field = next(f for f in self.fields if f["id"] == field_id)
                number = next(n for n, it in self.items.items() if it["id"] == item_id)
                opt_m = re.search(r'singleSelectOptionId:\s*"([^"]+)"', query)
                if opt_m:
                    option = next(o for o in field["options"] if o["id"] == opt_m.group(1))
                    self.items[number]["fields"][field["name"]] = option["name"]
                else:
                    text = re.search(r'text:\s*"([^"]*)"', query).group(1)
                    self.items[number]["fields"][field["name"]] = text
                return json.dumps({"data": {"updateProjectV2ItemFieldValue":
                                             {"projectV2Item": {"id": item_id}}}})
            if "addProjectV2ItemById" in query:
                kv = self._kv_args(args)
                number = next(n for n, i in self.issues.items() if i["id"] == kv["content"])
                item_id = f"ITEM_{self._next_item}"
                self._next_item += 1
                self.items[number] = {"id": item_id, "fields": {}}
                return json.dumps({"data": {"addProjectV2ItemById": {"item": {"id": item_id}}}})
            # the plain board-load query
            return json.dumps(self._board_json())

        raise AssertionError(f"FakeGh got an unexpected gh invocation: {args!r}")


class TestGitHubTrackerContract(TrackerContractTests, unittest.TestCase):
    def make_tracker(self):
        self.fake = FakeGh()
        return GitHubTracker(run=self.fake)

    def board_ref(self):
        return BoardRef(owner="o", number=1)

    def triggered(self):
        return self.fake.triggered

    def test_set_board_field_right_after_add_survives_a_lagging_board_query(self):
        """The failure PR #252's own sync run hit after the pagination fix:
        `add_to_board(#225)` succeeded, `set_board_field` re-queried the
        board, the just-added item was not on the page yet, and the sync
        exited 1 with "issue #225 is not on this board". The add mutation
        already returned the item's id; a field write straight after an add
        must use it rather than depend on the read catching up."""
        board = self.board_ref()
        self.fake.lagging.add(1)
        self.tracker.add_to_board(board, 1)
        self.assertIsNone(self.tracker.board_item(board, 1),
                          "fixture must model the lag: the query does not list #1 yet")
        self.tracker.set_board_field(board, 1, "Status", "Todo")
        self.fake.lagging.discard(1)
        self.assertEqual(self.tracker.board_item(board, 1).field_values["Status"], "Todo")

    def test_lookup_of_an_item_never_added_still_raises(self):
        """The remembered id is a fallback for an add this adapter made, not
        a way to invent items: an issue that was never added still fails."""
        with self.assertRaises(KeyError):
            self.tracker.set_board_field(self.board_ref(), 2, "Status", "Todo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
