---
name: copier-template-sync
description: >-
  Use this skill whenever updating or syncing a repository with its upstream Copier template, pulling updates from an upstream template (e.g. python-package-template), or resolving conflicts and missed tasks from a copier update.
---

# Copier Template Sync & Reconcile

This skill guides updating a project generated from an upstream Copier template (such as `python-package-template`), resolving merge conflicts, and catching changes missed due to `--skip-tasks`, template exclusions, or file renames.

## Workflow Overview

1. **Pre-flight Checks & Dirty Working Tree Handling**
2. **Execute Copier Update**
3. **Resolve Merge Conflicts**
4. **Inspect Upstream Git History for Missed & Excluded Changes**
5. **Apply Missed Upstream Improvements**
6. **Linting & Test Verification**

## Step 1: Pre-flight Checks & Dirty Working Tree Handling

Copier will abort if the working directory has untracked or modified files (`Destination repository is dirty; cannot continue`).

1. Check git status:
   ```bash
   git status --porcelain
   ```
2. If untracked files are present (such as `.ipython_history` or local development scratch files) and should not be committed:
   - Add them to `.git/info/exclude` (so working tree is clean without modifying `.gitignore`).
3. Note the previous template commit in `.copier-answers.yml`:
   ```bash
   git log -p -n 1 .copier-answers.yml
   ```
   Save the old commit SHA (e.g. `16f1909` from `v1.0.0-57-g16f1909`).

## Step 2: Execute Copier Update

1. Check if the project has a `Justfile` recipe for template updates:
   ```bash
   just --list | grep update
   ```
2. Run the recipe (or equivalent copier update command):
   ```bash
   just update_from_upstream_template
   ```
   Or manually:
   ```bash
   uv tool run --with jinja2_shell_extension copier@latest update --vcs-ref=HEAD --trust --skip-tasks --skip-answered
   ```
3. **Interactive Prompts**: If prompted for template options (e.g. `is_cli_tool`):
   - Check `pyproject.toml` for `[project.scripts]`. If absent or project is a plugin/library without a CLI executable, answer `No`.
4. Note the newly applied template commit in `.copier-answers.yml` (e.g. `e2bd664`).

## Step 3: Resolve Merge Conflicts

Copier often produces merge conflicts in files where both the template and the project have evolved.

1. List unmerged files:
   ```bash
   git status
   ```
2. Common conflict areas and resolution patterns:
   - **`pyproject.toml`**:
     * Upstream changes: new `classifiers`, updated `build-system.requires` (e.g. `uv_build>=0.11.0,<0.14`), updated `dev` dependencies (`beautiful-traceback`).
     * Project-specific lines to preserve: project name, version, dependencies, custom tool configs (`[tool.pytest.ini_options]`, `[tool.uv]`, `[project.entry-points]`).
   - **Package `__init__.py`**:
     * Upstream changes: dynamic version imports (`from .version import __version__`).
     * Resolution: Export `__all__ = ["__version__"]` if re-exporting to satisfy linters; remove obsolete boilerplate like `def main()` if not a CLI tool.
   - **`tests/test_import.py`**:
     * Upstream changes: added `test_version()` to verify dynamic package version resolution.
     * Resolution: keep `test_version()` alongside existing import tests.

## Step 4: Inspect Upstream Git History for Missed & Excluded Changes

Because template updates typically run with `--skip-tasks`, and because Copier's three-way merge cannot track files that were renamed, conditionally generated, excluded, or relocated during initial generation, upstream enhancements can be silently missed.

### Common Classes of Missed or Excluded Files

1. **GitHub Actions Workflows (`.github/workflows/`)**:
   - **Conditional File Renames**: Workflows often exist upstream under conditional template names (e.g. `build_and_publish_release_please_test_matrix.yml.jinja`, `ci_matrix.yml.jinja`) that a post-copy task moves to a canonical destination (e.g. `build_and_publish.yml` or `ci.yml`). Copier update does not know about destination renames, so upstream changes to the `.jinja` source file are never automatically merged.
   - **Jinja Syntax Merge Failures**: Heavy Jinja templating tags (`{% if ... %}`, `${{ '{{' }} ... {{ '}}' }}`) frequently fail to merge cleanly into rendered YAML in destination workflows, causing partial merges or dropped blocks.
   - **Workflow Enhancements**: Always manually review upstream workflow diffs for updated action versions, checkout depth (`fetch-depth: 0` for tools like Gitleaks), environment variables (`MISE_ENV: ci`), interpreter and matrix scoping (`mise use --path mise.toml`, `uv venv --clear`), permissions (`contents: write`), and post-publish hooks (e.g. `uv.lock` sync).

2. **Template-Excluded Files (`_exclude` in `copier.yml`)**:
   - Files explicitly listed in `_exclude` (e.g. `mise.lock`, `uv.lock`, `metadata.json`, `copier.yml`, `LICENSE`, `CHANGELOG.md`, `TODO`) are completely ignored by Copier during updates.
   - Upstream updates to how these files are configured, pinned, or managed require manual reconciliation (e.g. running `mise install && mise lock`, `uv lock`, or updating project metadata).

3. **Skipped Post-Copy Tasks (`_tasks` in `copier.yml`)**:
   - Running with `--skip-tasks` bypasses all lifecycle hooks defined under `_tasks`.
   - Inspect `copier.yml` diffs for skipped commands such as tool installations (`mise install`), rule explosions (`llm-ide-rules explode`), baseline generations (`just gitleaks_baseline`), or dependency upgrades (`just upgrade`).

4. **Templated & Dynamic Directory Paths (`{{...}}`)**:
   - Files living under templated directory paths (e.g. `{{project_name_snake_case}}/`, `src/{{project_name}}/`) can fail to update if the project structure was flattened or renamed.

5. **New Dotfiles, Tool Configurations, & Templates**:
   - Check if new configuration files were introduced upstream (e.g. `.cursor/environment.json`, `.github/PULL_REQUEST_TEMPLATE.md`, `ruff.toml`, `.vscode/settings.json`) that need to be committed or adapted.

### Inspect Upstream Changes

1. Locate or clone the upstream template repository (e.g. `/Users/mike/Projects/python/python-package-template` or via `git clone --bare`):
2. Inspect the commit summary:
   ```bash
   git log --oneline <old-sha>..<new-sha>
   ```
3. List all changed files across the commit range:
   ```bash
   git diff --name-status <old-sha>..<new-sha>
   ```
4. Inspect diffs for files that map to different destination paths or were excluded:
   ```bash
   git diff <old-sha>..<new-sha> -- .github/workflows/ copier.yml
   ```

## Step 5: Apply Missed Upstream Improvements

Compare upstream template changes against project files and reconcile differences across all affected areas:

1. **GitHub Actions Workflows (`.github/workflows/`)**:
   - **Checkout Depth**: Check if `actions/checkout` requires `fetch-depth: 0` for secret scanning tools like Gitleaks.
   - **Mise Bootstrap**: Ensure `jdx/mise-action` includes `bootstrap: true` and `bootstrap_args: --update --yes` if `mise.toml` includes bootstrap packages (`apt:zsh`).
   - **Matrix Scoping**: Verify `mise use --path mise.toml python@...` and `uv venv --clear` are used in matrix jobs to prevent global configuration contamination and ensure clean interpreter isolation.
   - **Publish Permissions & Branch Checkout**: Check if `build-and-publish` requires `contents: write` and `ref: ${{ github.ref_name }}` to commit updated lockfiles back to the repository.
   - **Lockfile Sync**: Check for post-release steps (e.g. running `uv lock` and committing with `[skip ci]`).
   - *Always preserve repository-specific CI steps* (e.g., Playwright dependencies, browser installations, or CLI help checks).
2. **Tool Configurations, Lockfiles & Exclusions**:
   - Reconcile files in `_exclude`: run `mise install` / `mise lock` if tool pins changed, run `uv lock` if python build/lock requirements changed.
   - Check if new configuration files were introduced (e.g. `ruff.toml`, `.cursor/environment.json`, `.github/PULL_REQUEST_TEMPLATE.md`).
   - Check if `Justfile` recipes received updates (e.g. strict zsh shell, `upgrade`, `gitleaks_baseline`, `github_enforce_squash_merge`).

## Step 6: Linting & Test Verification

1. Sync local dependencies:
   ```bash
   uv sync
   ```
2. Run automated fixes and formatters:
   ```bash
   just lint-fix
   ```
3. Run linting checks (Ruff, Pyright, Gitleaks):
   ```bash
   just lint
   ```
4. Run the full test suite:
   ```bash
   just test
   ```
5. Review final git status:
   ```bash
   git status
   ```
   *(Note: Adhere to any read-only git constraints before staging or committing changes).*
