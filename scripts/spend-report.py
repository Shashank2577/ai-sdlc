#!/usr/bin/env python3
"""Turn a Claude Code execution log into a spend summary, and say whether
the session stayed inside its budget.

Cost is the ceiling (PRD §13): a breach means real money was spent, not
that a large cached context was re-read. Turns, wall clock and cost can
breach; tokens are a tripwire — reported, flagged when abnormal, never a
reason to fail a session. That distinction is not theoretical. The first
live dispatch cost $0.61 and "breached" a 400k token budget, because
1.35M of its 1.41M tokens were cache reads.

This prints a markdown table for the work-item comment and exits 3 when a
breaching line was exceeded, so the dispatcher can escalate on that alone.

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


def load_records(path: Path) -> list[dict]:
    """Every message in the execution log, for the activity summary."""
    if not path or not path.is_file():
        return []
    try:
        text = path.read_text().strip()
        if not text:
            return []
        try:
            data = json.loads(text)
            return data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            return [json.loads(line) for line in text.splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError):
        return []


def describe_activity(records: list[dict]) -> str:
    """What the session actually did, from its own tool calls.

    The escalation used to say "read the transcript". The transcript is
    written to the runner's temp directory and destroyed with the runner,
    so that advice could never be followed. PRD §7 says humans are handed
    decisions, not transcripts — so this summarises the trace onto the work
    item, where it survives, instead of pointing at something that does not.
    """
    tools: dict[str, int] = {}
    recent: list[str] = []
    for record in records:
        if record.get("type") != "assistant":
            continue
        for block in (record.get("message") or {}).get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name", "?")
            tools[name] = tools.get(name, 0) + 1
            args = block.get("input") or {}
            detail = (args.get("file_path") or args.get("path") or args.get("pattern")
                      or args.get("command") or "")
            recent.append(f"{name} {str(detail)[:70]}".strip())

    if not tools:
        return ("**What the session did:** no tool calls were recorded. Either it "
                "never started work, or the execution log did not capture the "
                "trace — both are worth knowing before spending again.")

    ranked = ", ".join(f"`{n}` ×{c}" for n, c in
                       sorted(tools.items(), key=lambda kv: -kv[1])[:8])
    lines = [f"**What the session did:** {sum(tools.values())} tool call(s) — {ranked}.",
             "", "Last actions before it stopped:", ""]
    lines += [f"- `{a}`" for a in recent[-5:]]
    return "\n".join(lines)


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
        # Fresh tokens: what the session actually generated or sent anew.
        # Cache reads are excluded — they are re-reads of context already
        # paid for, and counting them made a 61-cent session look like a
        # 1.4M-token overrun.
        "fresh_tokens": inp + out + cache_write,
        "total_tokens": inp + out + cache_read + cache_write,
        "cost_usd": result.get("total_cost_usd"),
        "wall_clock_minutes": round(duration_ms / 60000, 1) if duration_ms else None,
        # A session that burns its budget on denied tool calls looks
        # identical to one that got lost, unless you say so.
        "permission_denials": int(result.get("permission_denials_count") or 0),
        "is_error": bool(result.get("is_error")),
    }


def check(spend: dict, budget: dict) -> list[dict]:
    """One row per budget line. `used is None` means it was not measured.

    `enforced` is the whole point: only cost, turns and wall clock can
    fail a session. Tokens are a tripwire — over the line it says so, and
    the session still passes.
    """
    pairs = [
        ("cost", "USD", spend["cost_usd"], budget.get("cost_usd"), True),
        ("turns", "turns", spend["turns"], budget.get("turns"), True),
        ("wall clock", "minutes", spend["wall_clock_minutes"],
         budget.get("wall_clock_minutes"), True),
        ("fresh tokens", "tokens", spend["fresh_tokens"] or None,
         budget.get("tokens"), False),
    ]
    rows = []
    for label, unit, used, limit, enforced in pairs:
        over = used is not None and limit is not None and used > limit
        rows.append({"label": label, "unit": unit, "used": used, "limit": limit,
                     "enforced": enforced, "over": over,
                     "breached": over and enforced})
    return rows


def render(rows: list[dict], spend: dict, note: str, activity: str = "") -> str:
    def fmt(v, money=False):
        if v is None:
            return "unknown"
        if isinstance(v, float):
            return f"{v:.4f}" if money else f"{v:g}"
        return f"{v:,}" if isinstance(v, int) else str(v)

    lines = ["| Budget line | Used | Limit | |", "|---|---|---|---|"]
    for r in rows:
        money = r["label"] == "cost"
        if r["used"] is None:
            mark = "—"
        elif r["breached"]:
            mark = "**over**"
        elif r["over"]:
            mark = "over (tripwire — not a breach)"
        else:
            mark = "ok"
        lines.append(f"| {r['label']} ({r['unit']}) | {fmt(r['used'], money)} "
                     f"| {fmt(r['limit'], money)} | {mark} |")

    if spend.get("total_tokens"):
        lines.append("")
        lines.append(
            f"Tokens: {spend['input_tokens']:,} in · {spend['output_tokens']:,} out · "
            f"{spend['cache_write_tokens']:,} cache write · "
            f"{spend['cache_read_tokens']:,} cache read _(cache reads are excluded "
            f"from the tripwire — they are re-reads of context already paid for)_."
        )
    denials = spend.get("permission_denials") or 0
    if denials:
        lines += ["", f"> **{denials} tool call(s) were denied by the session's "
                      f"permission settings.** A session that spends its budget "
                      f"discovering what it may not do will ship nothing. Check "
                      f"the compiled permissions in the run summary against "
                      f"`role-packs/<role>/tools.yaml`."]
    if activity:
        lines += ["", activity]
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
    records = load_records(args.execution)
    spend = summarise(result)
    rows = check(spend, budget)
    markdown = render(rows, spend, note, describe_activity(records))

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
