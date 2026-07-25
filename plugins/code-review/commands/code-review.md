---
description: Review uncommitted and branch changes and print a severity-tabulated report by category. Delegates the actual review to the code-reviewer subagent so the main conversation stays clean.
argument-hint: "[branch | scope hint] (optional — default: uncommitted changes + diff since the default branch)"
---

Run a code review of the current changes and show the user the result.

**You must delegate this to the `code-reviewer` subagent — do not read diffs, read files, or
analyze code yourself in this conversation.** The entire point of this command is to keep this
session's context clean; every git command, file read, and piece of reasoning about the changes
belongs inside the subagent's isolated context, not here.

Steps:

1. If the user passed an argument (`$ARGUMENTS`), treat it as a scope hint (e.g. a branch name
   to diff against, or "just staged", etc.) and pass it along to the subagent verbatim. If no
   argument was given, tell the subagent to use its default scope (uncommitted changes + diff
   since the auto-detected default branch).

2. Launch the `code-reviewer` subagent with that scope. Wait for it to return its report.

3. Print the subagent's returned report **verbatim** to the user — that markdown report *is*
   your entire response. Do not summarize it, do not re-explain it, do not prepend or append
   commentary, and do not save it to a file. If the subagent's response contains anything other
   than the report (it shouldn't), strip that and show only the report.

Do not proceed with any other action after showing the report unless the user asks for one.
