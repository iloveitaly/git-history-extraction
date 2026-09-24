"""gh stack integration for stacked PR workflows."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from git import Repo


@dataclass(frozen=True)
class StackBranch:
    name: str
    is_merged: bool = False
    is_queued: bool = False


@dataclass(frozen=True)
class Stack:
    trunk: str
    branches: list[StackBranch]
    id: str | None = None
    number: int | None = None

    def index_of(self, branch_name: str) -> int:
        for idx, b in enumerate(self.branches):
            if b.name == branch_name:
                return idx
        return -1

    def active_base_branch(self, branch_name: str) -> str:
        """
        Return the effective parent for a branch, skipping merged ancestors.
        If idx == 0 or all downstack branches are merged, returns trunk.
        """
        idx = self.index_of(branch_name)
        if idx <= 0:
            return self.trunk

        for j in range(idx - 1, -1, -1):
            if not self.branches[j].is_merged and not self.branches[j].is_queued:
                return self.branches[j].name

        return self.trunk


def find_stack_file(repo: Repo) -> Path | None:
    candidates: list[Path] = []
    if hasattr(repo, "git_dir"):
        candidates.append(Path(repo.git_dir) / "gh-stack")
    if hasattr(repo, "common_dir") and repo.common_dir != repo.git_dir:
        candidates.append(Path(repo.common_dir) / "gh-stack")

    for path in candidates:
        if path.is_file():
            return path
    return None


def load_stacks_from_disk(repo: Repo) -> list[Stack]:
    stack_file = find_stack_file(repo)
    if not stack_file:
        return []

    try:
        data = json.loads(stack_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    stacks_data = data.get("stacks", [])
    stacks: list[Stack] = []
    for s in stacks_data:
        trunk_name = s.get("trunk", {}).get("branch")
        if not trunk_name:
            continue

        branches: list[StackBranch] = []
        for b in s.get("branches", []):
            b_name = b.get("branch")
            if not b_name:
                continue
            pr = b.get("pullRequest") or {}
            is_merged = bool(pr.get("merged", False))
            branches.append(StackBranch(name=b_name, is_merged=is_merged))

        stacks.append(
            Stack(
                trunk=trunk_name,
                branches=branches,
                id=s.get("id"),
                number=s.get("number"),
            )
        )
    return stacks


def load_stack_from_gh_cli(repo_dir: Path) -> Stack | None:
    if not shutil.which("gh"):
        return None

    try:
        proc = subprocess.run(
            ["gh", "stack", "view", "--json"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode != 0:
            return None

        data = json.loads(proc.stdout)
        trunk = data.get("trunk")
        if not trunk:
            return None

        branches = [
            StackBranch(
                name=b["name"],
                is_merged=b.get("isMerged", False),
                is_queued=b.get("isQueued", False),
            )
            for b in data.get("branches", [])
            if "name" in b
        ]
        return Stack(trunk=trunk, branches=branches)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return None


def resolve_stack_parent_branch(
    repo: Repo, branch_name: str
) -> tuple[str, int, int, str]:
    """
    Find the stack containing branch_name and return:
    (parent_branch, stack_index, total_branches_in_stack, trunk_branch).

    Raises ValueError if:
    - Branch is not in any stack
    - Branch is the trunk branch
    """
    repo_dir = Path(repo.working_dir) if repo.working_dir else Path(".")

    # 1. If checked-out branch, try `gh stack view --json` first for synced PR states
    matched_stack: Stack | None = None
    try:
        is_active = repo.active_branch.name == branch_name
    except (TypeError, ValueError):
        is_active = False

    if is_active:
        matched_stack = load_stack_from_gh_cli(repo_dir)

    # 2. Fall back to reading `.git/gh-stack` directly
    if matched_stack is None:
        disk_stacks = load_stacks_from_disk(repo)
        for s in disk_stacks:
            if s.index_of(branch_name) >= 0:
                matched_stack = s
                break
            if s.trunk == branch_name:
                raise ValueError(
                    f"Branch '{branch_name}' is the trunk branch and is not stacked on another branch."
                )

    if matched_stack is None:
        raise ValueError(f"Branch '{branch_name}' is not part of a gh stack.")

    idx = matched_stack.index_of(branch_name)
    if idx < 0:
        if matched_stack.trunk == branch_name:
            raise ValueError(
                f"Branch '{branch_name}' is the trunk branch and is not stacked on another branch."
            )
        raise ValueError(f"Branch '{branch_name}' is not part of a gh stack.")

    parent = matched_stack.active_base_branch(branch_name)
    return parent, idx, len(matched_stack.branches), matched_stack.trunk
