"""Tests for the HamsterEffectHandler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceNotFound,
    ServiceValidationError,
)
import pytest

from hamster.component.http import HamsterEffectHandler


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations for testing."""


@pytest.fixture
def mock_hass() -> MagicMock:
    """Create a mock HomeAssistant instance."""
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


@pytest.fixture
def effect_handler(mock_hass: MagicMock) -> HamsterEffectHandler:
    """Create an effect handler with mock hass."""
    return HamsterEffectHandler(mock_hass)


async def test_successful_service_call(
    effect_handler: HamsterEffectHandler, mock_hass: MagicMock
) -> None:
    """Test successful service call returns success result."""
    mock_hass.services.async_call.return_value = {"state": "on"}

    result = await effect_handler.execute_service_call(
        domain="light",
        service="turn_on",
        target={"entity_id": ["light.living_room"]},
        data={"brightness": 255},
    )

    assert result.success is True
    assert result.data == {"state": "on"}
    assert result.error is None

    mock_hass.services.async_call.assert_called_once_with(
        "light",
        "turn_on",
        {"brightness": 255},
        target={"entity_id": ["light.living_room"]},
        blocking=True,
        return_response=True,
    )


async def test_successful_service_call_no_response(
    effect_handler: HamsterEffectHandler, mock_hass: MagicMock
) -> None:
    """Test successful service call with no response data."""
    mock_hass.services.async_call.return_value = None

    result = await effect_handler.execute_service_call(
        domain="light",
        service="turn_on",
        target=None,
        data={},
    )

    assert result.success is True
    assert result.data is None
    assert result.error is None


async def test_service_not_found(
    effect_handler: HamsterEffectHandler, mock_hass: MagicMock
) -> None:
    """Test ServiceNotFound exception is handled."""
    mock_hass.services.async_call.side_effect = ServiceNotFound(
        domain="fake", service="service"
    )

    result = await effect_handler.execute_service_call(
        domain="fake",
        service="service",
        target=None,
        data={},
    )

    assert result.success is False
    assert result.data is None
    assert result.error is not None
    assert "Service not found: fake.service" in result.error


async def test_service_validation_error(
    effect_handler: HamsterEffectHandler, mock_hass: MagicMock
) -> None:
    """Test ServiceValidationError exception is handled."""
    mock_hass.services.async_call.side_effect = ServiceValidationError(
        translation_domain="test",
        translation_key="test_key",
        translation_placeholders={},
    )

    result = await effect_handler.execute_service_call(
        domain="light",
        service="turn_on",
        target=None,
        data={"invalid": "param"},
    )

    assert result.success is False
    assert result.data is None
    assert result.error is not None
    assert "Validation error" in result.error


async def test_home_assistant_error(
    effect_handler: HamsterEffectHandler, mock_hass: MagicMock
) -> None:
    """Test HomeAssistantError exception is handled."""
    mock_hass.services.async_call.side_effect = HomeAssistantError(
        "Something went wrong"
    )

    result = await effect_handler.execute_service_call(
        domain="light",
        service="turn_on",
        target=None,
        data={},
    )

    assert result.success is False
    assert result.data is None
    assert result.error is not None
    assert "Home Assistant error" in result.error
    assert "Something went wrong" in result.error


async def test_generic_exception_logged_and_handled(
    effect_handler: HamsterEffectHandler, mock_hass: MagicMock
) -> None:
    """Test generic Exception is logged and handled."""
    mock_hass.services.async_call.side_effect = ValueError("Unexpected error")

    with patch("hamster.component.http._LOGGER") as mock_logger:
        result = await effect_handler.execute_service_call(
            domain="light",
            service="turn_on",
            target=None,
            data={},
        )

        # Verify exception was logged
        mock_logger.exception.assert_called_once()

    assert result.success is False
    assert result.data is None
    assert result.error is not None
    assert "Unexpected error" in result.error
    assert "ValueError" in result.error
