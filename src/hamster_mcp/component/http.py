"""HTTP view and effect handler for Hamster MCP.

Provides the Home Assistant HTTP view that handles MCP requests and
the effect handler that executes service calls and WebSocket commands.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

from aiohttp import web  # noqa: TC002 - used in method signature annotations
from homeassistant.components.http.view import (  # type: ignore[attr-defined]
    HomeAssistantView,
)
from homeassistant.core import Context, callback
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceNotFound,
    ServiceValidationError,
)
import voluptuous as vol

from hamster_mcp.mcp._core.types import (
    HassCommandResult,
    ServiceCallResult,
    SupervisorCallResult,
)
from hamster_mcp.mcp._io.aiohttp import AiohttpMCPTransport  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable

    from homeassistant.auth.models import User
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class InternalConnection:
    """Internal adapter for invoking WS handlers without a real WebSocket.

    Supports request/response commands only. Subscription commands are
    filtered out by HassGroup and not supported here.
    """

    def __init__(self, hass: HomeAssistant, user: User | None) -> None:
        """Initialize the internal connection.

        Args:
            hass: Home Assistant instance
            user: Authenticated user, or None for unauthenticated
        """
        self.hass = hass
        self.user = user
        # Required by ActiveConnection interface
        self.subscriptions: dict[Hashable, Callable[[], Any]] = {}
        self.supported_features: dict[str, float] = {}
        self.logger = logging.getLogger(__name__)
        # Result capture
        self._result_event = asyncio.Event()
        self.result: object = None
        self.error: tuple[str, str] | None = None  # (code, message)

    def context(self, msg: dict[str, object]) -> Context:
        """Create a context for command execution.

        Args:
            msg: The command message (unused but part of interface)

        Returns:
            Context with user_id set
        """
        return Context(user_id=self.user.id if self.user else None)

    @callback
    def send_result(self, msg_id: int, result: object = None) -> None:
        """Receive result from command handler.

        Args:
            msg_id: Message ID (unused for internal invocation)
            result: Command result (may contain orjson.Fragment objects)

        Note:
            Some HA handlers return data containing orjson.Fragment objects
            for performance (pre-serialized JSON). We unwrap these by doing
            a round-trip through orjson serialization.
        """
        import orjson

        # Unwrap any orjson.Fragment objects by serializing and deserializing.
        # This ensures the result contains only plain Python types that can be
        # serialized by any JSON library (e.g., the stdlib json module).
        if result is not None:
            result = orjson.loads(orjson.dumps(result))
        self.result = result
        self._result_event.set()

    @callback
    def send_error(
        self,
        msg_id: int,
        code: str,
        message: str,
        translation_key: str | None = None,
        translation_domain: str | None = None,
        translation_placeholders: dict[str, object] | None = None,
    ) -> None:
        """Receive error from command handler.

        Args:
            msg_id: Message ID (unused for internal invocation)
            code: Error code
            message: Error message
            translation_key: Optional translation key (unused)
            translation_domain: Optional translation domain (unused)
            translation_placeholders: Optional translation placeholders (unused)
        """
        self.error = (code, message)
        self._result_event.set()

    def send_message(self, message: bytes | str | dict[str, object]) -> None:
        """Parse and handle pre-serialized WebSocket response messages.

        Many HA handlers call this method with pre-serialized bytes for
        performance (e.g., device_registry/list, entity_registry/list).
        This implementation parses those messages to extract result/error data.

        Args:
            message: Response message as bytes, str, or dict

        Supported message types:
            - {"type": "result", "success": true, "result": ...} -> captures result
            - {"type": "result", "success": false, "error": {...}} -> captures error
            - {"type": "pong"} -> captures None result
            - {"type": "event", ...} -> raises NotImplementedError
        """
        import orjson

        # Parse to dict
        msg_dict: dict[str, object]
        try:
            if isinstance(message, (bytes, str)):
                msg_dict = orjson.loads(message)
            else:
                msg_dict = message
        except orjson.JSONDecodeError as err:
            self.error = ("json_error", f"Failed to parse message: {err}")
            self._result_event.set()
            return

        msg_type = msg_dict.get("type")

        if msg_type == "result":
            if msg_dict.get("success", False):
                self.result = msg_dict.get("result")
            else:
                error = msg_dict.get("error", {})
                if isinstance(error, dict):
                    code = str(error.get("code", "unknown"))
                    error_msg = str(error.get("message", "Unknown error"))
                else:
                    code = "unknown"
                    error_msg = str(error) if error else "Unknown error"
                self.error = (code, error_msg)
            self._result_event.set()
        elif msg_type == "pong":
            # Pong response - treat as success with no data
            self.result = None
            self._result_event.set()
        elif msg_type == "event":
            raise NotImplementedError(
                "send_message with type 'event' not supported - "
                "subscriptions are filtered"
            )
        else:
            raise NotImplementedError(
                f"send_message with type '{msg_type}' not supported "
                "for internal command invocation"
            )

    def send_event(self, msg_id: int, event: object = None) -> None:
        """Not supported --- subscription commands are filtered.

        Args:
            msg_id: Message ID (unused)
            event: Event data (unused)

        Raises:
            NotImplementedError: Always
        """
        raise NotImplementedError(
            "send_event not supported --- subscriptions are filtered"
        )

    def async_handle_exception(self, msg: dict[str, object], err: Exception) -> None:
        """Handle exception from command handler.

        Args:
            msg: The command message
            err: The exception that occurred
        """
        self.logger.exception("Error in websocket command handler")
        self.error = ("exception", str(err))
        self._result_event.set()

    async def wait_for_result(
        self,
        timeout: float = 30.0,  # noqa: ASYNC109 - spec uses parameter
    ) -> None:
        """Wait for handler to call send_result or send_error.

        Args:
            timeout: Maximum time to wait in seconds

        Raises:
            TimeoutError: If timeout is exceeded
        """
        await asyncio.wait_for(self._result_event.wait(), timeout)


class HamsterEffectHandler:
    """Effect handler that executes Home Assistant service calls and commands."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the effect handler.

        Args:
            hass: Home Assistant instance
        """
        self._hass = hass

    async def execute_service_call(
        self,
        domain: str,
        service: str,
        target: dict[str, object] | None,
        data: dict[str, object],
        user_id: str | None,
    ) -> ServiceCallResult:
        """Execute a Home Assistant service call.

        Args:
            domain: Service domain (e.g. 'light')
            service: Service name (e.g. 'turn_on')
            target: Target entities/devices/areas, or None
            data: Service data parameters
            user_id: Authenticated user ID for authorization

        Returns:
            ServiceCallResult indicating success or failure
        """
        context = Context(user_id=user_id)
        try:
            result = await self._hass.services.async_call(
                domain,
                service,
                data,
                target=target,
                context=context,
                blocking=True,
                return_response=True,
            )
            # Cast result to dict[str, object] - HA returns JsonValueType but
            # our interface uses object for flexibility
            data_result = cast("dict[str, object] | None", result)
            return ServiceCallResult(success=True, data=data_result)
        except ServiceNotFound:
            return ServiceCallResult(
                success=False, error=f"Service not found: {domain}.{service}"
            )
        except ServiceValidationError as err:
            return ServiceCallResult(success=False, error=f"Validation error: {err}")
        except HomeAssistantError as err:
            return ServiceCallResult(
                success=False, error=f"Home Assistant error: {err}"
            )
        except Exception as err:
            _LOGGER.exception("Unexpected error executing %s.%s", domain, service)
            return ServiceCallResult(
                success=False, error=f"Unexpected error: {type(err).__name__}: {err}"
            )

    async def execute_hass_command(
        self,
        command_type: str,
        params: dict[str, object],
        user_id: str | None,
    ) -> HassCommandResult:
        """Execute a WebSocket command.

        Args:
            command_type: Command type (e.g. 'get_states')
            params: Command parameters
            user_id: Authenticated user ID for authorization

        Returns:
            HassCommandResult indicating success or failure
        """
        handlers = self._hass.data.get("websocket_api", {})
        handler_info = handlers.get(command_type)
        if handler_info is None:
            return HassCommandResult(
                success=False, error=f"Unknown command: {command_type}"
            )

        handler, schema = handler_info

        # Build message with required fields
        msg: dict[str, object] = {"id": 1, "type": command_type, **params}

        # Validate params against schema if present (schema=False means no params)
        if schema is not False:
            try:
                msg = schema(msg)
            except vol.Invalid as err:
                return HassCommandResult(
                    success=False, error=f"Validation error: {err}"
                )

        # Resolve user_id to User object for authorization checks
        user = None
        if user_id:
            user = await self._hass.auth.async_get_user(user_id)

        conn = InternalConnection(self._hass, user)

        try:
            # Handlers are always sync in the registry (async handlers are
            # wrapped by @async_response which schedules a background task)
            handler(self._hass, conn, msg)

            # Wait for result --- handles both sync handlers (already set)
            # and async-wrapped handlers (result comes from background task)
            await conn.wait_for_result(timeout=30.0)
        except TimeoutError:
            return HassCommandResult(
                success=False, error=f"Command '{command_type}' timed out"
            )
        except Exception as err:
            _LOGGER.exception("Error executing hass command %s", command_type)
            return HassCommandResult(
                success=False, error=f"Execution error: {type(err).__name__}: {err}"
            )

        if conn.error:
            return HassCommandResult(success=False, error=conn.error[1])
        return HassCommandResult(success=True, data=conn.result)

    async def execute_supervisor_call(
        self,
        method: str,
        path: str,
        params: dict[str, object],
        user_id: str | None,
    ) -> SupervisorCallResult:
        """Execute a Supervisor API call.

        Args:
            method: HTTP method (e.g. 'GET', 'POST')
            path: API path (e.g. '/core/logs')
            params: Query params (GET) or body (POST)
            user_id: Authenticated user ID for authorization

        Returns:
            SupervisorCallResult indicating success or failure
        """
        # Require authentication for Supervisor access
        if user_id is None:
            return SupervisorCallResult(
                success=False, error="Authentication required for Supervisor access"
            )

        # Resolve user_id to User object for authorization checks
        user = await self._hass.auth.async_get_user(user_id)
        if user is None or not user.is_admin:
            return SupervisorCallResult(
                success=False, error="Supervisor access requires admin privileges"
            )

        # Import hassio components - they may not be available on all installations
        try:
            from homeassistant.components.hassio import (  # type: ignore[attr-defined]
                HassioAPIError,
            )
            from homeassistant.components.hassio.const import DATA_COMPONENT
        except ImportError:
            return SupervisorCallResult(
                success=False, error="Supervisor integration not available"
            )

        hassio = self._hass.data.get(DATA_COMPONENT)
        if hassio is None:
            return SupervisorCallResult(success=False, error="Supervisor not available")

        try:
            # Determine if this returns text (logs) or JSON
            returns_text = path.endswith("/logs")

            # Use the hassio client to make the API call
            result = await hassio.send_command(
                path,
                method=method.lower(),
                payload=params if method.upper() in ("POST", "PUT", "PATCH") else None,
                timeout=None,
                return_text=returns_text,
            )

            if returns_text:
                # Log content returned as string
                return SupervisorCallResult(success=True, data={"logs": result})
            # JSON responses have a "data" key
            return SupervisorCallResult(
                success=True, data=result.get("data") if result else None
            )

        except HassioAPIError as err:
            return SupervisorCallResult(success=False, error=str(err))
        except Exception as err:
            _LOGGER.exception("Error calling Supervisor API: %s", path)
            return SupervisorCallResult(
                success=False, error=f"Supervisor error: {type(err).__name__}: {err}"
            )


class HamsterMCPView(HomeAssistantView):
    """Home Assistant view for MCP requests."""

    url = "/api/hamster_mcp"
    name = "api:hamster_mcp"
    requires_auth = True

    def __init__(self, transport: AiohttpMCPTransport) -> None:
        """Initialize the view.

        Args:
            transport: The MCP transport instance
        """
        self._transport = transport

    async def post(self, request: web.Request) -> web.Response:
        """Handle POST requests (JSON-RPC messages)."""
        return await self._transport.handle(request)

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET requests (future SSE endpoint)."""
        return await self._transport.handle(request)

    async def delete(self, request: web.Request) -> web.Response:
        """Handle DELETE requests (session termination)."""
        return await self._transport.handle(request)
