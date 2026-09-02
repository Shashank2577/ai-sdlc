#!/usr/bin/env python3
"""Turn a Claude Code execution log into a spend summary, and say whether
the session stayed inside its budget.

Cost is a first-class, per-story, visible metric (PRD §13). This prints a
markdown table for the work-item comment and exits 3 when any budget line
was breached, so the dispatcher can escalate on that alone.

    spend-report.py --execution out.json --budget '{"turns":30,...}'
    spend-report.py --execution missing.json --budget '{}'   # degrades

Exit codes: 0 inside budget · 3 breached · 1 bad arguments.
A missing or unreadable execution log is 0 with an explicit "unknown"
row — no measurement is not the same as a breach, and pretending
otherwise would make the escalation ladder fire on tooling noise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BREACH = 3


def load_execution(path: Path) -> tuple[dict, str]:
    """Pull the final `result` record out of the execution log.

    Claude Code writes a stream of JSON messages; the last one with
    `type == "result"` carries the totals. Accepts either the array form
    or JSON-lines, because both have been seen in the wild.
    """
    if not path or not path.is_file():
        return {}, "no execution log was produced"
    try:
        text = path.read_text().strip()
        if not text:
            return {}, "execution log is empty"
        try:
            data = json.loads(text)
            records = data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"execution log unreadable ({exc.__class__.__name__})"

    for record in reversed(records):
        if isinstance(record, dict) and record.get("type") == "result":
            return record, ""
    return {}, "execution log has no result record"


def summarise(result: dict) -> dict:
    usage = result.get("usage") or {}
    inp = int(usage.get("input_tokens") or 0)
    out = int(usage.get("output_tokens") or 0)
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    cache_write = int(usage.get("cache_creation_input_tokens") or 0)
    duration_ms = result.get("duration_ms")
    return {
        "turns": result.get("num_turns"),
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "total_tokens": inp + out + cache_read + cache_write,
        "cost_usd": result.get("total_cost_usd"),
        "wall_clock_minutes": round(duration_ms / 60000, 1) if duration_ms else None,
        "is_error": bool(result.get("is_error")),
    }


def check(spend: dict, budget: dict) -> list[dict]:
    """One row per budget line. `used is None` means it was not measured."""
    pairs = [
        ("turns", "turns", spend["turns"], budget.get("turns")),
        ("tokens", "tokens", spend["total_tokens"] or None, budget.get("tokens")),
        ("wall clock", "minutes", spend["wall_clock_minutes"],
         budget.get("wall_clock_minutes")),
    ]
    rows = []
    for label, unit, used, limit in pairs:
        breached = used is not None and limit is not None and used > limit
        rows.append({"label": label, "unit": unit, "used": used,
                     "limit": limit, "breached": breached})
    return rows


def render(rows: list[dict], spend: dict, note: str) -> str:
    def fmt(v):
        if v is None:
            return "unknown"
        return f"{v:,}" if isinstance(v, int) else str(v)

    lines = ["| Budget line | Used | Limit | |", "|---|---|---|---|"]
    for r in rows:
        mark = "over" if r["breached"] else ("—" if r["used"] is None else "ok")
        lines.append(f"| {r['label']} ({r['unit']}) | {fmt(r['used'])} "
                     f"| {fmt(r['limit'])} | {mark} |")

    if spend.get("cost_usd") is not None:
        lines.append(f"| cost (USD) | {spend['cost_usd']:.4f} | — | — |")
    if spend.get("total_tokens"):
        lines.append("")
        lines.append(
            f"Tokens: {spend['input_tokens']:,} in · {spend['output_tokens']:,} out · "
            f"{spend['cache_read_tokens']:,} cache read · "
            f"{spend['cache_write_tokens']:,} cache write."
        )
    if note:
        lines += ["", f"_Spend not measured: {note}. Budget compliance is "
                      f"unknown for this session, which is reported rather than "
                      f"assumed either way._"]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--execution", type=Path)
    ap.add_argument("--budget", default="{}", help="JSON budget object")
    ap.add_argument("--out", type=Path, help="write the markdown here too")
    args = ap.parse_args()

    try:
        budget = json.loads(args.budget or "{}")
    except json.JSONDecodeError as exc:
        sys.exit(f"spend-report: --budget is not valid JSON: {exc}")

    result, note = load_execution(args.execution)
    spend = summarise(result)
    rows = check(spend, budget)
    markdown = render(rows, spend, note)

    print(markdown, end="")
    if args.out:
        args.out.write_text(markdown)

    breached = [r["label"] for r in rows if r["breached"]]
    if breached:
        print(f"\nBUDGET BREACH: {', '.join(breached)}", file=sys.stderr)
        return BREACH
    return 0


if __name__ == "__main__":
    sys.exit(main())
