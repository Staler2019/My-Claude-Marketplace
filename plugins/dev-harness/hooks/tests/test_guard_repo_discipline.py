"""Tests for guard-repo-discipline.py: stdin JSON in, a deny decision (or nothing) out."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

HOOK = Path(os.environ.get("HOOK_UNDER_TEST",
                           Path(__file__).resolve().parent.parent / "guard-repo-discipline.py"))


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

    def test_blanket_git_add(self):
        self.assert_denied("git add -A", "git add --all", "git add .", "git add -Av",
                           "git add src/a.cpp .", "git add -- .")

    def test_commit_all(self):
        self.assert_denied("git commit -a", "git commit -am 'x'", "git commit --all -m x")

    def test_checkout_overwriting_files(self):
        self.assert_denied("git checkout -- a.txt", "git checkout HEAD -- a.txt", "git checkout .")

    def test_fullscreen_screencapture(self):
        self.assert_denied("screencapture out.png", "screencapture -x out.png",
                           "/usr/sbin/screencapture out.png")

    def test_found_behind_operators_wrappers_and_git_options(self):
        self.assert_denied("cd x && git add -A", "true; git add .", "true\ngit add -A",
                           "echo $(git add -A)", "echo `git add -A`", "sudo git add -A",
                           "FOO=1 git add -A", "git -C /tmp/r add -A",
                           "git -c a.b=c commit -a", "(screencapture out.png)")

    def test_unparseable_quote_still_guarded_per_line(self):
        self.assert_denied("echo it's\ngit add -A")

    def test_command_after_a_heredoc_ends(self):
        self.assert_denied("cat <<EOF\nbody\nEOF\ngit add -A",
                           "cat <<A <<B\none\nA\ntwo\nB\ngit add -A",
                           "cat <<-EOF\n\tbody\n\tEOF\ngit add -A")

    def test_here_string_has_no_body_to_skip(self):
        self.assert_denied("cat <<< x\ngit add -A")

    def test_command_on_the_line_after_a_comment(self):
        self.assert_denied("echo a # note\ngit add -A")


class Allowed(unittest.TestCase):
    def assert_allowed(self, *commands):
        for command in commands:
            with self.subTest(command=command):
                self.assertIsNone(decide(command))

    def test_staging_by_file(self):
        self.assert_allowed("git add a.txt b/c.py", "git add -p a.txt", "git add -- a.txt",
                            "git add ./a.txt")

    def test_ordinary_commit(self):
        self.assert_allowed("git commit -m 'x'", "git commit --amend -m x", "git commit -F msg.txt",
                            "git commit -mall", "git commit -Fa.txt")

    def test_checkout_switching_branches(self):
        self.assert_allowed("git checkout main", "git checkout -b topic", "git checkout -",
                            "git checkout main --")

    def test_window_scoped_screencapture(self):
        self.assert_allowed("screencapture -R10,20,300,400 out.png",
                            "screencapture -x -R 10,20,300,400 out.png",
                            "screencapture -xR10,20,300,400 out.png",
                            "screencapture -l 1234 out.png")

    def test_quoted_text_is_not_a_command(self):
        self.assert_allowed("git commit -m 'never git add -A; git add .'",
                            'echo "git checkout -- a.txt && screencapture out.png"')

    def test_comment_is_not_a_command(self):
        self.assert_allowed("# git add -A\ngit status")

    def test_heredoc_body_is_not_a_command(self):
        self.assert_allowed("cat <<EOF\nrun `git add -A` never\nEOF",
                            "gh pr create --body-file - <<'E'\n- `git add .`\nE\ngit status",
                            'cat <<"EOF"\ngit add -A\nEOF',
                            "cat <<-EOF\n\tgit add -A\n\tEOF",
                            "cat <<A <<B\none\nA\ngit add -A\nB")

    def test_other_programs(self):
        self.assert_allowed("ls -A", "grep -a add .", "gitk --all", "git status .", "git log --all")

    def test_bad_stdin_is_ignored(self):
        for data in ("not json", "[]", "{}"):
            with self.subTest(data=data):
                proc = subprocess.run([sys.executable, str(HOOK)], input=data, text=True,
                                      capture_output=True, timeout=10)
                self.assertEqual((proc.returncode, proc.stdout), (0, ""))


class WhateverTheConsoleEncoding(unittest.TestCase):
    """Claude Code sends UTF-8; a Windows console code page must not make the guard fail open."""

    def test_denies_a_utf8_command_with_chinese_text(self):
        stdin = json.dumps({"tool_input": {"command": 'git add -A && echo "这个功能已经完成了，请测试一下"'}}, ensure_ascii=False).encode()
        proc = subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True,
                              timeout=10, env={**os.environ, "PYTHONIOENCODING": "cp950"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        decision = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]
        self.assertEqual(decision, "deny")


if __name__ == "__main__":
    unittest.main()
