"""End-to-end tests for the native git hooks: real temp repos, hooks installed by the installer.

Tokens and personal values are built at run time; HOME and the global git config are pointed
at the temp dir so the personal rules see injected values only.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent
SCRIPTS = HOOKS.parent / "scripts"
INSTALLER = SCRIPTS / "install-git-hooks"

UPPER, LOWER, DIGITS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz", "0123456789"


def body(n, alphabet=UPPER + LOWER + DIGITS):
    return "".join(alphabet[i % len(alphabet)] for i in range(n))


GITHUB_TOKEN = "gh" + "p_" + body(36)
OPENAI_TOKEN = "sk-" + "proj-" + body(74) + "T3Blbk" + "FJ" + body(74)
PEM = "\n".join(["-" * 5 + "BEGIN RSA PRIV" + "ATE KEY" + "-" * 5, body(64), body(64), body(64),
                 "-" * 5 + "END RSA PRIV" + "ATE KEY" + "-" * 5]) + "\n"
EMAIL = "someone" + "@example.org"


class Repo(unittest.TestCase):
    personal = True

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.home.mkdir()
        (self.home / ".gitconfig").write_text("")
        self.env = dict(os.environ, HOME=str(self.home), GIT_CONFIG_GLOBAL=str(self.home / ".gitconfig"),
                        GIT_CONFIG_NOSYSTEM="1", PYTHONDONTWRITEBYTECODE="1")
        self.env.pop("GIT_DIR", None)
        self.env.pop("GIT_INDEX_FILE", None)
        self.repo = self.tmp / "repo"
        self.remote = self.tmp / "remote.git"
        self.git("init", "-q", "-b", "main", str(self.repo), cwd=self.tmp)
        self.git("init", "-q", "--bare", str(self.remote), cwd=self.tmp)
        self.git("config", "user.email", EMAIL)
        self.git("config", "user.name", "T")
        self.git("remote", "add", "origin", str(self.remote))
        self.write("README.md", "hello\n")
        self.git("add", "README.md")
        self.git("commit", "-q", "-m", "init")
        self.git("push", "-q", "origin", "main")
        args = [sys.executable, str(INSTALLER)] + ([] if self.personal else ["--no-personal"]) + [str(self.repo)]
        subprocess.run(args, check=True, capture_output=True, env=self.env)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args, cwd=None, check=True):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, env=self.env,
                              capture_output=True, text=True, check=check)

    def sh(self, command):
        return subprocess.run(command, shell=True, cwd=self.repo, env=self.env, capture_output=True, text=True)

    def write(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


class PreCommit(Repo):
    def test_add_and_commit_in_one_command_is_rejected_and_masked(self):
        self.write("s.txt", f"key: '{GITHUB_TOKEN}'\n")
        result = self.sh("git add s.txt && git commit -m x")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("s.txt:1 github-pat ghp_", result.stderr)
        self.assertNotIn(GITHUB_TOKEN, result.stderr + result.stdout)

    def test_clean_commit_passes(self):
        self.write("ok.txt", "nothing to see\n")
        self.assertEqual(self.sh("git add ok.txt && git commit -q -m ok").returncode, 0)

    def test_commit_all_scans_the_temporary_index(self):
        self.write("README.md", f"hello {GITHUB_TOKEN}\n")
        self.assertNotEqual(self.sh("git commit -a -m x").returncode, 0)

    def test_binary_attribute_does_not_hide_content(self):
        self.write(".gitattributes", "* -diff\n")
        self.write("t.txt", OPENAI_TOKEN + "\n")
        result = self.sh("git add .gitattributes t.txt && git commit -m x")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("openai-api-key", result.stderr)

    def test_rename_to_a_key_file_name_is_rejected(self):
        self.write("a.txt", "plain\n")
        self.sh("git add a.txt && git commit -q -m a")
        result = self.sh("git mv a.txt .env && git commit -m x")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(".env:0 file-name", result.stderr)

    def test_private_key_in_an_ordinary_file_name(self):
        self.write("notes.txt", PEM)
        result = self.sh("git add notes.txt && git commit -m x")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("notes.txt:1 private-key-header", result.stderr)
        self.assertNotIn(body(64), result.stderr)

    def test_home_path_and_email_are_personal(self):
        for text in (f"see {self.home}/x\n", f"mail {EMAIL}\n"):
            with self.subTest(text=text.split()[0]):
                self.write("p.txt", text)
                result = self.sh("git add p.txt && git commit -m x")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("p.txt:1 personal ••••", result.stderr)
                self.git("reset", "-q")

    def test_missing_scanner_fails_closed(self):
        hooks_dir = Path(self.git("rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()) / "hooks"
        (hooks_dir / "secret_scan.py").unlink()
        self.write("ok.txt", "fine\n")
        result = self.sh("git add ok.txt && git commit -m ok")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("dev-harness", result.stderr)


    def test_installed_hook_never_loads_a_scanner_from_the_worktree(self):
        # A repo's own hooks/lib/secret_scan.py must not stand in for the installed copy.
        hooks_dir = self.repo / ".git" / "hooks"
        (hooks_dir / "secret_scan.py").unlink()
        self.write("hooks/lib/secret_scan.py", "raise SystemExit(0)\n")
        self.write("s.txt", GITHUB_TOKEN + "\n")
        result = self.sh("git add s.txt && git commit -m x")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("secret_scan.py not found", result.stderr)


    def test_source_tree_hook_uses_the_plugin_scanner(self):
        self.write("s.txt", GITHUB_TOKEN + "\n")
        self.git("add", "s.txt")
        result = subprocess.run([sys.executable, str(SCRIPTS / "git-hooks" / "pre-commit")], cwd=self.repo,
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("s.txt:1 github-pat", result.stderr)


class CommitMessage(Repo):
    def test_token_in_the_message_is_rejected_and_masked(self):
        self.write("ok.txt", "fine\n")
        self.git("add", "ok.txt")
        result = self.git("commit", "-m", f"debug: token was {GITHUB_TOKEN}", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("commit-msg:1 github-pat ghp_", result.stderr)
        self.assertNotIn(GITHUB_TOKEN, result.stderr + result.stdout)

    def test_home_path_in_the_message_is_rejected(self):
        self.write("ok.txt", "fine\n")
        self.git("add", "ok.txt")
        result = self.git("commit", "-m", f"see {self.home}/notes", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("personal", result.stderr)

    def run_commit_msg(self, text):
        message = self.tmp / "MSG"
        message.write_text(text)
        return subprocess.run([sys.executable, str(self.repo / ".git" / "hooks" / "commit-msg"), str(message)],
                              cwd=self.repo, env=self.env, capture_output=True, text=True)

    def test_hash_lines_are_scanned_because_dash_m_keeps_them(self):
        result = self.git("commit", "--allow-empty", "-m", f"#leak {GITHUB_TOKEN}", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("commit-msg:1 github-pat", result.stderr)

    def test_verbose_diff_below_the_scissors_skips_removed_and_context_lines(self):
        # `git commit -v` shows the staged diff; removing a secret must not be refused.
        result = self.run_commit_msg("remove leaked key\n"
                                     "# ------------------------ >8 ------------------------\n"
                                     "diff --git a/k.txt b/k.txt\n--- a/k.txt\n+++ b/k.txt\n@@ -1 +0,0 @@\n"
                                     f"-{GITHUB_TOKEN}\n {GITHUB_TOKEN}\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_free_text_below_the_scissors_is_scanned(self):
        result = self.run_commit_msg("subject\n# ------------------------ >8 ------------------------\n"
                                     f"note {GITHUB_TOKEN}\n")
        self.assertIn("commit-msg:3 github-pat", result.stderr)

    def test_body_token_is_reported_with_its_line(self):
        self.assertIn("commit-msg:2 github-pat", self.run_commit_msg(f"subject\nbody {GITHUB_TOKEN}\n").stderr)


class PrePush(Repo):
    def commit_skipping_hooks(self, name, text, message):
        self.write(name, text)
        self.git("add", name)
        self.git("commit", "-q", "--no-verify", "-m", message)

    def test_secret_added_then_removed_is_still_rejected(self):
        self.commit_skipping_hooks("k.txt", OPENAI_TOKEN + "\n", "add")
        self.commit_skipping_hooks("k.txt", "gone\n", "remove")
        self.git("branch", "other")
        for command in ("git push origin main", "git push origin other:main", "git push --all origin"):
            with self.subTest(command=command):
                result = self.sh(command)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("openai-api-key", result.stderr)

    def test_stale_tracking_ref_does_not_hide_a_commit(self):
        # The local origin/main claims the remote has the secret commit; the remote does not.
        self.commit_skipping_hooks("k.txt", OPENAI_TOKEN + "\n", "add")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        result = self.sh("git push origin main")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("openai-api-key", result.stderr)

    def test_history_the_remote_already_holds_is_not_rescanned(self):
        self.commit_skipping_hooks("k.txt", OPENAI_TOKEN + "\n", "old leak")
        self.git("push", "-q", "--no-verify", "origin", "main")
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        self.write("ok.txt", "fine\n")
        self.sh("git add ok.txt && git commit -q -m ok")
        result = self.sh("git push origin main")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unreachable_remote_fails_closed(self):
        self.write("ok.txt", "fine\n")
        self.sh("git add ok.txt && git commit -q -m ok")
        head = self.git("rev-parse", "HEAD").stdout.strip()
        missing = str(self.tmp / "missing.git")
        result = subprocess.run([sys.executable, str(self.repo / ".git" / "hooks" / "pre-push"), "origin", missing],
                                input=f"refs/heads/main {head} refs/heads/main {'0' * 40}\n", cwd=self.repo,
                                env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing", result.stderr)

    def test_private_key_committed_past_pre_commit_is_rejected_at_push(self):
        self.commit_skipping_hooks("notes.txt", PEM, "pem")
        result = self.sh("git push origin main")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("private-key-header", result.stderr)

    def test_token_in_a_commit_message_is_rejected_at_push(self):
        self.write("ok.txt", "fine\n")
        self.git("add", "ok.txt")
        self.git("commit", "-q", "--no-verify", "-m", f"oops {GITHUB_TOKEN}")
        result = self.sh("git push origin main")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("message:1 github-pat", result.stderr)
        self.assertNotIn(GITHUB_TOKEN, result.stderr)

    def test_token_in_an_annotated_tag_message_is_rejected_at_push(self):
        self.git("tag", "-a", "v1", "-m", f"release {GITHUB_TOKEN}")
        result = self.sh("git push origin v1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tag-message:1 github-pat", result.stderr)

    def test_clean_push_and_branch_delete_pass(self):
        self.write("ok.txt", "fine\n")
        self.sh("git add ok.txt && git commit -q -m ok")
        self.assertEqual(self.sh("git push -q origin main:side").returncode, 0)
        self.assertEqual(self.sh("git push -q origin :side").returncode, 0)


class NoPersonal(Repo):
    personal = False

    def test_home_path_passes_but_tokens_do_not(self):
        self.write("p.txt", f"path {self.home}/x\n")
        self.assertEqual(self.sh("git add p.txt && git commit -q -m p").returncode, 0)
        self.write("s.txt", GITHUB_TOKEN + "\n")
        self.assertNotEqual(self.sh("git add s.txt && git commit -m s").returncode, 0)


if __name__ == "__main__":
    unittest.main()
