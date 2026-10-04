# JiraTracker

> 22 nodes

## Key Concepts

- **JiraTracker** (33 connections) — `adapters/tracker/jira/client.py`
- **._request()** (12 connections) — `adapters/tracker/jira/client.py`
- **._key()** (8 connections) — `adapters/tracker/jira/client.py`
- **.board_item()** (7 connections) — `adapters/tracker/jira/client.py`
- **._to_issue()** (7 connections) — `adapters/tracker/jira/client.py`
- **._active_sprint()** (5 connections) — `adapters/tracker/jira/client.py`
- **.add_to_board()** (5 connections) — `adapters/tracker/jira/client.py`
- **.get_issue()** (5 connections) — `adapters/tracker/jira/client.py`
- **.list_comments()** (5 connections) — `adapters/tracker/jira/client.py`
- **.list_issues()** (5 connections) — `adapters/tracker/jira/client.py`
- **.comment()** (4 connections) — `adapters/tracker/jira/client.py`
- **.list_pull_requests()** (4 connections) — `adapters/tracker/jira/client.py`
- **.set_board_field()** (4 connections) — `adapters/tracker/jira/client.py`
- **.board_fields()** (3 connections) — `adapters/tracker/jira/client.py`
- **.edit_labels()** (3 connections) — `adapters/tracker/jira/client.py`
- **.__init__()** (3 connections) — `adapters/tracker/jira/client.py`
- **._number()** (2 connections) — `adapters/tracker/jira/client.py`
- **.trigger_workflow()** (1 connections) — `adapters/tracker/jira/client.py`
- **Transport** (1 connections)
- **`Issue.state` is OPEN/CLOSED, the same binary every caller in this codebase…** (1 connections) — `adapters/tracker/jira/client.py`
- **A plain Jira project has no separate "is this issue on the board" flag the way…** (1 connections) — `adapters/tracker/jira/client.py`
- **`field_map` maps the logical board field names sync-project.py writes (`QA-…** (1 connections) — `adapters/tracker/jira/client.py`

## Relationships

- [BoardRef](BoardRef.md) (9 shared connections)
- [json](json.md) (8 shared connections)
- [test_jira.py](test_jira.py.md) (7 shared connections)
- [GitHubTracker](GitHubTracker.md) (4 shared connections)
- [sync-project.py](sync-project.py.md) (2 shared connections)

## Source Files

- `adapters/tracker/jira/client.py`

## Audit Trail

- EXTRACTED: 70 (93%)
- INFERRED: 5 (7%)
- AMBIGUOUS: 0 (0%)

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*