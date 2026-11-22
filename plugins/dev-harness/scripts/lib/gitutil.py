"""Helpers shared by the dev-harness scripts."""
import subprocess
import sys


def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True).stdout.strip()


def fail(prefix: str, message: str) -> int:
    print(f"{prefix}: {message}", file=sys.stderr)
    return 1
