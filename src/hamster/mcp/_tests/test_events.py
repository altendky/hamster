"""Tests for _core/events.py."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from hamster.mcp._core.events import (
    Continuation,
    Done,
    FormatServiceResponse,
    ReceiveResult,
    RunEffects,
    SendResponse,
    ServiceCall,
    SessionExpired,
    ToolEffect,
)
from hamster.mcp._core.types import CallToolResult, TextContent


class TestFormatServiceResponse:
    """Tests for FormatServiceResponse dataclass."""

    def test_construction(self) -> None:
        cont = FormatServiceResponse()
        assert isinstance(cont, FormatServiceResponse)

    def test_is_frozen_dataclass(self) -> None:
        # FormatServiceResponse has no fields, but it should still be a frozen dataclass
        cont = FormatServiceResponse()
        # Verify it's a dataclass with slots (no __dict__)
        assert not hasattr(cont, "__dict__")


class TestDone:
    """Tests for Done dataclass."""

    def test_construction(self) -> None:
        result = CallToolResult(content=(TextContent(text="ok"),))
        done = Done(result=result)
        assert done.result == result

    def test_frozen(self) -> None:
        result = CallToolResult(content=())
        done = Done(result=result)
        with pytest.raises(FrozenInstanceError):
            done.result = result  # type: ignore[misc]


class TestServiceCall:
    """Tests for ServiceCall dataclass."""

    def test_construction(self) -> None:
        sc = ServiceCall(
            domain="light",
            service="turn_on",
            target={"entity_id": ["light.living_room"]},
            data={"brightness": 255},
            continuation=FormatServiceResponse(),
        )
        assert sc.domain == "light"
        assert sc.service == "turn_on"
        assert sc.target == {"entity_id": ["light.living_room"]}
        assert sc.data == {"brightness": 255}
        assert isinstance(sc.continuation, FormatServiceResponse)

    def test_target_none(self) -> None:
        sc = ServiceCall(
            domain="homeassistant",
            service="reload",
            target=None,
            data={},
            continuation=FormatServiceResponse(),
        )
        assert sc.target is None

    def test_frozen(self) -> None:
        sc = ServiceCall(
            domain="light",
            service="turn_on",
            target=None,
            data={},
            continuation=FormatServiceResponse(),
        )
        with pytest.raises(FrozenInstanceError):
            sc.domain = "switch"  # type: ignore[misc]


class TestToolEffectUnion:
    """Tests for ToolEffect type alias."""

    def test_done_is_tool_effect(self) -> None:
        effect: ToolEffect = Done(result=CallToolResult(content=()))
        assert isinstance(effect, Done)

    def test_service_call_is_tool_effect(self) -> None:
        effect: ToolEffect = ServiceCall(
            domain="light",
            service="turn_on",
            target=None,
            data={},
            continuation=FormatServiceResponse(),
        )
        assert isinstance(effect, ServiceCall)

    def test_pattern_matching_done(self) -> None:
        effect: ToolEffect = Done(result=CallToolResult(content=()))
        match effect:
            case Done(result=r):
                assert isinstance(r, CallToolResult)
            case ServiceCall():
                pytest.fail("Should not match ServiceCall")

    def test_pattern_matching_service_call(self) -> None:
        effect: ToolEffect = ServiceCall(
            domain="light",
            service="turn_on",
            target=None,
            data={},
            continuation=FormatServiceResponse(),
        )
        match effect:
            case Done():
                pytest.fail("Should not match Done")
            case ServiceCall(domain=d, service=s):
                assert d == "light"
                assert s == "turn_on"


class TestSendResponse:
    """Tests for SendResponse dataclass."""

    def test_construction_with_body(self) -> None:
        resp = SendResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body={"result": "ok"},
        )
        assert resp.status == 200
        assert resp.headers == {"Content-Type": "application/json"}
        assert resp.body == {"result": "ok"}

    def test_construction_no_body(self) -> None:
        resp = SendResponse(
            status=202,
            headers={},
            body=None,
        )
        assert resp.status == 202
        assert resp.body is None

    def test_with_session_header(self) -> None:
        resp = SendResponse(
            status=200,
            headers={
                "Content-Type": "application/json",
                "Mcp-Session-Id": "abc123",
            },
            body={"result": {}},
        )
        assert resp.headers["Mcp-Session-Id"] == "abc123"

    def test_frozen(self) -> None:
        resp = SendResponse(status=200, headers={}, body=None)
        with pytest.raises(FrozenInstanceError):
            resp.status = 201  # type: ignore[misc]


class TestRunEffects:
    """Tests for RunEffects dataclass."""

    def test_construction(self) -> None:
        effect = Done(result=CallToolResult(content=()))
        run = RunEffects(request_id=42, effect=effect)
        assert run.request_id == 42
        assert run.effect == effect

    def test_with_service_call_effect(self) -> None:
        effect = ServiceCall(
            domain="light",
            service="turn_on",
            target=None,
            data={},
            continuation=FormatServiceResponse(),
        )
        run = RunEffects(request_id="req-1", effect=effect)
        assert run.request_id == "req-1"
        assert isinstance(run.effect, ServiceCall)

    def test_frozen(self) -> None:
        effect = Done(result=CallToolResult(content=()))
        run = RunEffects(request_id=1, effect=effect)
        with pytest.raises(FrozenInstanceError):
            run.request_id = 2  # type: ignore[misc]


class TestReceiveResultUnion:
    """Tests for ReceiveResult type alias."""

    def test_send_response_is_receive_result(self) -> None:
        result: ReceiveResult = SendResponse(status=200, headers={}, body={})
        assert isinstance(result, SendResponse)

    def test_run_effects_is_receive_result(self) -> None:
        effect = Done(result=CallToolResult(content=()))
        result: ReceiveResult = RunEffects(request_id=1, effect=effect)
        assert isinstance(result, RunEffects)

    def test_pattern_matching_send_response(self) -> None:
        result: ReceiveResult = SendResponse(status=202, headers={}, body=None)
        match result:
            case SendResponse(status=s, body=b):
                assert s == 202
                assert b is None
            case RunEffects():
                pytest.fail("Should not match RunEffects")

    def test_pattern_matching_run_effects(self) -> None:
        effect = Done(result=CallToolResult(content=()))
        result: ReceiveResult = RunEffects(request_id=99, effect=effect)
        match result:
            case SendResponse():
                pytest.fail("Should not match SendResponse")
            case RunEffects(request_id=rid, effect=e):
                assert rid == 99
                assert isinstance(e, Done)


class TestNestedDispatch:
    """Tests for nested pattern matching (extract effect from RunEffects)."""

    def test_extract_done_from_run_effects(self) -> None:
        done = Done(result=CallToolResult(content=(TextContent(text="hi"),)))
        result: ReceiveResult = RunEffects(request_id=1, effect=done)

        match result:
            case RunEffects(effect=e):
                match e:
                    case Done(result=r):
                        assert r.content[0].text == "hi"  # type: ignore[union-attr]
                    case ServiceCall():
                        pytest.fail("Should be Done")
            case SendResponse():
                pytest.fail("Should be RunEffects")

    def test_extract_service_call_from_run_effects(self) -> None:
        sc = ServiceCall(
            domain="switch",
            service="toggle",
            target={"entity_id": ["switch.fan"]},
            data={},
            continuation=FormatServiceResponse(),
        )
        result: ReceiveResult = RunEffects(request_id=2, effect=sc)

        match result:
            case RunEffects(effect=e):
                match e:
                    case Done():
                        pytest.fail("Should be ServiceCall")
                    case ServiceCall(domain=d, target=t):
                        assert d == "switch"
                        assert t == {"entity_id": ["switch.fan"]}
            case SendResponse():
                pytest.fail("Should be RunEffects")


class TestSessionExpired:
    """Tests for SessionExpired dataclass."""

    def test_construction(self) -> None:
        exp = SessionExpired(session_id="sess-abc-123")
        assert exp.session_id == "sess-abc-123"

    def test_frozen(self) -> None:
        exp = SessionExpired(session_id="test")
        with pytest.raises(FrozenInstanceError):
            exp.session_id = "changed"  # type: ignore[misc]


class TestContinuationUnion:
    """Tests for Continuation type alias."""

    def test_format_service_response_is_continuation(self) -> None:
        cont: Continuation = FormatServiceResponse()
        assert isinstance(cont, FormatServiceResponse)
