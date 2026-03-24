import pytest
import sys
import structlog
from pathlib import Path
from git import Repo
from git_history_extraction import extract_history
from structlog_config import configure_logger

@pytest.fixture(autouse=True)
def setup_logging():
    configure_logger(
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )

def test_extract_history_basic(tmp_path: Path):
    # Setup a dummy repo
    repo = Repo.init(tmp_path)
    (tmp_path / "file.txt").write_text("content")
    repo.index.add(["file.txt"])
    repo.index.commit("Initial commit\n\nUser-facing: New feature")
    
    commits = extract_history(repo_path=tmp_path, include_stats=True)
    
    assert len(commits) == 1
    assert "Initial commit" in commits[0]["body"]
    assert "file.txt" in commits[0]["files"]
    assert "file_stats" in commits[0]

def test_extract_history_trailers(tmp_path: Path):
    repo = Repo.init(tmp_path)
    (tmp_path / "file.txt").write_text("content")
    repo.index.add(["file.txt"])
    repo.index.commit("Commit 1\n\nUser-facing: Feature 1\nInternal: Note 1")
    
    # Filter by trailers
    commits = extract_history(repo_path=tmp_path, trailers="User-facing")
    
    assert len(commits) == 1
    assert "matched_trailers" in commits[0]
    # Check that only the requested trailer is in matched_trailers
    trailer_keys = [t[0] for t in commits[0]["matched_trailers"]]
    assert "User-facing" in trailer_keys
    assert "Internal" not in trailer_keys

def test_extract_history_invalid_repo():
    with pytest.raises(ValueError, match="is not a git repository"):
        extract_history(repo_path="/non/existent/path")

def test_extract_history_branch_conflict(tmp_path: Path):
    repo = Repo.init(tmp_path)
    with pytest.raises(ValueError, match="--branch cannot be combined with"):
        extract_history(repo_path=tmp_path, branch="main", since="last monday")
