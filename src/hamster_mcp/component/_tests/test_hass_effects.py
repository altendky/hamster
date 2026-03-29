"""Tests for HassCommand effect handling.

Tests for InternalConnection and execute_hass_command() in the effect handler.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from hamster_mcp.component.http import HamsterEffectHandler, InternalConnection


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations for testing."""


# --- InternalConnection Tests ---


class TestInternalConnectionConstruction:
    """Tests for InternalConnection construction."""

    def test_construction_with_user(self) -> None:
        """InternalConnection can be constructed with a user."""
        hass = MagicMock()
        user = MagicMock()
        user.id = "user-123"

        conn = InternalConnection(hass, user)

        assert conn.hass is hass
        assert conn.user is user
        assert conn.subscriptions == {}
        assert conn.supported_features == {}
        assert conn.result is None
        assert conn.error is None

    def test_construction_without_user(self) -> None:
        """InternalConnection can be constructed without a user."""
        hass = MagicMock()

        conn = InternalConnection(hass, None)

        assert conn.hass is hass
        assert conn.user is None

    def test_context_with_user(self) -> None:
        """context() returns Context with user_id."""
        hass = MagicMock()
        user = MagicMock()
        user.id = "user-456"

        conn = InternalConnection(hass, user)
        ctx = conn.context({"id": 1, "type": "get_states"})

        assert ctx.user_id == "user-456"

    def test_context_without_user(self) -> None:
        """context() returns Context with None user_id when no user."""
        hass = MagicMock()

        conn = InternalConnection(hass, None)
        ctx = conn.context({"id": 1, "type": "get_states"})

        assert ctx.user_id is None


class TestInternalConnectionSendResult:
    """Tests for InternalConnection.send_result()."""

    def test_send_result_captures_result(self) -> None:
        """send_result captures the result."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)

        conn.send_result(1, {"states": []})

        assert conn.result == {"states": []}
        assert conn.error is None
        assert conn._result_event.is_set()

    def test_send_result_with_none(self) -> None:
        """send_result captures None result."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)

        conn.send_result(1, None)

        assert conn.result is None
        assert conn.error is None
        assert conn._result_event.is_set()

    def test_send_result_unwraps_orjson_fragment(self) -> None:
        """send_result unwraps orjson.Fragment objects in the result.

        Some HA WebSocket handlers return data containing orjson.Fragment
        objects for performance (pre-serialized JSON). The InternalConnection
        must unwrap these so the result contains only plain Python types.
        """
        import orjson

        hass = MagicMock()
        conn = InternalConnection(hass, None)

        # Simulate a result containing orjson.Fragment objects
        result_with_fragments = {
            "normal_key": "normal_value",
            "fragment_key": orjson.Fragment(b'{"nested": "data"}'),
            "list_with_fragment": [1, orjson.Fragment(b'"string_value"'), 3],
        }

        conn.send_result(1, result_with_fragments)

        # The result should be unwrapped to plain Python types
        assert conn.result == {
            "normal_key": "normal_value",
            "fragment_key": {"nested": "data"},
            "list_with_fragment": [1, "string_value", 3],
        }
        assert conn.error is None
        assert conn._result_event.is_set()

    def test_send_result_unwraps_deeply_nested_fragments(self) -> None:
        """send_result unwraps deeply nested orjson.Fragment objects."""
        import orjson

        hass = MagicMock()
        conn = InternalConnection(hass, None)

        # Simulate deeply nested fragments
        result_with_fragments = {
            "level1": {
                "level2": {
                    "fragment": orjson.Fragment(b'{"deep": "value"}'),
                }
            }
        }

        conn.send_result(1, result_with_fragments)

        assert conn.result == {
            "level1": {
                "level2": {
                    "fragment": {"deep": "value"},
                }
            }
        }


class TestInternalConnectionSendError:
    """Tests for InternalConnection.send_error()."""

    def test_send_error_captures_error(self) -> None:
        """send_error captures the error."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)

        conn.send_error(1, "invalid_param", "Missing required parameter")

        assert conn.error == ("invalid_param", "Missing required parameter")
        assert conn.result is None
        assert conn._result_event.is_set()

    def test_send_error_with_optional_params(self) -> None:
        """send_error works with optional translation params."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)

        conn.send_error(
            1,
            "auth_failed",
            "Authentication failed",
            translation_key="key",
            translation_domain="domain",
            translation_placeholders={"foo": "bar"},
        )

        assert conn.error == ("auth_failed", "Authentication failed")
        assert conn._result_event.is_set()


class TestInternalConnectionSendMessage:
    """Tests for InternalConnection.send_message()."""

    # --- Success cases with bytes ---

    def test_send_message_bytes_success(self) -> None:
        """send_message with bytes success result."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)
        msg = b'{"id": 1, "type": "result", "success": true, "result": {"devices": []}}'

        conn.send_message(msg)

        assert conn.result == {"devices": []}
        assert conn.error is None
        assert conn._result_event.is_set()

    def test_send_message_bytes_success_null_result(self) -> None:
        """send_message with bytes success and null result."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)
        msg = b'{"id": 1, "type": "result", "success": true, "result": null}'

        conn.send_message(msg)

        assert conn.result is None
        assert conn.error is None
        assert conn._result_event.is_set()

    def test_send_message_bytes_success_no_result_key(self) -> None:
        """send_message with bytes success but no result key."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)
        msg = b'{"id": 1, "type": "result", "success": true}'

        conn.send_message(msg)

        assert conn.result is None
        assert conn.error is None
        assert conn._result_event.is_set()

    # --- Error cases with bytes ---

    def test_send_message_bytes_error(self) -> None:
        """send_message with bytes error result."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)
        msg = (
            b'{"id": 1, "type": "result", "success": false, '
            b'"error": {"code": "not_found", "message": "Entity not found"}}'
        )

        conn.send_message(msg)

        assert conn.result is None
        assert conn.error == ("not_found", "Entity not found")
        assert conn._result_event.is_set()

    def test_send_message_bytes_error_missing_fields(self) -> None:
        """send_message with bytes error missing code/message."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)
        msg = b'{"id": 1, "type": "result", "success": false, "error": {}}'

        conn.send_message(msg)

        assert conn.error == ("unknown", "Unknown error")
        assert conn._result_event.is_set()

    # --- Success cases with str ---

    def test_send_message_str_success(self) -> None:
        """send_message with str success result."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)
        msg = (
            '{"id": 1, "type": "result", "success": true, "result": ["item1", "item2"]}'
        )

        conn.send_message(msg)

        assert conn.result == ["item1", "item2"]
        assert conn.error is None
        assert conn._result_event.is_set()

    # --- Success cases with dict ---

    def test_send_message_dict_success(self) -> None:
        """send_message with dict success result."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)
        msg: dict[str, object] = {
            "id": 1,
            "type": "result",
            "success": True,
            "result": {"key": "value"},
        }

        conn.send_message(msg)

        assert conn.result == {"key": "value"}
        assert conn.error is None
        assert conn._result_event.is_set()

    def test_send_message_dict_error(self) -> None:
        """send_message with dict error result."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)
        msg: dict[str, object] = {
            "id": 1,
            "type": "result",
            "success": False,
            "error": {"code": "invalid", "message": "Bad input"},
        }

        conn.send_message(msg)

        assert conn.error == ("invalid", "Bad input")
        assert conn._result_event.is_set()

    # --- Pong message ---

    def test_send_message_pong(self) -> None:
        """send_message with pong message."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)
        msg: dict[str, object] = {"id": 1, "type": "pong"}

        conn.send_message(msg)

        assert conn.result is None
        assert conn.error is None
        assert conn._result_event.is_set()

    # --- Error handling ---

    def test_send_message_event_raises(self) -> None:
        """send_message with event type raises NotImplementedError."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)
        msg: dict[str, object] = {"id": 1, "type": "event", "event": {"data": "value"}}

        with pytest.raises(NotImplementedError) as exc_info:
            conn.send_message(msg)

        assert "event" in str(exc_info.value)

    def test_send_message_unknown_type_raises(self) -> None:
        """send_message with unknown type raises NotImplementedError."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)
        msg: dict[str, object] = {"id": 1, "type": "custom_type"}

        with pytest.raises(NotImplementedError) as exc_info:
            conn.send_message(msg)

        assert "custom_type" in str(exc_info.value)

    def test_send_message_invalid_json_bytes(self) -> None:
        """send_message with invalid JSON bytes captures error."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)
        msg = b"not valid json"

        conn.send_message(msg)

        assert conn.error is not None
        assert conn.error[0] == "json_error"
        assert "parse" in conn.error[1].lower() or "Failed" in conn.error[1]
        assert conn._result_event.is_set()

    def test_send_message_invalid_json_str(self) -> None:
        """send_message with invalid JSON str captures error."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)
        msg = "not valid json"

        conn.send_message(msg)

        assert conn.error is not None
        assert conn.error[0] == "json_error"
        assert conn._result_event.is_set()


class TestInternalConnectionUnsupportedMethods:
    """Tests for unsupported InternalConnection methods."""

    def test_send_event_raises(self) -> None:
        """send_event raises NotImplementedError."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)

        with pytest.raises(NotImplementedError) as exc_info:
            conn.send_event(1, {"event": "data"})

        assert "send_event" in str(exc_info.value)


class TestInternalConnectionExceptionHandling:
    """Tests for InternalConnection.async_handle_exception()."""

    def test_async_handle_exception_captures_error(self) -> None:
        """async_handle_exception captures exception as error."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)

        conn.async_handle_exception({"id": 1, "type": "test"}, ValueError("Test error"))

        assert conn.error == ("exception", "Test error")
        assert conn._result_event.is_set()


class TestInternalConnectionWaitForResult:
    """Tests for InternalConnection.wait_for_result()."""

    async def test_wait_returns_after_send_result(self) -> None:
        """wait_for_result returns after send_result is called."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)

        conn.send_result(1, {"data": "value"})
        await conn.wait_for_result(timeout=1.0)

        assert conn.result == {"data": "value"}

    async def test_wait_returns_after_send_error(self) -> None:
        """wait_for_result returns after send_error is called."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)

        conn.send_error(1, "code", "message")
        await conn.wait_for_result(timeout=1.0)

        assert conn.error == ("code", "message")

    async def test_wait_times_out(self) -> None:
        """wait_for_result raises TimeoutError on timeout."""
        hass = MagicMock()
        conn = InternalConnection(hass, None)

        with pytest.raises(TimeoutError):
            await conn.wait_for_result(timeout=0.01)


# --- execute_hass_command Tests ---


@pytest.fixture
def mock_hass() -> MagicMock:
    """Create a mock HomeAssistant instance."""
    hass = MagicMock()
    hass.data = {}
    hass.auth = MagicMock()
    hass.auth.async_get_user = AsyncMock()
    return hass


@pytest.fixture
def effect_handler(mock_hass: MagicMock) -> HamsterEffectHandler:
    """Create an effect handler with mock hass."""
    return HamsterEffectHandler(mock_hass)


class TestExecuteHassCommandBasics:
    """Basic tests for execute_hass_command."""

    async def test_unknown_command_returns_error(
        self, effect_handler: HamsterEffectHandler, mock_hass: MagicMock
    ) -> None:
        """Unknown command returns error result."""
        mock_hass.data = {"websocket_api": {}}

        result = await effect_handler.execute_hass_command(
            command_type="unknown_command",
            params={},
            user_id=None,
        )

        assert result.success is False
        assert "Unknown command" in (result.error or "")

    async def test_missing_websocket_api_returns_error(
        self, effect_handler: HamsterEffectHandler, mock_hass: MagicMock
    ) -> None:
        """Missing websocket_api data returns error result."""
        mock_hass.data = {}

        result = await effect_handler.execute_hass_command(
            command_type="get_states",
            params={},
            user_id=None,
        )

        assert result.success is False
        assert "Unknown command" in (result.error or "")


class TestExecuteHassCommandSchemaValidation:
    """Tests for schema validation in execute_hass_command."""

    async def test_schema_validation_failure_returns_error(
        self, effect_handler: HamsterEffectHandler, mock_hass: MagicMock
    ) -> None:
        """Schema validation failure returns error result."""
        schema = vol.Schema(
            {
                vol.Required("id"): int,
                vol.Required("type"): str,
                vol.Required("entity_id"): str,
            }
        )
        handler = MagicMock()
        mock_hass.data = {"websocket_api": {"get_entity": (handler, schema)}}

        result = await effect_handler.execute_hass_command(
            command_type="get_entity",
            params={},  # Missing required entity_id
            user_id=None,
        )

        assert result.success is False
        assert "Validation error" in (result.error or "")

    async def test_schema_false_no_validation(
        self, effect_handler: HamsterEffectHandler, mock_hass: MagicMock
    ) -> None:
        """schema=False means no validation required."""

        def sync_handler(
            hass: MagicMock, conn: InternalConnection, msg: dict[str, object]
        ) -> None:
            conn.send_result(msg["id"], {"states": []})  # type: ignore[arg-type]

        mock_hass.data = {"websocket_api": {"get_states": (sync_handler, False)}}

        result = await effect_handler.execute_hass_command(
            command_type="get_states",
            params={},
            user_id=None,
        )

        assert result.success is True
        assert result.data == {"states": []}


class TestExecuteHassCommandHandlerExecution:
    """Tests for handler execution in execute_hass_command."""

    async def test_successful_sync_handler(
        self, effect_handler: HamsterEffectHandler, mock_hass: MagicMock
    ) -> None:
        """Successful sync handler returns success result."""

        def sync_handler(
            hass: MagicMock, conn: InternalConnection, msg: dict[str, object]
        ) -> None:
            conn.send_result(msg["id"], {"result": "value"})  # type: ignore[arg-type]

        mock_hass.data = {"websocket_api": {"test_command": (sync_handler, False)}}

        result = await effect_handler.execute_hass_command(
            command_type="test_command",
            params={},
            user_id=None,
        )

        assert result.success is True
        assert result.data == {"result": "value"}

    async def test_handler_send_error(
        self, effect_handler: HamsterEffectHandler, mock_hass: MagicMock
    ) -> None:
        """Handler calling send_error returns error result."""

        def error_handler(
            hass: MagicMock, conn: InternalConnection, msg: dict[str, object]
        ) -> None:
            conn.send_error(msg["id"], "error_code", "Error message")  # type: ignore[arg-type]

        mock_hass.data = {"websocket_api": {"error_command": (error_handler, False)}}

        result = await effect_handler.execute_hass_command(
            command_type="error_command",
            params={},
            user_id=None,
        )

        assert result.success is False
        assert result.error == "Error message"

    async def test_handler_exception_returns_error(
        self, effect_handler: HamsterEffectHandler, mock_hass: MagicMock
    ) -> None:
        """Handler raising exception returns error result."""

        def error_handler(
            hass: MagicMock, conn: InternalConnection, msg: dict[str, object]
        ) -> None:
            raise RuntimeError("Handler crashed")

        mock_hass.data = {"websocket_api": {"crash_command": (error_handler, False)}}

        with patch("hamster_mcp.component.http._LOGGER") as mock_logger:
            result = await effect_handler.execute_hass_command(
                command_type="crash_command",
                params={},
                user_id=None,
            )

            # Verify exception was logged
            mock_logger.exception.assert_called_once()

        assert result.success is False
        assert "RuntimeError" in (result.error or "")


class TestExecuteHassCommandUserResolution:
    """Tests for user resolution in execute_hass_command."""

    async def test_user_id_resolved(
        self, effect_handler: HamsterEffectHandler, mock_hass: MagicMock
    ) -> None:
        """user_id is resolved to User object."""
        user = MagicMock()
        user.id = "user-123"
        mock_hass.auth.async_get_user.return_value = user

        captured_conn = None

        def capture_handler(
            hass: MagicMock, conn: InternalConnection, msg: dict[str, object]
        ) -> None:
            nonlocal captured_conn
            captured_conn = conn
            conn.send_result(msg["id"], None)  # type: ignore[arg-type]

        mock_hass.data = {"websocket_api": {"test_command": (capture_handler, False)}}

        await effect_handler.execute_hass_command(
            command_type="test_command",
            params={},
            user_id="user-123",
        )

        mock_hass.auth.async_get_user.assert_called_once_with("user-123")
        assert captured_conn is not None
        assert captured_conn.user is user

    async def test_no_user_id_no_resolution(
        self, effect_handler: HamsterEffectHandler, mock_hass: MagicMock
    ) -> None:
        """No user_id means no user resolution."""
        captured_conn = None

        def capture_handler(
            hass: MagicMock, conn: InternalConnection, msg: dict[str, object]
        ) -> None:
            nonlocal captured_conn
            captured_conn = conn
            conn.send_result(msg["id"], None)  # type: ignore[arg-type]

        mock_hass.data = {"websocket_api": {"test_command": (capture_handler, False)}}

        await effect_handler.execute_hass_command(
            command_type="test_command",
            params={},
            user_id=None,
        )

        mock_hass.auth.async_get_user.assert_not_called()
        assert captured_conn is not None
        assert captured_conn.user is None


class TestExecuteHassCommandTimeout:
    """Tests for timeout handling in execute_hass_command."""

    async def test_handler_timeout_returns_error(
        self, effect_handler: HamsterEffectHandler, mock_hass: MagicMock
    ) -> None:
        """Handler that never responds times out."""

        def slow_handler(
            hass: MagicMock, conn: InternalConnection, msg: dict[str, object]
        ) -> None:
            # Never calls send_result or send_error
            pass

        mock_hass.data = {"websocket_api": {"slow_command": (slow_handler, False)}}

        # Patch the wait_for_result to simulate timeout
        with patch.object(
            InternalConnection, "wait_for_result", side_effect=TimeoutError
        ):
            result = await effect_handler.execute_hass_command(
                command_type="slow_command",
                params={},
                user_id=None,
            )

        assert result.success is False
        assert "timed out" in (result.error or "").lower()


class TestExecuteHassCommandParams:
    """Tests for parameter handling in execute_hass_command."""

    async def test_params_passed_to_handler(
        self, effect_handler: HamsterEffectHandler, mock_hass: MagicMock
    ) -> None:
        """Parameters are passed to the handler in the message."""
        captured_msg = None

        def capture_handler(
            hass: MagicMock, conn: InternalConnection, msg: dict[str, object]
        ) -> None:
            nonlocal captured_msg
            captured_msg = msg
            conn.send_result(msg["id"], None)  # type: ignore[arg-type]

        mock_hass.data = {"websocket_api": {"test_command": (capture_handler, False)}}

        await effect_handler.execute_hass_command(
            command_type="test_command",
            params={"entity_id": "light.living_room", "extra": 123},
            user_id=None,
        )

        assert captured_msg is not None
        assert captured_msg["type"] == "test_command"
        assert captured_msg["entity_id"] == "light.living_room"
        assert captured_msg["extra"] == 123
        assert "id" in captured_msg  # Message ID is added
