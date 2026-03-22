"""Root pytest configuration.

This file conditionally loads test infrastructure based on test location.
"""

from __future__ import annotations

from pathlib import Path
import sys

# Add repo root to sys.path so Home Assistant can import custom_components.hamster
_REPO_ROOT = Path(__file__).parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Load the pytest-homeassistant-custom-component plugin for HA tests
pytest_plugins = ["pytest_homeassistant_custom_component"]
