# sync-project.py

> 17 nodes

## Key Concepts

- **sync-project.py** (23 connections) — `scripts/sync-project.py`
- **run_sync()** (10 connections) — `scripts/sync-project.py`
- **make_tracker()** (6 connections) — `scripts/sync-project.py`
- **apply_fields()** (5 connections) — `scripts/sync-project.py`
- **_issue_dict()** (4 connections) — `scripts/sync-project.py`
- **main()** (4 connections) — `scripts/sync-project.py`
- **desired_fields()** (3 connections) — `scripts/sync-project.py`
- **diff()** (3 connections) — `scripts/sync-project.py`
- **plan_additions()** (3 connections) — `scripts/sync-project.py`
- **Only what actually differs. A no-op run must write nothing.** (1 connections) — `scripts/sync-project.py`
- **Open issues missing from the board — sorted so a run is deterministic. Closed…** (1 connections) — `scripts/sync-project.py`
- **`desired_fields` was written (and is tested) against the dict shape `gh issue…** (1 connections) — `scripts/sync-project.py`
- **The one place a run picks its `Tracker` implementation. `TRACKER_IMPL=github`…** (1 connections) — `scripts/sync-project.py`
- **Write every field in `delta`. Returns 1 on failure, None on success.** (1 connections) — `scripts/sync-project.py`
- **The whole sync algorithm, independent of argv — so `main()` and tests can drive…** (1 connections) — `scripts/sync-project.py`
- **Make the project board reflect the repository, not somebody's memory. Labels…** (1 connections) — `scripts/sync-project.py`
- **What the board should say about this issue, from the issue alone.** (1 connections) — `scripts/sync-project.py`

## Relationships

- [json](json.md) (8 shared connections)
- [BoardRef](BoardRef.md) (4 shared connections)
- [GitHubTracker](GitHubTracker.md) (4 shared connections)
- [JiraTracker](JiraTracker.md) (2 shared connections)
- [pathlib](pathlib.md) (2 shared connections)
- [argparse](argparse.md) (1 shared connections)
- [check-story-scope.py](check-story-scope.py.md) (1 shared connections)
- [subprocess](subprocess.md) (1 shared connections)

## Source Files

- `scripts/sync-project.py`

## Audit Trail

- EXTRACTED: 40 (87%)
- INFERRED: 6 (13%)
- AMBIGUOUS: 0 (0%)

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*