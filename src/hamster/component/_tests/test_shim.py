"""Import smoke tests for the HACS shim.

Verifies that the custom_components/hamster/ shim correctly re-exports
the hamster.component entry points.
"""

from __future__ import annotations


def test_init_exports_async_setup_entry() -> None:
    """Test that async_setup_entry is exported from custom_components.hamster."""
    from custom_components.hamster import async_setup_entry
    from hamster.component import async_setup_entry as original

    assert async_setup_entry is original


def test_init_exports_async_unload_entry() -> None:
    """Test that async_unload_entry is exported from custom_components.hamster."""
    from custom_components.hamster import async_unload_entry
    from hamster.component import async_unload_entry as original

    assert async_unload_entry is original


def test_config_flow_exports_config_flow() -> None:
    """Test that ConfigFlow is exported from custom_components.hamster.config_flow."""
    from custom_components.hamster.config_flow import ConfigFlow
    from hamster.component.config_flow import HamsterConfigFlow

    assert ConfigFlow is HamsterConfigFlow


def test_all_exports_are_defined() -> None:
    """Test that __all__ is defined correctly in the shim modules."""
    import custom_components.hamster as shim_init
    import custom_components.hamster.config_flow as shim_config_flow

    assert hasattr(shim_init, "__all__")
    assert "async_setup_entry" in shim_init.__all__
    assert "async_unload_entry" in shim_init.__all__

    assert hasattr(shim_config_flow, "__all__")
    assert "ConfigFlow" in shim_config_flow.__all__
