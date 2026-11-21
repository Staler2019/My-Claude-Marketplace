# dev-harness

A developer harness for Claude Code: read-only role agents, a Plan-structure gate, git
discipline guards, and a secret scanner wired into native git hooks so secrets and personal
values never reach a commit or a push.

## Install

```
/plugin marketplace add Staler2019/My-Claude-Marketplace
/plugin install dev-harness@My-Claude-Marketplace
```

## What is inside

| Part | What it does |
|---|---|
| `agents/` | Eight read-only roles: `scout`, `Explore`, `algorithm-chooser`, `arch-suggester`, `spec-auditor`, `plan-verifier`, `security-reviewer`, `verifier` (the last one may run tests). |
| `skills/` | `plan-preflight` (self-check a Plan before review) and the `arch-suggester` checklist. |
| `hooks/hooks.json` | PreToolUse guards: `guard-hook-bypass` (no skipping git hooks), `guard-repo-discipline` (stage by file, no blanket checkout), `block-fuzzy-kill`, `backup-before-git-discard`, `require-plan-structure`. |
| `scripts/install-git-hooks` | Installs the secret scanner as native `pre-commit`, `pre-merge-commit`, `commit-msg` and `pre-push` hooks in one repo. |

## Secret scanning in git hooks

```sh
python3 "<plugin dir>/scripts/install-git-hooks" [--no-personal] <repo>
```

The installer copies a self-contained set into `<repo>/.git/hooks/` and prints every file it
wrote; uninstalling is removing those files. It refuses a linked worktree, a repo with
`core.hooksPath` set, and any existing hook it did not install.

What is checked, on every added line, file name, commit message and annotated tag message:

- tokens matching the gitleaks default rules (GitHub, Anthropic, OpenAI, AWS, GCP, Slack,
  Stripe, npm, PyPI, Hugging Face, GitLab, JWT) and private-key headers;
- generic `password=` / `token:` style assignments of 8+ characters;
- key and credential file names (`.env`, `*.pem`, `id_rsa`, `.mcp.json`, `*.jsonl`, …);
- personal values: your home path, the repo and global `user.email`, and every line of
  `~/.config/dev-harness/personal-patterns.txt` (4+ characters, `#` lines skipped).
  `--no-personal` turns this group off for repos where those values are expected.
  A git email ending in `@users.noreply.github.com` is not treated as personal: it is public
  once used as a commit identity. A personal email that `git config` does not return (for
  example one set only through `includeIf`) is caught only when written into the patterns file.

Findings are printed masked (`ghp_••••`, `personal ••••`). `pre-push` scans every commit the
remote does not hold (asked with `git ls-remote`), so a secret added and later removed is still
caught. Any scanner or git error refuses the commit or push.

### Allow list

A token or generic finding on an added line is printed with a fingerprint (`fp:<16 hex>`, a
hash of path, rule and the whole line). When it is a false positive — test data, a placeholder
in documentation — open the line, then list it in `.dev-harness-allow` at the repo root and
commit that file with the line:

```
# <fp>  <path>:<line> <kind>
0123456789abcdef  docs/example.md:12 generic-secret
```

`pre-commit` reads the list from the index (what is being committed) and `pre-push` from each
pushed commit's own tree, so an entry added in a later commit does not clear an earlier one.
Editing the line or moving the file changes its fingerprint, and it is reported again. Every
finding let through is printed as `allowed by .dev-harness-allow: …`. Personal and file-name
findings, commit messages and tag messages carry no fingerprint and cannot be listed. A
`.dev-harness-allow` that is not a regular file (a directory, a symlink) refuses the commit.
The list is committed, so its fingerprints, paths and kinds are as public as the repo: list
only lines committed with their entry.

## Limits

`guard-hook-bypass` is a best-effort check of command text, not a gate: shell grammar is too
rich for a text check to close every spelling. The gates are the native `pre-push` scan, which
re-checks every commit the remote does not hold however it was made, and a server-side scan.
The guard reads command text. It refuses the skip-verify flag in any literal spelling
(quotes, escapes, line continuations), any brace expansion in a git command, `core.hooksPath` /
`GIT_CONFIG_*` overrides, any `alias.*` defined in the command, and — without parsing options or splitting the command — any single-dash word holding an `n`
after `commit` (so `git commit -n`, but also `-m -n` or `commit … && git log -n 1`; use `-F` or
separate commands for those). Text the shell builds at run time (variables,
command substitution, `$'\x..'` escapes, globbing, aliases, scripts) is out of its reach, and a
skipped local hook cannot be caught locally: enable a server-side scan such as GitHub push
protection as the last line.

The guard also keeps Claude from writing `.dev-harness-allow`: Write, Edit, MultiEdit and
NotebookEdit of that name (any letter case, also through a symlink) and any Bash command naming
it are denied, so only the user lists entries. It cannot see the file arrive by other routes —
`git apply` / `git am` / `patch`, `cp -r` or `tar x` of a directory holding it, checkout,
restore, merge, cherry-pick or stash of a branch carrying entries, or a clean filter. The
`allowed by .dev-harness-allow` notice and review of the committed list cover those.

## License

MIT — see [LICENSE](LICENSE).
