# Skill — issuing a security verdict

## Exactly one label, always

```sh
# Approve
gh issue edit <n> --add-label security:approved --remove-label security:rejected

# Reject
gh issue edit <n> --add-label security:rejected --remove-label security:approved
```

Comment first, label second — a comment with no label is recoverable, a
label with no reasons is a decision nobody can act on.

## Say the enforcement gap out loud, every time

Because no required check reads `security:rejected` yet (see charter.md),
end every verdict comment with one line stating that plainly:

> This verdict is not yet enforced by a required check —
> `security:rejected` does not block a merge structurally, the way
> `qa:rejected` does. See Shashank2577/ai-sdlc#216.

That line costs nothing and prevents the label being mistaken for a gate
that exists. Do not let a clean verdict imply otherwise by omission.

## Approving

Approve when none of the five categories in
`reviewing-for-security.md` turned up a finding you can point at with
evidence. An approval can still carry observations — real but non-blocking
findings, or new bug issues for exposure outside this story's scope. File
them; do not hold the story hostage to a finding it was never asked to fix.

## Rejecting

Reject when a finding is real and you can cite it. Every rejection names:

- Which category it falls under (secrets, permission widening, injection,
  dependency, out-of-scope access).
- The file and line, quoted.
- The concrete consequence — what an attacker or a misbehaving session
  could do with it, not just that it "looks risky".

Never "tighten the permissions" with no line cited. Never reject for a
choice you would have made differently that carries no actual exposure.

## Third rejection

Same threshold as QA: three `security:rejected` events on one work item and
`needs-human` goes on with a summary written for the human who is about to
arrive — what is the pattern, and is the story's approach the actual
problem.
