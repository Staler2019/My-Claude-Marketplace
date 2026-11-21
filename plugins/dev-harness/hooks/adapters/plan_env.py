"""The filesystem side of require-plan-structure.py: the brief's Plan path, cited files, the user's words."""
import json
import os
import re
from typing import Optional

_PLAN_LINE = re.compile(r"(?m)^\s*Plan:\s*`?([^`\s]+)`?\s*$")
# Harness-injected spans inside a user turn; their text is not the user's.
_INJECTED = re.compile(r"<(system-reminder|task-notification|agent-message|local-command-stdout)\b.*?</\1>",
                       re.DOTALL)


def plan_path(brief: str, cwd: str) -> Optional[str]:
    """The `Plan: <path>` line of a dispatch brief, resolved against cwd."""
    found = _PLAN_LINE.search(brief or "")
    return os.path.normpath(os.path.join(cwd, os.path.expanduser(found.group(1)))) if found else None


def location_base(cwd: str) -> str:
    """The repo root holding cwd (`.git` dir, or a worktree's `.git` file), else cwd itself."""
    directory = os.path.realpath(cwd)
    while True:
        if os.path.exists(os.path.join(directory, ".git")):
            return directory
        parent = os.path.dirname(directory)
        if parent == directory:
            return os.path.realpath(cwd)
        directory = parent


def line_counter(base: str):
    def line_count(path: str) -> Optional[int]:
        full = os.path.join(base, os.path.expanduser(path))
        if not os.path.isfile(full):
            return None
        with open(full, "rb") as handle:
            return sum(1 for _ in handle)
    return line_count


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def user_words(transcript_path: str) -> str:
    """Everything the user typed in this session, whitespace removed; tool results and meta turns excluded."""
    texts = []
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                message = entry.get("message") or {}
                if entry.get("type") != "user" or entry.get("isMeta") or message.get("role") != "user":
                    continue
                content = message.get("content")
                if isinstance(content, str):
                    texts.append(content)
                elif isinstance(content, list):
                    texts.extend(block.get("text", "") for block in content
                                 if isinstance(block, dict) and block.get("type") == "text")
    except OSError:
        return ""
    return _squash(_INJECTED.sub("", "\n".join(texts)))


def quote_checker(transcript_path: str):
    said = user_words(transcript_path)
    return lambda quote: bool(_squash(quote)) and _squash(quote) in said
