"""Tests for --stack-aware functionality and gh stack integration."""

import json
import subprocess
from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest
from click.testing import CliRunner
from git import Repo

from git_history_extraction import extract_history, main
from git_history_extraction.stack import (
    Stack,
    StackBranch,
    StackContext,
    find_stack_file,
    find_stack_parent_branch,
    load_stack_from_gh_cli,
    load_stacks_from_disk,
    resolve_safe_parent_ref,
    resolve_stack_parent_branch,
)


@pytest.fixture(autouse=True)
def hermetic_gh_cli(request):
    """Ensure tests do not accidentally invoke the real gh CLI binary installed on the host,
    unless explicitly opted in with @pytest.mark.allow_gh_cli.
    """
    if "allow_gh_cli" in request.keywords:
        yield
        return
    with patch("git_history_extraction.stack.shutil.which", return_value=None):
        yield


class TestStackModels:
    def test_stack_index_of(self):
        s = Stack(
            trunk="main",
            branches=[
                StackBranch(name="b1"),
                StackBranch(name="b2"),
            ],
        )
        assert s.index_of("b1") == 0
        assert s.index_of("b2") == 1
        assert s.index_of("b3") == -1

    def test_active_base_branch_single_branch(self):
        s = Stack(trunk="main", branches=[StackBranch(name="b1")])
        assert s.active_base_branch("b1") == "main"

    def test_active_base_branch_chain(self):
        s = Stack(
            trunk="main",
            branches=[
                StackBranch(name="b1"),
                StackBranch(name="b2"),
                StackBranch(name="b3"),
            ],
        )
        assert s.active_base_branch("b1") == "main"
        assert s.active_base_branch("b2") == "b1"
        assert s.active_base_branch("b3") == "b2"

    def test_active_base_branch_skips_merged(self):
        s = Stack(
            trunk="main",
            branches=[
                StackBranch(name="b1", is_merged=True),
                StackBranch(name="b2"),
                StackBranch(name="b3"),
            ],
        )
        # b1 is merged into main, so b2 effectively bases on main
        assert s.active_base_branch("b2") == "main"
        # b3 bases on b2 (unmerged)
        assert s.active_base_branch("b3") == "b2"

    def test_active_base_branch_skips_multiple_merged(self):
        s = Stack(
            trunk="main",
            branches=[
                StackBranch(name="b1", is_merged=True),
                StackBranch(name="b2", is_merged=True),
                StackBranch(name="b3"),
            ],
        )
        assert s.active_base_branch("b3") == "main"

    def test_active_base_branch_skips_queued(self):
        s = Stack(
            trunk="main",
            branches=[
                StackBranch(name="b1", is_queued=True),
                StackBranch(name="b2"),
            ],
        )
        assert s.active_base_branch("b2") == "main"


class TestDiskLoading:
    def test_find_stack_file(self, tmp_path: Path):
        repo = Repo.init(tmp_path)
        git_dir = Path(repo.git_dir)
        stack_file = git_dir / "gh-stack"
        stack_file.write_text("{}", encoding="utf-8")

        found = find_stack_file(repo)
        assert found == stack_file

    def test_find_stack_file_missing(self, tmp_path: Path):
        repo = Repo.init(tmp_path)
        assert find_stack_file(repo) is None

    def test_load_stacks_from_disk(self, tmp_path: Path):
        repo = Repo.init(tmp_path)
        git_dir = Path(repo.git_dir)
        stack_file = git_dir / "gh-stack"
        data = {
            "schemaVersion": 1,
            "repository": "owner/repo",
            "stacks": [
                {
                    "id": "stack-1",
                    "number": 1,
                    "trunk": {"branch": "main"},
                    "branches": [
                        {"branch": "feature-1", "pullRequest": {"merged": False}},
                        {"branch": "feature-2", "pullRequest": {"merged": True}},
                    ],
                }
            ],
        }
        stack_file.write_text(json.dumps(data), encoding="utf-8")

        stacks = load_stacks_from_disk(repo)
        assert len(stacks) == 1
        assert stacks[0].trunk == "main"
        assert len(stacks[0].branches) == 2
        assert stacks[0].branches[0].name == "feature-1"
        assert stacks[0].branches[0].is_merged is False
        assert stacks[0].branches[1].name == "feature-2"
        assert stacks[0].branches[1].is_merged is True

    def test_load_stacks_corrupted_json(self, tmp_path: Path):
        repo = Repo.init(tmp_path)
        git_dir = Path(repo.git_dir)
        stack_file = git_dir / "gh-stack"
        stack_file.write_text("{broken json", encoding="utf-8")

        assert load_stacks_from_disk(repo) == []


class TestGHCLILoading:
    @pytest.mark.allow_gh_cli
    def test_load_stack_from_gh_cli_success(self, tmp_path: Path):
        cli_output = json.dumps(
            {
                "trunk": "main",
                "currentBranch": "feature-2",
                "branches": [
                    {
                        "name": "feature-1",
                        "head": "sha-feat1",
                        "base": "sha-trunk",
                        "isCurrent": False,
                        "isMerged": True,
                        "isQueued": False,
                    },
                    {
                        "name": "feature-2",
                        "head": "sha-feat2",
                        "base": "sha-feat1",
                        "isCurrent": True,
                        "isMerged": False,
                        "isQueued": False,
                    },
                ],
            }
        )
        fake_proc = subprocess.CompletedProcess(
            args=["gh", "stack", "view", "--json"],
            returncode=0,
            stdout=cli_output,
            stderr="",
        )

        with (
            patch(
                "git_history_extraction.stack.shutil.which",
                return_value="/usr/local/bin/gh",
            ),
            patch(
                "git_history_extraction.stack.subprocess.run",
                return_value=fake_proc,
            ),
        ):
            stack = load_stack_from_gh_cli(tmp_path)
            assert stack is not None
            assert stack.trunk == "main"
            assert len(stack.branches) == 2
            assert stack.branches[0].is_merged is True
            assert stack.branches[0].head == "sha-feat1"
            assert stack.branches[1].name == "feature-2"
            assert stack.branches[1].base == "sha-feat1"

    @pytest.mark.allow_gh_cli
    def test_load_stack_from_gh_cli_not_found_or_error(self, tmp_path: Path):
        with patch("git_history_extraction.stack.shutil.which", return_value=None):
            assert load_stack_from_gh_cli(tmp_path) is None

        fake_err = subprocess.CompletedProcess(
            args=["gh", "stack", "view", "--json"],
            returncode=2,
            stdout="",
            stderr="✗ current branch is not part of a stack",
        )
        with (
            patch(
                "git_history_extraction.stack.shutil.which",
                return_value="/usr/local/bin/gh",
            ),
            patch(
                "git_history_extraction.stack.subprocess.run",
                return_value=fake_err,
            ),
        ):
            assert load_stack_from_gh_cli(tmp_path) is None

    @pytest.mark.allow_gh_cli
    def test_load_stack_from_gh_cli_timeout(self, tmp_path: Path):
        with (
            patch(
                "git_history_extraction.stack.shutil.which",
                return_value="/usr/local/bin/gh",
            ),
            patch(
                "git_history_extraction.stack.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=5.0),
            ),
        ):
            assert load_stack_from_gh_cli(tmp_path) is None


class TestResolveStackParentBranch:
    def test_resolve_parent_from_disk(self, tmp_path: Path):
        repo = Repo.init(tmp_path)
        git_dir = Path(repo.git_dir)
        data = {
            "schemaVersion": 1,
            "repository": "owner/repo",
            "stacks": [
                {
                    "trunk": {"branch": "main"},
                    "branches": [
                        {"branch": "feat-a"},
                        {"branch": "feat-b"},
                    ],
                }
            ],
        }
        (git_dir / "gh-stack").write_text(json.dumps(data), encoding="utf-8")

        parent, idx, total, trunk = resolve_stack_parent_branch(repo, "feat-b")
        assert parent == "feat-a"
        assert idx == 1
        assert total == 2
        assert trunk == "main"

        parent, idx, total, trunk = resolve_stack_parent_branch(repo, "feat-a")
        assert parent == "main"
        assert idx == 0
        assert total == 2
        assert trunk == "main"

    def test_resolve_parent_trunk_error(self, tmp_path: Path):
        repo = Repo.init(tmp_path)
        git_dir = Path(repo.git_dir)
        data = {
            "schemaVersion": 1,
            "repository": "owner/repo",
            "stacks": [
                {
                    "trunk": {"branch": "main"},
                    "branches": [{"branch": "feat-a"}],
                }
            ],
        }
        (git_dir / "gh-stack").write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(
            ValueError, match="is the trunk branch and is not stacked on another branch"
        ):
            resolve_stack_parent_branch(repo, "main")

    def test_resolve_parent_not_in_stack_error(self, tmp_path: Path):
        repo = Repo.init(tmp_path)
        with pytest.raises(ValueError, match="is not part of a gh stack"):
            resolve_stack_parent_branch(repo, "non-existent")


class TestFindStackParentBranch:
    def test_find_parent_on_stacked_branch(self, tmp_path: Path):
        repo = _setup_stacked_repo(tmp_path)
        info = find_stack_parent_branch(repo, "feat-3")
        assert info == ("feat-2", 2, 3, "main")

    def test_find_parent_on_trunk_returns_none(self, tmp_path: Path):
        repo = _setup_stacked_repo(tmp_path)
        assert find_stack_parent_branch(repo, "main") is None

    def test_find_parent_not_in_stack_returns_none(self, tmp_path: Path):
        repo = _setup_stacked_repo(tmp_path)
        assert find_stack_parent_branch(repo, "non-existent") is None

    def test_find_parent_repo_without_stack_returns_none(self, tmp_path: Path):
        repo = Repo.init(tmp_path)
        assert find_stack_parent_branch(repo, "any-branch") is None


def _setup_stacked_repo(repo_path: Path):
    """Create a git repo with a 3-branch stack."""
    repo = Repo.init(repo_path)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "-b", "main"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    # Initial commit on main
    (repo_path / "main.txt").write_text("main")
    subprocess.run(
        ["git", "add", "main.txt"], cwd=repo_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit on main"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    # Branch feat-1
    subprocess.run(
        ["git", "checkout", "-b", "feat-1"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    (repo_path / "feat1.txt").write_text("feat1")
    subprocess.run(
        ["git", "add", "feat1.txt"], cwd=repo_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Commit on feat-1"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    # Branch feat-2
    subprocess.run(
        ["git", "checkout", "-b", "feat-2"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    (repo_path / "feat2.txt").write_text("feat2")
    subprocess.run(
        ["git", "add", "feat2.txt"], cwd=repo_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Commit on feat-2"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    # Branch feat-3
    subprocess.run(
        ["git", "checkout", "-b", "feat-3"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    (repo_path / "feat3.txt").write_text("feat3")
    subprocess.run(
        ["git", "add", "feat3.txt"], cwd=repo_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Commit on feat-3"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    # Configure .git/gh-stack
    git_dir = Path(repo.git_dir)
    stack_data = {
        "schemaVersion": 1,
        "repository": "owner/repo",
        "stacks": [
            {
                "trunk": {"branch": "main"},
                "branches": [
                    {"branch": "feat-1"},
                    {"branch": "feat-2"},
                    {"branch": "feat-3"},
                ],
            }
        ],
    }
    (git_dir / "gh-stack").write_text(json.dumps(stack_data), encoding="utf-8")
    return repo


class TestExtractHistoryStackAware:
    def test_extract_history_top_of_stack(self, tmp_path: Path):
        _setup_stacked_repo(tmp_path)
        # On feat-3: should compare against feat-2
        commits = extract_history(
            repo_path=tmp_path,
            branch="feat-3",
            remote=False,
        )
        assert len(commits) == 1
        assert "Commit on feat-3" in commits[0]["body"]
        assert "Commit on feat-2" not in commits[0]["body"]

    def test_extract_history_middle_of_stack(self, tmp_path: Path):
        _setup_stacked_repo(tmp_path)
        # On feat-2: should compare against feat-1
        commits = extract_history(
            repo_path=tmp_path,
            branch="feat-2",
            remote=False,
        )
        assert len(commits) == 1
        assert "Commit on feat-2" in commits[0]["body"]
        assert "Commit on feat-1" not in commits[0]["body"]

    def test_extract_history_bottom_of_stack(self, tmp_path: Path):
        _setup_stacked_repo(tmp_path)
        # On feat-1: should compare against trunk (main)
        commits = extract_history(
            repo_path=tmp_path,
            branch="feat-1",
            remote=False,
        )
        assert len(commits) == 1
        assert "Commit on feat-1" in commits[0]["body"]
        assert "Initial commit on main" not in commits[0]["body"]

    def test_extract_history_active_branch_auto_detected(self, tmp_path: Path):
        _setup_stacked_repo(tmp_path)
        # Current active branch is feat-3, automatically detected without flags
        commits = extract_history(
            repo_path=tmp_path,
            remote=False,
        )
        assert len(commits) == 1
        assert "Commit on feat-3" in commits[0]["body"]

    def test_extract_history_skips_merged_ancestor(self, tmp_path: Path):
        repo = _setup_stacked_repo(tmp_path)
        # Mark feat-1 as merged in .git/gh-stack
        git_dir = Path(repo.git_dir)
        stack_data = {
            "schemaVersion": 1,
            "repository": "owner/repo",
            "stacks": [
                {
                    "trunk": {"branch": "main"},
                    "branches": [
                        {"branch": "feat-1", "pullRequest": {"merged": True}},
                        {"branch": "feat-2"},
                        {"branch": "feat-3"},
                    ],
                }
            ],
        }
        (git_dir / "gh-stack").write_text(json.dumps(stack_data), encoding="utf-8")

        # For feat-2, parent should skip merged feat-1 and compare against trunk (main)
        commits = extract_history(
            repo_path=tmp_path,
            branch="feat-2",
            remote=False,
        )
        bodies = [c["body"] for c in commits]
        assert any("Commit on feat-2" in b for b in bodies)
        assert not any("Initial commit on main" in b for b in bodies)

    def test_extract_history_opt_out_stack_aware(self, tmp_path: Path):
        _setup_stacked_repo(tmp_path)
        # With stack_aware=False and branch="feat-3", it compares against main
        commits = extract_history(
            repo_path=tmp_path,
            branch="feat-3",
            stack_aware=False,
            remote=False,
        )
        bodies = [c["body"] for c in commits]
        assert any("Commit on feat-3" in b for b in bodies)
        assert any("Commit on feat-2" in b for b in bodies)
        assert any("Commit on feat-1" in b for b in bodies)

    def test_extract_history_explicit_since_bypasses_stack(self, tmp_path: Path):
        _setup_stacked_repo(tmp_path)
        # Explicit since overrides stack parent comparison
        commits = extract_history(repo_path=tmp_path, since="yesterday", remote=False)
        assert isinstance(commits, list)

    def test_extract_history_on_trunk_falls_back(self, tmp_path: Path):
        repo = _setup_stacked_repo(tmp_path)
        # Checkout trunk branch main
        repo.git.checkout("main")
        commits = extract_history(repo_path=tmp_path, remote=False)
        assert isinstance(commits, list)

    def test_extract_history_not_in_stack_falls_back(self, tmp_path: Path):
        repo_path = tmp_path / "repo_no_stack"
        Repo.init(repo_path)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo_path,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"], cwd=repo_path, check=True
        )
        subprocess.run(["git", "checkout", "-b", "main"], cwd=repo_path, check=True)
        (repo_path / "file.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo_path, check=True)

        commits = extract_history(repo_path=repo_path, remote=False)
        assert isinstance(commits, list)


class TestCLIStackAware:
    def test_cli_auto_detect_active_branch(self, tmp_path: Path):
        _setup_stacked_repo(tmp_path)
        runner = CliRunner()
        # No --stack-aware needed! Automatically detected.
        result = runner.invoke(
            main,
            ["--repo", str(tmp_path), "--local"],
        )
        assert result.exit_code == 0
        assert "Commit on feat-3" in result.stdout
        assert "Commit on feat-2" not in result.stdout

    def test_cli_explicit_branch_auto_stack(self, tmp_path: Path):
        _setup_stacked_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--repo", str(tmp_path), "--branch", "feat-2", "--local"],
        )
        assert result.exit_code == 0
        assert "Commit on feat-2" in result.stdout
        assert "Commit on feat-1" not in result.stdout

    def test_cli_no_stack_aware_opt_out(self, tmp_path: Path):
        _setup_stacked_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "--repo",
                str(tmp_path),
                "--branch",
                "feat-3",
                "--no-stack-aware",
                "--local",
            ],
        )
        assert result.exit_code == 0
        assert "Commit on feat-3" in result.stdout
        assert "Commit on feat-2" in result.stdout
        assert "Commit on feat-1" in result.stdout

    def test_cli_stack_aware_json_format(self, tmp_path: Path):
        _setup_stacked_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "--repo",
                str(tmp_path),
                "--local",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) == 1
        assert "Commit on feat-3" in data[0]["body"]

    def test_cli_repo_without_stack_succeeds(self, tmp_path: Path):
        repo_path = tmp_path / "repo_no_stack"
        Repo.init(repo_path)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo_path,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"], cwd=repo_path, check=True
        )
        subprocess.run(["git", "checkout", "-b", "main"], cwd=repo_path, check=True)
        (repo_path / "file.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo_path, check=True)
        subprocess.run(["git", "checkout", "-b", "feat"], cwd=repo_path, check=True)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--repo", str(repo_path), "--local"],
        )
        assert result.exit_code == 0


class TestStackContext:
    def test_stack_context_attributes(self):
        ctx = StackContext(
            parent_branch="feat-1",
            stack_index=1,
            total_branches=2,
            trunk_branch="main",
            exclude_refs=("sha1", "sha2"),
        )
        assert ctx.parent_branch == "feat-1"
        assert ctx.stack_index == 1
        assert ctx.total_branches == 2
        assert ctx.trunk_branch == "main"
        assert ctx.exclude_refs == ("sha1", "sha2")

    def test_stack_context_tuple_unpacking(self):
        ctx = StackContext(
            parent_branch="feat-1",
            stack_index=1,
            total_branches=2,
            trunk_branch="main",
        )
        parent, idx, total, trunk = ctx
        assert parent == "feat-1"
        assert idx == 1
        assert total == 2
        assert trunk == "main"

    def test_stack_context_equality_with_tuple(self):
        ctx = StackContext(
            parent_branch="feat-1",
            stack_index=1,
            total_branches=2,
            trunk_branch="main",
        )
        assert ctx == ("feat-1", 1, 2, "main")
        assert ctx != ("feat-2", 1, 2, "main")

    def test_resolve_safe_parent_ref_fallback_chain(self, tmp_path: Path):
        repo = Repo.init(tmp_path)
        repo.config_writer().set_value("user", "name", "T").release()
        repo.config_writer().set_value("user", "email", "t@e.com").release()

        repo.git.checkout("-b", "main")
        (tmp_path / "m.txt").write_text("m")
        repo.index.add(["m.txt"])
        init_commit = repo.index.commit("init")

        stack = Stack(
            trunk="main",
            branches=[
                StackBranch(name="missing-p1", head="0" * 40),
                StackBranch(name="f2", base=init_commit.hexsha),
            ],
        )

        # 1. Base SHA fallback when parent missing
        resolved = resolve_safe_parent_ref(
            repo,
            candidate_parent="missing-p1",
            stack=stack,
            target_branch="f2",
            remote=False,
        )
        assert resolved == init_commit.hexsha

        # 2. Trunk fallback when parent and base SHA both missing
        stack_no_base = Stack(
            trunk="main",
            branches=[
                StackBranch(name="missing-p1"),
                StackBranch(name="f2"),
            ],
        )
        resolved_trunk = resolve_safe_parent_ref(
            repo,
            candidate_parent="missing-p1",
            stack=stack_no_base,
            target_branch="f2",
            remote=False,
        )
        assert resolved_trunk == "main"


class TestP0Correctness:
    def test_non_main_trunk(self, tmp_path: Path):
        """Bug #1: gh stack with develop trunk must compare against develop, not main."""
        repo = Repo.init(tmp_path)
        repo.config_writer().set_value("user", "name", "T").release()
        repo.config_writer().set_value("user", "email", "t@e.com").release()

        # Commit on main
        repo.git.checkout("-b", "main")
        (tmp_path / "main.txt").write_text("main")
        repo.index.add(["main.txt"])
        repo.index.commit("main commit")

        # Develop branch with develop commit
        repo.git.checkout("-b", "develop")
        (tmp_path / "dev.txt").write_text("dev")
        repo.index.add(["dev.txt"])
        repo.index.commit("develop commit")

        # Feat branch stacked on develop
        repo.git.checkout("-b", "feat")
        (tmp_path / "feat.txt").write_text("feat")
        repo.index.add(["feat.txt"])
        repo.index.commit("feat commit")

        # Stack file with trunk = develop
        git_dir = Path(repo.git_dir)
        stack_data = {
            "schemaVersion": 1,
            "stacks": [
                {
                    "trunk": {"branch": "develop"},
                    "branches": [{"branch": "feat"}],
                }
            ],
        }
        (git_dir / "gh-stack").write_text(json.dumps(stack_data), encoding="utf-8")

        commits = extract_history(tmp_path, branch="feat", remote=False)
        bodies = [c["body"].strip() for c in commits]
        assert bodies == ["feat commit"]
        assert "develop commit" not in bodies

    def test_squash_merged_parent_commits_excluded(self, tmp_path: Path):
        """Bug #2: squash-merged parent PR commits must be excluded from child branch."""
        repo = Repo.init(tmp_path)
        repo.config_writer().set_value("user", "name", "T").release()
        repo.config_writer().set_value("user", "email", "t@e.com").release()

        repo.git.checkout("-b", "main")
        (tmp_path / "m.txt").write_text("m")
        repo.index.add(["m.txt"])
        repo.index.commit("main init")

        # Branch f1
        repo.git.checkout("-b", "f1")
        (tmp_path / "f1.txt").write_text("f1")
        repo.index.add(["f1.txt"])
        f1_commit = repo.index.commit("f1 commit")

        # Branch f2 branched off f1
        repo.git.checkout("-b", "f2")
        (tmp_path / "f2.txt").write_text("f2")
        repo.index.add(["f2.txt"])
        repo.index.commit("f2 commit")

        # Squash merge f1 into main
        repo.git.checkout("main")
        repo.git.merge("--squash", "f1")
        repo.index.commit("squash f1 into main")

        # Stack file records f1 as merged with mergedHead
        git_dir = Path(repo.git_dir)
        stack_data = {
            "schemaVersion": 1,
            "stacks": [
                {
                    "trunk": {"branch": "main"},
                    "branches": [
                        {
                            "branch": "f1",
                            "pullRequest": {
                                "number": 1,
                                "merged": True,
                                "mergedHead": f1_commit.hexsha,
                            },
                        },
                        {
                            "branch": "f2",
                            "base": f1_commit.hexsha,
                        },
                    ],
                }
            ],
        }
        (git_dir / "gh-stack").write_text(json.dumps(stack_data), encoding="utf-8")

        commits = extract_history(tmp_path, branch="f2", remote=False)
        bodies = [c["body"].strip() for c in commits]
        assert bodies == ["f2 commit"]
        assert "f1 commit" not in bodies

    def test_deleted_parent_branch_falls_back_safely(self, tmp_path: Path):
        """Bug #3: if a parent branch is deleted locally, fall back without crashing."""
        repo = Repo.init(tmp_path)
        repo.config_writer().set_value("user", "name", "T").release()
        repo.config_writer().set_value("user", "email", "t@e.com").release()

        repo.git.checkout("-b", "main")
        (tmp_path / "m.txt").write_text("m")
        repo.index.add(["m.txt"])
        repo.index.commit("main init")

        repo.git.checkout("-b", "f2")
        (tmp_path / "f2.txt").write_text("f2")
        repo.index.add(["f2.txt"])
        repo.index.commit("f2 commit")

        git_dir = Path(repo.git_dir)
        stack_data = {
            "schemaVersion": 1,
            "stacks": [
                {
                    "trunk": {"branch": "main"},
                    "branches": [
                        {"branch": "f1-deleted"},
                        {"branch": "f2"},
                    ],
                }
            ],
        }
        (git_dir / "gh-stack").write_text(json.dumps(stack_data), encoding="utf-8")

        # Should not raise GitCommandError (fatal: bad revision 'f1-deleted..f2')
        commits = extract_history(tmp_path, branch="f2", remote=False)
        assert len(commits) == 1
        assert "f2 commit" in commits[0]["body"]

    def test_corrupt_stack_file_handling(self, tmp_path: Path):
        """Bug #4 & #5: malformed JSON or unknown schemaVersion degrades gracefully."""
        repo = Repo.init(tmp_path)
        git_dir = Path(repo.git_dir)

        # 1. Null trunk
        (git_dir / "gh-stack").write_text(
            json.dumps({"stacks": [{"trunk": None, "branches": []}]}),
            encoding="utf-8",
        )
        assert load_stacks_from_disk(repo) == []

        # 2. Null stacks
        (git_dir / "gh-stack").write_text(
            json.dumps({"stacks": None}),
            encoding="utf-8",
        )
        assert load_stacks_from_disk(repo) == []

        # 3. schemaVersion > 1
        (git_dir / "gh-stack").write_text(
            json.dumps({"schemaVersion": 2, "stacks": []}),
            encoding="utf-8",
        )
        assert load_stacks_from_disk(repo) == []


class TestP1Robustness:
    def test_common_dir_takes_precedence_over_git_dir(self, tmp_path: Path):
        """Bug #6: common_dir catalog must take precedence over legacy git_dir file."""
        repo = Repo.init(tmp_path)
        git_dir = Path(repo.git_dir)
        common_dir = tmp_path / "custom_common"
        common_dir.mkdir()

        (git_dir / "gh-stack").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "stacks": [
                        {
                            "trunk": {"branch": "main"},
                            "branches": [{"branch": "legacy-branch"}],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        (common_dir / "gh-stack").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "stacks": [
                        {
                            "trunk": {"branch": "main"},
                            "branches": [{"branch": "canonical-branch"}],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        # Mock Repo.common_dir as a PropertyMock
        with patch.object(
            Repo, "common_dir", new_callable=PropertyMock, return_value=str(common_dir)
        ):
            found = find_stack_file(repo)
            assert found == common_dir / "gh-stack"
            stacks = load_stacks_from_disk(repo)
            assert len(stacks) == 1
            assert stacks[0].branches[0].name == "canonical-branch"

    def test_local_mode_skips_gh_cli(self, tmp_path: Path):
        """Bug #7: remote=False should skip gh CLI invocation even if branch is active."""
        _setup_stacked_repo(tmp_path)
        with patch("git_history_extraction.stack.load_stack_from_gh_cli") as mock_cli:
            extract_history(tmp_path, remote=False)
            mock_cli.assert_not_called()

    def test_multiple_stacks_search_order(self, tmp_path: Path):
        """Bug #11: search member branches across all stacks before checking trunk."""
        repo = Repo.init(tmp_path)
        git_dir = Path(repo.git_dir)

        # Stack 1 has trunk: feat-x, branch: feat-y
        # Stack 2 has trunk: main, branches: [feat-x, feat-z]
        stack_data = {
            "schemaVersion": 1,
            "stacks": [
                {
                    "trunk": {"branch": "feat-x"},
                    "branches": [{"branch": "feat-y"}],
                },
                {
                    "trunk": {"branch": "main"},
                    "branches": [{"branch": "feat-x"}, {"branch": "feat-z"}],
                },
            ],
        }
        (git_dir / "gh-stack").write_text(json.dumps(stack_data), encoding="utf-8")

        # When resolving feat-x, it should match Stack 2 where it is a member branch!
        ctx = resolve_stack_parent_branch(repo, "feat-x", allow_gh_cli=False)
        assert ctx.parent_branch == "main"
        assert ctx.trunk_branch == "main"

    def test_multiple_stacks_disambiguation_error(self, tmp_path: Path):
        """Bug #11: raises ValueError when branch is present in multiple stacks."""
        repo = Repo.init(tmp_path)
        git_dir = Path(repo.git_dir)

        stack_data = {
            "schemaVersion": 1,
            "stacks": [
                {
                    "trunk": {"branch": "main"},
                    "branches": [{"branch": "shared-branch"}],
                },
                {
                    "trunk": {"branch": "develop"},
                    "branches": [{"branch": "shared-branch"}],
                },
            ],
        }
        (git_dir / "gh-stack").write_text(json.dumps(stack_data), encoding="utf-8")

        with pytest.raises(ValueError, match="belongs to multiple stacks"):
            resolve_stack_parent_branch(repo, "shared-branch", allow_gh_cli=False)


class TestStackParentOverride:
    def test_extract_history_with_stack_parent(self, tmp_path: Path):
        _setup_stacked_repo(tmp_path)
        # On feat-3: normally compares against feat-2. Override to feat-1:
        commits = extract_history(
            repo_path=tmp_path,
            branch="feat-3",
            stack_parent="feat-1",
            remote=False,
        )
        bodies = [c["body"] for c in commits]
        assert any("Commit on feat-3" in b for b in bodies)
        assert any("Commit on feat-2" in b for b in bodies)
        assert not any("Commit on feat-1" in b for b in bodies)

    def test_cli_stack_parent_override(self, tmp_path: Path):
        _setup_stacked_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "--repo",
                str(tmp_path),
                "--branch",
                "feat-3",
                "--stack-parent",
                "feat-1",
                "--local",
            ],
        )
        assert result.exit_code == 0
        assert "Commit on feat-3" in result.stdout
        assert "Commit on feat-2" in result.stdout
        assert "Commit on feat-1" not in result.stdout
