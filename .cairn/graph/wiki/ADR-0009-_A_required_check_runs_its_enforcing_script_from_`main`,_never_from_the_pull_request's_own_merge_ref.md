# ADR-0009: A required check runs its enforcing script from `main`, never from the pull request's own merge ref

> 9 nodes

## Key Concepts

- **ADR-0009: A required check runs its enforcing script from `main`, never from the pull request's own merge ref** (6 connections) — `adrs/0009-required-checks-run-from-main-not-the-merge-ref.md`
- **Options considered** (3 connections) — `adrs/0009-required-checks-run-from-main-not-the-merge-ref.md`
- **0009-required-checks-run-from-main-not-the-merge-ref.md** (1 connections) — `adrs/0009-required-checks-run-from-main-not-the-merge-ref.md`
- **Consequences** (1 connections) — `adrs/0009-required-checks-run-from-main-not-the-merge-ref.md`
- **Context** (1 connections) — `adrs/0009-required-checks-run-from-main-not-the-merge-ref.md`
- **Decision** (1 connections) — `adrs/0009-required-checks-run-from-main-not-the-merge-ref.md`
- **Option A: Check out `main` for the whole job, judge the PR's diff from the API instead of local git** (1 connections) — `adrs/0009-required-checks-run-from-main-not-the-merge-ref.md`
- **Option B: Keep the existing checkout (merge ref, `fetch-depth: 0`, so `BASE_SHA..HEAD_SHA` still resolves locally); before running the check, overwrite the working copy of the script with the version read from `origin/main`** (1 connections) — `adrs/0009-required-checks-run-from-main-not-the-merge-ref.md`
- **Recommendation** (1 connections) — `adrs/0009-required-checks-run-from-main-not-the-merge-ref.md`

## Relationships

- No strong cross-community connections detected

## Source Files

- `adrs/0009-required-checks-run-from-main-not-the-merge-ref.md`

## Audit Trail

- EXTRACTED: 8 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the Cairn knowledge wiki. See [index](index.md) to navigate.*