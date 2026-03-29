"""Root pytest configuration.

Sets up sys.path for custom_components discovery and loads the HA test plugin.
See also: src/hamster_mcp/component/_tests/conftest.py (triggers module import).
"""

from __future__ import annotations

from pathlib import Path
import sys

# Add repo root to sys.path so HA's loader can find custom_components.hamster_mcp.
# pytest's pythonpath option is evaluated too late for HA's loader.
_REPO_ROOT = Path(__file__).parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

pytest_plugins = ["pytest_homeassistant_custom_component"]
