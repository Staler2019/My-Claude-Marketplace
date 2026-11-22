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
| `agents/` | Eight read-only roles: `scout`, `Explore`, `algorithm-chooser`, `arch-suggester`, `spec-auditor`, `plan-verifier`, `security-reviewer`, `verifier` (the last one may run tests). One write-capable role, `executor`: does one approved Plan unit in the current directory or bails out, never pushes, and ends with `EXECUTOR: DONE <first-sha>..<last-sha>` or `EXECUTOR: BAIL <one-line reason>`. |
| `skills/` | `plan-preflight` (self-check a Plan before review) and the `arch-suggester` checklist. |
| `hooks/hooks.json` | PreToolUse guards: `guard-hook-bypass` (no skipping git hooks), `guard-repo-discipline` (stage by file, no blanket checkout), `block-fuzzy-kill`, `backup-before-git-discard`, `require-plan-structure`; `guard-merge-and-push` (Bash, PowerShell and `mcp__*` tools: no merge, no push to or force over a default branch, no local default-branch move, no push at all from the executor); `guard-write-scope` (Write/Edit in every session: no write into `.git/hooks`, `.git/config`, the profile's `settings*.json` or `plugins/`, or the loaded plugin directory). |
| `scripts/install-git-hooks` | Installs the secret scanner as native `pre-commit`, `pre-merge-commit`, `commit-msg` and `pre-push` hooks in one repo. |
| `scripts/score-attempt` | Scores one executor attempt: commits after the base, clean tree, test command passes, changed paths inside `--allow` globs; prints JSON, exits 0 pass / 1 fail / 2 usage. |

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

`guard-merge-and-push` is also a check of command text. It sees through wrappers (`sudo`, `env`,
`timeout`, `nice`, …), `sh -c`, `eval`, heredocs fed to a shell or to `git … --stdin`, and git and
gh aliases. A push or merge made from a script file, a variable, `curl` with a token, a
PowerShell backtick escape, an MCP shell or filesystem server, or a `gh api` body read from a
file beyond the listed forms is out of its reach; a server-side branch protection rule is the
gate. The default-branch set is `main`, `master` and every `refs/remotes/<remote>/HEAD`; when
that lookup fails the guard denies and names `git remote set-head <remote> --auto`. Through
MCP, a tool whose `base` is a default branch is denied too, including a pull request into one;
`gh pr create` is the route for that.

The executor's no-push rule has the same reach. The executor is not isolated: it runs in the
current directory with the user's environment, network and credentials, so a push hidden from
command text would succeed. Choosing the executor's model tier, and capping it, is the dispatcher's
job, not this plugin's.

`guard-write-scope` covers the Write, Edit, MultiEdit and NotebookEdit tools only; a Bash write
to `.git/hooks`, git config, the profile or the plugin directory is not caught. When the plugin
is loaded from a working checkout, that checkout's plugin directory is not editable from a
session that loads it; edit it from a session without the plugin.

## License

MIT — see [LICENSE](LICENSE).
