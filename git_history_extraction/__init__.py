import re
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
import click
import structlog
from structlog_config import configure_logger
from git import Repo, InvalidGitRepositoryError, GitCommandError, BadName, NoSuchPathError

from .version import __version__


class OptionalIntOption(click.Option):
    def __init__(self, *args, **kwargs):
        kwargs["is_flag"] = False
        super().__init__(*args, **kwargs)
        self._flag_needs_value = True


class OptionalStringOption(click.Option):
    def __init__(self, *args, **kwargs):
        kwargs["is_flag"] = False
        super().__init__(*args, **kwargs)
        self._flag_needs_value = True


def is_git_repository(repo_path: Path) -> bool:
    """Check if the given path is inside a git repository."""
    try:
        Repo(repo_path)
        return True
    except (InvalidGitRepositoryError, NoSuchPathError):
        return False


def get_last_monday() -> str:
    """Return last Monday at midnight as git-compatible timestamp."""
    today = datetime.now()
    days_since_monday = today.weekday()
    if days_since_monday == 0:
        last_monday = today
    else:
        last_monday = today - timedelta(days=days_since_monday)

    return last_monday.replace(hour=0, minute=0, second=0, microsecond=0).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def fetch_remote_branch(
    repo: Repo,
    remote_name: str,
    branch_name: str,
    log: structlog.stdlib.BoundLogger,
) -> None:
    try:
        remote = getattr(repo.remotes, remote_name)
    except AttributeError:
        log.warning("remote not configured", remote=remote_name)
        return

    refspec = f"+refs/heads/{branch_name}:refs/remotes/{remote_name}/{branch_name}"
    log.info(
        "fetching remote branch",
        remote=remote_name,
        branch=branch_name,
        refspec=refspec,
    )
    remote.fetch(refspec=refspec)


def get_local_branch(repo: Repo, branch_name: str):
    try:
        return repo.heads[branch_name]
    except IndexError:
        return None


def find_local_default_branch(repo: Repo, reference_ref: str = "HEAD") -> str | None:
    candidate_branch_names = [
        branch_name
        for branch_name in ["main", "master"]
        if get_local_branch(repo, branch_name) is not None
    ]

    if not candidate_branch_names:
        return None

    if reference_ref in candidate_branch_names:
        return reference_ref

    selected_branch_name: str | None = None
    selected_merge_base_time = -1

    for branch_name in candidate_branch_names:
        try:
            merge_bases = repo.merge_base(reference_ref, branch_name)
        except (BadName, GitCommandError):
            continue

        if not merge_bases:
            continue

        newest_merge_base = max(merge_bases, key=lambda commit: commit.committed_date)
        if newest_merge_base.committed_date > selected_merge_base_time:
            selected_branch_name = branch_name
            selected_merge_base_time = newest_merge_base.committed_date

    return selected_branch_name


def find_tracking_branch(
    repo: Repo,
    branch_name: str,
) -> tuple[str, str, str] | None:
    branch = get_local_branch(repo, branch_name)
    if branch is None:
        return None

    tracking_branch = branch.tracking_branch()
    if tracking_branch is None:
        return None

    return tracking_branch.name, tracking_branch.remote_name, tracking_branch.remote_head


def find_remote_default_branch(
    repo: Repo,
    reference_ref: str = "HEAD",
) -> tuple[str, str, str] | None:
    local_default_branch = find_local_default_branch(repo, reference_ref)
    if local_default_branch:
        tracking_branch = find_tracking_branch(repo, local_default_branch)
        if tracking_branch:
            return tracking_branch

    branch_names = [local_default_branch] if local_default_branch else []
    branch_names.extend(
        branch_name
        for branch_name in ["main", "master"]
        if branch_name not in branch_names
    )

    for branch_name in branch_names:
        for remote_name in ["upstream", "origin"]:
            try:
                getattr(repo.remotes, remote_name)
            except AttributeError:
                continue

            ref = f"{remote_name}/{branch_name}"
            try:
                repo.commit(ref)
            except (BadName, GitCommandError):
                continue

            return ref, remote_name, branch_name

    return None


def get_default_branch(
    repo_path: Path | None = None,
    use_remote: bool = False,
    fetch: bool = False,
    log: structlog.stdlib.BoundLogger | None = None,
    reference_ref: str = "HEAD",
) -> str:
    """Return the default branch name (main or master), optionally as a remote ref."""
    repo = Repo(repo_path if repo_path else ".")

    if use_remote:
        remote_ref = find_remote_default_branch(repo, reference_ref=reference_ref)
        if remote_ref:
            ref, remote_name, branch_name = remote_ref
            if fetch and log:
                fetch_remote_branch(repo, remote_name, branch_name, log)
            if log:
                log.info("using remote branch reference", ref=ref)
            return ref

        if log:
            log.warning("no remote default branch found, falling back to local")

    local_default_branch = find_local_default_branch(repo, reference_ref=reference_ref)
    if local_default_branch:
        if log:
            log.info("using local branch reference", ref=local_default_branch)
        return local_default_branch

    for branch in ["main", "master"]:
        try:
            repo.commit(branch)
            if log:
                log.info("using local branch reference", ref=branch)
            return branch
        except (BadName, GitCommandError):
            continue

    try:
        remote_head = repo.remotes.origin.refs.HEAD.ref.name
        if log:
            log.info("using origin head reference", ref=remote_head)
        return remote_head.replace("origin/", "")
    except (AttributeError, IndexError, GitCommandError):
        pass

    if log:
        log.info("using fallback branch reference", ref="main")
    return "main"


def get_recent_version_tags(
    repo_path: Path | None = None,
    limit: int = 1,
    log: structlog.stdlib.BoundLogger | None = None,
) -> list[str]:
    repo = Repo(repo_path if repo_path else ".")

    try:
        if log:
            log.info("fetching tags from origin")
        repo.remotes.origin.fetch(tags=True)
    except (AttributeError, GitCommandError):
        if log:
            log.warning("failed to fetch tags from origin")

    version_pattern = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
    tags_with_versions: list[tuple[tuple[int, int, int], str]] = []

    for tag in repo.tags:
        tag_name = tag.name.strip()
        match = version_pattern.match(tag_name)
        if match:
            version = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
            tags_with_versions.append((version, tag_name))

    if not tags_with_versions:
        return []

    tags_with_versions.sort(reverse=True)
    return [t[1] for t in tags_with_versions[:limit]]


def get_latest_version_tag(repo_path: Path | None = None, skip: int = 0) -> str | None:
    """Fetch and return the Nth highest semantic version tag (X.Y.Z or vX.Y.Z), skipping N most recent tags."""
    tags = get_recent_version_tags(repo_path, limit=skip + 1)
    if skip >= len(tags):
        return None

    return tags[skip]


def get_commit_files(sha: str, repo_path: Path | None = None) -> list[str]:
    """Return list of file paths changed in a commit."""
    repo = Repo(repo_path if repo_path else ".")
    commit = repo.commit(sha)
    return [str(f) for f in commit.stats.files.keys()]


def get_file_change_stats(sha: str, repo_path: Path | None = None) -> list[dict]:
    """Return detailed stats for each file in a commit: path, type (A/M/D/R/C), and line counts."""
    repo = Repo(repo_path if repo_path else ".")
    commit = repo.commit(sha)

    status_map = {}
    if commit.parents:
        parent = commit.parents[0]
        diffs = parent.diff(commit)

        for diff in diffs:
            if diff.new_file:
                status_map[diff.b_path] = "A"
            elif diff.deleted_file:
                status_map[diff.a_path] = "D"
            elif diff.renamed_file:
                status_map[diff.b_path] = "R"
            elif diff.copied_file:
                status_map[diff.b_path] = "C"
            else:
                status_map[diff.b_path or diff.a_path] = "M"
    else:
        for filepath in commit.stats.files.keys():
            status_map[filepath] = "A"

    file_stats = []
    for filepath, stats in commit.stats.files.items():
        change_type = status_map.get(filepath, "M")
        added_count = stats.get("insertions", 0)
        deleted_count = stats.get("deletions", 0)

        file_stats.append(
            {
                "path": filepath,
                "type": change_type,
                "lines_added": added_count,
                "lines_deleted": deleted_count,
                "lines_changed": added_count + deleted_count,
            }
        )

    return file_stats


def get_git_commits(
    since,
    since_commit=None,
    until_commit="HEAD",
    repo_path: Path | None = None,
    include_stats: bool = False,
):
    """Extract commits with sha, date, body, files. Optionally include per-file change stats."""
    repo = Repo(repo_path if repo_path else ".")

    if since_commit:
        rev = f"{since_commit}..{until_commit}"
        commits_iter = repo.iter_commits(rev)
    else:
        commits_iter = repo.iter_commits(until_commit, since=since)

    commits: list[dict] = []
    for commit in commits_iter:
        files = list(commit.stats.files.keys())

        commit_data = {
            "sha": commit.hexsha,
            "date": commit.committed_datetime.isoformat(),
            "body": commit.message,
            "files": files,
        }

        if include_stats:
            commit_data["file_stats"] = get_file_change_stats(commit.hexsha, repo_path)

        commits.append(commit_data)

    return commits


def remove_git_trailers(commit_body: str) -> str:
    """Strip trailers (key: value pairs) from end of commit message."""
    lines = commit_body.splitlines()
    trailer_regex = re.compile(r"^\s*[-*]?\s*[A-Z][a-z-]*(-[A-Z][a-z-]*)*:\s+.+$")

    if not lines:
        return ""

    while lines and not lines[-1].strip():
        lines.pop()

    if len(lines) <= 1:
        return "\n".join(lines)

    trailer_start_idx = len(lines)
    for i in range(len(lines) - 1, 0, -1):
        if trailer_regex.match(lines[i]):
            trailer_start_idx = i
        elif lines[i].strip():
            break

    if trailer_start_idx < len(lines) and trailer_start_idx > 1:
        lines = lines[:trailer_start_idx]

    while lines and not lines[-1].strip():
        lines.pop()

    return "\n".join(lines)


def extract_git_trailers(commit_body: str) -> list[tuple[str, str]]:
    """Extract trailers from commit body as (key, value) tuples. Deduplicates case-insensitively."""
    lines = commit_body.splitlines()
    trailer_regex = re.compile(r"^\s*[-*]?\s*([^:]+):\s*(.*)$")

    idx = len(lines) - 1
    while idx >= 0 and not lines[idx].strip():
        idx -= 1

    collected: list[tuple[str, str]] = []
    seen_keys: set[tuple[str, str]] = set()
    j = idx
    while j >= 0:
        m = trailer_regex.match(lines[j])
        if not m:
            break
        pair = (m.group(1), m.group(2))
        collected.append(pair)
        seen_keys.add((m.group(1).strip().lower(), m.group(2).strip()))
        j -= 1
    collected.reverse()

    for line in lines:
        m = trailer_regex.match(line)
        if not m:
            continue
        key_norm = (m.group(1).strip().lower(), m.group(2).strip())
        if key_norm in seen_keys:
            continue
        collected.append((m.group(1), m.group(2)))
        seen_keys.add(key_norm)

    return collected


def extract_history(
    repo_path=".",
    since=None,
    since_commit=None,
    since_last_tag=None,
    branch=None,
    remote=True,
    include_stats=True,
    trailers=None,
):
    """
    Extracts git history based on the provided parameters.
    Returns a list of commit dictionaries, identical to the CLI's JSON format.
    """
    repo = Path(repo_path)
    log = structlog.get_logger()

    if not is_git_repository(repo):
        raise ValueError(f"'{repo}' is not a git repository.")

    until_commit = "HEAD"
    default_repo_branch: str | None = None
    if branch is not None:
        if since is not None or since_commit is not None or since_last_tag is not None:
            raise ValueError("--branch cannot be combined with --since, --since-commit, or --since-last-tag.")

        repo_obj = Repo(repo)
        if branch == "":
            try:
                target_branch = repo_obj.active_branch.name
            except TypeError:
                raise ValueError("Repository is in a detached HEAD state. Please specify a branch name.")
        else:
            target_branch = branch

        log.info("comparing branch against remote default", target_branch=target_branch)
        default_repo_branch = get_default_branch(
            repo,
            use_remote=True,
            fetch=True,
            log=log,
            reference_ref=target_branch,
        )
        branch_name = default_repo_branch.split("/", 1)[-1]
        invalid_branches = {
            default_repo_branch,
            branch_name,
            "main",
            "master",
            f"origin/{branch_name}",
            f"upstream/{branch_name}",
        }
        if target_branch in invalid_branches:
            raise ValueError(f"'{target_branch}' is not a valid value for --branch.")

        since_commit = default_repo_branch
        until_commit = target_branch

    latest_tag = None
    if since_last_tag is not None:
        tags = get_recent_version_tags(repo, limit=since_last_tag + 1, log=log)
        if not tags or since_last_tag >= len(tags):
            raise ValueError(f"No version tag found at skip position {since_last_tag}.")

        latest_tag = tags[since_last_tag]
        since_commit = latest_tag

        if since_last_tag == 0:
            until_commit = "HEAD"
        else:
            until_commit = tags[since_last_tag - 1]

    if since is None and since_commit is None and branch is None:
        since = get_last_monday()

    if default_repo_branch is None:
        default_repo_branch = get_default_branch(
            repo,
            use_remote=remote,
            fetch=remote,
            log=log,
            reference_ref=until_commit,
        )

    log.info("selected reference branch", branch=default_repo_branch)

    if remote and until_commit == "HEAD":
        until_commit = default_repo_branch

    if since_commit:
        range_str = f"{since_commit}..{until_commit}"
    else:
        range_str = f"since={since}"

    log.info("git commit range", range=range_str)

    commits = get_git_commits(
        since,
        since_commit,
        until_commit=until_commit,
        repo_path=repo,
        include_stats=include_stats,
    )

    if trailers is not None:
        if isinstance(trailers, str):
            selectors = {part.strip().lower() for part in trailers.split(",") if part.strip()}
        else:
            selectors = {t.strip().lower() for t in trailers}

        filtered_commits = []
        for c in commits:
            trailer_items = extract_git_trailers(c["body"]) or []
            if selectors:
                trailer_items = [t for t in trailer_items if t[0].lower() in selectors]
            if not trailer_items:
                continue

            c["matched_trailers"] = trailer_items
            filtered_commits.append(c)
        commits = filtered_commits

    return commits


@click.command()
@click.version_option(version=__version__, message="%(version)s")
@click.option(
    "--since",
    type=str,
    default=None,
    help="ISO date/time or relative time (default: last Monday)",
)
@click.option(
    "--since-commit",
    type=str,
    default=None,
    help="Specific commit sha to start from (e.g. abc123). Overrides --since if provided.",
)
@click.option(
    "--since-last-tag",
    type=int,
    default=None,
    flag_value=0,
    cls=OptionalIntOption,
    help="Use the Nth most recent version tag (X.Y.Z or vX.Y.Z) as the starting point. 0 = LatestTag..HEAD (default), 1 = PreviousTag..LatestTag, etc. Fetches tags from origin first. Overrides --since and --since-commit if provided.",
)
@click.option(
    "--branch",
    "branch_opt",
    type=str,
    default=None,
    flag_value="",
    cls=OptionalStringOption,
    help="Get commits unique to the specified branch. Cannot be combined with --since, --since-commit, or --since-last-tag. If no branch is specified, uses the current branch.",
)
@click.option(
    "--repo",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=Path("."),
    help="Path to the git repository to summarize.",
)
@click.option(
    "--trailers",
    type=str,
    default=None,
    help="Comma-separated trailer key(s) to output (case-insensitive).",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["simple", "json"]),
    default="simple",
    help="Output format (default: simple)",
)
@click.option(
    "--remote/--local",
    default=True,
    help="Use remote references (upstream then origin) instead of local (default: remote). Upstream is preferred since often when a fork is in place, the master/main branch on the origin is not kept up to date.",
)
@click.option(
    "--verbose",
    is_flag=True,
    help="Enable DEBUG level logging",
)
def main(
    since: str | None,
    since_commit: str | None,
    since_last_tag: int | None,
    branch_opt: str | None,
    repo: Path,
    trailers: str | None,
    output_format: str,
    remote: bool,
    verbose: bool,
):
    if verbose:
        os.environ["LOG_LEVEL"] = "DEBUG"

    log = configure_logger(
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )

    include_stats = output_format == "simple" or trailers is not None

    try:
        commits = extract_history(
            repo_path=repo,
            since=since,
            since_commit=since_commit,
            since_last_tag=since_last_tag,
            branch=branch_opt,
            remote=remote,
            include_stats=include_stats,
            trailers=trailers,
        )
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()

    if not commits:
        click.echo("No commits found using the specified parameters.")
        return

    if since_last_tag is not None:
        default_branch = get_default_branch(repo, use_remote=remote, fetch=remote, log=log)
        tags = get_recent_version_tags(repo, limit=since_last_tag + 1, log=log)
        latest_tag = tags[since_last_tag]
        click.echo(f"branch: {default_branch}")
        click.echo(f"version: {latest_tag}")
        click.echo(f"commits: {len(commits)}")
        click.echo()

    if trailers is not None:
        out_lines: list[str] = []
        for c in commits:
            trailer_items = c.get("matched_trailers", [])
            out_lines.append(f"Commit: {c['sha']}")
            out_lines.append(f"Date: {c['date']}")

            if "file_stats" in c and c["file_stats"]:
                out_lines.append("Files:")
                for stat in c["file_stats"]:
                    type_label = {
                        "A": "added",
                        "M": "modified",
                        "D": "deleted",
                        "R": "renamed",
                        "C": "copied",
                    }.get(stat["type"], stat["type"])
                    lines_info = f"+{stat['lines_added']}/-{stat['lines_deleted']}"
                    out_lines.append(f"  {stat['path']} ({type_label}, {lines_info})")
            else:
                files = ", ".join(c.get("files", []))
                out_lines.append(f"Files: {files}")

            out_lines.extend([f"{k}: {v}" for k, v in trailer_items])
            out_lines.append("")
        click.echo("\n".join(out_lines).rstrip())
        return

    if output_format == "json":
        import json
        click.echo(json.dumps(commits, indent=2))
    else:
        for c in commits:
            body = remove_git_trailers(c["body"]) or "(no message)"
            click.echo(f"Commit: {c['sha']}")
            click.echo(f"Date: {c['date']}")

            if "file_stats" in c and c["file_stats"]:
                click.echo("\nFiles:")
                for stat in c["file_stats"]:
                    type_label = {
                        "A": "added",
                        "M": "modified",
                        "D": "deleted",
                        "R": "renamed",
                        "C": "copied",
                    }.get(stat["type"], stat["type"])

                    lines_info = f"+{stat['lines_added']}/-{stat['lines_deleted']}"
                    click.echo(f"  {stat['path']} ({type_label}, {lines_info})")
            else:
                files = ", ".join(c.get("files", []))
                click.echo(f"Files: {files}")

            click.echo(f"\n{body}\n")
            click.echo("-" * 80)
