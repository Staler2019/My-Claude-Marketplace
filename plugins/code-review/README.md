# code-review

Language-agnostic code review for Claude Code, with a clean-context orchestrator and
per-category severity tables printed straight to the terminal.

## Usage

```
/code-review
```

Reviews uncommitted changes plus everything committed on the current branch since it diverged
from the repo's default branch (auto-detected from `origin/HEAD`, falling back to `main` then
`master`). Untracked files are included.

You can optionally pass a scope hint:

```
/code-review compare against develop
/code-review just the staged changes
```

## How it works

`/code-review` is a thin entry point. All the actual work — resolving the diff, reading
changed files and their surrounding context, and judging each category — happens inside the
`code-reviewer` subagent, in its own isolated context. The subagent never writes a file; it
returns the finished report as its final message, and the command prints that report verbatim.
This keeps the calling session's context limited to the report itself, not the diff, file
contents, or review reasoning that produced it.

## Review categories

Every review walks changed files through seven categories, each rendered as its own table with
columns `File | Line(s) | Reason | Fix | Severity`:

1. Correctness & Logic
2. Security
3. Error Handling & Robustness
4. Performance
5. Maintainability & Style
6. Testing
7. Documentation

Severity is one of `Critical | High | Medium | Low | Info`.

The review is principle-based rather than tied to one language or framework: the agent infers
each file's language from its extension and applies idiomatic judgment, instead of relying on a
hardcoded per-language rule catalog. It works the same way across Python, TypeScript, Go, Rust,
Java, C, Ruby, or anything else.

## Output

The report is printed directly in the terminal as the command's response. Nothing is written to
disk.
