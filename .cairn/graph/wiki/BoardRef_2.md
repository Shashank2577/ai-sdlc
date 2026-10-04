# BoardRef

> God node · 39 connections · `adapters/tracker/base.py`

**Community:** [BoardRef](BoardRef.md)

## Connections by Relation

### calls
- .board_ref() `EXTRACTED`
- main() `EXTRACTED`
- .test_dry_run_against_jira_stub_changes_nothing() `EXTRACTED`
- .test_full_sync_against_github_stub() `EXTRACTED`
- .test_full_sync_against_jira_stub() `EXTRACTED`
- .board_ref() `EXTRACTED`

### contains
- tracker/base.py `EXTRACTED`

### imports
- [sync-project.py](sync-project.py.md) `EXTRACTED`
- test_sync_project.py `EXTRACTED`
- jira/client.py `EXTRACTED`
- [test_jira.py](test_jira.py.md) `EXTRACTED`
- github/client.py `EXTRACTED`
- test_github.py `EXTRACTED`
- tracker/__init__.py `EXTRACTED`
- tracker/tests/contract.py `EXTRACTED`

### rationale_for
- Which board to talk to. `owner`/`number` mirror sync-project.py's… `EXTRACTED`

### references
- .board_ref() `EXTRACTED`
- ._load_board() `EXTRACTED`
- .board_item() `EXTRACTED`
- .add_to_board() `EXTRACTED`
- .board_item() `EXTRACTED`
- .set_board_field() `EXTRACTED`
- ._active_sprint() `EXTRACTED`
- .add_to_board() `EXTRACTED`
- .board_item() `EXTRACTED`
- .board_fields() `EXTRACTED`
- .set_board_field() `EXTRACTED`
- .add_to_board() `EXTRACTED`
- .board_fields() `EXTRACTED`
- .set_board_field() `EXTRACTED`
- .board_fields() `EXTRACTED`

### uses
- [GitHubTracker](GitHubTracker.md) `INFERRED`
- [JiraTracker](JiraTracker.md) `INFERRED`
- [TrackerContractTests](TrackerContractTests.md) `INFERRED`
- run_sync() `INFERRED`
- [TestGitHubTrackerContract](TestGitHubTrackerContract.md) `INFERRED`
- TestRunSyncAgainstTrackerStubs `INFERRED`
- TestJiraTrackerContract `INFERRED`
- apply_fields() `INFERRED`

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*