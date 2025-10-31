# Playground Scripts

## summarize_commits.py

This script uses OpenAI to summarize git commit messages extracted by `main.py`.

### Usage

Pipe JSON output from main.py:
```bash
uv run main.py --since "1 week ago" --format json | uv run playground/summarize_commits.py
```

Or use a file:
```bash
uv run main.py --since "1 week ago" --format json > commits.json
uv run playground/summarize_commits.py --input commits.json
```

Preview the prompt without calling OpenAI:
```bash
uv run main.py --since "1 week ago" --format json | uv run playground/summarize_commits.py --dump-prompt
```

### Requirements

- `OPENAI_API_KEY` environment variable must be set
- The script uses the `gpt-4o-mini` model by default
