"""gh stack integration for stacked PR workflows."""

import json
import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from git import BadName, GitCommandError

if TYPE_CHECKING:
    from git import Repo

log = structlog.get_logger()


@dataclass(frozen=True)
class StackBranch:
    """Represents a branch in a PR stack."""

    name: str
    is_merged: bool = False
    is_queued: bool = False
    head: str | None = None
    base: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    merged_head: str | None = None
    needs_rebase: bool = False


@dataclass(frozen=True)
class Stack:
    """Represents a linear stack of branches targeting a trunk branch."""

    trunk: str
    branches: tuple[StackBranch, ...]
    id: str | None = None
    number: int | None = None
    trunk_head: str | None = None

    def __init__(
        self,
        trunk: str,
        branches: Sequence[StackBranch] = (),
        id: str | None = None,
        number: int | None = None,
        trunk_head: str | None = None,
    ):
        object.__setattr__(self, "trunk", trunk)
        object.__setattr__(self, "branches", tuple(branches))
        object.__setattr__(self, "id", id)
        object.__setattr__(self, "number", number)
        object.__setattr__(self, "trunk_head", trunk_head)

    def index_of(self, branch_name: str) -> int:
        """Return 0-based index of branch_name in this stack, or -1 if not found."""
        for idx, b in enumerate(self.branches):
            if b.name == branch_name:
                return idx
        return -1

    def active_base_branch(self, branch_name: str) -> str:
        """Return the effective parent branch, skipping merged and queued ancestors.

        If idx <= 0 or all downstack branches are merged/queued, returns trunk.
        """
        idx = self.index_of(branch_name)
        if idx <= 0:
            return self.trunk

        for j in range(idx - 1, -1, -1):
            if not self.branches[j].is_merged and not self.branches[j].is_queued:
                return self.branches[j].name

        return self.trunk

    def get_ancestor_exclusions(self, branch_name: str) -> list[str]:
        """Collect commit SHAs/refs of merged downstack ancestors that should be excluded
        to prevent squash/rebase merged commits from leaking into diffs.
        """
        idx = self.index_of(branch_name)
        if idx <= 0:
            return []

        exclusions: list[str] = []
        target = self.branches[idx]
        if target.base:
            exclusions.append(target.base)

        for j in range(idx - 1, -1, -1):
            ancestor = self.branches[j]
            if ancestor.is_merged or ancestor.is_queued:
                if ancestor.merged_head and ancestor.merged_head not in exclusions:
                    exclusions.append(ancestor.merged_head)
                if ancestor.head and ancestor.head not in exclusions:
                    exclusions.append(ancestor.head)
                if ancestor.name and ancestor.name not in exclusions:
                    exclusions.append(ancestor.name)
        return exclusions


@dataclass(frozen=True)
class StackContext:
    """Context and comparison metadata for a branch within a gh stack."""

    parent_branch: str
    stack_index: int
    total_branches: int
    trunk_branch: str
    exclude_refs: tuple[str, ...] = ()
    stack: Stack | None = None

    def __iter__(self):
        """Allow backwards-compatible 4-tuple unpacking:
        parent_branch, idx, total, trunk = context
        """
        return iter(
            (
                self.parent_branch,
                self.stack_index,
                self.total_branches,
                self.trunk_branch,
            )
        )

    def __eq__(self, other: object) -> bool:
        """Support equality comparisons with both StackContext and 4-tuples."""
        if isinstance(other, tuple):
            return tuple(self) == other
        if not isinstance(other, StackContext):
            return NotImplemented
        return (
            self.parent_branch == other.parent_branch
            and self.stack_index == other.stack_index
            and self.total_branches == other.total_branches
            and self.trunk_branch == other.trunk_branch
            and self.exclude_refs == other.exclude_refs
            and self.stack == other.stack
        )


def find_stack_file(repo: "Repo") -> Path | None:
    """Locate the gh-stack catalog file in the repository.

    The git common directory is checked first (canonical upstream storage for
    multi-worktree repositories), followed by git_dir for backwards compatibility.
    """
    candidates: list[Path] = []
    common_dir = getattr(repo, "common_dir", None)
    if common_dir:
        candidates.append(Path(common_dir) / "gh-stack")
    git_dir = getattr(repo, "git_dir", None)
    if git_dir:
        p = Path(git_dir) / "gh-stack"
        if p not in candidates:
            candidates.append(p)

    for path in candidates:
        if path.is_file():
            return path
    return None


def load_stacks_from_disk(repo: "Repo") -> list[Stack]:
    """Load stacks from the .git/gh-stack file on disk.

    Safely handles malformed JSON or unexpected types, and checks schema version <= 1.
    """
    stack_file = find_stack_file(repo)
    if not stack_file:
        return []

    try:
        data = json.loads(stack_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(data, dict):
        return []

    schema_version = data.get("schemaVersion", 1)
    if isinstance(schema_version, int) and schema_version > 1:
        log.warning(
            "unsupported gh-stack schemaVersion",
            schema_version=schema_version,
            supported=1,
        )
        return []

    stacks_data = data.get("stacks")
    if not isinstance(stacks_data, list):
        return []

    stacks: list[Stack] = []
    for s in stacks_data:
        if not isinstance(s, dict):
            continue

        trunk_data = s.get("trunk")
        trunk_name: str | None = None
        trunk_head: str | None = None
        if isinstance(trunk_data, dict):
            trunk_name = trunk_data.get("branch")
            trunk_head = trunk_data.get("head")
        elif isinstance(trunk_data, str):
            trunk_name = trunk_data

        if not trunk_name or not isinstance(trunk_name, str):
            continue

        branches_data = s.get("branches")
        if not isinstance(branches_data, list):
            branches_data = []

        branches: list[StackBranch] = []
        for b in branches_data:
            if not isinstance(b, dict):
                continue
            b_name = b.get("branch")
            if not b_name or not isinstance(b_name, str):
                continue

            pr = b.get("pullRequest")
            if not isinstance(pr, dict):
                pr = {}

            is_merged = bool(pr.get("merged", False))
            merged_head = pr.get("mergedHead")
            head = b.get("head")
            base = b.get("base")
            pr_number = pr.get("number")
            pr_url = pr.get("url")

            branches.append(
                StackBranch(
                    name=b_name,
                    is_merged=is_merged,
                    is_queued=False,
                    head=head,
                    base=base,
                    pr_number=pr_number,
                    pr_url=pr_url,
                    merged_head=merged_head,
                )
            )

        stacks.append(
            Stack(
                trunk=trunk_name,
                branches=branches,
                id=s.get("id"),
                number=s.get("number"),
                trunk_head=trunk_head,
            )
        )
    return stacks


def load_stack_from_gh_cli(
    repo_dir: Path, timeout: float | None = None
) -> Stack | None:
    """Query `gh stack view --json` to load real-time stack state.

    Extracts branch names, PR merge status, merge queue status, and base/head SHAs.
    Returns None if gh is not installed, fails, or times out.
    """
    if not shutil.which("gh"):
        return None

    if timeout is None:
        try:
            timeout = float(os.getenv("GH_STACK_TIMEOUT", "5.0"))
        except ValueError:
            timeout = 5.0

    try:
        proc = subprocess.run(
            ["gh", "stack", "view", "--json"],
            cwd=repo_dir,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode != 0:
            log.debug(
                "gh stack view returned non-zero",
                code=proc.returncode,
                stderr=proc.stderr.strip() if proc.stderr else "",
            )
            return None

        data = json.loads(proc.stdout)
        if not isinstance(data, dict):
            return None

        trunk_val = data.get("trunk")
        trunk_name: str | None = None
        if isinstance(trunk_val, str):
            trunk_name = trunk_val
        elif isinstance(trunk_val, dict):
            trunk_name = trunk_val.get("branch")

        if not trunk_name:
            return None

        branches_raw = data.get("branches")
        if not isinstance(branches_raw, list):
            return None

        branches: list[StackBranch] = []
        for b in branches_raw:
            if not isinstance(b, dict):
                continue
            name = b.get("name")
            if not name or not isinstance(name, str):
                continue

            pr_data = b.get("pr")
            if not isinstance(pr_data, dict):
                pr_data = {}

            is_merged = bool(b.get("isMerged", False)) or (
                pr_data.get("state") == "MERGED"
            )
            is_queued = bool(b.get("isQueued", False)) or (
                pr_data.get("state") == "QUEUED"
            )
            head = b.get("head")
            base = b.get("base")
            needs_rebase = bool(b.get("needsRebase", False))
            pr_number = pr_data.get("number")
            pr_url = pr_data.get("url")
            merged_head = head if is_merged else None

            branches.append(
                StackBranch(
                    name=name,
                    is_merged=is_merged,
                    is_queued=is_queued,
                    head=head,
                    base=base,
                    pr_number=pr_number,
                    pr_url=pr_url,
                    merged_head=merged_head,
                    needs_rebase=needs_rebase,
                )
            )

        log.debug(
            "loaded stack from gh CLI",
            trunk=trunk_name,
            branches_count=len(branches),
        )
        return Stack(trunk=trunk_name, branches=branches)
    except subprocess.TimeoutExpired:
        log.warning("gh stack view timed out", timeout=timeout)
        return None
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as e:
        log.debug("failed to run gh stack view", error=str(e))
        return None


def resolve_safe_parent_ref(
    repo: "Repo",
    candidate_parent: str,
    stack: Stack,
    target_branch: str,
    remote: bool = True,
) -> str:
    """Resolve a valid git reference for the stack parent.

    Tries in priority order:
    1. Local parent branch
    2. Remote tracking / remote branch (<upstream|origin>/<parent>) if remote=True
    3. Stored base SHA of the target branch in the stack file
    4. Trunk branch (local or remote)
    """
    # 1. Local candidate branch
    try:
        repo.commit(candidate_parent)
        return candidate_parent
    except (BadName, GitCommandError):
        pass

    # 2. Remote tracking candidate branch
    if remote:
        for r_name in ["upstream", "origin"]:
            remote_ref = f"{r_name}/{candidate_parent}"
            try:
                repo.commit(remote_ref)
                log.debug(
                    "using remote reference for missing stack parent", ref=remote_ref
                )
                return remote_ref
            except (BadName, GitCommandError):
                continue

    # 3. Stored base commit of target branch
    target_idx = stack.index_of(target_branch)
    if target_idx >= 0:
        base_sha = stack.branches[target_idx].base
        if base_sha:
            try:
                repo.commit(base_sha)
                log.debug(
                    "stack parent branch missing locally; using stored base SHA",
                    branch=candidate_parent,
                    base_sha=base_sha,
                )
                return base_sha
            except (BadName, GitCommandError):
                pass

    # 4. Fallback to trunk branch
    log.warning(
        "stack parent branch missing; falling back to trunk",
        parent=candidate_parent,
        trunk=stack.trunk,
    )
    return stack.trunk


def resolve_stack_parent_branch(
    repo: "Repo",
    branch_name: str,
    allow_gh_cli: bool = True,
) -> StackContext:
    """Find the stack containing branch_name and return a StackContext.

    Raises ValueError if:
    - Branch belongs to multiple stacks (ambiguity)
    - Branch is the trunk branch
    - Branch is not in any stack
    """
    repo_dir = Path(repo.working_dir) if repo.working_dir else Path(repo.git_dir).parent

    matched_stack: Stack | None = None
    try:
        is_active = repo.active_branch.name == branch_name
    except (TypeError, ValueError):
        is_active = False

    # 1. If checked-out branch and allow_gh_cli is True, try `gh stack view --json`
    if is_active and allow_gh_cli:
        matched_stack = load_stack_from_gh_cli(repo_dir)

    disk_stacks = load_stacks_from_disk(repo)

    # 2. Fall back to reading .git/gh-stack directly
    if matched_stack is None:
        # Check membership across all stacks first to avoid order-dependent trunk collisions
        member_matches = [s for s in disk_stacks if s.index_of(branch_name) >= 0]
        if len(member_matches) > 1:
            raise ValueError(
                f"Branch '{branch_name}' belongs to multiple stacks. Please checkout a specific branch."
            )
        if len(member_matches) == 1:
            matched_stack = member_matches[0]
        else:
            trunk_matches = [s for s in disk_stacks if s.trunk == branch_name]
            if trunk_matches:
                raise ValueError(
                    f"Branch '{branch_name}' is the trunk branch and is not stacked on another branch."
                )
            raise ValueError(f"Branch '{branch_name}' is not part of a gh stack.")
    else:
        # If loaded from gh CLI, enrich with disk metadata if available (e.g. mergedHead)
        for s in disk_stacks:
            if s.trunk == matched_stack.trunk and s.index_of(branch_name) >= 0:
                enriched_branches: list[StackBranch] = []
                for b_cli in matched_stack.branches:
                    d_idx = s.index_of(b_cli.name)
                    if d_idx >= 0:
                        b_disk = s.branches[d_idx]
                        merged_head = b_cli.merged_head or b_disk.merged_head
                        base = b_cli.base or b_disk.base
                        enriched_branches.append(
                            StackBranch(
                                name=b_cli.name,
                                is_merged=b_cli.is_merged or b_disk.is_merged,
                                is_queued=b_cli.is_queued or b_disk.is_queued,
                                head=b_cli.head or b_disk.head,
                                base=base,
                                pr_number=b_cli.pr_number or b_disk.pr_number,
                                pr_url=b_cli.pr_url or b_disk.pr_url,
                                merged_head=merged_head,
                                needs_rebase=b_cli.needs_rebase,
                            )
                        )
                    else:
                        enriched_branches.append(b_cli)

                matched_stack = Stack(
                    trunk=matched_stack.trunk,
                    branches=enriched_branches,
                    id=s.id,
                    number=s.number,
                    trunk_head=s.trunk_head,
                )
                break

    idx = matched_stack.index_of(branch_name)
    if idx < 0:
        if matched_stack.trunk == branch_name:
            raise ValueError(
                f"Branch '{branch_name}' is the trunk branch and is not stacked on another branch."
            )
        raise ValueError(f"Branch '{branch_name}' is not part of a gh stack.")

    parent = matched_stack.active_base_branch(branch_name)
    exclusions = matched_stack.get_ancestor_exclusions(branch_name)

    return StackContext(
        parent_branch=parent,
        stack_index=idx,
        total_branches=len(matched_stack.branches),
        trunk_branch=matched_stack.trunk,
        exclude_refs=tuple(exclusions),
        stack=matched_stack,
    )


def find_stack_parent_branch(
    repo: "Repo",
    branch_name: str,
    allow_gh_cli: bool = True,
) -> StackContext | None:
    """Safely find the stack containing branch_name and return a StackContext,
    or None if the branch is not in any stack, is trunk, or if stack loading fails.
    """
    try:
        return resolve_stack_parent_branch(repo, branch_name, allow_gh_cli=allow_gh_cli)
    except (ValueError, OSError):
        return None
