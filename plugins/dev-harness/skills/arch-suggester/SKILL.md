---
name: arch-suggester
description: Reference checklist read by the `arch-suggester` agent when deciding where a new helper function or new file goes. Not a workflow to run by hand — edit `references/checklist.md` to add, remove, or reorder decision points; the agent file never needs to change for that.
user-invocable: false
---

# arch-suggester checklist

This skill only holds data. The `arch-suggester` agent (`agents/arch-suggester.md` in this plugin)
reads `references/checklist.md` at the start of every run and cites its section numbers.

- Add or remove a decision point → edit `references/checklist.md` only.
- Keep section numbers stable where possible; the agent cites them in `Why:`.
- Output format and the read-only contract live in the agent file, not here.
