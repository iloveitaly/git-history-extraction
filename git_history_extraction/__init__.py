import re
from pathlib import Path
from datetime import datetime, timedelta
import click
from git import Repo, InvalidGitRepositoryError, GitCommandError


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


def get_latest_version_tag(repo_path: Path | None = None) -> str | None:
    """Fetch and return the highest semantic version tag (X.Y.Z or vX.Y.Z)."""
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
        return None

    tags_with_versions.sort(reverse=True)
    return tags_with_versions[0][1]


def get_default_branch(repo_path: Path | None = None) -> str:
    """Return the default branch name (main or master)."""
    repo = Repo(repo_path if repo_path else ".")

    for branch in ["main", "master"]:
        try:
            repo.commit(branch)
            return branch
        except:
            continue

    try:
        remote_head = repo.remotes.origin.refs.HEAD.ref.name
        return remote_head.replace("origin/", "")
    except:
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


def get_git_commits(since, since_commit=None, repo_path: Path | None = None, include_stats: bool = False):
    """Extract commits with sha, date, body, files. Optionally include per-file change stats."""
    repo = Repo(repo_path if repo_path else ".")

    if since_commit:
        rev = f"{since_commit}..HEAD"
        commits_iter = repo.iter_commits(rev)
    else:
        commits_iter = repo.iter_commits(since=since)

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
    trailer_regex = re.compile(r"^\s*[-*]?\s*[^:]+:\s*.*$")

    while lines and not lines[-1].strip():
        lines.pop()

    while lines and trailer_regex.match(lines[-1]):
        lines.pop()

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
    is_flag=True,
    default=False,
    help="Use the latest version tag (X.Y.Z or vX.Y.Z) as the starting point. Fetches tags from origin first. Overrides --since and --since-commit if provided.",
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
    type=click.Choice(["simple", "json"]),
    default="simple",
    help="Output format (default: simple)",
)
def main(since: str | None, since_commit: str | None, since_last_tag: bool, repo: Path, trailers: str | None, format: str):
    if not is_git_repository(repo):
        click.echo(f"Error: '{repo}' is not a git repository.", err=True)
        raise click.Abort()

    if since_last_tag:
        latest_tag = get_latest_version_tag(repo)
        if not latest_tag:
            click.echo("No version tags found in repository.", err=True)
            raise click.Abort()
        since_commit = latest_tag

    if since is None:
        since = get_last_monday()

    include_stats = format == "simple" or trailers is not None
    commits = get_git_commits(since, since_commit, repo_path=repo, include_stats=include_stats)
    if not commits:
        click.echo("No commits found using the specified parameters.")
        return

    if since_last_tag:
        branch = get_default_branch(repo)
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

    if format == "json":
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
