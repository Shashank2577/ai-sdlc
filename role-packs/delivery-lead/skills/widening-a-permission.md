# Skill — widening a permission

## The situation this skill is for

A session somewhere — developer, QA, devops, anyone — is blocked. The
blocker is a `write_scope` deny entry, a `policies/gates.yaml` rule, or a
token scope. You are the only role that can edit the file that would
unblock it. The fix looks like one line.

That is the one moment this pack exists to get right. Everything else you
do is read-mostly; this is the part that is hard to undo.

## The order of questions

1. **Should this role be able to do that at all?** Often the answer is no,
   and the work belongs to a different role, not a wider one. A developer
   session blocked on `policies/**` is not evidence the developer pack
   needs `policies/**` — it is evidence the story should have been routed
   here in the first place.
2. **If yes, would a narrower credential or a narrower pattern do it?**
   Prefer widening one `write_scope` glob over removing a `deny` entry
   wholesale, and prefer a role-specific fix over a shared one. Widening a
   token every role shares raises every role's reach to unblock one story
   — `role-packs/devops/skills/least-privilege-credentials.md` documents
   the exact credential table this protects.
3. **Only then, does the existing control change** — and that is a
   decision with your name on the commit, made because it is correct, not
   because a session is waiting on it.

## Never to unblock a story

If the reason you are editing a `write_scope` or a gate rule is "session
X is stuck right now," stop. That is the tell. A permission widened under
that pressure is a permission widened without the question "should this
role be able to do that at all" ever actually being asked — the deadline
answered it instead.

The correct response to a blocked session is usually one of:

- Escalate the blocked session's work item, not this one. Let a human
  decide whether the block is correct.
- If the block is wrong, open this role's own story, argue the case in
  the PR body per the charter's three questions, and let
  `policies/gates.yaml`'s `touches_governance` rule route it to a human
  before it ships — same as any other change here.

Either way, the story that is blocked and the story that changes the
policy are two different pull requests, reviewed on their own timelines.
Collapsing them into one "unblock now" commit is exactly how a gate
becomes a suggestion.

## What this repo got wrong before this pack existed

Three changes landed with no owning role: `policies/gates.yaml` itself,
the orchestrator's refill floor, and routing for two new roles — each
committed under `Agent-Role: devops` or `orchestrator`, because every pack
denied every other pack's paths and something still had to give. The
provenance was wrong on the record in a repo whose whole claim is that the
audit trail is honest. This pack is the fix: the ownership is explicit,
and `policies/gates.yaml`'s critical classification means a person signs
off before any of it ships — including the case above.
