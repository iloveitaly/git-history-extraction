"""Test git-history-extraction."""

import git_history_extraction


def test_import() -> None:
    """Test that the  can be imported."""
    assert isinstance(git_history_extraction.__name__, str)