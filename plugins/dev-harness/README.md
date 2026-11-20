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

Findings are printed masked (`ghp_••••`, `personal ••••`). `pre-push` scans every commit the
remote does not hold (asked with `git ls-remote`), so a secret added and later removed is still
caught. Any scanner or git error refuses the commit or push.

## Limits

`guard-hook-bypass` reads command text. It refuses the skip-verify flag in any literal spelling
(quotes, escapes, line continuations), any brace expansion in a git command, `core.hooksPath` /
`GIT_CONFIG_*` overrides, and — without parsing options — any single-dash word holding an `n`
after `commit` (so `git commit -n`, but also a message such as `-m -n`; use `-F` for those). Text the shell builds at run time (variables,
command substitution, `$'\x..'` escapes, globbing, aliases, scripts) is out of its reach, and a
skipped local hook cannot be caught locally: enable a server-side scan such as GitHub push
protection as the last line.

## License

MIT — see [LICENSE](LICENSE).
