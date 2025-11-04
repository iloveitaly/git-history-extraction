import subprocess
import re
from pathlib import Path
from datetime import datetime, timedelta
import click


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
    subprocess.run(
        ["git", "fetch", "--tags"],
        capture_output=True,
        text=True,
        cwd=str(repo_path) if repo_path else None,
    )

    result = subprocess.run(
        ["git", "tag", "-l"],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(repo_path) if repo_path else None,
    )

    version_pattern = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
    tags_with_versions: list[tuple[tuple[int, int, int], str]] = []

    for tag in result.stdout.splitlines():
        tag = tag.strip()
        match = version_pattern.match(tag)
        if match:
            version = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
            tags_with_versions.append((version, tag))

    if not tags_with_versions:
        return None

    tags_with_versions.sort(reverse=True)
    return tags_with_versions[0][1]


def get_commit_files(sha: str, repo_path: Path | None = None) -> list[str]:
    """Return list of file paths changed in a commit."""
    cmd = ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        cwd=str(repo_path) if repo_path else None,
    )
    return [l.strip() for l in result.stdout.splitlines() if l.strip()]


def get_file_change_stats(sha: str, repo_path: Path | None = None) -> list[dict]:
    """Return detailed stats for each file in a commit: path, type (A/M/D/R/C), and line counts."""
    status_cmd = ["git", "diff-tree", "--no-commit-id", "--name-status", "-r", sha]
    status_result = subprocess.run(
        status_cmd,
        capture_output=True,
        text=True,
        check=True,
        cwd=str(repo_path) if repo_path else None,
    )

    numstat_cmd = ["git", "diff-tree", "--no-commit-id", "--numstat", "-r", sha]
    numstat_result = subprocess.run(
        numstat_cmd,
        capture_output=True,
        text=True,
        check=True,
        cwd=str(repo_path) if repo_path else None,
    )

    status_map = {}
    for line in status_result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) == 2:
            status, filepath = parts
            status_map[filepath] = status

    file_stats = []
    for line in numstat_result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            added, deleted, filepath = parts[0], parts[1], parts[2]
            change_type = status_map.get(filepath, "M")

            added_count = 0 if added == "-" else int(added)
            deleted_count = 0 if deleted == "-" else int(deleted)

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
    rec_sep = "\x1e"
    fld_sep = "\x1f"
    end_hdr = "\x1d"

    pretty = f"{rec_sep}%H{fld_sep}%cI{fld_sep}%B{end_hdr}"
    if since_commit:
        cmd = [
            "git",
            "log",
            f"{since_commit}..HEAD",
            f"--pretty=format:{pretty}",
            "--name-only",
        ]
    else:
        cmd = [
            "git",
            "log",
            f"--since={since}",
            f"--pretty=format:{pretty}",
            "--name-only",
        ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        cwd=str(repo_path) if repo_path else None,
    )

    commits: list[dict] = []
    stream = result.stdout
    for block in stream.split(rec_sep):
        if not block.strip():
            continue
        if end_hdr not in block:
            continue
        header, files_blob = block.split(end_hdr, 1)
        parts = header.split(fld_sep, 2)
        if len(parts) != 3:
            continue
        sha, date_iso, body = parts
        files = [l.strip() for l in files_blob.splitlines() if l.strip()]

        commit_data = {
            "sha": sha.strip(),
            "date": date_iso.strip(),
            "body": body.strip(),
            "files": files,
        }

        if include_stats:
            commit_data["file_stats"] = get_file_change_stats(sha.strip(), repo_path)

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
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    default=False,
    help="Output in JSON format (shorthand for --format json)",
)
def main(since: str | None, since_commit: str | None, since_last_tag: bool, repo: Path, trailers: str | None, format: str, output_json: bool):
    if output_json:
        format = "json"

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
