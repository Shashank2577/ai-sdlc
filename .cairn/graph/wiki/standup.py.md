# standup.py

> 18 nodes

## Key Concepts

- **standup.py** (20 connections) — `dashboards/standup.py`
- **main()** (9 connections) — `dashboards/standup.py`
- **build_digest()** (6 connections) — `dashboards/standup.py`
- **gh_json()** (5 connections) — `dashboards/standup.py`
- **parse_iso()** (5 connections) — `dashboards/standup.py`
- **collect_blocked_since()** (4 connections) — `dashboards/standup.py`
- **collect_commits()** (4 connections) — `dashboards/standup.py`
- **collect_issues()** (3 connections) — `dashboards/standup.py`
- **collect_pulls()** (3 connections) — `dashboards/standup.py`
- **collect_runs()** (3 connections) — `dashboards/standup.py`
- **render_digest_html()** (3 connections) — `dashboards/standup.py`
- **datetime** (3 connections)
- **recent()** (2 connections) — `dashboards/standup.py`
- **_pr()** (2 connections) — `dashboards/standup.py`
- **links()** (1 connections) — `dashboards/standup.py`
- **Reduce raw event data to the digest. No network, no side effects.** (1 connections) — `dashboards/standup.py`
- **Build the daily standup digest — from events, never from self-reports. Nobody…** (1 connections) — `dashboards/standup.py`
- **When did each currently-blocked issue last acquire status:blocked? From the…** (1 connections) — `dashboards/standup.py`

## Relationships

- [dashboards/build.py](dashboards-build.py.md) (2 shared connections)
- [pathlib](pathlib.md) (2 shared connections)
- [argparse](argparse.md) (1 shared connections)
- [json](json.md) (1 shared connections)
- [subprocess](subprocess.md) (1 shared connections)
- [qa.py](qa.py.md) (1 shared connections)

## Source Files

- `dashboards/standup.py`

## Audit Trail

- EXTRACTED: 42 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*