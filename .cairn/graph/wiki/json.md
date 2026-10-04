# json

> 35 nodes

## Key Concepts

- **json** (30 connections)
- **Tracker** (26 connections) — `adapters/tracker/base.py`
- **jira/client.py** (19 connections) — `adapters/tracker/jira/client.py`
- **re** (19 connections)
- **tracker/base.py** (16 connections) — `adapters/tracker/base.py`
- **github/client.py** (14 connections) — `adapters/tracker/github/client.py`
- **test_github.py** (12 connections) — `adapters/tracker/tests/test_github.py`
- **BoardItem** (9 connections) — `adapters/tracker/base.py`
- **Comment** (9 connections) — `adapters/tracker/base.py`
- **PullRequest** (9 connections) — `adapters/tracker/base.py`
- **tracker/__init__.py** (7 connections) — `adapters/tracker/__init__.py`
- **tracker/tests/contract.py** (7 connections) — `adapters/tracker/tests/contract.py`
- **typing** (6 connections)
- **.board_item()** (4 connections) — `adapters/tracker/base.py`
- **github/__init__.py** (4 connections) — `adapters/tracker/github/__init__.py`
- **.list_comments()** (3 connections) — `adapters/tracker/base.py`
- **.list_pull_requests()** (3 connections) — `adapters/tracker/base.py`
- **.comment()** (2 connections) — `adapters/tracker/base.py`
- **.edit_labels()** (2 connections) — `adapters/tracker/base.py`
- **.trigger_workflow()** (2 connections) — `adapters/tracker/base.py`
- **ABC** (2 connections)
- **_default_run()** (1 connections) — `adapters/tracker/github/client.py`
- **The tracker seam (P3-4 / REQ-004). This is not a general tracker API. Every…** (1 connections) — `adapters/tracker/base.py`
- **`gh pr list --state <state> --limit <limit> --json ...` (assign.py: state=open,…** (1 connections) — `adapters/tracker/base.py`
- **`gh workflow run <workflow> -f k=v ...` (assign.py, dispatching a role session…** (1 connections) — `adapters/tracker/base.py`
- *... and 10 more nodes in this community*

## Relationships

- [GitHubTracker](GitHubTracker.md) (16 shared connections)
- [BoardRef](BoardRef.md) (11 shared connections)
- [JiraTracker](JiraTracker.md) (8 shared connections)
- [sync-project.py](sync-project.py.md) (8 shared connections)
- [test_jira.py](test_jira.py.md) (8 shared connections)
- [check-story-scope.py](check-story-scope.py.md) (5 shared connections)
- [TrackerContractTests](TrackerContractTests.md) (4 shared connections)
- [bootstrap-product.py](bootstrap-product.py.md) (3 shared connections)
- [pathlib](pathlib.md) (3 shared connections)
- [subprocess](subprocess.md) (2 shared connections)
- [adr.py](adr.py.md) (2 shared connections)
- [dashboards/build.py](dashboards-build.py.md) (2 shared connections)

## Source Files

- `adapters/tracker/__init__.py`
- `adapters/tracker/base.py`
- `adapters/tracker/github/__init__.py`
- `adapters/tracker/github/client.py`
- `adapters/tracker/jira/client.py`
- `adapters/tracker/tests/contract.py`
- `adapters/tracker/tests/test_github.py`

## Audit Trail

- EXTRACTED: 152 (94%)
- INFERRED: 10 (6%)
- AMBIGUOUS: 0 (0%)

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*