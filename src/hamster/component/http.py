"""HTTP view and effect handler for Hamster MCP.

Provides the Home Assistant HTTP view that handles MCP requests and
the effect handler that executes service calls.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from aiohttp import web  # noqa: TC002 - used in method signature annotations
from homeassistant.components.http.view import (  # type: ignore[attr-defined]
    HomeAssistantView,
)
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceNotFound,
    ServiceValidationError,
)

from hamster.mcp._core.types import ServiceCallResult
from hamster.mcp._io.aiohttp import AiohttpMCPTransport  # noqa: TC001

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class HamsterEffectHandler:
    """Effect handler that executes Home Assistant service calls."""

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
    ) -> ServiceCallResult:
        """Execute a Home Assistant service call.

        Args:
            domain: Service domain (e.g. 'light')
            service: Service name (e.g. 'turn_on')
            target: Target entities/devices/areas, or None
            data: Service data parameters

        Returns:
            ServiceCallResult indicating success or failure
        """
        try:
            result = await self._hass.services.async_call(
                domain,
                service,
                data,
                target=target,
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


class HamsterMCPView(HomeAssistantView):
    """Home Assistant view for MCP requests."""

    url = "/api/hamster"
    name = "api:hamster"
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
