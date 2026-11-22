"""Tests for scripts/score-attempt: four mechanical checks on an executor's attempt, JSON out."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCORER = Path(__file__).resolve().parent.parent.parent / "scripts" / "score-attempt"


class Attempt(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp()).resolve()
        self.git("init", "-q", "-b", "feat/x")
        self.commit("base.txt", "base")
        self.base = self.git("rev-parse", "HEAD")

    def tearDown(self):
        shutil.rmtree(self.repo)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@example.invalid",
                               "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, name, text="x"):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        self.git("add", name)
        self.git("commit", "-q", "-m", name)

    def score(self, *extra, test="true", base=None):
        args = [sys.executable, str(SCORER), "--repo", str(self.repo), "--base", base or self.base,
                "--test", test, *extra]
        proc = subprocess.run(args, capture_output=True, text=True, timeout=60)
        return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else None)

    def failed(self, result):
        return [c["name"] for c in result["checks"] if not c["pass"]]

    def test_a_good_attempt_passes(self):
        self.commit("src/a.py")
        code, result = self.score("--allow", "src/*.py")
        self.assertEqual((code, result["pass"], self.failed(result)), (0, True, []))
        for check in result["checks"]:
            self.assertEqual(set(check), {"name", "pass", "detail"})

    def test_no_commit_after_base(self):
        code, result = self.score()
        self.assertEqual((code, self.failed(result)), (1, ["commits"]))

    def test_base_not_an_ancestor(self):
        self.git("switch", "-q", "-c", "other", self.base)
        self.commit("other.txt")
        other = self.git("rev-parse", "HEAD")
        self.git("switch", "-q", "feat/x")
        self.commit("src/a.py")
        code, result = self.score(base=other)
        self.assertEqual(code, 1)
        self.assertIn("commits", self.failed(result))

    def test_dirty_and_untracked_trees(self):
        self.commit("src/a.py")
        (self.repo / "src" / "a.py").write_text("changed")
        self.assertEqual(self.failed(self.score()[1]), ["clean"])
        self.git("checkout", "--", "src/a.py")
        (self.repo / "new" / "deep").mkdir(parents=True)
        (self.repo / "new" / "deep" / "u.txt").write_text("u")
        self.assertEqual(self.failed(self.score()[1]), ["clean"])

    def test_failing_test_command(self):
        self.commit("src/a.py")
        code, result = self.score(test="exit 3")
        self.assertEqual((code, self.failed(result)), (1, ["tests"]))

    def test_test_runs_in_the_repo(self):
        self.commit("src/a.py")
        code, _ = self.score(test="test -f src/a.py")
        self.assertEqual(code, 0)

    def test_test_timeout(self):
        self.commit("src/a.py")
        code, result = self.score("--timeout", "1", test="sleep 5")
        self.assertEqual((code, self.failed(result)), (1, ["tests"]))

    def test_path_outside_the_allow_list(self):
        self.commit("src/a.py")
        self.commit("docs/b.md")
        code, result = self.score("--allow", "src/*.py")
        self.assertEqual((code, self.failed(result)), (1, ["scope"]))
        self.assertIn("docs/b.md", [c for c in result["checks"] if c["name"] == "scope"][0]["detail"])

    def test_star_does_not_cross_a_slash(self):
        self.commit("src/deep/a.py")
        self.assertEqual(self.failed(self.score("--allow", "src/*.py")[1]), ["scope"])
        self.assertEqual(self.failed(self.score("--allow", "src/**/*.py")[1]), [])

    def test_no_allow_list_skips_the_scope_check(self):
        self.commit("anywhere/a.txt")
        code, result = self.score()
        self.assertEqual((code, self.failed(result)), (0, []))

    def test_usage_errors_exit_2(self):
        for args in ([], ["--repo", str(self.repo)], ["--repo", str(self.repo), "--base", self.base]):
            with self.subTest(args=args):
                proc = subprocess.run([sys.executable, str(SCORER), *args], capture_output=True,
                                      text=True, timeout=30)
                self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
