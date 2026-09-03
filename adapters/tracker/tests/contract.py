"""The one contract, run against both trackers (P3-4 acceptance criteria).

`TrackerContractTests` is a plain mixin, not a `unittest.TestCase` — that is
deliberate, so importing this module never collects it as a runnable test
on its own; only `test_github.py` and `test_jira.py`, which mix it with
`unittest.TestCase`, do.

Every concrete subclass must seed the exact same fixture before each test:

- issue #1: OPEN, has label "status:ready"
- issue #2: CLOSED
- a pull request on a branch matching `story/FDY-1-*`, state OPEN
- a pull request on a branch matching `story/FDY-9-*`, state MERGED
- a board (`board_ref()`) with a "Status" select field (>= 2 options) and a
  "Requirement-ID" free-text field, and issue #1 not yet on the board

and must implement `make_tracker()` and `board_ref()`. `triggered()` exposes
whatever `trigger_workflow` calls the fake backend recorded, as a list of
`(workflow, inputs)` tuples — used only by the one test that checks dispatch.
"""

from __future__ import annotations

from adapters.tracker.base import Tracker, BoardRef


class TrackerContractTests:
    def make_tracker(self) -> Tracker:
        raise NotImplementedError

    def board_ref(self) -> BoardRef:
        raise NotImplementedError

    def triggered(self) -> list:
        raise NotImplementedError

    def setUp(self):
        super().setUp()
        self.tracker = self.make_tracker()

    # --- issues -----------------------------------------------------------------

    def test_get_issue_returns_the_seeded_fields(self):
        issue = self.tracker.get_issue(1)
        self.assertEqual(issue.number, 1)
        self.assertEqual(issue.state, "OPEN")
        self.assertIn("status:ready", issue.labels)

    def test_list_issues_all_includes_open_and_closed(self):
        numbers = {i.number for i in self.tracker.list_issues(state="all")}
        self.assertEqual({1, 2}, numbers & {1, 2})

    def test_list_issues_open_excludes_closed(self):
        numbers = {i.number for i in self.tracker.list_issues(state="open")}
        self.assertIn(1, numbers)
        self.assertNotIn(2, numbers)

    def test_comment_is_visible_in_list_comments(self):
        self.tracker.comment(1, "contract-probe hello")
        bodies = [c.body for c in self.tracker.list_comments(1)]
        self.assertIn("contract-probe hello", bodies)

    def test_edit_labels_add_and_remove_are_both_applied(self):
        self.tracker.edit_labels(1, add=("status:in-progress",), remove=("status:ready",))
        labels = self.tracker.get_issue(1).labels
        self.assertIn("status:in-progress", labels)
        self.assertNotIn("status:ready", labels)

    # --- pull requests --------------------------------------------------------

    def test_list_pull_requests_open_only_returns_open(self):
        prs = self.tracker.list_pull_requests(state="open")
        self.assertTrue(prs)
        self.assertTrue(all(p.state == "OPEN" for p in prs))
        self.assertTrue(any(p.head_ref.startswith("story/FDY-1-") for p in prs))

    def test_list_pull_requests_all_includes_non_open(self):
        prs = self.tracker.list_pull_requests(state="all")
        states = {p.state for p in prs}
        self.assertIn("OPEN", states)
        self.assertIn("MERGED", states)

    # --- dispatch -----------------------------------------------------------------

    def test_trigger_workflow_is_recorded(self):
        self.tracker.trigger_workflow("dispatch.yml", {"issue": "1", "role": "developer"})
        self.assertIn(("dispatch.yml", {"issue": "1", "role": "developer"}), self.triggered())

    # --- project board ----------------------------------------------------------

    def test_board_item_is_none_before_being_added(self):
        self.assertIsNone(self.tracker.board_item(self.board_ref(), 1))

    def test_add_to_board_then_item_exists(self):
        self.tracker.add_to_board(self.board_ref(), 1)
        item = self.tracker.board_item(self.board_ref(), 1)
        self.assertIsNotNone(item)
        self.assertEqual(item.issue_number, 1)

    def test_board_fields_reports_select_options_and_free_text(self):
        fields = self.tracker.board_fields(self.board_ref())
        self.assertIn("Status", fields)
        self.assertGreaterEqual(len(fields["Status"]), 2)
        self.assertIn("Requirement-ID", fields)
        self.assertEqual(fields["Requirement-ID"], [])

    def test_set_board_field_select_value_is_reflected(self):
        board = self.board_ref()
        self.tracker.add_to_board(board, 1)
        options = self.tracker.board_fields(board)["Status"]
        # Pick anything other than whatever it already is: a Jira workflow
        # has no transition from a status to itself, so re-asserting the
        # current value is not a fair test of "setting it is reflected".
        current = self.tracker.board_item(board, 1).field_values.get("Status")
        target = next(o for o in options if o != current)
        self.tracker.set_board_field(board, 1, "Status", target)
        self.assertEqual(self.tracker.board_item(board, 1).field_values["Status"], target)

    def test_set_board_field_free_text_value_is_reflected(self):
        board = self.board_ref()
        self.tracker.add_to_board(board, 1)
        self.tracker.set_board_field(board, 1, "Requirement-ID", "REQ-004")
        self.assertEqual(
            self.tracker.board_item(board, 1).field_values["Requirement-ID"], "REQ-004")

    def test_set_board_field_unknown_field_raises_keyerror(self):
        board = self.board_ref()
        self.tracker.add_to_board(board, 1)
        with self.assertRaises(KeyError):
            self.tracker.set_board_field(board, 1, "No Such Field", "x")

    def test_set_board_field_unknown_option_raises_keyerror(self):
        board = self.board_ref()
        self.tracker.add_to_board(board, 1)
        with self.assertRaises(KeyError):
            self.tracker.set_board_field(board, 1, "Status", "Not A Real Status")
