import re
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from importlib.metadata import version
import click
import structlog
from structlog_config import configure_logger
from git import Repo, InvalidGitRepositoryError, GitCommandError, BadName


class OptionalIntOption(click.Option):
    def __init__(self, *args, **kwargs):
        kwargs["is_flag"] = False
        super().__init__(*args, **kwargs)
        self._flag_needs_value = True


def is_git_repository(repo_path: Path) -> bool:
    """Check if the given path is inside a git repository."""
    try:
        Repo(repo_path)
        return True
    except InvalidGitRepositoryError:
        return False


def get_last_monday() -> str:
    """Return last Monday at midnight as git-compatible timestamp."""
    today = datetime.now()
    days_since_monday = today.weekday()
    if days_since_monday == 0:
        last_monday = today
    else:
        last_monday = today - timedelta(days=days_since_monday)

    return last_monday.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def get_recent_version_tags(repo_path: Path | None = None, limit: int = 1) -> list[str]:
    repo = Repo(repo_path if repo_path else ".")

    try:
        repo.remotes.origin.fetch(tags=True)
    except (AttributeError, GitCommandError):
        pass

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


def get_default_branch(repo_path: Path | None = None, use_remote: bool = False) -> str:
    """Return the default branch name (main or master)."""
    repo = Repo(repo_path if repo_path else ".")

    if use_remote:
        # check upstream first, then origin
        # this is important because often when a fork is in place, the master/main branch
        # on the origin is not kept up to date with the upstream repo
        for remote in ["upstream", "origin"]:
            for branch in ["main", "master"]:
                ref = f"{remote}/{branch}"
                try:
                    repo.commit(ref)
                    return ref
                except (BadName, GitCommandError):
                    continue

    for branch in ["main", "master"]:
        try:
            repo.commit(branch)
            return branch
        except (BadName, GitCommandError):
            continue

    try:
        remote_head = repo.remotes.origin.refs.HEAD.ref.name
        return remote_head.replace("origin/", "")
    except (AttributeError, IndexError, GitCommandError):
        pass

    return "main"


def get_commit_files(sha: str, repo_path: Path | None = None) -> list[str]:
    """Return list of file paths changed in a commit."""
    repo = Repo(repo_path if repo_path else ".")
    commit = repo.commit(sha)
    return list(commit.stats.files.keys())


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

        file_stats.append({
            "path": filepath,
            "type": change_type,
            "lines_added": added_count,
            "lines_deleted": deleted_count,
            "lines_changed": added_count + deleted_count,
        })

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


@click.command()
@click.version_option(version=version("git-history-extraction"), message="%(version)s")
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
    type=click.Choice(["simple", "json", "toon"]),
    default="simple",
    help="Output format (default: simple)",
)
@click.option(
    "--remote",
    is_flag=True,
    help="Use remote references (upstream then origin) instead of local. Upstream is used since often when a fork is in place, the master/main branch on the origin is not kept up to date.",
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

    if not is_git_repository(repo):
        click.echo(f"Error: '{repo}' is not a git repository.", err=True)
        raise click.Abort()

    until_commit = "HEAD"
    latest_tag = None
    if since_last_tag is not None:
        tags = get_recent_version_tags(repo, limit=since_last_tag + 1)
        if not tags or since_last_tag >= len(tags):
            click.echo(f"No version tag found at skip position {since_last_tag}.", err=True)
            raise click.Abort()

        latest_tag = tags[since_last_tag]
        since_commit = latest_tag

        if since_last_tag == 0:
            until_commit = "HEAD"
        else:
            until_commit = tags[since_last_tag - 1]

    if since is None:
        since = get_last_monday()

    branch = get_default_branch(repo, use_remote=remote)
    log.info("selected branch", branch=branch)

    if remote and until_commit == "HEAD":
        # if we are using remote references, we want to ensure we are using the remote branch
        # as the upper bound for the commit range, not the local HEAD
        until_commit = branch

    if since_commit:
        range_str = f"{since_commit}..{until_commit}"
    else:
        range_str = f"since={since}"

    log.info("git commit range", range=range_str)

    include_stats = output_format == "simple" or trailers is not None
    commits = get_git_commits(
        since,
        since_commit,
        until_commit=until_commit,
        repo_path=repo,
        include_stats=include_stats,
    )
    if not commits:
        click.echo("No commits found using the specified parameters.")
        return

    if since_last_tag is not None:
        branch = get_default_branch(repo, use_remote=remote)
        click.echo(f"branch: {branch}")
        click.echo(f"version: {latest_tag}")
        click.echo(f"commits: {len(commits)}")
        click.echo()

    if trailers is not None:
        selectors = {part.strip().lower() for part in trailers.split(",") if part.strip()}
        out_lines: list[str] = []
        for c in commits:
            trailer_items = extract_git_trailers(c["body"]) or []
            if selectors:
                trailer_items = [t for t in trailer_items if t[0].lower() in selectors]
            if not trailer_items:
                continue

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
    elif output_format == "toon":
        from toon_python import encode
        click.echo(encode(commits))
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
