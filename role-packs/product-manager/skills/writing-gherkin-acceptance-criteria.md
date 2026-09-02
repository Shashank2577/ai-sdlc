# Writing acceptance criteria in Gherkin

Your acceptance criteria and QA's test plan are one artifact with two
consumers (PRD §5.1). If you write prose, QA has to translate it into
something testable before they can use it, and that translation step is
exactly where "looks done" and "is done" quietly diverge.

## The format

Every criterion is a scenario:

```gherkin
Given <the state the system is in before>
When <the action that happens>
Then <the observable, checkable result>
```

`Given` is state, not narrative. `When` is one action, not several. `Then`
is something a QA session — or a script — can actually check: an exit
code, a label, a file's contents, a response body. "Then it works
correctly" is not a `Then`; it is a `Then`-shaped sentence with nothing
inside it.

## A worked example, good and bad

Bad (prose wearing bullet points):

> - The compiler should validate packs properly
> - Errors should be clear

Good:

```gherkin
Given a policy.yaml missing the `cost_usd` budget key
When compiler/compile-pack.py --check runs
Then it exits non-zero and names `cost_usd` and the role in the error
```

The good version is directly checkable — someone can run the command and
read the output against the sentence. The bad version requires the reader
to already agree on what "properly" and "clear" mean.

## The REQ marker

Every story's user-story line ends with the marker
`→ **REQ-0XX**` (comma-separated for more than one REQ). This is not
stylistic — `scripts/sync-project.py`'s `REQ_MARKER` pattern parses exactly
this format to populate the board and, downstream, the traceability
matrix. A REQ mentioned in passing elsewhere in the body does not count;
if the marker is missing, the tooling treats the story as unlinked to any
requirement, regardless of what the acceptance criteria imply.

If you cannot cite a REQ id for a story, stop and check `requirements/`
before inventing scope. A story with no REQ id is not yet refined.

## What doesn't belong in acceptance criteria

- Implementation detail that constrains *how*, when the requirement only
  cares *what*. That belongs in the notes for whoever implements it, not
  in a `Then`.
- Anything you cannot phrase as `Given`/`When`/`Then` without inventing a
  new noun to paper over the gap. That is a sign the requirement itself is
  still ambiguous — file an open question instead of forcing the format.
