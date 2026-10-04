# JiraTracker

> God node · 33 connections · `adapters/tracker/jira/client.py`

**Community:** [JiraTracker](JiraTracker.md)

## Connections by Relation

### calls
- make_tracker() `EXTRACTED`
- .test_dry_run_against_jira_stub_changes_nothing() `EXTRACTED`
- .test_full_sync_against_jira_stub() `EXTRACTED`
- .make_tracker() `EXTRACTED`

### contains
- jira/client.py `EXTRACTED`

### imports
- [sync-project.py](sync-project.py.md) `EXTRACTED`
- test_sync_project.py `EXTRACTED`
- [test_jira.py](test_jira.py.md) `EXTRACTED`
- jira/__init__.py `EXTRACTED`

### inherits
- [Tracker](Tracker.md) `EXTRACTED`

### method
- ._request() `EXTRACTED`
- ._key() `EXTRACTED`
- ._to_issue() `EXTRACTED`
- .board_item() `EXTRACTED`
- .list_issues() `EXTRACTED`
- .get_issue() `EXTRACTED`
- .list_comments() `EXTRACTED`
- ._active_sprint() `EXTRACTED`
- .add_to_board() `EXTRACTED`
- .comment() `EXTRACTED`
- .list_pull_requests() `EXTRACTED`
- .set_board_field() `EXTRACTED`
- .edit_labels() `EXTRACTED`
- .board_fields() `EXTRACTED`
- .__init__() `EXTRACTED`
- ._default_transport() `EXTRACTED`
- ._number() `EXTRACTED`
- .trigger_workflow() `EXTRACTED`

### uses
- [BoardRef](BoardRef.md) `INFERRED`
- Issue `INFERRED`
- Comment `INFERRED`
- PullRequest `INFERRED`
- BoardItem `INFERRED`

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*