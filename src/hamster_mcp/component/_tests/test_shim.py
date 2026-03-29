"""Import smoke tests for the HACS shim.

Verifies that the custom_components/hamster_mcp/ shim correctly re-exports
the hamster_mcp.component entry points.
"""

from __future__ import annotations


def test_init_exports_async_setup_entry() -> None:
    """Test that async_setup_entry is exported from custom_components.hamster_mcp."""
    from custom_components.hamster_mcp import async_setup_entry
    from hamster_mcp.component import async_setup_entry as original

    assert async_setup_entry is original


def test_init_exports_async_unload_entry() -> None:
    """Test that async_unload_entry is exported from custom_components.hamster_mcp."""
    from custom_components.hamster_mcp import async_unload_entry
    from hamster_mcp.component import async_unload_entry as original

    assert async_unload_entry is original


def test_config_flow_exports_config_flow() -> None:
    """Test ConfigFlow is exported from the config_flow shim."""
    from custom_components.hamster_mcp.config_flow import ConfigFlow
    from hamster_mcp.component.config_flow import HamsterConfigFlow

    assert ConfigFlow is HamsterConfigFlow


def test_all_exports_are_defined() -> None:
    """Test that __all__ is defined correctly in the shim modules."""
    import custom_components.hamster_mcp as shim_init
    import custom_components.hamster_mcp.config_flow as shim_config_flow

    assert hasattr(shim_init, "__all__")
    assert "async_setup_entry" in shim_init.__all__
    assert "async_unload_entry" in shim_init.__all__

    assert hasattr(shim_config_flow, "__all__")
    assert "ConfigFlow" in shim_config_flow.__all__
