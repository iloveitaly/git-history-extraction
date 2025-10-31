#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["click", "openai"]
# ///
import sys
import json
from pathlib import Path
import click
from openai import OpenAI


def build_prompt(commits: list[dict]) -> str:
    entries: list[str] = []
    for c in commits:
        files = ", ".join(c.get("files", []))
        entries.append(
            f"Commit: {c['sha']}\nDate: {c['date']}\nFiles: {files}\n\n{c['body']}"
        )

    commits_text = "\n\n".join(entries)

    prompt = (
        "You are an assistant that analyzes git commit messages. "
        "Below are commit messages. "
        "Summarize all user-facing changes and noteworthy developer changes into two separate sections. "
        "Title one section 'User-Facing Changes' and the other 'Developer Changes'. "
        "If a commit includes both types of changes, list them in the appropriate sections.\n\n"
        "Commit Messages:\n"
        f"{commits_text}\n\n"
        "Summaries:"
    )
    return prompt


def summarize_commits(prompt: str) -> str:
    client = OpenAI()
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "You are a concise assistant that outputs only the summary.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content.strip()


@click.command()
@click.option(
    "--input",
    type=click.Path(exists=True, path_type=Path),
    help="JSON file containing commits (if not provided, reads from stdin)",
)
@click.option(
    "--dump-prompt",
    is_flag=True,
    help="Print the prompt and exit without calling OpenAI.",
)
def main(input: Path | None, dump_prompt: bool):
    """Summarize git commits using OpenAI.
    
    Input should be JSON output from main.py --format=json
    """
    if input:
        commits = json.loads(input.read_text())
    else:
        commits = json.load(sys.stdin)

    if not commits:
        click.echo("No commits to summarize.", err=True)
        return

    prompt = build_prompt(commits)
    
    if dump_prompt:
        click.echo(prompt)
        return

    summary = summarize_commits(prompt)
    click.echo(summary)


if __name__ == "__main__":
    main()
