"""Tests for --stack-aware functionality and gh stack integration."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from git import Repo

from git_history_extraction import extract_history, main
from git_history_extraction.stack import (
    Stack,
    StackBranch,
    find_stack_file,
    load_stack_from_gh_cli,
    load_stacks_from_disk,
    resolve_stack_parent_branch,
)


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
    def test_load_stack_from_gh_cli_success(self, tmp_path: Path):
        cli_output = json.dumps(
            {
                "trunk": "main",
                "currentBranch": "feature-2",
                "branches": [
                    {
                        "name": "feature-1",
                        "isCurrent": False,
                        "isMerged": True,
                        "isQueued": False,
                    },
                    {
                        "name": "feature-2",
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
            patch("shutil.which", return_value="/usr/local/bin/gh"),
            patch("subprocess.run", return_value=fake_proc),
        ):
            stack = load_stack_from_gh_cli(tmp_path)
            assert stack is not None
            assert stack.trunk == "main"
            assert len(stack.branches) == 2
            assert stack.branches[0].is_merged is True
            assert stack.branches[1].name == "feature-2"

    def test_load_stack_from_gh_cli_not_found_or_error(self, tmp_path: Path):
        with patch("shutil.which", return_value=None):
            assert load_stack_from_gh_cli(tmp_path) is None

        fake_err = subprocess.CompletedProcess(
            args=["gh", "stack", "view", "--json"],
            returncode=2,
            stdout="",
            stderr="✗ current branch is not part of a stack",
        )
        with (
            patch("shutil.which", return_value="/usr/local/bin/gh"),
            patch("subprocess.run", return_value=fake_err),
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
            stack_aware=True,
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
            stack_aware=True,
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
            stack_aware=True,
            remote=False,
        )
        assert len(commits) == 1
        assert "Commit on feat-1" in commits[0]["body"]
        assert "Initial commit on main" not in commits[0]["body"]

    def test_extract_history_active_branch_default(self, tmp_path: Path):
        _setup_stacked_repo(tmp_path)
        # Current active branch is feat-3
        commits = extract_history(
            repo_path=tmp_path,
            stack_aware=True,
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
            stack_aware=True,
            remote=False,
        )
        # Commits from feat-2 and feat-1 (since feat-1 was based on main)
        bodies = [c["body"] for c in commits]
        assert any("Commit on feat-2" in b for b in bodies)
        assert not any("Initial commit on main" in b for b in bodies)

    def test_stack_aware_conflict_with_since(self, tmp_path: Path):
        _setup_stacked_repo(tmp_path)
        with pytest.raises(
            ValueError, match="--stack-aware cannot be combined with --since"
        ):
            extract_history(repo_path=tmp_path, stack_aware=True, since="yesterday")

    def test_stack_aware_on_trunk_fails(self, tmp_path: Path):
        _setup_stacked_repo(tmp_path)
        with pytest.raises(ValueError, match="is the trunk branch"):
            extract_history(
                repo_path=tmp_path,
                branch="main",
                stack_aware=True,
                remote=False,
            )


class TestCLIStackAware:
    def test_cli_stack_aware_active_branch(self, tmp_path: Path):
        _setup_stacked_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--repo", str(tmp_path), "--stack-aware", "--local"],
        )
        assert result.exit_code == 0
        assert "Commit on feat-3" in result.stdout
        assert "Commit on feat-2" not in result.stdout

    def test_cli_stack_aware_explicit_branch(self, tmp_path: Path):
        _setup_stacked_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--repo", str(tmp_path), "--branch", "feat-2", "--stack-aware", "--local"],
        )
        assert result.exit_code == 0
        assert "Commit on feat-2" in result.stdout
        assert "Commit on feat-1" not in result.stdout

    def test_cli_stack_aware_json_format(self, tmp_path: Path):
        _setup_stacked_repo(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "--repo",
                str(tmp_path),
                "--stack-aware",
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

    def test_cli_stack_aware_not_in_stack_error(self, tmp_path: Path):
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
            ["--repo", str(repo_path), "--stack-aware"],
        )
        assert result.exit_code != 0
        assert "is not part of a gh stack" in result.output
