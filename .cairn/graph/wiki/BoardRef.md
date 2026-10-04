# BoardRef

> 27 nodes

## Key Concepts

- **BoardRef** (39 connections) — `adapters/tracker/base.py`
- **test_sync_project.py** (20 connections) — `scripts/test_sync_project.py`
- **FakeGh** (9 connections) — `adapters/tracker/tests/test_github.py`
- **FakeJira** (9 connections) — `adapters/tracker/tests/test_jira.py`
- **TestRunSyncAgainstTrackerStubs** (8 connections) — `scripts/test_sync_project.py`
- **.test_dry_run_against_jira_stub_changes_nothing()** (4 connections) — `scripts/test_sync_project.py`
- **.test_full_sync_against_github_stub()** (4 connections) — `scripts/test_sync_project.py`
- **.test_full_sync_against_jira_stub()** (4 connections) — `scripts/test_sync_project.py`
- **TestAgainstThisRepo** (3 connections) — `scripts/test_sync_project.py`
- **.add_to_board()** (3 connections) — `adapters/tracker/base.py`
- **.board_fields()** (3 connections) — `adapters/tracker/base.py`
- **.set_board_field()** (3 connections) — `adapters/tracker/base.py`
- **.__call__()** (3 connections) — `adapters/tracker/tests/test_github.py`
- **._board_json()** (2 connections) — `adapters/tracker/tests/test_github.py`
- **._kv_args()** (2 connections) — `adapters/tracker/tests/test_github.py`
- **.__init__()** (2 connections) — `adapters/tracker/tests/test_jira.py`
- **.__init__()** (1 connections) — `adapters/tracker/tests/test_github.py`
- **._done()** (1 connections) — `adapters/tracker/tests/test_jira.py`
- **status()** (1 connections) — `adapters/tracker/tests/test_jira.py`
- **.test_every_role_pack_in_the_repo_has_a_role_label_mapping()** (1 connections) — `scripts/test_sync_project.py`
- **.test_every_status_label_in_conventions_has_a_column()** (1 connections) — `scripts/test_sync_project.py`
- **Field name -> allowed option names (`[]` for a free-text field). Backs…** (1 connections) — `adapters/tracker/base.py`
- **Put an issue on the board. Backs `add_item` (`addProjectV2ItemById`) in sync-…** (1 connections) — `adapters/tracker/base.py`
- **Write one field on one board item. Backs `write_field`…** (1 connections) — `adapters/tracker/base.py`
- **Which board to talk to. `owner`/`number` mirror sync-project.py's…** (1 connections) — `adapters/tracker/base.py`
- *... and 2 more nodes in this community*

## Relationships

- [json](json.md) (11 shared connections)
- [JiraTracker](JiraTracker.md) (9 shared connections)
- [GitHubTracker](GitHubTracker.md) (8 shared connections)
- [test_jira.py](test_jira.py.md) (6 shared connections)
- [issue](issue.md) (5 shared connections)
- [sync-project.py](sync-project.py.md) (4 shared connections)
- [pathlib](pathlib.md) (4 shared connections)
- [TestGitHubTrackerContract](TestGitHubTrackerContract.md) (3 shared connections)
- [TrackerContractTests](TrackerContractTests.md) (2 shared connections)
- [check-story-scope.py](check-story-scope.py.md) (1 shared connections)
- [TestDiff](TestDiff.md) (1 shared connections)
- [TestMakeTracker](TestMakeTracker.md) (1 shared connections)

## Source Files

- `adapters/tracker/base.py`
- `adapters/tracker/tests/test_github.py`
- `adapters/tracker/tests/test_jira.py`
- `scripts/test_sync_project.py`

## Audit Trail

- EXTRACTED: 82 (89%)
- INFERRED: 10 (11%)
- AMBIGUOUS: 0 (0%)

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*