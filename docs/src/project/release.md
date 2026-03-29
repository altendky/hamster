# Release

Placeholder --- to be written when release infrastructure is built.

## Distribution Channels

| Channel | Artifact | Mechanism |
| --- | --- | --- |
| PyPI | `hamster-mcp` package | GitHub release → publish workflow |
| HACS (custom) | `custom_components/hamster_mcp/` | Users add repo URL manually |
| HACS (default) | `custom_components/hamster_mcp/` | Submit to HACS default repository list |

## Versioning

Semantic versioning (SemVer).
The version in `pyproject.toml`, `manifest.json`, and `__init__.py` must stay
in sync.

## Release Process

1. Update version in `pyproject.toml` and `manifest.json`
2. Update changelog
3. Create a GitHub release with a semver tag (e.g., `v0.1.0`)
4. CI publishes to PyPI
5. HACS picks up the new release automatically
