"""Tests for lib/shell_text.py, and for the two hooks that share it."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS))

from lib.shell_text import command_segments, without_heredoc_bodies  # noqa: E402

ENTRY_POINTS = ("block-fuzzy-kill.py", "guard-repo-discipline.py", "guard-hook-bypass.py")


class WithoutHeredocBodies(unittest.TestCase):
    def test_keeps_a_command_with_no_heredoc(self):
        self.assertEqual(without_heredoc_bodies("a\nb"), "a\nb")

    def test_drops_the_body_and_terminator(self):
        self.assertEqual(without_heredoc_bodies("cat <<EOF\nbody\nEOF\nnext"), "cat <<EOF\nnext")

    def test_quoted_delimiters(self):
        self.assertEqual(without_heredoc_bodies("cat <<'E'\nbody\nE\nnext"), "cat <<'E'\nnext")
        self.assertEqual(without_heredoc_bodies('cat <<"E"\nbody\nE\nnext'), 'cat <<"E"\nnext')

    def test_dash_form_allows_an_indented_terminator(self):
        self.assertEqual(without_heredoc_bodies("cat <<-E\n\tbody\n\tE\nnext"), "cat <<-E\nnext")

    def test_two_heredocs_on_one_line(self):
        self.assertEqual(without_heredoc_bodies("cat <<A <<B\none\nA\ntwo\nB\nnext"),
                         "cat <<A <<B\nnext")

    def test_here_string_has_no_body(self):
        self.assertEqual(without_heredoc_bodies("cat <<< x\nnext"), "cat <<< x\nnext")

    def test_unterminated_heredoc_drops_to_the_end(self):
        self.assertEqual(without_heredoc_bodies("cat <<EOF\nbody"), "cat <<EOF")


class CommandSegments(unittest.TestCase):
    def test_splits_on_control_operators(self):
        self.assertEqual(list(command_segments("git add x; echo hi && ls | wc")),
                         [["git", "add", "x"], ["echo", "hi"], ["ls"], ["wc"]])

    def test_drops_env_assignments_and_wrappers(self):
        self.assertEqual(list(command_segments("FOO=1 sudo env git status")), [["git", "status"]])

    def test_quoted_operator_stays_inside_one_word(self):
        self.assertEqual(list(command_segments('echo "a;b"')), [["echo", "a;b"]])

    def test_unbalanced_quote_falls_back_to_each_line(self):
        self.assertEqual(list(command_segments("echo it's\ngit add -A"))[-1], ["git", "add", "-A"])

    def test_heredoc_body_is_not_a_segment(self):
        self.assertEqual(list(command_segments("cat <<E\ngit add -A\nE")), [["cat", "<<E"]])


class EntryPoints(unittest.TestCase):
    def test_each_hook_imports_the_helper_from_any_working_directory(self):
        # A failed import exits non-zero, which Claude Code treats as non-blocking: the guard
        # would go quiet rather than red. Registered commands run from any project's cwd.
        with tempfile.TemporaryDirectory() as cwd:
            for name in ENTRY_POINTS:
                with self.subTest(hook=name):
                    proc = subprocess.run(
                        [sys.executable, str(HOOKS / name)], cwd=cwd, text=True,
                        input=json.dumps({"tool_input": {"command": "cat <<E\nbody\nE"}}),
                        capture_output=True, timeout=10)
                    self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, "", ""))

    def test_no_hook_keeps_a_private_copy(self):
        for name in ENTRY_POINTS:
            with self.subTest(hook=name):
                source = (HOOKS / name).read_text(encoding="utf-8")
                self.assertNotIn("def without_heredoc_bodies", source)
                self.assertIn("from lib.shell_text import", source)

    def test_guard_uses_the_shared_segmenter(self):
        source = (HOOKS / "guard-repo-discipline.py").read_text(encoding="utf-8")
        self.assertNotIn("def segments", source)
        self.assertNotIn("def tokens", source)
        self.assertIn("command_segments", source)


if __name__ == "__main__":
    unittest.main()
