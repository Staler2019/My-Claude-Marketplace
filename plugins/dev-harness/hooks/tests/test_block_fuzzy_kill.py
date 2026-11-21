"""Tests for block-fuzzy-kill.py: stdin JSON in, a deny decision (or nothing) out."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

HOOK = Path(os.environ.get("HOOK_UNDER_TEST",
                           Path(__file__).resolve().parent.parent / "block-fuzzy-kill.py"))


def decide(command):
    proc = subprocess.run([sys.executable, str(HOOK)],
                          input=json.dumps({"tool_input": {"command": command}}),
                          text=True, capture_output=True, timeout=10)
    assert proc.returncode == 0, proc.stderr
    if not proc.stdout.strip():
        return None
    return json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]


class Denied(unittest.TestCase):
    def assert_denied(self, *commands):
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(decide(command), "deny")

    def test_name_and_group_kills(self):
        self.assert_denied("pkill foo", "killall foo", "kill -9 -1", "kill %1", "kill foo")

    def test_kill_fed_by_a_substitution(self):
        self.assert_denied("kill $(pgrep foo)", "kill `pgrep foo`")

    def test_command_after_a_heredoc_ends(self):
        self.assert_denied("cat <<EOF\nbody\nEOF\npkill foo",
                           "cat <<EOF\nbody\nEOF\nkill $(pgrep foo)",
                           "cat <<-EOF\n\tbody\n\tEOF\npkill foo")

    def test_here_string_has_no_body_to_skip(self):
        self.assert_denied("cat <<< x\npkill foo")


class Allowed(unittest.TestCase):
    def assert_allowed(self, *commands):
        for command in commands:
            with self.subTest(command=command):
                self.assertIsNone(decide(command))

    def test_plain_pids(self):
        self.assert_allowed("kill 123", "kill -9 123 456", "kill -l", "pgrep foo")

    def test_heredoc_body_is_not_a_command(self):
        self.assert_allowed("cat <<EOF\n- `pkill` is banned\nEOF",
                            "gh pr create --body-file - <<'E'\npkill foo\nE\ngit status",
                            "cat <<EOF\nkill $(pgrep foo)\nEOF",
                            "cat <<-EOF\n\tpkill foo\n\tEOF",
                            "cat <<A <<B\none\nA\npkill foo\nB")

    def test_bad_stdin_is_ignored(self):
        for data in ("not json", "[]", "{}"):
            with self.subTest(data=data):
                proc = subprocess.run([sys.executable, str(HOOK)], input=data, text=True,
                                      capture_output=True, timeout=10)
                self.assertEqual((proc.returncode, proc.stdout), (0, ""))


class WhateverTheConsoleEncoding(unittest.TestCase):
    """Claude Code sends UTF-8; a Windows console code page must not make the guard fail open."""

    def test_denies_a_utf8_command_with_chinese_text(self):
        stdin = json.dumps({"tool_input": {"command": 'pkill foo && echo "这个功能已经完成了，请测试一下"'}}, ensure_ascii=False).encode()
        proc = subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True,
                              timeout=10, env={**os.environ, "PYTHONIOENCODING": "cp950"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        decision = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]
        self.assertEqual(decision, "deny")


if __name__ == "__main__":
    unittest.main()
