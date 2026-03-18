# Principles

## Sans-IO Design

The project follows **full sans-IO design principles** to maximize testability.

### Core Principles

1. **Core modules have zero I/O dependencies** --- no asyncio, no aiohttp,
   no network, no filesystem
2. **Core modules CAN have pure computation dependencies** --- stdlib only for
   now, potentially `dataclasses`, `enum`, `json`, `re`, etc.
3. **State machines over async/await in core** --- pure functions that produce
   effects
4. **Effects are data** --- I/O operations are represented as frozen dataclasses
5. **I/O modules interpret effects** --- thin async wrappers that execute effects
6. **100% testable without mocking** --- core logic tested with deterministic
   inputs, no mocks needed

### The Effect/Continuation Pattern

Adapted from the pattern used in
[onshape-mcp](https://github.com/altendky/onshape-mcp).
Core functions return **effect objects** describing what I/O they need.
The I/O layer runs a **dispatch loop** that executes effects and feeds results
back through a pure `resume()` function.

```python
# Core module --- pure logic, no I/O

@dataclass(frozen=True)
class Done:
    """Tool completed --- no further I/O needed."""
    result: CallToolResult

@dataclass(frozen=True)
class ServiceCall:
    """Tool needs an HA service call."""
    domain: str
    service: str
    data: dict[str, object]
    continuation: Continuation

# Plain-data continuation --- no closures, fully inspectable
@dataclass(frozen=True)
class FormatServiceResponse:
    """Format the raw service response into MCP content."""
    pass

ToolEffect = Done | ServiceCall

def call_tool(name: str, arguments: dict[str, object]) -> ToolEffect:
    """Pure function: tool call arguments -> effect."""
    ...

def resume(
    continuation: Continuation,
    io_result: IoResult,
) -> ToolEffect:
    """Pure dispatch: continuation + I/O result -> next effect."""
    ...

# I/O module --- interprets effects in a loop
async def dispatch_effect(
    hass: HomeAssistant,
    effect: ToolEffect,
) -> CallToolResult:
    current = effect
    while True:
        match current:
            case Done(result=result):
                return result
            case ServiceCall(
                domain=domain,
                service=service,
                data=data,
                continuation=continuation,
            ):
                result = await hass.services.async_call(
                    domain, service, data, blocking=True,
                )
                current = resume(
                    continuation,
                    ServiceCallResult(result),
                )
```

### Why This Matters

- **Core logic is trivially testable** --- feed in a dict, assert the returned
  effect.
  No mocks, no event loops, no fixtures.
- **I/O adapter is trivially testable** --- the dispatch loop is a simple
  match/case.
  Only needs a thin integration test.
- **Effects are inspectable** --- unlike closures, you can print, compare, and
  serialize continuation values.
- **Deterministic** --- same input always produces the same output.
  No timing dependencies, no race conditions in core logic.

## Import Rules

Import boundaries are enforced at the package level.
These are the hard rules:

| Module | May Import | Must NOT Import |
| --- | --- | --- |
| `hamster.mcp._core` | stdlib only | `asyncio`, `aiohttp`, `homeassistant`, `hamster.mcp._io` |
| `hamster.mcp._io` | stdlib, `asyncio`, `aiohttp`, `hamster.mcp._core` | `homeassistant` |
| `hamster.component` | stdlib, `asyncio`, `aiohttp`, `homeassistant`, `hamster.mcp` | (no restrictions) |

The key insight: `_core` is a pure Python library with no async and no
framework dependencies.
It can be tested, understood, and reused independently.

## Dependencies Policy

### Core Modules (sans-IO)

**Allowed:**

- Python standard library
- Pure computation (no I/O, no async)

**Forbidden:**

- `asyncio` or any async runtime
- `aiohttp`, `httpx`, or HTTP libraries
- File system access
- Network access
- Anything from `homeassistant`

### I/O Modules

**Allowed:**

- `asyncio`
- `aiohttp`
- `hamster.mcp._core`

**Forbidden:**

- `homeassistant` (the I/O adapter is HA-independent)

### Component Modules

**Allowed:**

- Everything from core and I/O
- `homeassistant` internals
- HA's pinned dependencies (`voluptuous`, etc.)

## Dynamic Tool Discovery

Every existing HA MCP project defines tools statically.
Hamster generates them at runtime:

1. Call `hass.services.async_services()` --- returns all domains, services, and
   field schemas
2. For each service, generate an MCP tool definition with:
   - Name derived from domain + service
   - Description from the service schema
   - Input schema from field definitions (selectors to JSON Schema)
3. Apply tristate filtering (Enabled/Dynamic/Disabled)
4. Serve dynamically on `tools/list`
5. On `tools/call`, dispatch to `hass.services.async_call()`

The tool generation function itself is **pure** --- it takes service data in and
returns tool definitions out.
The I/O layer handles calling `async_services()` and wiring the results.

## Tristate Tool Control

Each service has three states:

| State | Behavior |
| --- | --- |
| **Enabled** | Always exposed as an MCP tool |
| **Dynamic** | Exposed based on runtime discovery (the default) |
| **Disabled** | Never exposed |

This allows users to:

- Disable dangerous services (e.g., `homeassistant.restart`)
- Force-enable specific services regardless of filtering
- Let most services be discovered automatically
