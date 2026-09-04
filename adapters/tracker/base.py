"""The tracker seam (P3-4 / REQ-004).

This is not a general tracker API. Every method here exists because one of
`scripts/sync-project.py`, `scripts/assign.py` or `.github/workflows/dispatch.yml`
makes that exact call today. See the PR for the call-site list. Adding a
method with no caller is scope creep on this interface, not "completeness".

Two implementations satisfy this contract: `adapters/tracker/github/` (the
existing behaviour, moved behind the seam) and `adapters/tracker/jira/` (new,
unverified against a live Jira — see that package's docstring). Both are
exercised by the single shared suite in `adapters/tracker/tests/contract.py`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Issue:
    number: int
    id: str  # opaque content id — GitHub's node id; a Jira issue key works too
    title: str
    body: str
    state: str  # "OPEN" or "CLOSED"
    labels: tuple[str, ...] = ()
    url: str = ""


@dataclass(frozen=True)
class Comment:
    body: str


@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str
    head_ref: str
    state: str  # "OPEN", "CLOSED", "MERGED"


@dataclass(frozen=True)
class BoardRef:
    """Which board to talk to. `owner`/`number` mirror sync-project.py's
    `--owner`/`--project` flags; a Jira implementation is free to read only
    one of the two (e.g. `number` as a board id, `owner` ignored)."""
    owner: str
    number: int


@dataclass(frozen=True)
class BoardItem:
    issue_number: int
    field_values: dict = field(default_factory=dict)


class Tracker(ABC):
    """The operations sync-project.py, assign.py and dispatch.yml call.

    Every abstract method below maps to one or more `gh` invocations in
    those three files today. Nothing here is speculative.
    """

    # --- issues -----------------------------------------------------------

    @abstractmethod
    def list_issues(self, *, state: str = "all", limit: int = 200) -> list[Issue]:
        """`gh issue list --state <state> --limit <limit> --json ...`
        (sync-project.py: state=all; assign.py: state=open)."""

    @abstractmethod
    def get_issue(self, number: int) -> Issue:
        """`gh issue view <number> --json ...` (dispatch.yml calls this
        three times for different field subsets — number/state/title/labels
        for the guard, title, body, and labels separately elsewhere; one
        Issue with everything populated covers all three)."""

    @abstractmethod
    def comment(self, number: int, body: str) -> None:
        """`gh issue comment <number> --body-file ...` (dispatch.yml, three
        call sites: session start, session end, retry-ceiling escalation)."""

    @abstractmethod
    def edit_labels(self, number: int, *, add: tuple[str, ...] = (),
                     remove: tuple[str, ...] = ()) -> None:
        """`gh issue edit <number> --add-label X --remove-label Y`
        (dispatch.yml: session start, the failure/success label rollback)."""

    @abstractmethod
    def list_comments(self, number: int) -> list[Comment]:
        """`gh api --paginate repos/.../issues/<number>/comments`
        (dispatch.yml, counting prior `foundry:dispatch result=failure`
        sessions against the retry ceiling)."""

    # --- pull requests ------------------------------------------------------

    @abstractmethod
    def list_pull_requests(self, *, state: str = "open", limit: int = 100) -> list[PullRequest]:
        """`gh pr list --state <state> --limit <limit> --json ...`
        (assign.py: state=open, to find issues with a PR already in flight;
        dispatch.yml: state=all, to find this issue's PR at session end)."""

    # --- dispatch -----------------------------------------------------------

    @abstractmethod
    def trigger_workflow(self, workflow: str, inputs: dict) -> None:
        """`gh workflow run <workflow> -f k=v ...` (assign.py, dispatching a
        role session for an eligible issue)."""

    # --- project board --------------------------------------------------------

    @abstractmethod
    def board_fields(self, board: BoardRef) -> dict:
        """Field name -> allowed option names (`[]` for a free-text field).
        Backs `load_board`/`field_index` in sync-project.py, which reads a
        GitHub Projects v2 board's field schema over GraphQL."""

    @abstractmethod
    def board_item(self, board: BoardRef, issue_number: int) -> BoardItem | None:
        """The board's current field values for one issue, or None if the
        issue is not on the board. Backs `current_values` in
        sync-project.py."""

    @abstractmethod
    def add_to_board(self, board: BoardRef, issue_number: int) -> None:
        """Put an issue on the board. Backs `add_item`
        (`addProjectV2ItemById`) in sync-project.py."""

    @abstractmethod
    def set_board_field(self, board: BoardRef, issue_number: int, field_name: str,
                         value: str) -> None:
        """Write one field on one board item. Backs `write_field`
        (`updateProjectV2ItemFieldValue`) in sync-project.py. Raises
        `KeyError` if `field_name` or `value` (for a select field) does not
        exist on the board, matching sync-project.py's existing failure
        mode."""
