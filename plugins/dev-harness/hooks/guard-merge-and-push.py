#!/usr/bin/env python3
"""PreToolUse guard: no merge, no push to or force over a default branch, no local default-branch
move — through Bash, PowerShell or an MCP tool — and no push at all from the executor.

Reads command text only: a push hidden in a script file or a variable is out of reach (README
Limits). A lookup the decision needs that fails or times out denies.
"""
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.shell_text import (  # noqa: E402
    nested_commands,
    raw_segments,
    strip_wrappers,
    without_heredoc_bodies,
)

PREFIX = "Blocked by dev-harness/guard-merge-and-push:"
EXECUTOR = "dev-harness:executor"
ALWAYS_DEFAULT = {"main", "master"}
MAX_DEPTH = 10
ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
REDIRECT = re.compile(r""">>?\|?\s*("[^"]*"|'[^']*'|[^\s;&|]+)""")
STDIN_REF = re.compile(r"^\s*(?:update|create|delete)\s+(\S+)", re.M)

GIT_VALUE_OPTIONS = {"-C", "-c", "--config-env", "--git-dir", "--work-tree", "--namespace",
                     "--super-prefix", "--exec-path", "--attr-source", "--list-cmds"}
# Shell words that may open a segment before the command they run (`then git push`, `{ git …`).
SHELL_KEYWORDS = {"!", "{", "}", "if", "then", "elif", "else", "fi", "while", "until", "do", "done"}
# Subcommands git runs itself; anything else may be a user alias.
GIT_BUILTINS = set("""add am annotate apply archive bisect blame branch bundle cat-file checkout
checkout-index cherry cherry-pick citool clean clone commit commit-tree config count-objects
describe diff diff-files diff-index diff-tree difftool fetch filter-branch for-each-ref
format-patch fsck gc grep gui hash-object help init init-db log ls-files ls-remote ls-tree
merge merge-base mergetool mv notes pull push range-diff read-tree rebase reflog remote repack
replace reset restore rev-list rev-parse revert rm send-email send-pack http-push shortlog show
show-branch show-ref sparse-checkout stash status submodule subtree switch symbolic-ref tag
update-index update-ref var verify-commit verify-tag version whatchanged worktree write-tree
maintenance""".split())
PUSH_LONG = ("all", "mirror", "prune", "force", "force-with-lease", "force-if-includes", "delete",
             "tags", "follow-tags", "set-upstream", "dry-run", "porcelain", "verbose", "quiet",
             "progress", "no-verify", "verify", "atomic", "signed", "repo", "receive-pack", "exec",
             "push-option", "recurse-submodules", "thin", "no-thin", "ipv4", "ipv6",
             "no-force-with-lease", "no-force-if-includes", "no-signed", "no-atomic")
PUSH_DANGEROUS = {"all", "mirror", "prune", "force", "force-with-lease", "force-if-includes"}
PUSH_VALUE = {"repo", "receive-pack", "exec", "push-option"}
BRANCH_MOVING = {"-f", "--force", "-M", "-m", "--move", "-C", "-c", "--copy", "-D", "-d", "--delete"}
GH_COMMANDS = set("""alias api attestation auth browse cache co codespace completion config
extension gist gpg-key help issue label org pr project release repo ruleset run search secret
ssh-key status variable workflow""".split())
API_VALUE = {"-X", "--method", "-f", "-F", "--field", "--raw-field", "--input", "-H", "--header",
             "-q", "--jq", "-t", "--template", "-p", "--preview", "--hostname", "--cache"}
API_WRITE_PATH = re.compile(
    r"(^|/)(merge|merges|merge-upstream)(/|$)|/git/refs(/|$)|/contents/|/branches/.+/rename$"
    r"|^repos/[^/]+/[^/]+/?$")


class Denied(Exception):
    pass


class LookupFailed(Exception):
    pass


def deny(rule: str):
    raise Denied(f"{PREFIX} {rule}")


class Repo:
    """Git state for the repository a command runs in, looked up on first need."""

    def __init__(self, cwd: str, env: dict):
        self.cwd, self.env = cwd, env
        self._defaults = None

    def git(self, *args) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(["git", "-c", "core.fsmonitor=false", *args], cwd=self.cwd,
                                  env=self.env, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise LookupFailed(str(error)) from error

    def defaults(self) -> set:
        if self._defaults is None:
            out = self.git("for-each-ref", "--format=%(symref)", "refs/remotes/*/HEAD")
            if out.returncode:
                raise LookupFailed(out.stderr.strip())
            names = {line.split("/", 3)[3] for line in out.stdout.split() if line.count("/") >= 3}
            self._defaults = ALWAYS_DEFAULT | names
        return self._defaults

    def is_default(self, name: str) -> bool:
        return name in ALWAYS_DEFAULT or name in self.defaults()

    def config(self, key: str):
        out = self.git("config", "--get", key)
        return out.stdout.strip() if out.returncode == 0 else None

    def current_branch(self):
        out = self.git("symbolic-ref", "-q", "--short", "HEAD")
        return out.stdout.strip() if out.returncode == 0 else None

    def upstream_branch(self):
        out = self.git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
        return out.stdout.strip().split("/", 1)[-1] if out.returncode == 0 else None

    def has_remote_push_config(self) -> bool:
        return self.git("config", "--get-regexp", r"^remote\..*\.push$").returncode == 0


def branch_name(ref: str) -> str:
    ref = ref.lstrip("+")
    for prefix in ("refs/heads/", "heads/"):
        if ref.startswith(prefix):
            return ref[len(prefix):]
    return ref


def is_push_config(key: str) -> bool:
    key = key.lower()
    return (key.startswith("push.") or (key.startswith("remote.") and key.endswith(".push"))
            or (key.startswith("branch.") and key.endswith(".merge")))


class Judge:
    def __init__(self, cwd: str, executor: bool):
        self.cwd, self.executor = cwd, executor

    # -- shell text ------------------------------------------------------------------------------
    def command(self, text: str, cwd: str, depth: int = 0) -> None:
        if depth > MAX_DEPTH:
            deny("command nesting too deep to judge")
        for nested in nested_commands(text):
            self.command(nested, cwd, depth + 1)
            for ref in STDIN_REF.findall(nested):
                if ref.startswith("refs/heads/") and Repo(cwd, dict(os.environ)).is_default(
                        branch_name(ref)):
                    deny(f"update-ref --stdin moves default branch {branch_name(ref)}")
        for target in REDIRECT.findall(without_heredoc_bodies(text)):
            if "refs/heads/" in target or "packed-refs" in target:
                deny("a redirect writes into the ref store")
        for words in raw_segments(text):
            env = dict(os.environ)
            for word in words:
                found = ASSIGNMENT.match(word)
                if not found:
                    break
                env[found.group(1)] = found.group(2)
            words = strip_wrappers(words)
            while words and words[0] in SHELL_KEYWORDS:
                words = strip_wrappers(words[1:])
            if not words:
                continue
            prog = words[0].rsplit("/", 1)[-1]
            if prog == "cd" and len(words) > 1:
                cwd = os.path.join(cwd, os.path.expanduser(words[1]))
            elif prog == "git":
                self.git(words[1:], Repo(cwd, env), depth)
            elif prog == "hub":
                if words[1:2] == ["api"]:
                    self.api(words[2:])
                else:
                    self.git(words[1:], Repo(cwd, env), depth)
            elif prog == "gh":
                self.gh(words[1:], cwd, depth)

    # -- git -------------------------------------------------------------------------------------
    def git(self, args: list, repo: Repo, depth: int, aliases: dict = None) -> None:
        aliases = dict(aliases or {})
        args = list(args)
        while args and args[0].startswith("-"):
            option = args.pop(0)
            name, eq, value = option.partition("=")
            if name in GIT_VALUE_OPTIONS and not eq and args:
                value = args.pop(0)
            if name == "-C":
                repo = Repo(os.path.join(repo.cwd, os.path.expanduser(value)), repo.env)
            elif name == "--git-dir":
                repo = Repo(repo.cwd, dict(repo.env, GIT_DIR=value))
            elif name in ("-c", "--config-env"):
                key, _, setting = value.partition("=")
                if is_push_config(key):
                    deny(f"`{name} {key}` changes where a push goes")
                if key.lower().startswith("alias."):
                    aliases[key[6:]] = setting
        if not args:
            return
        sub, rest = args[0], args[1:]
        if sub not in GIT_BUILTINS:
            expansion = aliases.get(sub)
            if expansion is None:
                expansion = repo.config(f"alias.{sub}")
            if expansion is not None:
                if depth >= MAX_DEPTH:
                    deny("alias nesting too deep to judge")
                if expansion.startswith("!"):
                    self.command(" ".join([expansion[1:], *map(shlex.quote, rest)]), repo.cwd,
                                 depth + 1)
                else:
                    self.git(shlex.split(expansion) + rest, repo, depth + 1, aliases)
                return
        if sub == "push":
            self.push(rest, repo)
        elif sub in ("send-pack", "http-push"):
            deny(f"git {sub} pushes refs directly")
        elif sub == "subtree" and "push" in rest:
            deny("git subtree push")
        elif sub == "branch":
            self.branch(rest, repo)
        elif sub == "update-ref":
            self.update_ref(rest, repo)
        elif sub == "fetch":
            for refspec in [w for w in rest if not w.startswith("-")][1:]:
                target = branch_name(refspec.split(":", 1)[1]) if ":" in refspec else ""
                if target and repo.is_default(target):
                    deny(f"git fetch into local default branch {target}")
        elif sub in ("checkout", "switch", "worktree"):
            for i, word in enumerate(rest):
                name, eq, value = word.partition("=")
                if name in ("-B", "-C", "--force-create"):
                    target = value if eq else (rest[i + 1] if i + 1 < len(rest) else "")
                    if target and repo.is_default(target):
                        deny(f"git {sub} {name} resets default branch {target}")
        elif sub == "rebase":
            positionals, skip = [], False
            for word in rest:
                if skip:
                    skip = False
                elif word in ("--onto", "-s", "--strategy", "-X", "--strategy-option", "-x",
                              "--exec"):
                    skip = True
                elif not word.startswith("-"):
                    positionals.append(word)
            if len(positionals) >= 2 and repo.is_default(positionals[-1]):
                deny(f"git rebase rewrites default branch {positionals[-1]}")

    def push(self, args: list, repo: Repo) -> None:
        if self.executor:
            deny("the executor never pushes; the main session pushes")
        flags, positionals, i = set(), [], 0
        while i < len(args):
            word = args[i]
            i += 1
            if word == "--":
                positionals.extend(args[i:])
                break
            if word.startswith("--"):
                name, eq, _ = word[2:].partition("=")
                # git takes a unique prefix of a long option; an ambiguous one counts as each.
                matches = [o for o in PUSH_LONG if o == name] or [
                    o for o in PUSH_LONG if o.startswith(name)]
                flags.update(matches)
                if len(matches) == 1 and matches[0] in PUSH_VALUE and not eq:
                    i += 1
            elif word.startswith("-") and len(word) > 1:
                for j, char in enumerate(word[1:]):
                    flags.add({"f": "force", "d": "delete", "u": "set-upstream"}.get(char, char))
                    if char == "o":
                        if j == len(word) - 2:
                            i += 1
                        break
            else:
                positionals.append(word)
        dangerous = flags & PUSH_DANGEROUS
        if dangerous:
            deny(f"git push --{sorted(dangerous)[0]}")
        refspecs = positionals[1:]
        for refspec in refspecs:
            if refspec.startswith("+"):
                deny(f"forced refspec {refspec}")
            if "*" in refspec:
                deny(f"wildcard refspec {refspec}")
            if ":" in refspec:
                destination = refspec.split(":", 1)[1]
            elif refspec in ("HEAD", "@"):
                destination = repo.current_branch() or ""
            else:
                destination = refspec
            name = branch_name(destination)
            if name and repo.is_default(name):
                deny(f"push to default branch {name}")
        if all(":" not in r for r in refspecs) and "delete" not in flags:
            if repo.config("push.default") == "matching":
                deny("push.default=matching pushes every branch")
            if repo.has_remote_push_config():
                deny("remote.<name>.push decides the destination")
            if not refspecs:
                for name in (repo.current_branch(), repo.upstream_branch()):
                    if name and repo.is_default(name):
                        deny(f"push from or to default branch {name}")

    def branch(self, args: list, repo: Repo) -> None:
        moving, names, skip = False, [], False
        for word in args:
            if skip:
                skip = False
            elif word in ("-u", "--set-upstream-to"):
                skip = True
            elif word.startswith("--"):
                moving |= word.split("=")[0] in BRANCH_MOVING
            elif word.startswith("-"):
                moving |= any(f"-{c}" in BRANCH_MOVING for c in word[1:])
            else:
                names.append(word)
        if not moving:
            return
        for name in names:
            if repo.is_default(branch_name(name)):
                deny(f"git branch moves or deletes default branch {name}")
        renaming = any(w in ("-M", "-m", "--move", "-C", "-c", "--copy") for w in args)
        current = repo.current_branch() if renaming and len(names) == 1 else None
        if current and repo.is_default(current):
            deny(f"git branch renames default branch {current}")

    def update_ref(self, args: list, repo: Repo) -> None:
        positionals, skip = [], False
        for word in args:
            if skip:
                skip = False
            elif word == "-m":
                skip = True
            elif not word.startswith("-"):
                positionals.append(word)
        if not positionals:
            return
        ref = positionals[0]
        if ref == "HEAD":
            current = repo.current_branch()
            if current and repo.is_default(current):
                deny(f"update-ref HEAD while on default branch {current}")
        elif ref.startswith("refs/heads/") and repo.is_default(branch_name(ref)):
            deny(f"update-ref moves default branch {branch_name(ref)}")

    # -- gh --------------------------------------------------------------------------------------
    def gh(self, args: list, cwd: str, depth: int) -> None:
        positionals, i = [], 0
        while i < len(args) and len(positionals) < 2:
            word = args[i]
            i += 1
            if word in ("-R", "--repo", "--hostname"):
                i += 1
            elif not word.startswith("-"):
                positionals.append((i - 1, word))
        if not positionals:
            return
        first_at, top = positionals[0]
        if top not in GH_COMMANDS:
            expansion = gh_alias(top)
            if expansion is not None:
                rest = args[first_at + 1:]
                if depth >= MAX_DEPTH:
                    deny("alias nesting too deep to judge")
                if expansion.startswith("!"):
                    self.command(" ".join([expansion[1:], *map(shlex.quote, rest)]), cwd, depth + 1)
                else:
                    self.gh(shlex.split(expansion) + rest, cwd, depth + 1)
                return
        sub_at, sub = positionals[1] if len(positionals) > 1 else (len(args), "")
        if top == "pr" and sub == "merge":
            deny("gh pr merge")
        if top == "repo" and sub == "sync":
            deny("gh repo sync")
        if top == "repo" and sub == "edit" and any(
                w.split("=")[0] == "--default-branch" for w in args):
            deny("gh repo edit --default-branch")
        if top == "api":
            self.api(args[first_at + 1:])

    def api(self, args: list) -> None:
        method, fields, has_input, positionals, i = None, [], False, [], 0
        while i < len(args):
            word = args[i]
            i += 1
            if word.startswith("--") and "=" in word:
                name, value = word.split("=", 1)
            elif word.startswith("-X") and len(word) > 2:
                name, value = "-X", word[2:]
            elif word in API_VALUE:
                name, value = word, args[i] if i < len(args) else ""
                i += 1
            elif word.startswith("-"):
                continue
            else:
                positionals.append(word)
                continue
            if name in ("-X", "--method"):
                method = value.upper()
            elif name in ("-f", "-F", "--field", "--raw-field"):
                fields.append(value)
            elif name == "--input":
                has_input = True
        path = positionals[0].lstrip("/").split("?")[0] if positionals else ""
        if path == "graphql":
            for value in fields:
                key, _, body = value.partition("=")
                if key == "query" and ("mutation" in body.lower() or body.startswith("@")):
                    deny("GraphQL mutation through gh api")
            if has_input:
                deny("GraphQL query from --input")
            return
        method = method or ("POST" if fields or has_input else "GET")
        if method != "GET" and API_WRITE_PATH.search(path):
            deny(f"gh api {method} {path}")

    # -- MCP -------------------------------------------------------------------------------------
    def mcp(self, tool_name: str, tool_input: dict) -> None:
        tool = tool_name.rsplit("__", 1)[-1]
        if "merge" in tool.lower():
            deny(f"MCP tool {tool_name}")
        repo = Repo(self.cwd, dict(os.environ))
        for key in ("branch", "base"):
            value = tool_input.get(key)
            if isinstance(value, str) and repo.is_default(branch_name(value)):
                deny(f"MCP tool {tool_name} writes to default branch {value}")


def gh_alias(name: str):
    try:
        out = subprocess.run(["gh", "alias", "list"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in out.stdout.splitlines():
        alias, sep, expansion = line.partition(":")
        if sep and alias.strip() == name:
            return expansion.strip().strip("'\"")
    return None


def decide(payload: dict):
    cwd = payload.get("cwd") or os.getcwd()
    judge = Judge(cwd, payload.get("agent_type") == EXECUTOR)
    tool_name = payload.get("tool_name") or "Bash"
    tool_input = payload.get("tool_input") or {}
    try:
        if tool_name.startswith("mcp__"):
            judge.mcp(tool_name, tool_input)
        else:
            judge.command(tool_input.get("command") or "", cwd)
    except Denied as denied:
        return str(denied)
    except LookupFailed as failed:
        return (f"{PREFIX} could not read the default branch ({failed or 'git lookup failed'}); "
                "run `git remote set-head <remote> --auto` and retry")
    return None


def main() -> None:
    try:
        payload = json.load(sys.stdin.buffer)
    except ValueError:
        return
    if not isinstance(payload, dict):
        return
    reason = decide(payload)
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}))


main()
