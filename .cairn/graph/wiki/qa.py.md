# qa.py

> 15 nodes

## Key Concepts

- **qa.py** (18 connections) — `dashboards/qa.py`
- **build_matrix()** (5 connections) — `dashboards/qa.py`
- **main()** (4 connections) — `dashboards/qa.py`
- **collect_issues()** (3 connections) — `dashboards/qa.py`
- **issue_requirements()** (3 connections) — `dashboards/qa.py`
- **render_html()** (3 connections) — `dashboards/qa.py`
- **req_status()** (3 connections) — `dashboards/qa.py`
- **verdict()** (3 connections) — `dashboards/qa.py`
- **gh_json()** (2 connections) — `dashboards/qa.py`
- **collections** (2 connections)
- **REQ -> issues carrying it, each marked approved/rejected/pending. A rejected…** (1 connections) — `dashboards/qa.py`
- **One-word rollup for a requirement's row: a single rejected issue fails the row…** (1 connections) — `dashboards/qa.py`
- **Build the QA verdict dashboard: a pass/fail matrix, grouped by requirement.…** (1 connections) — `dashboards/qa.py`
- **REQ ids from a story's `→ **REQ-00N**` marker, and only that marker. sync-…** (1 connections) — `dashboards/qa.py`
- **Rejected outranks approved — the same precedence as the QA policy's own veto (a…** (1 connections) — `dashboards/qa.py`

## Relationships

- [pathlib](pathlib.md) (3 shared connections)
- [argparse](argparse.md) (1 shared connections)
- [json](json.md) (1 shared connections)
- [subprocess](subprocess.md) (1 shared connections)
- [dashboards/build.py](dashboards-build.py.md) (1 shared connections)
- [plan.py](plan.py.md) (1 shared connections)
- [standup.py](standup.py.md) (1 shared connections)

## Source Files

- `dashboards/qa.py`

## Audit Trail

- EXTRACTED: 30 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*