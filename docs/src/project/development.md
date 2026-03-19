# Development

Placeholder --- to be written during Phase 1 implementation.

## Prerequisites

- [mise](https://mise.jdx.dev/) for tool management
- Python 3.14 (installed via mise)
- pre-commit (installed via mise)

## Setup

```bash
mise install
uv sync --extra dev
pre-commit install
```

## Running Tests

```bash
pytest src/
```

## Pre-commit Hooks

```bash
pre-commit run --all-files
```

## Project Structure

See [Architecture](architecture.md) for the full package layout.
