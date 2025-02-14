#!/usr/bin/env python
import subprocess
import datetime
import re
import os
import sys
import argparse
import openai


def get_git_commits(since):
    # Use a unique separator to split commits.
    separator = "<<<END>>>"
    cmd = ["git", "log", f"--since={since}", f"--pretty=format:%B{separator}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit("Error running git log")
    commits = [c.strip() for c in result.stdout.split(separator) if c.strip()]
    return commits


def remove_git_trailers(commit):
    lines = commit.splitlines()
    trailer_regex = re.compile(r"^[A-Za-z0-9-]+:\s+.*$")
    # Remove contiguous trailer lines from the end.
    while lines and trailer_regex.match(lines[-1]):
        lines.pop()
    # Remove any trailing blank lines.
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def build_prompt(commits_text):
    prompt = (
        "You are an assistant that analyzes git commit messages. "
        "Below are commit messages (with trailers removed). "
        "Summarize all user-facing changes and noteworthy developer changes into two separate sections. "
        "Title one section 'User-Facing Changes' and the other 'Developer Changes'. "
        "If a commit includes both types of changes, list them in the appropriate sections.\n\n"
        "Commit Messages:\n"
        f"{commits_text}\n\n"
        "Summaries:"
    )
    return prompt


def summarize_commits(prompt):
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
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


def main():
    parser = argparse.ArgumentParser(
        description="Summarize git commit messages using OpenAI."
    )
    parser.add_argument(
        "--since",
        type=str,
        default="24 hours ago",
        help="ISO date/time or relative time (default: '24 hours ago')",
    )
    args = parser.parse_args()

    commits = get_git_commits(args.since)
    if not commits:
        print(f"No commits found since {args.since}")
        sys.exit(0)

    processed_commits = [remove_git_trailers(commit) for commit in commits]
    commits_text = "\n\n".join(processed_commits)
    prompt = build_prompt(commits_text)
    summary = summarize_commits(prompt)
    print(summary)


if __name__ == "__main__":
    main()
