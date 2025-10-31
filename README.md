# git-history-extraction

A tool to extract and analyze git commit history with support for filtering, formatting, and AI-powered summarization.

## Features

- Extract git commits with metadata (SHA, date, files, message)
- Filter commits by time range or starting commit
- Extract and filter git trailers (e.g., `Co-authored-by`, `Reviewed-by`)
- Output in simple text or JSON format
- Optional AI-powered summarization via OpenAI (separate script)

## Installation

### Using uv (Recommended)

No installation needed! The tool can be run directly:

```bash
uv run git-history-extraction --help
```

### Install as Package

```bash
pip install git-history-extraction
```

## Usage

### Basic Examples

Extract commits from the last 24 hours (default):
```bash
git-history-extraction
```

Extract commits from the last 7 days:
```bash
git-history-extraction --since "7 days ago"
```

Extract commits from a specific repository:
```bash
git-history-extraction --repo /path/to/repo --since "1 week ago"
```

### Output Formats

Simple text format (default):
```bash
git-history-extraction --since "1 day ago"
```

JSON format for piping to other tools:
```bash
git-history-extraction --since "1 day ago" --format json
```

### Commit Range Selection

By time range:
```bash
git-history-extraction --since "2024-01-01"
```

From a specific commit to HEAD:
```bash
git-history-extraction --since-commit abc1234
```

### Git Trailers

Extract specific trailers only (case-insensitive):
```bash
git-history-extraction --since "1 week ago" --trailers "co-authored-by,reviewed-by"
```

## Summarizing Git History with AI

The tool enables you to extract targeted slices of git history for different audiences. For example, use git trailers like `User-Facing:` to mark end-user changes, then extract and summarize them for changelogs or internal notifications.

### Using with Gemini CLI

Extract user-facing changes and generate a non-technical summary:
```bash
git-history-extraction --repo . --since "last monday" \
  --trailers "User-Facing" | \
  gemini -i "This is a compressed git history identifying user-facing changes. \
Can you write a 1-2 sentence overview of the changes, with a list of bullets \
identifying changes. This is for a non-technical internal audience, letting \
them know what the development team has done. Separate into 'new' and 'fixed' \
sections. Include a 'Updates Since' with the date of the first commit in the \
history. Remove fluff, keep it concise and information dense."
```

### Using the OpenAI Playground Script

For AI-powered commit summarization using OpenAI, use the playground script:

```bash
# Generate summary
git-history-extraction --since "1 week ago" --format json | \
  uv run playground/summarize_commits.py

# Preview the prompt without calling OpenAI
git-history-extraction --since "1 week ago" --format json | \
  uv run playground/summarize_commits.py --dump-prompt
```

**Requirements:**
- `OPENAI_API_KEY` environment variable
- The script uses GPT-4o-mini by default

See [playground/README.md](playground/README.md) for more details.

## Output Format

### Simple Format

Each commit is displayed with:
- **Commit:** SHA hash
- **Date:** ISO 8601 timestamp
- **Files:** Comma-separated list of changed files
- **Message:** Commit body with trailers removed

### JSON Format

Array of commit objects:
```json
[
  {
    "sha": "abc123...",
    "date": "2024-10-31T08:00:00-06:00",
    "body": "commit message with trailers",
    "files": ["file1.py", "file2.md"]
  }
]
```

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `--since TEXT` | ISO date/time or relative time | `"24 hours ago"` |
| `--since-commit TEXT` | Start from specific commit (overrides `--since`) | None |
| `--repo DIRECTORY` | Path to git repository | `.` (current directory) |
| `--trailers TEXT` | Comma-separated trailer keys to extract | None (show all) |
| `--format [simple\|json]` | Output format | `simple` |

## How It Works

- Uses `git log` with custom formatting for efficient single-pass extraction
- Parses commit metadata, body, and file changes in one command
- Intelligently extracts git trailers from commit messages
- No per-commit subprocess calls for optimal performance

## Development

The main logic lives in `git_history_extraction/__init__.py`. The tool is structured as a Python package with:

- **main.py:** Entry point script
- **git_history_extraction/:** Core module with extraction logic
- **playground/:** Optional AI summarization scripts

### Running Tests

```bash
pytest
```

## Limitations

- Large commit ranges may generate significant output; consider narrowing the time range
- AI summarization requires network connectivity and OpenAI API access
- Git must be available in PATH

## Requirements

- Python >= 3.9
- git
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
