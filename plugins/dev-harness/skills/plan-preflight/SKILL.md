---
name: plan-preflight
description: Self-check one Plan unit before sending it to `plan-verifier`, and again before resubmitting after a `REVISE`. Use only for units that get a readiness review.
---

# Plan preflight

Run against one Plan unit, in the main session. For each check, write the evidence into the
Plan or fix the Plan. Checks that do not apply to the unit are skipped, not padded.

## Before writing the Plan

Settle these in order, the way a PM and an RD settle a requirement. Each step's output feeds
the next; none is left for `plan-verifier` to discover.

1. **Outcome from the user.** Write each outcome as an observable result: an action and what
   is seen after it ("press Local → only local branches are listed"). Quote the user's words
   that state it. When their words do not pin an observable result, ask (`AskUserQuestion`)
   until they do, and quote the answer that states the result — never a bare "ok".
2. **Understand before writing.** Read the code where the outcome actually has to change, and
   state what each change means for the outcome, before writing any row. Direction over
   activity: a list of search hits is not understanding, and an inventory is not the goal.
   Every row cites lines that exist now; a fact you did not read is not a row.
3. **Change inventory.** One row per place that changes. "Expected change" says what that code
   does after the change, specific enough that a reviewer can predict the diff — not "update"
   or "adjust". "Serves" names the outcome the row exists for. A row that serves no outcome is
   out of scope: drop it, or ask the user whether it is an outcome.
4. **Refactor inventory.** Only refactors the change needs, held to the same two rules: a
   predictable change, and serving a named outcome. A refactor that serves no outcome is a
   separate round.

```markdown
## Outcome
- O1: <action → observable result>
  > <the user's own words that state it>

## Change inventory
| Location | Expected change | Serves |
|---|---|---|
| `src/existing.ext:L12-L30` | <what this code does after the change> | O1 |
| `src/added.ext:new` | <what the new file holds> | O1 |

## Refactor inventory
| Location | Expected change | Serves |
|---|---|---|
| `src/existing.ext:L40` | <the restructure, and why O1 needs it> | O1 |
```

`require-plan-structure.py` denies a `plan-verifier` dispatch until this structure holds: the
brief carries a `Plan: <path>` line, every quote is found in the user's messages, every cited
line exists, every row names an outcome. It checks shape only; whether a row is predictable and
serves only its outcome is this checklist's job, then `plan-verifier`'s.

## Before every dispatch

1. **Inventory.** For each changed signature, field, or behavior, record the grep command and
   its hit count, and list every caller and consumer: tests and spies, the other side of a
   language boundary, other routes to the same outcome. Each one is a Change inventory row or
   a named non-goal.
2. **Acceptance can go red.** For each check, name a wrong implementation that fails it, and
   confirm correct code passes it. Confirm the named test file can reach the behavior with its
   fixtures, and that any command runs as written in the stated environment.
3. **Every commit stands alone.** Each commit builds and tests at its own checkout, callers and
   bindings included. A rollback claim says what the revert leaves behind.
4. **State table.** For each new flow, give the defined result for: cancel, failure, empty or
   missing data, a change between read and write, re-entry.
5. **Producer and reader.** Every new field, event, or error code has a named reader, and a
   named surface if the user sees it. Every new reader has a producer.
6. **External facts.** Each SDK, tool, or CLI behavior the design rests on cites a source line
   or a measured probe. Anything else is marked unverified and carries a stop condition.
7. **Gates and fields.** The fields in the Plan gate bullet of `CLAUDE.md` are all present. A
   security-sensitive unit carries `security-reviewer` findings; a UI change names its G1 step.
8. **One current contract.** The unit's execution contract holds current text only. Superseded
   text moves, struck and with its reason, to `## Revision log` in the same Plan file. The
   `plan-verifier` brief points at the contract with a `Plan: <path>` line.

## After a REVISE

1. **Fix the class.** For each blocker, search for other instances of the same defect and fix
   them in the same revision.
2. **Check the revision itself.** Run the checks above on every behavior the revision adds.
3. **Two REVISEs on one mechanism mean the design is unsettled.** The next step is the smallest
   reversible probe or a user ruling, with the result recorded, not another rewording. The
   review cap in the Orchestration block still applies.
