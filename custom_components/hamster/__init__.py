"""Hamster MCP --- HACS deployment shim.

This file re-exports the HA integration entry points from the hamster
library package.  The actual implementation lives in
src/hamster/component/.  This shim exists because HA discovers custom
components by looking for custom_components/<domain>/__init__.py.
"""

# TODO: uncomment once hamster.component has real entry points
# from hamster.component import (
#     async_setup_entry,
#     async_unload_entry,
# )
