# Principles

## Sans-IO Design

The project follows **full sans-IO design principles** to maximize testability.

### Core Principles

1. **Core modules perform no I/O and hold no global state** --- no network,
   no filesystem, no event loops, no mutable module-level state
2. **Core modules may have dependencies** --- any library is allowed as long
   as the core code itself performs no I/O and references no global state
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

# I/O transport --- runs the dispatch loop, delegates I/O to EffectHandler
async def run_effects(
    effect_handler: EffectHandler,
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
                result = await effect_handler.execute_service_call(
                    domain, service, data,
                )
                current = resume(
                    continuation,
                    result,
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

## Layer Constraints

Each layer has a **behavioral** contract (what code may *do*) and a
**structural** contract (what it may *import*).
The behavioral rules are the fundamental ones --- the structural rules follow
from them.

| Layer | Behavioral Contract | Structural |
| --- | --- | --- |
| `hamster.mcp._core` | **No I/O, no global state.** Pure functions and data types only. | Must not import `_io` or `component`. |
| `hamster.mcp._io` | **Async I/O adapter.** Bridges HTTP to the sans-IO core. | May import `_core`. Does not import `homeassistant` (HA-independent for testability). |
| `hamster.component` | **HA integration.** No behavioral restrictions. | May import everything. |

The key insight: `_core` is defined by what its code *does* (no I/O, no global
state), not by what it *imports*.
It may depend on any library --- stdlib or third-party --- as long as the core
code itself remains pure.
In practice it currently needs only the stdlib, but the constraint is
behavioral, not a dependency whitelist.

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
The component layer handles calling `async_services()` and feeding the results
to the `SessionManager` via `update_tools()`.

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
