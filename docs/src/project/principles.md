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
    target: dict[str, object] | None
    data: dict[str, object]
    continuation: Continuation

# Plain-data continuation --- no closures, fully inspectable
@dataclass(frozen=True)
class FormatServiceResponse:
    """Format the raw service response into MCP content."""
    pass

ToolEffect = Done | ServiceCall

def call_tool(
    name: str,
    arguments: dict[str, object],
    index: ServiceIndex,
) -> ToolEffect:
    """Pure function: tool call arguments + index -> effect."""
    ...

def resume(
    continuation: Continuation,
    io_result: ServiceCallResult,
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
                target=target,
                data=data,
                continuation=continuation,
            ):
                result = await effect_handler.execute_service_call(
                    domain, service, target, data,
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
| `hamster_mcp.mcp._core` | **No I/O, no global state.** Pure functions and data types only. | Must not import `_io` or `component`. |
| `hamster_mcp.mcp._io` | **Async I/O adapter.** Bridges HTTP to the sans-IO core. | May import `_core`. Does not import `homeassistant` (HA-independent for testability). |
| `hamster_mcp.component` | **HA integration.** No behavioral restrictions. | May import everything. |

The key insight: `_core` is defined by what its code *does* (no I/O, no global
state), not by what it *imports*.
It may depend on any library --- stdlib or third-party --- as long as the core
code itself remains pure.
In practice it currently needs only the stdlib, but the constraint is
behavioral, not a dependency whitelist.

## Meta-Tool API Gateway

Every existing HA MCP project defines tools statically.
Hamster uses a **meta-tool pattern** (see D017):

1. Call `async_get_all_descriptions()` --- returns all services with field
   definitions, selectors, and target configuration
2. Build a `ServiceIndex` (pure construction, no I/O)
3. Expose 4 fixed MCP tools: `search`, `explain`, `call`, `schema`
4. The LLM discovers services via `search`, reads their details via
   `explain`, and invokes them via `call`
5. `call` dispatches to `hass.services.async_call()` with separate
   `target` and `data` parameters

The `ServiceIndex` constructor is **pure** --- it takes description data in
and returns an indexed, searchable structure out.
The component layer handles calling `async_get_all_descriptions()` and
feeding the results to the `SessionManager` via `update_index()`.

## Tristate Tool Control (Deferred)

Per-service filtering is deferred.  With 4 fixed meta-tools, there is no
per-service tool list to filter.  A future addition could restrict which
services the LLM can discover or invoke via the `ServiceIndex`.

Previously planned states:

| State | Behavior |
| --- | --- |
| **Enabled** | Always discoverable |
| **Dynamic** | Discoverable based on runtime state (the default) |
| **Disabled** | Hidden from search/explain, rejected by call |

This allows users to:

- Disable dangerous services (e.g., `homeassistant.restart`)
- Force-enable specific services regardless of filtering
- Let most services be discovered automatically
