"""Thin aiohttp adapter for MCP.

Bridges aiohttp request objects to the sans-IO core's IncomingRequest/ReceiveResult
interface. Uses asyncio and aiohttp but does not import homeassistant.

The transport performs only two kinds of work:
1. Data extraction - read bytes, extract headers, build IncomingRequest, translate
   SendResponse to web.Response
2. Effect dispatch - the async loop that executes I/O effects
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
import logging
import time
from typing import TYPE_CHECKING, Protocol

from aiohttp import web

from hamster.mcp._core.events import Done, RunEffects, SendResponse, ServiceCall
from hamster.mcp._core.tools import resume
from hamster.mcp._core.types import CallToolResult, IncomingRequest, ServiceCallResult

if TYPE_CHECKING:
    from hamster.mcp._core.events import ToolEffect
    from hamster.mcp._core.session import SessionManager

_LOGGER = logging.getLogger(__name__)


class EffectHandler(Protocol):
    """Protocol for executing service call effects.

    Defined here, implemented by hamster.component.http.
    """

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
        ...


# Type for index rebuild callback
IndexRebuildCallback = Callable[[], Awaitable[None]]


class AiohttpMCPTransport:
    """aiohttp transport for MCP protocol.

    Bridges aiohttp requests to the sans-IO SessionManager.
    """

    def __init__(
        self,
        manager: SessionManager,
        effect_handler: EffectHandler,
        index_rebuild_callback: IndexRebuildCallback | None = None,
    ) -> None:
        """Initialize the transport.

        Args:
            manager: The sans-IO session manager
            effect_handler: Handler for executing service call effects
            index_rebuild_callback: Optional callback for rebuilding service index
        """
        self._manager = manager
        self._effect_handler = effect_handler
        self._index_rebuild_callback = index_rebuild_callback
        self._loaded = True
        self._wakeup_task: asyncio.Task[None] | None = None
        self._wakeup_event = asyncio.Event()

    async def handle(self, request: web.Request) -> web.Response:
        """Handle an HTTP request.

        Single handler for all HTTP methods (POST, GET, DELETE).

        Args:
            request: aiohttp request object

        Returns:
            aiohttp response object
        """
        if not self._loaded:
            return web.Response(status=503)

        body = await request.read()
        incoming = IncomingRequest(
            http_method=request.method,
            content_type=request.content_type,
            accept=request.headers.get("Accept"),
            origin=request.headers.get("Origin"),
            host=request.host,
            session_id=request.headers.get("Mcp-Session-Id"),
            body=body,
        )

        result = self._manager.receive_request(incoming, now=time.monotonic())

        # Handle single result
        if isinstance(result, SendResponse):
            return self._make_response(result)
        if isinstance(result, RunEffects):
            call_result = await self._run_effects(result.effect)
            resp = self._manager.build_effect_response(result.request_id, call_result)
            return self._make_response(resp)

        # Handle batch result (list)
        if isinstance(result, list):
            return await self._handle_batch_results(result)

        # Should not reach here
        _LOGGER.error("Unexpected result type: %s", type(result))  # pragma: no cover
        return web.Response(status=500)  # pragma: no cover

    async def _handle_batch_results(
        self, results: list[SendResponse | RunEffects]
    ) -> web.Response:
        """Handle batch of results, collecting response bodies."""
        bodies: list[dict[str, object]] = []

        for item in results:
            if isinstance(item, SendResponse):
                if item.body is not None:
                    bodies.append(item.body)
                # SendResponse with body=None (notifications) omitted
            elif isinstance(item, RunEffects):
                call_result = await self._run_effects(item.effect)
                resp = self._manager.build_effect_response(item.request_id, call_result)
                if resp.body is not None:
                    bodies.append(resp.body)

        if not bodies:
            return web.Response(status=202)
        return web.json_response(data=bodies, status=200)

    def _make_response(self, result: SendResponse) -> web.Response:
        """Convert SendResponse to aiohttp response."""
        if result.body is None:
            return web.Response(status=result.status, headers=result.headers)
        # Filter out Content-Type from headers since json_response sets it automatically
        headers_without_ct = {
            k: v for k, v in result.headers.items() if k.lower() != "content-type"
        }
        return web.json_response(
            data=result.body, status=result.status, headers=headers_without_ct
        )

    async def _run_effects(self, effect: ToolEffect) -> CallToolResult:
        """Run the effect dispatch loop.

        Args:
            effect: Initial tool effect

        Returns:
            Final CallToolResult
        """
        current = effect
        while True:
            if isinstance(current, Done):
                return current.result
            if isinstance(current, ServiceCall):
                try:
                    io_result = await self._effect_handler.execute_service_call(
                        current.domain,
                        current.service,
                        current.target,
                        current.data,
                    )
                except Exception as err:
                    _LOGGER.exception(
                        "Error executing service call %s.%s",
                        current.domain,
                        current.service,
                    )
                    io_result = ServiceCallResult(
                        success=False,
                        error=f"Unexpected error: {type(err).__name__}: {err}",
                    )
                current = resume(current.continuation, io_result)

    def shutdown(self) -> None:
        """Shutdown the transport.

        Sets loaded flag to False so new requests return 503.
        In-flight requests complete naturally.
        """
        self._loaded = False

    def notify_activity(self) -> None:
        """Wake the wakeup loop early.

        Called after creating a new session or after notify_services_changed().
        """
        self._wakeup_event.set()

    async def start_wakeup_loop(self) -> None:
        """Start the background wakeup loop.

        Should be called as a background task.
        """
        self._wakeup_task = asyncio.current_task()
        consecutive_failures = 0

        while self._loaded:
            try:
                now = time.monotonic()
                expired_list, should_regenerate, wakeup = self._manager.check_wakeups(
                    now
                )

                # Handle expired sessions
                for expired in expired_list:
                    _LOGGER.debug("Session expired: %s", expired.session_id)

                # Handle index rebuild
                if should_regenerate and self._index_rebuild_callback is not None:
                    try:
                        await self._index_rebuild_callback()
                    except Exception:
                        _LOGGER.exception("Error rebuilding service index")

                # Wait for next wakeup
                if wakeup is None:
                    # No sessions, no pending debounce - wait for activity
                    self._wakeup_event.clear()
                    await self._wakeup_event.wait()
                else:
                    # Sleep until deadline
                    delay = max(0, wakeup.deadline - time.monotonic())
                    if delay > 0:
                        self._wakeup_event.clear()
                        with contextlib.suppress(TimeoutError):
                            await asyncio.wait_for(
                                self._wakeup_event.wait(), timeout=delay
                            )

                # Reset failure counter on success
                consecutive_failures = 0

            except asyncio.CancelledError:
                # Task cancelled - exit cleanly
                raise
            except Exception:
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    _LOGGER.critical(
                        "Wakeup loop has failed %d consecutive times",
                        consecutive_failures,
                    )
                else:
                    _LOGGER.exception(
                        "Error in wakeup loop (attempt %d)", consecutive_failures
                    )
                # Brief delay before retry to avoid tight loops
                await asyncio.sleep(0.1)

    async def stop_wakeup_loop(self) -> None:
        """Stop the wakeup loop.

        Cancels the background task and waits for it to complete.
        """
        if self._wakeup_task is not None:
            self._wakeup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._wakeup_task
            self._wakeup_task = None
