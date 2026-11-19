#!/usr/bin/env python3
"""PreToolUse(Bash|PowerShell): copy local work aside before a git command that can discard it.

Caught, behind operators, wrappers and git options, in the directory a preceding
`cd`/`Set-Location` or `git -C` names:
  reset (every form) . restore . rm (not --cached) . clean (not -n/--dry-run)
  checkout over files (`--`, `.`, -f/--force, -p, --ours/--theirs, `<tree> <path>`)
  switch -f/--force/--discard-changes . merge/rebase/cherry-pick/revert/am --abort
Backed up: modified tracked, staged and untracked-not-ignored files (worktree copies under
files/), plus whatever `git clean -n` with the same options would remove (ignored files too
under -x/-X), unstaged.patch and staged.patch (binary diffs, so staged content that differs
from the worktree survives) and info.txt (HEAD, command).
Destination: $GIT_DISCARD_BACKUP_ROOT, else $CLAUDE_CONFIG_DIR/backups/git-discard, else
~/.claude/backups/git-discard (each env value used only when non-empty and absolute), then
<repo>-<time>/.
Retention: before each backup, backups older than $GIT_DISCARD_BACKUP_DAYS (default 14) are
removed, then the oldest go until the new one fits under $GIT_DISCARD_BACKUP_MAX_BYTES
(default 2 GiB); only directories holding this hook's info.txt are ever removed. A single
backup over the cap denies the command instead of being made.
A clean tree is not backed up. A backup that fails denies the command: the rule this
enforces is "never discard without a copy", so failing open would defeat it.
Not a sandbox: `bash -c "..."`, `eval` and aliases are not looked into.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from lib.shell_text import command_segments

GIT_OPTIONS_WITH_VALUE = ("-C", "-c", "--git-dir", "--work-tree", "--namespace")
CD_COMMANDS = ("cd", "pushd", "set-location", "sl", "chdir")
ABORTABLE = ("merge", "rebase", "cherry-pick", "revert", "am")
CHECKOUT_VALUE_OPTIONS = ("-b", "-B", "--orphan", "--conflict", "--pathspec-from-file")


def short_flags(arg: str) -> str:
    return arg[1:] if re.match(r"^-[A-Za-z]", arg) else ""


def checkout_discards(rest: list) -> bool:
    positional, i = [], 0
    while i < len(rest):
        a = rest[i]
        if a in ("--", ".", "-f", "--force", "-p", "--patch", "--ours", "--theirs"):
            return True
        flags = short_flags(a)
        if flags and not a.startswith("--"):
            if "f" in flags or "p" in flags:
                return True
            if flags[-1] in "bB":
                i += 1  # the cluster's last flag takes the next word as its branch name
        elif a in CHECKOUT_VALUE_OPTIONS:
            i += 1
        elif not a.startswith("-"):
            positional.append(a)
        i += 1
    return len(positional) >= 2  # `checkout <tree> <path>...` overwrites the paths


def discards(sub: str, rest: list) -> bool:
    if "-h" in rest or "--help" in rest:
        return False
    if sub in ("reset", "restore"):
        return True
    if sub == "rm":
        return "--cached" not in rest
    if sub == "clean":
        return not ("--dry-run" in rest
                    or any("n" in short_flags(a) for a in rest if not a.startswith("--")))
    if sub == "checkout":
        return checkout_discards(rest)
    if sub == "switch":
        return any(a in ("--force", "--discard-changes") or
                   ("f" in short_flags(a) and not a.startswith("--")) for a in rest)
    if sub in ABORTABLE:
        return "--abort" in rest
    return False


def native_path(text: str, base: Path) -> Path:
    text = os.path.expanduser(text)
    drive = re.match(r"^/([A-Za-z])(/|$)", text)
    if os.name == "nt" and drive:  # Git Bash's /c/Users -> C:/Users
        text = f"{drive.group(1)}:/{text[3:]}"
    return (base / text).resolve()


def discarding_commands(cmd: str, cwd: Path):
    """Yield (directory, subcommand, args) for each git command that can discard local work."""
    here = cwd
    for words in command_segments(cmd):
        prog = words[0].rsplit("/", 1)[-1].lower()
        if prog in CD_COMMANDS:
            args = [a for a in words[1:] if not a.startswith("-")]
            if args:
                here = native_path(args[0], here)
            continue
        if prog not in ("git", "git.exe"):
            continue
        where, args = here, words[1:]
        while args and args[0].startswith("-"):
            if args[0] == "-C" and len(args) > 1:
                where = native_path(args[1], where)
            args = args[2:] if args[0] in GIT_OPTIONS_WITH_VALUE else args[1:]
        if args and discards(args[0], args[1:]):
            yield where, args[0], args[1:]


def git(where: Path, *args) -> bytes:
    return subprocess.run(["git", "-C", str(where), *args], check=True,
                          capture_output=True, timeout=60).stdout


def toplevel(where: Path):
    if not where.is_dir():
        return None
    proc = subprocess.run(["git", "-C", str(where), "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True, timeout=30)
    return Path(proc.stdout.strip()).resolve() if proc.returncode == 0 else None


def names(top: Path, *args) -> set:
    return {n for n in git(top, *args, "-z").decode("utf-8", "replace").split("\0") if n}


def clean_victims(where: Path, top: Path, rest: list) -> set:
    """What `git clean` with these options would remove, relative to the top level."""
    args = []
    for a in rest:
        # -i would prompt; -q would hide the very "Would remove" lines read below.
        if a in ("-i", "--interactive", "-q", "--quiet"):
            continue
        if short_flags(a) and not a.startswith("--"):
            a = "-" + short_flags(a).replace("i", "").replace("q", "")
            if a == "-":
                continue
        args.append(a)
    out = git(where, "clean", "-n", *args).decode("utf-8", "replace")
    victims = set()
    for line in out.splitlines():
        if line.startswith("Would remove "):
            path = (where / line[len("Would remove "):].rstrip("/")).resolve()
            victims.add(path.relative_to(top).as_posix())
    return victims


def changed_paths(top: Path) -> set:
    return (names(top, "diff", "--name-only") | names(top, "diff", "--cached", "--name-only")
            | names(top, "ls-files", "--others", "--exclude-standard"))


def tree_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if not path.is_dir() or (path / ".git").exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def prune(root: Path, keep_days: float, max_bytes: int, incoming: int) -> None:
    """Drop backups older than keep_days, then oldest first until incoming fits under max_bytes.

    Only directories holding an info.txt (one this hook wrote) are ever removed.
    """
    if not root.is_dir():
        return
    found = sorted(((d / "info.txt").stat().st_mtime, d) for d in root.iterdir()
                   if (d / "info.txt").is_file())
    cutoff = time.time() - keep_days * 86400
    kept = []
    for mtime, d in found:
        if mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)
        else:
            kept.append((d, tree_size(d)))
    total = sum(size for _, size in kept) + incoming
    for d, size in kept:
        if total <= max_bytes:
            break
        shutil.rmtree(d, ignore_errors=True)
        total -= size


def backup(top: Path, paths: set, command: str, root: Path):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = root / f"{top.name}-{stamp}-{os.getpid()}"
    files = dest / "files"
    files.mkdir(parents=True)
    copied = 0
    for rel in sorted(paths):
        src, out = top / rel, files / rel
        if src.is_dir() and not (src / ".git").exists():  # a directory `git clean -d` removes
            shutil.copytree(src, out, dirs_exist_ok=True)
            copied += 1
        elif src.is_file():  # deleted files are in the patches; submodules are skipped
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out)
            copied += 1
    (dest / "unstaged.patch").write_bytes(git(top, "diff", "--binary"))
    (dest / "staged.patch").write_bytes(git(top, "diff", "--cached", "--binary"))
    head = subprocess.run(["git", "-C", str(top), "rev-parse", "HEAD"], capture_output=True,
                          text=True, timeout=30).stdout.strip() or "(no commits)"
    (dest / "info.txt").write_text(f"repo: {top}\nHEAD: {head}\ncommand: {command}\n"
                                   f"copied: {copied} of {len(paths)} paths\n",
                                   encoding="utf-8")
    return dest


def emit(payload: dict) -> None:
    # ASCII-escaped: a cp1252 console (GitHub's Windows runner) cannot encode the Chinese text.
    print(json.dumps(payload))


def backup_root() -> Path:
    explicit = os.environ.get("GIT_DISCARD_BACKUP_ROOT") or ""
    if os.path.isabs(explicit):
        return Path(explicit)
    profile = os.environ.get("CLAUDE_CONFIG_DIR") or ""
    if os.path.isabs(profile):
        return Path(profile) / "backups" / "git-discard"
    return Path.home() / ".claude" / "backups" / "git-discard"


def deny(reason: str) -> None:
    emit({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": f"Blocked by dev-harness/backup-before-git-discard: {reason}",
    }})


def main() -> None:
    try:
        data = json.load(sys.stdin.buffer)
        cmd = data.get("tool_input", {}).get("command", "") or ""
        cwd = Path(data.get("cwd") or os.getcwd())
    except (ValueError, AttributeError):
        return
    if "git" not in cmd:
        return
    root = backup_root()
    keep_days = float(os.environ.get("GIT_DISCARD_BACKUP_DAYS") or "14")
    max_bytes = int(os.environ.get("GIT_DISCARD_BACKUP_MAX_BYTES") or 2 * 1024 ** 3)
    made = []
    try:
        plan = {}
        for where, sub, rest in discarding_commands(cmd, cwd):
            top = toplevel(where)
            if top is None:
                continue
            paths = plan.setdefault(top, set())
            if sub == "clean":
                paths |= clean_victims(where, top, rest)
        for top, paths in plan.items():
            paths |= changed_paths(top)
            if not paths:
                continue
            incoming = sum(tree_size(top / rel) for rel in paths)
            if incoming > max_bytes:
                deny(f"the local files to back up in {top} total {incoming} bytes, over the "
                     f"{max_bytes}-byte cap (GIT_DISCARD_BACKUP_MAX_BYTES). Narrow the command "
                     "or copy the work aside by hand, then retry.")
                return
            try:
                prune(root, keep_days, max_bytes, incoming)
            except OSError:
                pass  # a failed prune leaves old backups behind; it must not block this one
            made.append(backup(top, paths, cmd, root))
    except Exception as exc:  # noqa: BLE001 -- any failure must stop the discard
        deny(f"backing up local files first failed ({type(exc).__name__}: {exc}). "
             "Copy the work aside by hand, then retry.")
        return
    if made:
        where = ", ".join(str(d) for d in made)
        emit({
            "systemMessage": f"git 指令可能丟失本機檔案，已先備份：{where}",
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": f"Local files were backed up before the git command to: {where}",
            },
        })


main()
