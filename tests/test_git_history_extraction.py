"""Tests for git-history-extraction functionality."""

import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from git_history_extraction import (
    get_last_monday,
    get_latest_version_tag,
    is_git_repository,
    main,
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


class TestGetLatestVersionTag:
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

        result = get_latest_version_tag(repo_path)

        assert result == "1.2.0"

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

        result = get_latest_version_tag(repo_path)

        assert result == "v2.1.0"

    def test_returns_none_when_no_version_tags(self, tmp_path):
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

        result = get_latest_version_tag(repo_path)

        assert result is None

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

        result = get_latest_version_tag(repo_path)

        assert result == "v2.0.0"


class TestCLISinceLastTag:
    def test_since_last_tag_uses_latest_tag(self, tmp_path):
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
        result = runner.invoke(main, ["--since-last-tag", "--repo", str(repo_path)])

        assert result.exit_code == 0
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
        result = runner.invoke(main, ["--since-last-tag", "--repo", str(repo_path)])

        assert result.exit_code != 0
        assert "No version tags found" in result.output


class TestCLIGitRepositoryCheck:
    def test_fails_when_not_a_git_repository(self, tmp_path):
        non_repo_path = tmp_path / "not_a_repo"
        non_repo_path.mkdir()

        runner = CliRunner()
        result = runner.invoke(main, ["--repo", str(non_repo_path)])

        assert result.exit_code != 0
        assert "is not a git repository" in result.output
