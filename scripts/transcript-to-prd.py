#!/usr/bin/env python3
"""Transcript → draft PRD and candidate requirements (REQ-008).

    transcript-to-prd.py --in transcript.txt --out draft/prd-draft.md

Deterministic and offline: this script makes no model call. It extracts
and structures; the judgement work (accepting a candidate, resolving an
open question) happens in a dispatched product-manager session, not here
— a script that quietly calls a model would be untestable.

Format assumed of the transcript: blank-line-separated turns, each
optionally prefixed with `Speaker: `. A turn that wraps across several
physical lines (a typographic wrap, not a paragraph break) is joined into
one utterance before quoting — the quote stays verbatim word-for-word,
only the hard line-wrap is collapsed to a space.

Every candidate requirement carries the verbatim quote it came from; a
"requirement" with no quote is an invention and is dropped rather than
guessed at (and counted in the summary). Contradictions and ambiguous
statements are surfaced as open questions, never silently resolved.

Writes only to the path given by --out. Never writes into prds/ or
requirements/ — those are the product manager's to accept into.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROTECTED_DIRS = (REPO_ROOT / "prds", REPO_ROOT / "requirements")

# Phrases that mark a sentence as expressing a need, not just narration.
TRIGGER_PHRASES = [
    "need", "needs", "needed", "must", "should", "require", "requires",
    "requirement", "want", "wants", "would like", "has to", "have to",
    "shall", "expect", "expects", "expected",
]

# Hedges that mean the speaker themself hasn't resolved this — raise it as
# an open question rather than picking a reading for them.
AMBIGUITY_PHRASES = [
    "maybe", "possibly", "not sure", "i think", "i guess", "tbd",
    "to be determined", "unclear", "not certain", "sort of", "kind of",
    "or something", "not decided", "undecided",
]

NEGATION_WORDS = {"not", "never", "no", "without", "none", "neither", "nor"}

STOPWORDS = {
    "the", "a", "an", "to", "of", "for", "and", "or", "in", "on", "at",
    "is", "are", "be", "we", "i", "it", "that", "this", "our", "so",
    "will", "with", "as", "by", "if", "but", "just", "also", "then",
    "than", "from", "was", "were", "been", "do", "does", "did", "you",
    "your", "they", "their", "he", "she", "them", "us", "my", "me",
}

_WORD_RE = re.compile(r"[A-Za-z']+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_SPEAKER_RE = re.compile(r"^([A-Za-z][A-Za-z0-9 .'()-]{0,40}):\s+(.*)$")


def _compile_phrase_patterns(phrases: list[str]) -> list[re.Pattern]:
    return [
        re.compile(r"\b" + r"\s+".join(re.escape(w) for w in phrase.split()) + r"\b",
                   re.IGNORECASE)
        for phrase in phrases
    ]


_TRIGGER_TOKENS = {w for phrase in TRIGGER_PHRASES for w in phrase.split()}
_TRIGGER_PATTERNS = _compile_phrase_patterns(TRIGGER_PHRASES)
_AMBIGUITY_PATTERNS = _compile_phrase_patterns(AMBIGUITY_PHRASES)


def tokenize(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


def has_trigger(sentence: str) -> bool:
    return any(p.search(sentence) for p in _TRIGGER_PATTERNS)


def has_ambiguity_marker(sentence: str) -> bool:
    return any(p.search(sentence) for p in _AMBIGUITY_PATTERNS)


def is_negated(sentence: str) -> bool:
    toks = tokenize(sentence)
    if any(t.endswith("n't") for t in toks):
        return True
    return bool(set(toks) & NEGATION_WORDS)


def topic_tokens(sentence: str) -> set[str]:
    toks = tokenize(sentence)
    return {
        t for t in toks
        if t not in STOPWORDS and t not in _TRIGGER_TOKENS
        and t not in NEGATION_WORDS and not t.endswith("n't")
    }


# --------------------------------------------------------------------------
# Parsing — plain text in, utterances with line numbers out.
# --------------------------------------------------------------------------

@dataclass
class Utterance:
    speaker: str | None
    text: str
    start_line: int


def parse_utterances(raw: str) -> list[Utterance]:
    lines = raw.splitlines()
    utterances: list[Utterance] = []
    block: list[str] = []
    block_start: int | None = None

    def flush() -> None:
        nonlocal block, block_start
        if block:
            joined = " ".join(l.strip() for l in block if l.strip())
            if joined:
                speaker = None
                text = joined
                m = _SPEAKER_RE.match(joined)
                if m:
                    speaker, text = m.group(1).strip(), m.group(2).strip()
                if text:
                    utterances.append(Utterance(speaker, text, block_start))
        block = []
        block_start = None

    for i, line in enumerate(lines, start=1):
        if line.strip() == "":
            flush()
        else:
            if block_start is None:
                block_start = i
            block.append(line)
    flush()
    return utterances


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


# --------------------------------------------------------------------------
# Extraction — pure. Text in, candidates and open questions out.
# --------------------------------------------------------------------------

@dataclass
class Candidate:
    id: str
    quote: str
    speaker: str | None
    line: int


@dataclass
class OpenQuestion:
    id: str
    kind: str  # "contradiction" | "ambiguity"
    detail: str
    quotes: list[tuple[str, str | None, int]]


@dataclass
class ExtractionResult:
    candidates: list[Candidate] = field(default_factory=list)
    open_questions: list[OpenQuestion] = field(default_factory=list)
    dropped_no_quote: int = 0
    contradiction_count: int = 0
    ambiguity_count: int = 0


def make_candidate(index: int, sentence: str, speaker: str | None, line: int) -> Candidate | None:
    """A candidate with no quote is an invention, not a requirement — the
    caller drops it and counts the drop rather than guessing a quote."""
    quote = sentence.strip()
    if not quote:
        return None
    return Candidate(f"CAND-REQ-{index:03d}", quote, speaker, line)


def find_contradictions(candidates: list[Candidate]) -> list[OpenQuestion]:
    open_qs: list[OpenQuestion] = []
    used: set[str] = set()
    for i in range(len(candidates)):
        a = candidates[i]
        if a.id in used:
            continue
        for j in range(i + 1, len(candidates)):
            b = candidates[j]
            if b.id in used:
                continue
            ta, tb = topic_tokens(a.quote), topic_tokens(b.quote)
            if len(ta & tb) >= 2 and is_negated(a.quote) != is_negated(b.quote):
                open_qs.append(OpenQuestion(
                    id="",
                    kind="contradiction",
                    detail=(f"{a.id} and {b.id} appear to conflict. Not resolved "
                            "automatically — a human decides which (if either) stands."),
                    quotes=[(a.quote, a.speaker, a.line), (b.quote, b.speaker, b.line)],
                ))
                used.add(a.id)
                used.add(b.id)
                break
    return open_qs


def extract(raw: str) -> ExtractionResult:
    utterances = parse_utterances(raw)
    candidates: list[Candidate] = []
    ambiguities: list[OpenQuestion] = []
    dropped = 0
    n = 0

    for utt in utterances:
        for sentence in split_sentences(utt.text):
            if not has_trigger(sentence):
                continue
            if has_ambiguity_marker(sentence):
                quote = sentence.strip()
                if not quote:
                    dropped += 1
                    continue
                ambiguities.append(OpenQuestion(
                    id="",
                    kind="ambiguity",
                    detail=("This statement hedges on its own requirement. Raised as an "
                            "open question rather than resolved by guessing."),
                    quotes=[(quote, utt.speaker, utt.start_line)],
                ))
                continue
            n += 1
            cand = make_candidate(n, sentence, utt.speaker, utt.start_line)
            if cand is None:
                dropped += 1
                n -= 1
                continue
            candidates.append(cand)

    contradictions = find_contradictions(candidates)
    all_oq = ambiguities + contradictions
    all_oq.sort(key=lambda oq: oq.quotes[0][2])
    for idx, oq in enumerate(all_oq, start=1):
        oq.id = f"OQ-{idx:03d}"

    return ExtractionResult(
        candidates=candidates,
        open_questions=all_oq,
        dropped_no_quote=dropped,
        contradiction_count=len(contradictions),
        ambiguity_count=len(ambiguities),
    )


# --------------------------------------------------------------------------
# Rendering — pure. Result in, markdown out.
# --------------------------------------------------------------------------

def render(result: ExtractionResult, source_name: str, source_path: str, total_lines: int) -> str:
    lines: list[str] = []
    lines.append(f"# Draft PRD — extracted from transcript: {source_name}")
    lines.append("")
    lines.append(
        "_Generated by `scripts/transcript-to-prd.py` — deterministic extraction, "
        "no model call. This is a draft: nothing here is accepted into `prds/` or "
        "`requirements/` until a product manager reviews it._"
    )
    lines.append("")
    lines.append(f"Source: `{source_path}` ({total_lines} lines)")
    lines.append("")
    lines.append("## Candidate requirements")
    lines.append("")
    if not result.candidates:
        lines.append("_No candidate requirements were extracted from this transcript._")
        lines.append("")
    else:
        for c in result.candidates:
            lines.append(f"### {c.id}")
            lines.append("")
            lines.append(f"> {c.quote}")
            lines.append(f"— {c.speaker or 'unknown speaker'}, line {c.line}")
            lines.append("")

    lines.append("## Open questions")
    lines.append("")
    if not result.open_questions:
        lines.append("_None raised._")
        lines.append("")
    else:
        for oq in result.open_questions:
            label = "Contradiction" if oq.kind == "contradiction" else "Ambiguous statement"
            lines.append(f"### {oq.id} — {label}")
            lines.append("")
            for quote, speaker, line in oq.quotes:
                lines.append(f"> {quote}")
                lines.append(f"— {speaker or 'unknown speaker'}, line {line}")
                lines.append("")
            lines.append(oq.detail)
            lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Candidate requirements: {len(result.candidates)}")
    lines.append(
        f"- Open questions: {len(result.open_questions)} "
        f"({result.contradiction_count} contradiction(s), {result.ambiguity_count} ambiguity/ambiguities)"
    )
    lines.append(f"- Dropped (no quote): {result.dropped_no_quote}")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def guard_output_path(out_path: Path) -> None:
    """prds/ and requirements/ are the product manager's to accept into —
    this script proposes, it never commits a draft there directly."""
    out_resolved = out_path.resolve()
    for protected in PROTECTED_DIRS:
        try:
            out_resolved.relative_to(protected.resolve())
        except ValueError:
            continue
        raise SystemExit(
            f"transcript-to-prd: refusing to write into {protected} — that "
            "directory is the product manager's to accept a draft into, not "
            "this script's to write."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--in", dest="in_path", required=True, type=Path,
                         help="plain-text transcript to read")
    parser.add_argument("--out", dest="out_path", required=True, type=Path,
                         help="path to write the draft PRD to (never prds/ or requirements/)")
    args = parser.parse_args(argv)

    if not args.in_path.is_file():
        raise SystemExit(f"transcript-to-prd: no such file: {args.in_path}")

    guard_output_path(args.out_path)

    raw = args.in_path.read_text()
    result = extract(raw)
    doc = render(result, args.in_path.name, str(args.in_path), len(raw.splitlines()))

    args.out_path.parent.mkdir(parents=True, exist_ok=True)
    args.out_path.write_text(doc)

    print(
        f"transcript-to-prd: {len(result.candidates)} candidate requirement(s), "
        f"{len(result.open_questions)} open question(s), "
        f"{result.dropped_no_quote} dropped (no quote) -> {args.out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
