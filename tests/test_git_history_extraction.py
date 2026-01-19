"""Tests for git-history-extraction functionality."""

import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from git_history_extraction import (
    extract_git_trailers,
    get_last_monday,
    get_latest_version_tag,
    get_recent_version_tags,
    is_git_repository,
    main,
    remove_git_trailers,
)


class TestIsGitRepository:
    def test_returns_true_for_git_repository(self, tmp_path):
        repo_path = tmp_path / "test_repo"
        repo_path.mkdir()
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)

        assert is_git_repository(repo_path) is True

    def test_returns_false_for_non_git_directory(self, tmp_path):
        non_repo_path = tmp_path / "not_a_repo"
        non_repo_path.mkdir()

        assert is_git_repository(non_repo_path) is False


class TestGetLastMonday:
    def test_returns_last_monday_when_today_is_wednesday(self):
        with patch("git_history_extraction.datetime") as mock_datetime:
            wednesday = datetime(2025, 1, 15, 14, 30, 45)
            mock_datetime.now.return_value = wednesday

            result = get_last_monday()

            assert result == "2025-01-13 00:00:00"

    def test_returns_today_when_today_is_monday(self):
        with patch("git_history_extraction.datetime") as mock_datetime:
            monday = datetime(2025, 1, 13, 14, 30, 45)
            mock_datetime.now.return_value = monday

            result = get_last_monday()

            assert result == "2025-01-13 00:00:00"

    def test_returns_last_monday_when_today_is_sunday(self):
        with patch("git_history_extraction.datetime") as mock_datetime:
            sunday = datetime(2025, 1, 19, 14, 30, 45)
            mock_datetime.now.return_value = sunday

            result = get_last_monday()

            assert result == "2025-01-13 00:00:00"


class TestGetRecentVersionTags:
    def test_finds_latest_version_tag(self, tmp_path):
        repo_path = tmp_path / "test_repo"
        repo_path.mkdir()

        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
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

        (repo_path / "test.txt").write_text("initial")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        subprocess.run(
            ["git", "tag", "1.0.0"], cwd=repo_path, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "tag", "1.2.0"], cwd=repo_path, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "tag", "1.1.5"], cwd=repo_path, check=True, capture_output=True
        )

        result = get_recent_version_tags(repo_path, limit=1)

        assert result == ["1.2.0"]

    def test_finds_latest_version_tag_with_v_prefix(self, tmp_path):
        repo_path = tmp_path / "test_repo"
        repo_path.mkdir()

        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
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

        (repo_path / "test.txt").write_text("initial")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        subprocess.run(
            ["git", "tag", "v1.0.0"], cwd=repo_path, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "tag", "v2.1.0"], cwd=repo_path, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "tag", "v1.5.3"], cwd=repo_path, check=True, capture_output=True
        )

        result = get_recent_version_tags(repo_path, limit=1)

        assert result == ["v2.1.0"]

    def test_returns_empty_list_when_no_version_tags(self, tmp_path):
        repo_path = tmp_path / "test_repo"
        repo_path.mkdir()

        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
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

        (repo_path / "test.txt").write_text("initial")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        subprocess.run(
            ["git", "tag", "release-candidate"], cwd=repo_path, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "tag", "beta"], cwd=repo_path, check=True, capture_output=True
        )

        result = get_recent_version_tags(repo_path)

        assert result == []

    def test_handles_mixed_version_formats(self, tmp_path):
        repo_path = tmp_path / "test_repo"
        repo_path.mkdir()

        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
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

        (repo_path / "test.txt").write_text("initial")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        subprocess.run(
            ["git", "tag", "1.0.0"], cwd=repo_path, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "tag", "v2.0.0"], cwd=repo_path, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "tag", "1.5.0"], cwd=repo_path, check=True, capture_output=True
        )

        result = get_recent_version_tags(repo_path, limit=1)

        assert result == ["v2.0.0"]


class TestCLISinceLastTag:
    def test_since_last_tag_0_includes_commits_after_tag(self, tmp_path):
        repo_path = tmp_path / "test_repo"
        repo_path.mkdir()

        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
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

        (repo_path / "test.txt").write_text("initial")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "tag", "v1.0.0"], cwd=repo_path, check=True, capture_output=True
        )

        (repo_path / "test.txt").write_text("second")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Second commit"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        runner = CliRunner()
        result = runner.invoke(main, ["--since-last-tag=0", "--repo", str(repo_path)])

        assert result.exit_code == 0
        assert "Second commit" in result.output
        assert "Initial commit" not in result.output

    def test_since_last_tag_0_uses_range_latest_to_head(self, tmp_path):
        repo_path = tmp_path / "test_repo"
        repo_path.mkdir()

        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
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

        # Commit 1 (v1.0.0)
        (repo_path / "file1").write_text("1")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Commit 1"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "tag", "v1.0.0"], cwd=repo_path, check=True, capture_output=True
        )

        # Commit 2 (Middle)
        (repo_path / "file2").write_text("2")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Commit 2"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "tag", "v1.1.0"], cwd=repo_path, check=True, capture_output=True
        )

        # Commit 3 (After)
        (repo_path / "file3").write_text("3")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Commit 3"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        runner = CliRunner()
        result = runner.invoke(main, ["--since-last-tag", "--repo", str(repo_path)])

        assert result.exit_code == 0
        assert "Commit 3" in result.output
        assert "Commit 2" not in result.output
        assert "Commit 1" not in result.output

    def test_since_last_tag_with_skip(self, tmp_path):
        repo_path = tmp_path / "test_repo"
        repo_path.mkdir()

        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
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

        (repo_path / "test.txt").write_text("initial")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "tag", "v1.0.0"], cwd=repo_path, check=True, capture_output=True
        )

        (repo_path / "test.txt").write_text("second")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Second commit"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "tag", "v2.0.0"], cwd=repo_path, check=True, capture_output=True
        )

        (repo_path / "test.txt").write_text("third")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Third commit"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        runner = CliRunner()
        result = runner.invoke(main, ["--since-last-tag=1", "--repo", str(repo_path)])

        assert result.exit_code == 0
        assert "Third commit" not in result.output
        assert "Second commit" in result.output
        assert "Initial commit" not in result.output

    def test_since_last_tag_fails_when_no_tags(self, tmp_path):
        repo_path = tmp_path / "test_repo"
        repo_path.mkdir()

        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
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

        (repo_path / "test.txt").write_text("initial")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        runner = CliRunner()
        result = runner.invoke(main, ["--since-last-tag=0", "--repo", str(repo_path)])

        assert result.exit_code != 0
        assert "No version tag found at skip position" in result.output


class TestCLIGitRepositoryCheck:
    def test_fails_when_not_a_git_repository(self, tmp_path):
        non_repo_path = tmp_path / "not_a_repo"
        non_repo_path.mkdir()

        runner = CliRunner()
        result = runner.invoke(main, ["--repo", str(non_repo_path)])

        assert result.exit_code != 0
        assert "is not a git repository" in result.output


class TestRemoveGitTrailers:
    def test_preserves_conventional_commit_subject(self):
        message = "build: move dive to a dev-only toolset, bump bun version (#337)\n\n"
        result = remove_git_trailers(message)
        assert result == "build: move dive to a dev-only toolset, bump bun version (#337)"

    def test_preserves_subject_only_commit(self):
        message = "feat: add new feature"
        result = remove_git_trailers(message)
        assert result == "feat: add new feature"

    def test_removes_trailers_from_end(self):
        message = "feat: add authentication\n\nImplement user login\n\nSigned-off-by: User <user@example.com>\nReviewed-by: Reviewer <reviewer@example.com>"
        result = remove_git_trailers(message)
        assert result == "feat: add authentication\n\nImplement user login"

    def test_preserves_body_with_colons(self):
        message = "fix: resolve issue\n\nThe problem was in the config file"
        result = remove_git_trailers(message)
        assert result == "fix: resolve issue\n\nThe problem was in the config file"

    def test_handles_empty_message(self):
        message = ""
        result = remove_git_trailers(message)
        assert result == ""

    def test_removes_only_trailing_trailers(self):
        message = "feat: new feature\n\nUser-Facing: Added new button\n\nMore details here\n\nSigned-off-by: Dev <dev@example.com>"
        result = remove_git_trailers(message)
        assert result == "feat: new feature\n\nUser-Facing: Added new button\n\nMore details here"
