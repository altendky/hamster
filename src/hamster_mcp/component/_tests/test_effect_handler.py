"""Tests for the HamsterEffectHandler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceNotFound,
    ServiceValidationError,
)
import pytest

from hamster_mcp.component.http import HamsterEffectHandler


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
        user_id="test-user-123",
    )

    assert result.success is True
    assert result.data == {"state": "on"}
    assert result.error is None

    # Verify service was called with correct parameters including context
    mock_hass.services.async_call.assert_called_once()
    call_args = mock_hass.services.async_call.call_args
    assert call_args.args == ("light", "turn_on", {"brightness": 255})
    assert call_args.kwargs["target"] == {"entity_id": ["light.living_room"]}
    assert call_args.kwargs["blocking"] is True
    assert call_args.kwargs["return_response"] is True
    # Verify context has the user_id
    context = call_args.kwargs["context"]
    assert context.user_id == "test-user-123"


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
        user_id=None,
    )

    assert result.success is True
    assert result.data is None
    assert result.error is None

    # Verify context was created even with None user_id
    call_args = mock_hass.services.async_call.call_args
    context = call_args.kwargs["context"]
    assert context.user_id is None


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
        user_id=None,
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
        user_id=None,
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
        user_id=None,
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

    with patch("hamster_mcp.component.http._LOGGER") as mock_logger:
        result = await effect_handler.execute_service_call(
            domain="light",
            service="turn_on",
            target=None,
            data={},
            user_id=None,
        )

        # Verify exception was logged
        mock_logger.exception.assert_called_once()

    assert result.success is False
    assert result.data is None
    assert result.error is not None
    assert "Unexpected error" in result.error
    assert "ValueError" in result.error


# --- Supervisor call tests ---


class TestExecuteSupervisorCall:
    """Tests for execute_supervisor_call()."""

    @pytest.fixture
    def mock_admin_user(self) -> MagicMock:
        """Create a mock admin user."""
        user = MagicMock()
        user.id = "admin-user-123"
        user.is_admin = True
        return user

    @pytest.fixture
    def mock_non_admin_user(self) -> MagicMock:
        """Create a mock non-admin user."""
        user = MagicMock()
        user.id = "regular-user-456"
        user.is_admin = False
        return user

    @pytest.fixture
    def mock_hassio(self) -> MagicMock:
        """Create a mock hassio client."""
        hassio = MagicMock()
        hassio.send_command = AsyncMock()
        return hassio

    async def test_success_json_response(
        self,
        effect_handler: HamsterEffectHandler,
        mock_hass: MagicMock,
        mock_admin_user: MagicMock,
        mock_hassio: MagicMock,
    ) -> None:
        """Test successful supervisor call with JSON response."""
        mock_hass.auth = MagicMock()
        mock_hass.auth.async_get_user = AsyncMock(return_value=mock_admin_user)
        mock_hass.data = {"hassio": mock_hassio}
        mock_hassio.send_command.return_value = {
            "data": {"version": "2024.1", "hostname": "homeassistant"}
        }

        with patch.dict(
            "sys.modules",
            {
                "homeassistant.components.hassio": MagicMock(HassioAPIError=Exception),
                "homeassistant.components.hassio.const": MagicMock(
                    DATA_COMPONENT="hassio"
                ),
            },
        ):
            result = await effect_handler.execute_supervisor_call(
                method="GET",
                path="/core/info",
                params={},
                user_id="admin-user-123",
            )

        assert result.success is True
        assert result.data == {"version": "2024.1", "hostname": "homeassistant"}
        assert result.error is None

    async def test_success_text_response_logs(
        self,
        effect_handler: HamsterEffectHandler,
        mock_hass: MagicMock,
        mock_admin_user: MagicMock,
        mock_hassio: MagicMock,
    ) -> None:
        """Test successful supervisor call with text (logs) response."""
        mock_hass.auth = MagicMock()
        mock_hass.auth.async_get_user = AsyncMock(return_value=mock_admin_user)
        mock_hass.data = {"hassio": mock_hassio}
        mock_hassio.send_command.return_value = (
            "2024-01-01 INFO Starting...\n2024-01-01 INFO Ready"
        )

        with patch.dict(
            "sys.modules",
            {
                "homeassistant.components.hassio": MagicMock(HassioAPIError=Exception),
                "homeassistant.components.hassio.const": MagicMock(
                    DATA_COMPONENT="hassio"
                ),
            },
        ):
            result = await effect_handler.execute_supervisor_call(
                method="GET",
                path="/core/logs",
                params={},
                user_id="admin-user-123",
            )

        assert result.success is True
        assert result.data == {
            "logs": "2024-01-01 INFO Starting...\n2024-01-01 INFO Ready"
        }
        assert result.error is None

    async def test_no_user_id_returns_auth_error(
        self,
        effect_handler: HamsterEffectHandler,
        mock_hass: MagicMock,
    ) -> None:
        """Test that user_id=None returns auth required error."""
        result = await effect_handler.execute_supervisor_call(
            method="GET",
            path="/core/info",
            params={},
            user_id=None,
        )

        assert result.success is False
        assert "Authentication required" in result.error  # type: ignore[operator]

    async def test_non_admin_user_returns_admin_error(
        self,
        effect_handler: HamsterEffectHandler,
        mock_hass: MagicMock,
        mock_non_admin_user: MagicMock,
    ) -> None:
        """Test that non-admin user returns admin required error."""
        mock_hass.auth = MagicMock()
        mock_hass.auth.async_get_user = AsyncMock(return_value=mock_non_admin_user)

        result = await effect_handler.execute_supervisor_call(
            method="GET",
            path="/core/info",
            params={},
            user_id="regular-user-456",
        )

        assert result.success is False
        assert "admin" in result.error.lower()  # type: ignore[union-attr]

    async def test_user_not_found_returns_admin_error(
        self,
        effect_handler: HamsterEffectHandler,
        mock_hass: MagicMock,
    ) -> None:
        """Test that unknown user_id returns admin required error."""
        mock_hass.auth = MagicMock()
        mock_hass.auth.async_get_user = AsyncMock(return_value=None)

        result = await effect_handler.execute_supervisor_call(
            method="GET",
            path="/core/info",
            params={},
            user_id="unknown-user",
        )

        assert result.success is False
        assert "admin" in result.error.lower()  # type: ignore[union-attr]

    async def test_supervisor_not_available(
        self,
        effect_handler: HamsterEffectHandler,
        mock_hass: MagicMock,
        mock_admin_user: MagicMock,
    ) -> None:
        """Test that missing hassio returns not available error."""
        mock_hass.auth = MagicMock()
        mock_hass.auth.async_get_user = AsyncMock(return_value=mock_admin_user)
        mock_hass.data = {}  # No hassio

        with patch.dict(
            "sys.modules",
            {
                "homeassistant.components.hassio": MagicMock(HassioAPIError=Exception),
                "homeassistant.components.hassio.const": MagicMock(
                    DATA_COMPONENT="hassio"
                ),
            },
        ):
            result = await effect_handler.execute_supervisor_call(
                method="GET",
                path="/core/info",
                params={},
                user_id="admin-user-123",
            )

        assert result.success is False
        assert "not available" in result.error.lower()  # type: ignore[union-attr]

    async def test_hassio_api_error(
        self,
        effect_handler: HamsterEffectHandler,
        mock_hass: MagicMock,
        mock_admin_user: MagicMock,
        mock_hassio: MagicMock,
    ) -> None:
        """Test HassioAPIError is handled."""
        mock_hass.auth = MagicMock()
        mock_hass.auth.async_get_user = AsyncMock(return_value=mock_admin_user)
        mock_hass.data = {"hassio": mock_hassio}

        # Create the exception class for the mock
        class MockHassioAPIError(Exception):
            pass

        mock_hassio.send_command.side_effect = MockHassioAPIError(
            "API Error: 401 Unauthorized"
        )

        with patch.dict(
            "sys.modules",
            {
                "homeassistant.components.hassio": MagicMock(
                    HassioAPIError=MockHassioAPIError
                ),
                "homeassistant.components.hassio.const": MagicMock(
                    DATA_COMPONENT="hassio"
                ),
            },
        ):
            result = await effect_handler.execute_supervisor_call(
                method="GET",
                path="/core/info",
                params={},
                user_id="admin-user-123",
            )

        assert result.success is False
        assert "401" in result.error  # type: ignore[operator]

    async def test_generic_exception_logged(
        self,
        effect_handler: HamsterEffectHandler,
        mock_hass: MagicMock,
        mock_admin_user: MagicMock,
        mock_hassio: MagicMock,
    ) -> None:
        """Test generic exception is logged and returns error."""
        mock_hass.auth = MagicMock()
        mock_hass.auth.async_get_user = AsyncMock(return_value=mock_admin_user)
        mock_hass.data = {"hassio": mock_hassio}
        mock_hassio.send_command.side_effect = RuntimeError("Unexpected")

        # Create a proper exception class
        class MockHassioAPIError(Exception):
            pass

        with (
            patch.dict(
                "sys.modules",
                {
                    "homeassistant.components.hassio": MagicMock(
                        HassioAPIError=MockHassioAPIError
                    ),
                    "homeassistant.components.hassio.const": MagicMock(
                        DATA_COMPONENT="hassio"
                    ),
                },
            ),
            patch("hamster_mcp.component.http._LOGGER") as mock_logger,
        ):
            result = await effect_handler.execute_supervisor_call(
                method="GET",
                path="/core/info",
                params={},
                user_id="admin-user-123",
            )

            mock_logger.exception.assert_called_once()

        assert result.success is False
        assert "RuntimeError" in result.error  # type: ignore[operator]
        assert "Unexpected" in result.error  # type: ignore[operator]

    async def test_post_method_uses_payload(
        self,
        effect_handler: HamsterEffectHandler,
        mock_hass: MagicMock,
        mock_admin_user: MagicMock,
        mock_hassio: MagicMock,
    ) -> None:
        """Test POST method passes params as payload."""
        mock_hass.auth = MagicMock()
        mock_hass.auth.async_get_user = AsyncMock(return_value=mock_admin_user)
        mock_hass.data = {"hassio": mock_hassio}
        mock_hassio.send_command.return_value = {"data": {"success": True}}

        with patch.dict(
            "sys.modules",
            {
                "homeassistant.components.hassio": MagicMock(HassioAPIError=Exception),
                "homeassistant.components.hassio.const": MagicMock(
                    DATA_COMPONENT="hassio"
                ),
            },
        ):
            await effect_handler.execute_supervisor_call(
                method="POST",
                path="/some/endpoint",
                params={"key": "value"},
                user_id="admin-user-123",
            )

        mock_hassio.send_command.assert_called_once()
        call_kwargs = mock_hassio.send_command.call_args.kwargs
        assert call_kwargs["payload"] == {"key": "value"}
