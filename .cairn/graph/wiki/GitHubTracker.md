# GitHubTracker

> 28 nodes

## Key Concepts

- **GitHubTracker** (33 connections) — `adapters/tracker/github/client.py`
- **Issue** (16 connections) — `adapters/tracker/base.py`
- **._load_board()** (8 connections) — `adapters/tracker/github/client.py`
- **._gh_json()** (7 connections) — `adapters/tracker/github/client.py`
- **.add_to_board()** (5 connections) — `adapters/tracker/github/client.py`
- **.board_item()** (5 connections) — `adapters/tracker/github/client.py`
- **.get_issue()** (5 connections) — `adapters/tracker/github/client.py`
- **._gh()** (5 connections) — `adapters/tracker/github/client.py`
- **._graphql()** (5 connections) — `adapters/tracker/github/client.py`
- **.set_board_field()** (5 connections) — `adapters/tracker/github/client.py`
- **.board_fields()** (4 connections) — `adapters/tracker/github/client.py`
- **.list_issues()** (4 connections) — `adapters/tracker/github/client.py`
- **._to_issue()** (4 connections) — `adapters/tracker/github/client.py`
- **.get_issue()** (3 connections) — `adapters/tracker/base.py`
- **.list_issues()** (3 connections) — `adapters/tracker/base.py`
- **._field_index()** (3 connections) — `adapters/tracker/github/client.py`
- **.__init__()** (3 connections) — `adapters/tracker/github/client.py`
- **.list_comments()** (3 connections) — `adapters/tracker/github/client.py`
- **.list_pull_requests()** (3 connections) — `adapters/tracker/github/client.py`
- **.comment()** (2 connections) — `adapters/tracker/github/client.py`
- **._current_values()** (2 connections) — `adapters/tracker/github/client.py`
- **.edit_labels()** (2 connections) — `adapters/tracker/github/client.py`
- **.trigger_workflow()** (2 connections) — `adapters/tracker/github/client.py`
- **GhRunner** (1 connections)
- **`gh issue list --state <state> --limit <limit> --json ...` (sync-project.py:…** (1 connections) — `adapters/tracker/base.py`
- *... and 3 more nodes in this community*

## Relationships

- [json](json.md) (16 shared connections)
- [BoardRef](BoardRef.md) (8 shared connections)
- [JiraTracker](JiraTracker.md) (4 shared connections)
- [sync-project.py](sync-project.py.md) (4 shared connections)
- [TestGitHubTrackerContract](TestGitHubTrackerContract.md) (1 shared connections)

## Source Files

- `adapters/tracker/base.py`
- `adapters/tracker/github/client.py`

## Audit Trail

- EXTRACTED: 78 (92%)
- INFERRED: 7 (8%)
- AMBIGUOUS: 0 (0%)

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*