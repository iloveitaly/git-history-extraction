# git-history-extraction

A tool to extract and filter git commit history, making it easy to pipe to AI tools for changelog generation and summaries.

## Features

- Extract git commits with metadata (SHA, date, files, message)
- Filter commits by time range or starting commit
- Extract and filter git trailers (e.g., `Co-authored-by`, `User-Facing`)
- Output in simple text or JSON format
- Pipe output to AI tools (OpenAI, Gemini, Claude) for automated summarization

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

## Piping to AI Tools for Summarization

This tool extracts and formats git history, making it easy to pipe to AI tools for summarization. The tool itself **does not perform AI summarization**—it prepares the data so you can use your preferred AI tool.

The tool enables you to extract targeted slices of git history for different audiences. For example, use git trailers like `User-Facing:` to mark end-user changes, then extract and pipe them to AI for changelogs or internal notifications.

### Creating Structured Git Trailers with AI

Combine with [aiautocommit](https://github.com/iloveitaly/aiautocommit) to automatically generate git trailers during commits. This creates a structured history that can be easily filtered and summarized for different audiences.

**Example custom commit prompt for aiautocommit:**

```markdown
# IMPORTANT: Your Instructions

You are an expert software developer. Generate a commit message from the `git diff` output below using these rules:

## 1. Subject Line

- Use a conventional commit prefix:
  - `feat`: New features
  - `fix`: Bug fixes, including user-visible design or style fixes.
  - `docs`: Changes only to internal documentation (e.g., `.md`, `.rst`) or code comments.
  - `style`: Formatting, linting, or code style changes in code files.
  - `refactor`: Code structure improvements (no behavior changes).
  - `build`: Updates to build scripts or configs (e.g., `Makefile`, `Justfile`, `Dockerfile`, `package.json`).
  - `deploy`: Deployment script or IAC updates.
  - `test`: Changes to tests
- Add optional scope in parentheses when changes affect a specific module (e.g., `feat(auth): add login`)
- Limit to 50 characters after the prefix and scope.
- Use imperative mood (e.g., "improve layout").
- Describe the intent or outcome (e.g., "prevent text overflow" not "add break-all").
- Be specific about the change ("validate email format" not "improve validation").

## 2. Extended Commit Message

- Include only if changes have non-obvious implications, fix complex bugs, or introduce breaking changes.
- Separate from subject with one blank line.
- Use markdown bullets focusing on **why** the change was needed and **what impact** it has.
- Mention side effects, user impact, or important trade-offs.

## 3. User-facing Changes

If the change is something that a end-user (not internal admin!) would see, include a `User-facing:` git trailer with a sentence
or two explaining, to the user, what they would see differently because of this change.

## 4. General Guidelines

- Prioritize the purpose of changes over listing tools or properties used.
- Keep concise; avoid obvious or verbose details.
- Always generate a message based on the diff, even with limited context.

## 5. Scopes

Optional scopes (e.g., `feat(api):`):

- `match`: frontend or backend changes tied
- `site`: content, additional pages, etc for the static site content
- `internal-admin`: internal admin changes (including CMS)
```

With this setup, commits automatically get `User-facing:` trailers. You can then extract and summarize them:

```bash
# Extract only user-facing changes from the last sprint
git-history-extraction --since "last monday" --trailers "User-facing" | \
  gemini -i "Create a user-friendly changelog from these changes"
```

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

### Using the OpenAI Playground Script (Optional)

An optional playground script is included that demonstrates OpenAI integration:

```bash
# Generate summary with OpenAI
git-history-extraction --since "1 week ago" --format json | \
  uv run playground/summarize_commits.py

# Preview the prompt without calling OpenAI
git-history-extraction --since "1 week ago" --format json | \
  uv run playground/summarize_commits.py --dump-prompt
```

**Requirements:**
- `OPENAI_API_KEY` environment variable
- The script uses GPT-4o-mini by default

This is just an example—you can pipe to any AI tool you prefer. See [playground/README.md](playground/README.md) for more details.

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
- This tool extracts and formats data only—AI summarization requires external tools
- Git must be available in PATH

## Requirements

- Python >= 3.9
- git
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
