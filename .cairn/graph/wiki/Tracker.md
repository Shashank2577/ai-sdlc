# Tracker

> God node · 26 connections · `adapters/tracker/base.py`

**Community:** [json](json.md)

## Connections by Relation

### contains
- tracker/base.py `EXTRACTED`

### imports
- [sync-project.py](sync-project.py.md) `EXTRACTED`
- jira/client.py `EXTRACTED`
- github/client.py `EXTRACTED`
- tracker/__init__.py `EXTRACTED`
- tracker/tests/contract.py `EXTRACTED`

### inherits
- [GitHubTracker](GitHubTracker.md) `EXTRACTED`
- [JiraTracker](JiraTracker.md) `EXTRACTED`
- ABC `EXTRACTED`

### method
- .board_item() `EXTRACTED`
- .list_pull_requests() `EXTRACTED`
- .board_fields() `EXTRACTED`
- .add_to_board() `EXTRACTED`
- .set_board_field() `EXTRACTED`
- .list_issues() `EXTRACTED`
- .get_issue() `EXTRACTED`
- .list_comments() `EXTRACTED`
- .trigger_workflow() `EXTRACTED`
- .comment() `EXTRACTED`
- .edit_labels() `EXTRACTED`

### rationale_for
- The operations sync-project.py, assign.py and dispatch.yml call. Every abstract… `EXTRACTED`

### references
- .make_tracker() `EXTRACTED`

### uses
- [TrackerContractTests](TrackerContractTests.md) `INFERRED`
- run_sync() `INFERRED`
- make_tracker() `INFERRED`
- apply_fields() `INFERRED`

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*