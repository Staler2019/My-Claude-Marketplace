"""Tests for guard-merge-and-push.py: stdin JSON in, a deny decision (or nothing) out."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "guard-merge-and-push.py"
PREFIX = "Blocked by dev-harness/guard-merge-and-push:"
EXECUTOR = "dev-harness:executor"


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def run_hook(payload, cwd):
    proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, timeout=30, cwd=str(cwd))
    assert proc.returncode == 0, proc.stderr
    if not proc.stdout.strip():
        return None
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny", out
    return out["permissionDecisionReason"]


class Repo(unittest.TestCase):
    """A clone on `feat/x` tracking `origin/feat/x`, with `origin/HEAD` → `main`."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        origin, seed = self.tmp / "origin.git", self.tmp / "seed"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(origin))
        git(self.tmp, "init", "-q", "-b", "main", str(seed))
        git(seed, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q",
            "--allow-empty", "-m", "root")
        git(seed, "push", "-q", str(origin), "main", "main:feat/x")
        self.repo = self.tmp / "repo"
        git(self.tmp, "clone", "-q", str(origin), str(self.repo))
        git(self.repo, "switch", "-q", "feat/x")
        git(self.repo, "config", "push.default", "simple")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def bash(self, command, agent_type=None, tool="Bash", cwd=None):
        payload = {"tool_name": tool, "tool_input": {"command": command}, "cwd": str(cwd or self.repo)}
        if agent_type:
            payload["agent_type"] = agent_type
        return run_hook(payload, cwd or self.repo)

    def mcp(self, tool_name, **tool_input):
        return run_hook({"tool_name": tool_name, "tool_input": tool_input, "cwd": str(self.repo)},
                        self.repo)

    def assert_denied(self, *commands, **kw):
        for command in commands:
            with self.subTest(command=command):
                reason = self.bash(command, **kw)
                self.assertIsNotNone(reason, command)
                self.assertTrue(reason.startswith(PREFIX), reason)

    def assert_allowed(self, *commands, **kw):
        for command in commands:
            with self.subTest(command=command):
                self.assertIsNone(self.bash(command, **kw))


class Merge(Repo):
    def test_gh_pr_merge(self):
        self.assert_denied("gh pr merge 1", "gh pr merge --squash --delete-branch 1",
                           "gh pr -R o/r merge 1", "gh -R o/r pr merge 1", "GH_TOKEN=x gh pr merge 1")

    def test_gh_repo_sync_and_default_branch_edit(self):
        self.assert_denied("gh repo sync", "gh repo sync o/r --force",
                           "gh repo edit --default-branch dev", "gh repo edit o/r --default-branch=dev")

    def test_gh_api_writes_to_merge_and_ref_endpoints(self):
        self.assert_denied(
            "gh api -X PUT repos/o/r/pulls/1/merge",
            "gh api --method=PUT /repos/o/r/pulls/1/merge",
            "gh api repos/o/r/merges -f base=main -f head=x",
            "gh api -X POST repos/o/r/merge-upstream",
            "gh api -X PATCH repos/o/r/git/refs/heads/main -f sha=abc",
            "gh api -X DELETE repos/o/r/git/refs/heads/x",
            "gh api repos/o/r/contents/a.txt -f message=m -f content=eA==",
            "gh api -X POST repos/o/r/branches/main/rename -f new_name=old",
            "gh api -X PATCH repos/o/r -f default_branch=dev",
            "hub api -X PUT repos/o/r/pulls/1/merge",
        )

    def test_gh_api_graphql_mutations(self):
        self.assert_denied(
            "gh api graphql -f query='mutation { mergePullRequest(input: {}) { clientMutationId } }'",
            "gh api graphql -F query=@q.graphql",
            "gh api graphql --input q.json",
        )

    def test_reads_are_allowed(self):
        self.assert_allowed("gh pr view 1", "gh pr list", "gh api repos/o/r/pulls/1",
                            "gh api -X GET repos/o/r/pulls/1/merge",
                            "gh api graphql -f query='{ viewer { login } }'",
                            "gh pr create --base main --title t --body b")


class PushToDefault(Repo):
    def test_refspec_spellings(self):
        self.assert_denied(
            "git push origin main", "git push origin HEAD:main", "git push origin HEAD:refs/heads/main",
            "git push origin HEAD:heads/main", "git push origin feat/x:master", "git push origin :main",
            "git push origin --delete main", "git push origin -d main",
            "git push origin 'refs/heads/*:refs/heads/*'",
            "git push --mirror origin", "git push --all origin", "git push --prune origin",
            "hub push origin main",
        )

    def test_force_spellings(self):
        self.assert_denied(
            "git push -f origin feat/x", "git push --force", "git push --force-with-lease",
            "git push --force-with-lease=feat/x:abc origin feat/x", "git push --force-if-includes",
            "git push -uf origin feat/x", "git push --forc origin feat/x", "git push --mirr origin",
            "git push origin +feat/x", "git push origin +HEAD:feat/x",
        )

    def test_config_changing_the_destination(self):
        self.assert_denied(
            "git -c push.default=matching push origin",
            "git -c remote.origin.push=HEAD:main push",
            "git -c branch.feat/x.merge=refs/heads/main push",
            "git --config-env remote.origin.push=V push origin",
        )

    def test_other_push_commands(self):
        self.assert_denied("git send-pack ../origin.git HEAD:main", "git http-push https://h/r main",
                           "git subtree push --prefix=x origin main")

    def test_repo_selection_and_wrappers(self):
        self.assert_denied(f"git -C {self.repo} push origin main", "GIT_DIR=.git git push origin main",
                           "cd . && git push origin main", "timeout 5 git push origin main",
                           "env -i git push origin main", "sudo git push origin main")

    def test_nested_commands(self):
        self.assert_denied("sh -c 'git push origin main'", "bash -lc \"git push -f\"",
                           "bash <<EOF\ngit push --force\nEOF", "eval git push origin main",
                           "sh -c \"sh -c 'git push origin main'\"")

    def test_feature_pushes_are_allowed(self):
        self.assert_allowed("git push origin feat/x", "git push", "git push -u origin feat/x",
                            "git push origin HEAD:feat/y", "git push origin --delete feat/old",
                            "git fetch origin", "git log main", "git switch main",
                            "echo 'git push origin main'", "cat <<EOF\ngit push -f\nEOF")


class PushFromRepoState(Repo):
    def test_bare_push_on_the_default_branch(self):
        git(self.repo, "switch", "-q", "main")
        self.assert_denied("git push", "git push origin", "git push origin HEAD")

    def test_bare_push_whose_upstream_is_the_default_branch(self):
        git(self.repo, "branch", "-q", "--set-upstream-to=origin/main", "feat/x")
        self.assert_denied("git push", "git push origin")

    def test_matching_and_remote_push_config(self):
        git(self.repo, "config", "push.default", "matching")
        self.assert_denied("git push origin", "git push origin feat/x")
        git(self.repo, "config", "push.default", "simple")
        git(self.repo, "config", "remote.origin.push", "HEAD:main")
        self.assert_denied("git push", "git push origin feat/x")

    def test_remote_head_names_more_default_branches(self):
        git(self.repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/feat/x")
        self.assert_denied("git push origin feat/x")
        self.assert_denied("git push origin main")  # main and master always count

    def test_user_aliases(self):
        git(self.repo, "config", "alias.pm", "push origin main")
        git(self.repo, "config", "alias.sp", "!git push --force")
        self.assert_denied("git pm", "git sp")

    def test_repo_named_by_dash_c_or_cd_from_outside(self):
        outside = self.tmp / "elsewhere"
        outside.mkdir()
        self.assertIsNone(self.bash(f"git -C {self.repo} push origin feat/x", cwd=outside))
        self.assertIsNone(self.bash(f"cd {self.repo} && git push origin feat/x", cwd=outside))

    def test_lookup_failure_denies_with_the_set_head_hint(self):
        outside = self.tmp / "not-a-repo"
        outside.mkdir()
        reason = self.bash("git push origin feat/x", cwd=outside)
        self.assertIsNotNone(reason)
        self.assertIn("git remote set-head", reason)


class LocalDefaultBranchMoves(Repo):
    def test_branch_and_ref_commands(self):
        self.assert_denied(
            "git branch -f main HEAD", "git branch --force main", "git branch -M main",
            "git branch -m feat/x main", "git branch -D main", "git branch --delete main",
            "git branch -c feat/x main", "git branch --move feat/x master",
            "git update-ref refs/heads/main HEAD", "git update-ref -d refs/heads/main",
            "git update-ref --stdin <<E\nupdate refs/heads/main abc\nE",
            "git fetch . HEAD:main", "git fetch . +feat/x:main",
            "git checkout -B main", "git switch -C main", "git worktree add -B main ../w",
            "git rebase origin/main main",
            "echo abc > .git/refs/heads/main", "cat x > .git/packed-refs",
            "printf %s abc > \"$(git rev-parse --git-common-dir)/refs/heads/main\"",
        )

    def test_update_ref_head_while_on_the_default_branch(self):
        git(self.repo, "switch", "-q", "main")
        self.assert_denied("git update-ref HEAD abc")

    def test_renaming_the_current_default_branch(self):
        git(self.repo, "switch", "-q", "main")
        self.assert_denied("git branch -m trunk", "git branch -c trunk")

    def test_ordinary_branch_work_is_allowed(self):
        self.assert_allowed("git branch feat/y", "git branch -d feat/old", "git branch -f feat/y HEAD",
                            "git rebase main", "git checkout -b feat/z",
                            "git update-ref refs/heads/feat/y HEAD", "git update-ref HEAD abc",
                            "git fetch origin main:refs/remotes/origin/main", "git branch --list main",
                            "cat <<EOF > notes.txt\necho x > .git/refs/heads/main\nEOF")


class Executor(Repo):
    def test_every_push_is_denied(self):
        self.assert_denied("git push origin feat/x", "git push", "sh -c 'git push'",
                           "bash <<EOF\ngit push origin feat/x\nEOF", "git send-pack ../origin.git feat/x",
                           agent_type=EXECUTOR)

    def test_merge_is_denied_too(self):
        self.assert_denied("gh pr merge 1", agent_type=EXECUTOR)

    def test_the_same_commands_pass_for_the_main_session(self):
        self.assert_allowed("git push origin feat/x", "gh api -X POST repos/o/r/issues -f title=t")

    def test_executor_may_read_and_commit(self):
        self.assert_allowed("git status", "git commit -m x", "gh pr view 1", agent_type=EXECUTOR)


class PowerShellRoute(Repo):
    def test_same_rules(self):
        self.assert_denied("git push origin HEAD:main", "gh pr merge 1", tool="PowerShell")
        self.assert_allowed("git push origin feat/x", tool="PowerShell")


class Mcp(Repo):
    def test_merge_tools(self):
        for name in ("mcp__github__merge_pull_request", "mcp__plugin_x_github__merge_pull_request",
                     "mcp__gitlab__Merge_Request_Merge"):
            with self.subTest(tool=name):
                self.assertTrue(self.mcp(name, owner="o", repo="r", pullNumber=1).startswith(PREFIX))

    def test_writes_to_a_default_branch(self):
        for name, branch in (("mcp__github__push_files", "main"),
                             ("mcp__github__create_or_update_file", "master"),
                             ("mcp__github__delete_file", "main")):
            with self.subTest(tool=name):
                self.assertTrue(self.mcp(name, owner="o", repo="r", branch=branch).startswith(PREFIX))
        # The Plan's MCP rule reads `base` as well as `branch`.
        self.assertTrue(self.mcp("mcp__github__create_pull_request", base="main",
                                 head="feat/x").startswith(PREFIX))

    def test_other_tools_pass(self):
        self.assertIsNone(self.mcp("mcp__github__get_pull_request", owner="o", repo="r", pullNumber=1))
        self.assertIsNone(self.mcp("mcp__plugin_x_github__create_branch", branch="feat/x"))
        self.assertIsNone(self.mcp("mcp__github__push_files", branch="feat/x"))


class Robustness(unittest.TestCase):
    def test_unparseable_input_is_ignored(self):
        proc = subprocess.run([sys.executable, str(HOOK)], input="not json", text=True,
                              capture_output=True, timeout=10)
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))

    def test_runs_from_any_directory(self):
        with tempfile.TemporaryDirectory() as cwd:
            reason = run_hook({"tool_name": "Bash", "tool_input": {"command": "gh pr merge 1"},
                               "cwd": cwd}, cwd)
        self.assertTrue(reason.startswith(PREFIX))


if __name__ == "__main__":
    unittest.main()
