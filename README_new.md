git-summarize-activity

Purpose
- Summarize recent git commits into two sections: User-Facing Changes and Developer Changes, using OpenAI.
- Inspect commits without calling OpenAI by dumping the exact prompt or printing selected git trailers.
- Include commit SHA, ISO 8601 commit date, and a comma-separated list of changed files for each commit.

Requirements
- uv (to run the script): https://docs.astral.sh/uv/
- git
- OPENAI_API_KEY in the environment (only required when not using --dump or --trailers)

No installation
- The script runs directly via uv; dependencies are resolved on demand.

Core command
- Current directory repo, last 24 hours, and produce a summary via OpenAI:
  OPENAI_API_KEY=... uv run --script main.py --since "24 hours ago"

Target a repository
- Summarize a specific repo path:
  OPENAI_API_KEY=... uv run --script main.py --repo /path/to/repo --since "7 days ago"

Pick a starting commit
- Summarize from a given commit (overrides --since):
  OPENAI_API_KEY=... uv run --script main.py --repo . --since-commit abc1234

Preview without calling OpenAI
- Print the generated prompt and exit:
  uv run --script main.py --repo . --since "24 hours ago" --dump

Show git trailer content only
- Print only trailers (case-insensitive keys, comma-separated list):
  uv run --script main.py --repo . --since "24 hours ago" --trailers "User-Facing, Reviewed-by"

What the script includes per commit
- Commit: <sha>
- Date: <ISO 8601 timestamp>
- Files: <comma-separated changed file paths>
- Body: commit message with trailing trailer block removed (trailers still available through --trailers)

How files are collected
- Single-pass using: git log --pretty + --name-only.
- No per-commit subprocess calls to gather files.

Exit behavior
- If no commits match the criteria, the script prints: "No commits found using the specified parameters." and exits.

Notes
- --repo defaults to the current working directory.
- --trailers selection is case-insensitive.
- --dump is useful to validate the prompt content and token size before calling OpenAI.

Limitations
- Large commit ranges can generate a very large prompt; consider narrowing --since or using --since-commit.
- OpenAI usage requires network connectivity and a valid OPENAI_API_KEY.

Development tips
- main.py is a standalone uv script using Click for the CLI.
- Summarization prompt assembly lives in build_prompt(); adjust as needed.
- Trailer parsing is tolerant of whitespace/bullets and searches both trailing blocks and trailer-like lines in the body.
