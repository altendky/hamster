# CI

Placeholder --- to be written during Phase 1 implementation.

## Overview

GitHub Actions with reusable workflow files (`reflow-*.yml` pattern from
onshape-mcp).

## Pipeline

| Job | Workflow | What |
| --- | --- | --- |
| Pre-commit | `reflow-pre-commit.yml` | All hooks |
| Python | `reflow-python.yml` | ruff + mypy + pytest (3.13, 3.14 matrix) |
| Coverage | `reflow-coverage.yml` | pytest-cov → Codecov |
| HACS | `validate.yml` | hacs/action + hassfest |
| Checks | inline | alls-green gate |

## Coverage Policy

Codecov ratchet configuration:

- **Project threshold**: fail if coverage drops more than 2% from main
- **Patch target**: 100% for new code

## Tools

| Tool | Role |
| --- | --- |
| ruff format | Formatting |
| ruff check | Linting |
| mypy --strict | Type checking |
| pytest + pytest-asyncio | Test runner |
| pytest-cov + Codecov | Coverage |
| pip-audit | Dependency vulnerability audit |
| pip-licenses | Dependency license checking |
| typos | Spell checking |
| markdownlint-cli2 | Markdown linting |
| lychee | Link checking |
| actionlint | GitHub Actions linting |
| shellcheck | Shell script linting |
