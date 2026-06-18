"""Test git-history-extraction."""

import git_history_extraction


def test_import() -> None:
    """Test that the package can be imported."""
    assert isinstance(git_history_extraction.__name__, str)


def test_version() -> None:
    """Test that the version is available."""
    assert isinstance(git_history_extraction.__version__, str)
