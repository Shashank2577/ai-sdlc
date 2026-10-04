# adr.py

> 23 nodes

## Key Concepts

- **adr.py** (25 connections) — `dashboards/adr.py`
- **Adr** (9 connections) — `dashboards/adr.py`
- **render_full_record()** (7 connections) — `dashboards/adr.py`
- **index_row()** (6 connections) — `dashboards/adr.py`
- **render_html()** (6 connections) — `dashboards/adr.py`
- **scan_adrs()** (6 connections) — `dashboards/adr.py`
- **date_sort_key()** (4 connections) — `dashboards/adr.py`
- **link_supersession()** (4 connections) — `dashboards/adr.py`
- **main()** (4 connections) — `dashboards/adr.py`
- **parse_adr()** (4 connections) — `dashboards/adr.py`
- **render_body()** (4 connections) — `dashboards/adr.py`
- **status_pill()** (4 connections) — `dashboards/adr.py`
- **parse_sections()** (3 connections) — `dashboards/adr.py`
- **req_links()** (3 connections) — `dashboards/adr.py`
- **work_item_url()** (3 connections) — `dashboards/adr.py`
- **collect_known_reqs()** (2 connections) — `dashboards/adr.py`
- **inline()** (2 connections) — `dashboards/adr.py`
- **Path** (1 connections)
- **Fill `supersedes` from every other record's `superseded_by`, so a superseding…** (1 connections) — `dashboards/adr.py`
- **Records with a real date sort first, oldest first; unparseable or absent dates…** (1 connections) — `dashboards/adr.py`
- **Blank-line-delimited blocks, each a heading, a bullet list, or a paragraph —…** (1 connections) — `dashboards/adr.py`
- **Build the ADR dashboard: an index and full rendering of adrs/*.md. The work…** (1 connections) — `dashboards/adr.py`
- **Split on `## Heading` lines, in document order.** (1 connections) — `dashboards/adr.py`

## Relationships

- [json](json.md) (2 shared connections)
- [pathlib](pathlib.md) (2 shared connections)
- [argparse](argparse.md) (1 shared connections)
- [dashboards/build.py](dashboards-build.py.md) (1 shared connections)
- [subprocess](subprocess.md) (1 shared connections)
- [plan.py](plan.py.md) (1 shared connections)

## Source Files

- `dashboards/adr.py`

## Audit Trail

- EXTRACTED: 54 (98%)
- INFERRED: 1 (2%)
- AMBIGUOUS: 0 (0%)

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*