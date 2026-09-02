# Dashboards

Generated views over the program's own history. Nothing here is written by
hand — if a page is wrong, the generator is wrong, and that is a bug issue.

```sh
python3 dashboards/build.py --out site                 # needs gh auth
python3 dashboards/build.py --out site --no-github     # git only, offline
python3 dashboards/test_build.py                       # 17 tests
```

Published by `.github/workflows/dashboards.yml` on every push to `main`.

## Traceability matrix

`traceability.html` — every requirement in `requirements/index.md`, joined to
the commits carrying its `Requirement:` trailer, joined to the merged pull
requests those commits arrived in.

| Status | Means |
|---|---|
| **traced** (green) | at least one commit for this REQ reached `main` through a merged PR |
| **on main, no PR** (amber) | commits exist on `main` but none is attributable to a merged PR — a direct push, or seed history |
| **untraced** (red) | no commit on `main` carries this requirement |

The acceptance criterion for P0-5 says green/red. Amber is a third state
because the repo genuinely has one: the Stage 0 seed commit went straight to
`main` before the gate existed. Colouring that green would claim a PR trail
that does not exist; colouring it red would claim no work happened. Neither
is true, so it gets its own colour.

A `Requirement:` trailer naming a REQ that is **not** in the index still gets
a row, marked `⚠ not in requirements/index.md`. Either the trailer is wrong or
the index is — dropping it would hide whichever it is.

The commit → PR join uses `GET /repos/{owner}/{repo}/commits/{sha}/pulls`,
which is merge-strategy agnostic: squash, rebase and merge commits all resolve
correctly, where scraping subject lines for `(#123)` does not. If the lookup
fails the build still completes and those rows fall back to amber, with the
reason printed in the footer. A matrix that renders with a caveat beats no
matrix.

## `traceability.json`

Written next to the HTML, same data. Anything else that needs this — the
standup digest, a client report — reads the JSON rather than recomputing the
join.

## Adding a view

Write `render_<name>(data, meta) -> str`, write it into `--out`, and add it to
the `render_index` list. Share `CSS` so the pages stay one system. Keep every
page self-contained: no CDN, no external fonts, no network at view time. A
dashboard that needs the internet to render is a dashboard that breaks in
front of a client.
