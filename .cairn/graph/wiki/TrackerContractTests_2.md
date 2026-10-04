# TrackerContractTests

> God node · 26 connections · `adapters/tracker/tests/contract.py`

**Community:** [TrackerContractTests](TrackerContractTests.md)

## Connections by Relation

### contains
- tracker/tests/contract.py `EXTRACTED`

### imports
- [test_jira.py](test_jira.py.md) `EXTRACTED`
- test_github.py `EXTRACTED`

### inherits
- [TestGitHubTrackerContract](TestGitHubTrackerContract.md) `EXTRACTED`
- TestJiraTrackerContract `EXTRACTED`

### method
- .board_ref() `EXTRACTED`
- .setUp() `EXTRACTED`
- .make_tracker() `EXTRACTED`
- .test_board_fields_reports_select_options_and_free_text() `EXTRACTED`
- .test_set_board_field_select_value_is_reflected() `EXTRACTED`
- .test_set_board_field_free_text_value_is_reflected() `EXTRACTED`
- .test_set_board_field_unknown_field_raises_keyerror() `EXTRACTED`
- .test_set_board_field_unknown_option_raises_keyerror() `EXTRACTED`
- .triggered() `EXTRACTED`
- .test_trigger_workflow_is_recorded() `EXTRACTED`
- .test_board_item_is_none_before_being_added() `EXTRACTED`
- .test_add_to_board_then_item_exists() `EXTRACTED`
- .test_get_issue_returns_the_seeded_fields() `EXTRACTED`
- .test_list_issues_all_includes_open_and_closed() `EXTRACTED`
- .test_list_issues_open_excludes_closed() `EXTRACTED`
- .test_comment_is_visible_in_list_comments() `EXTRACTED`
- .test_edit_labels_add_and_remove_are_both_applied() `EXTRACTED`
- .test_list_pull_requests_open_only_returns_open() `EXTRACTED`
- .test_list_pull_requests_all_includes_non_open() `EXTRACTED`

### uses
- [BoardRef](BoardRef.md) `INFERRED`
- [Tracker](Tracker.md) `INFERRED`

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*