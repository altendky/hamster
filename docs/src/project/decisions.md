# Decisions

Resolved design decisions with rationale.

## D001: Custom Component (Not External Server or Add-on)

**Decision:** Build as an HA custom component.

**Rationale:** Only code running inside HA can access
`hass.services.async_services()` which returns service schemas with field
definitions.
The external REST API lists services but does not include schemas.
This is the single capability that enables dynamic tool generation.

**Trade-offs accepted:**

- HA restart required for code changes
- Must use HA's Python version
- Runs in HA's event loop

## D002: Sans-IO Core with Effect/Continuation

**Decision:** Implement the MCP protocol as a sans-IO state machine using the
effect/continuation pattern from onshape-mcp.

**Rationale:** Maximizes testability.
Core logic is tested with pure function calls --- no mocks, no event loops, no
fixtures.
The pattern has been proven in the onshape-mcp Rust codebase.

**Alternative considered:** Using the official `mcp` Python SDK.
Rejected because its HTTP transport is coupled to Starlette/ASGI (HA uses
aiohttp), and it adds 5 unused dependencies.
The session layer is coupled to anyio.
No sans-IO MCP library exists.

## D003: Direct MCP Protocol Implementation

**Decision:** Implement JSON-RPC + MCP protocol directly rather than depending
on the `mcp` Python SDK.

**Rationale:** The protocol surface area is small (~6 message types).
The SDK's transport layer is Starlette-based and incompatible with HA's aiohttp.
The SDK adds `starlette`, `uvicorn`, `sse-starlette`, `python-multipart`,
`pydantic-settings` as hard dependencies that would be installed but never used.
A direct implementation is ~500-800 lines.

## D004: Streamable HTTP Transport

**Decision:** Target MCP Streamable HTTP (spec 2025-03-26), not legacy SSE.

**Rationale:** Current spec.
Single POST endpoint.
Simpler to implement with `HomeAssistantView`.
SSE streaming within responses is optional and deferred.

## D005: Monorepo with Separate PyPI Package

**Decision:** Single repo containing both `src/hamster/` (PyPI package) and
`custom_components/hamster/` (HACS shim).

**Rationale:** HACS requires `custom_components/<domain>/` at the repo root.
HACS ignores everything else, so the library code in `src/` does not interfere.
The `manifest.json` declares `requirements: ["hamster"]` so HA pip-installs the
library automatically.

## D006: Hatchling Build Backend

**Decision:** Use hatchling instead of setuptools.

**Rationale:** Cleaner src/ layout support
(`packages = ["src/hamster"]` --- one line, unambiguous).
Built-in version management (no setuptools-scm dependency).
Lighter (~500KB vs ~1.5MB).
PyPA-maintained.
HA uses setuptools, but the build backend is invisible to users --- they just
`pip install`.

## D007: Python Version Policy

**Decision:** `requires-python = ">=3.13"` with CI testing on 3.13 and 3.14.
`mise.toml` pins 3.14 (latest stable HA).

**Rationale:** Minimum tracks the oldest Python required by any
currently-supported HA release.
HA 2025.2+ requires 3.13; HA 2026.3+ requires 3.14.
This covers ~14 months of HA releases.

## D008: Dual License (MIT OR Apache-2.0)

**Decision:** Dual MIT OR Apache-2.0 (SPDX: `MIT OR Apache-2.0`).
Users choose whichever they prefer.

**Rationale:** Matches onshape-mcp.
Compatible with HA core's Apache-2.0.
Standard Rust ecosystem convention that works equally well for Python.

## D009: Tooling Aligned with HA Ecosystem

**Decision:** Use ruff, mypy, pytest, pytest-asyncio, pre-commit --- matching
HA core's choices where applicable.

**Rationale:** Fit the ecosystem.
Developers familiar with HA core should find hamster's tooling familiar.
Language-agnostic tools (typos, markdownlint, actionlint, lychee) carried over
from onshape-mcp.

## D010: mkdocs-material for Documentation

**Decision:** Use mkdocs-material instead of mdBook (used by onshape-mcp).

**Rationale:** mdBook is a Rust ecosystem tool.
mkdocs-material is the standard for modern Python projects (used by Pydantic,
FastAPI, Polars, etc.).
Markdown-based, similar simplicity to mdBook, better Python ecosystem
integration (autodoc, intersphinx).

## D011: asyncio/aiohttp (Not anyio)

**Decision:** Use asyncio and aiohttp directly for the I/O layer.
anyio is a possible future addition.

**Rationale:** HA is built entirely on asyncio + aiohttp.
anyio is present in HA's environment only as a transitive dependency
(httpx → httpcore → anyio).
Aligning with HA's async framework is simpler and avoids introducing a new
abstraction layer.

## D012: Tool Name Format

**Decision:** `hamster_{domain}__{service}` (e.g., `hamster_light__turn_on`).

**Rationale:** MCP tool names must match `[a-zA-Z0-9_-]{1,64}` --- dots are not
allowed.
The `hamster_` prefix namespaces tools to avoid collisions with other MCP
servers.
Double underscore (`__`) separates domain from service unambiguously, since
neither HA domains nor service names contain double underscores.
Single underscore would be ambiguous (e.g., `climate_set_temperature` ---
is that `climate` + `set_temperature` or `climate_set` + `temperature`?).

## D013: Use pytest-homeassistant-custom-component

**Decision:** Use `pytest-homeassistant-custom-component` for
`hamster.component._tests/`.
Do not use it for `hamster.mcp._tests/`.

**Rationale:** It is the standard tool for testing HA custom components (~3M
downloads/month, no alternative).
It provides the exact same test fixtures as HA core: full `hass` instance, auth
users, HTTP test clients, registries, config entries, etc.

The split is clean:

- `hamster.mcp._tests/` --- pure Python, no HA dependency, fast.
  Tests the sans-IO core and I/O adapter.
- `hamster.component._tests/` --- uses `pytest-homeassistant-custom-component`.
  Tests the HA integration with realistic infrastructure.

**Trade-offs accepted:**

- Heavy install (pulls all of `homeassistant` core, ~500+ packages)
- All dependencies exact-pinned (can conflict with our own pins)
- CI for component tests is slower than for core tests

## D014: Ship Tests in Wheel

**Decision:** Include `_tests/` directories in the published wheel.
Test dependencies are a separate optional extras group (`test`).

**Rationale:** Users can verify their install with
`pip install hamster[test] && pytest --pyargs hamster`.
This is what `attrs`, `trio`, and other well-regarded libraries do.
The size cost is negligible.
Test dependencies (pytest, etc.) are not installed unless the user opts in via
the `test` extra.

## D015: Session Timeout in Sans-IO Core

**Decision:** Session idle timeout logic lives entirely in the sans-IO core.
No task per connection.
At most one I/O-layer task for timeout wakeups, or zero when no sessions exist.

**Design:** `SessionManager` lives in `hamster.mcp._core.session`.
It is a multi-session container: it routes messages to sessions by ID, creates
new sessions on `initialize`, tracks last-activity timestamps, and computes the
next wakeup time.
The I/O layer sleeps until that time, then asks the manager to expire idle
sessions and handle any other pending timed events (e.g. tool regeneration
debounce).

Session IDs are generated by an injected `session_id_factory` callable
(default: `secrets.token_hex`).
Tests inject a deterministic factory so session IDs are predictable and no real
entropy source is needed.

Timed events use a generic token-based wakeup mechanism: the core produces
`WakeupRequest(deadline, token)` where `token` is opaque to the I/O layer.
The I/O layer sleeps until the deadline and hands the token back.  This keeps
all timing logic in the pure core while allowing future wakeup reasons without
changing the I/O layer.

See the [Implementation Plan](implementation-plan.md) Stage 5 for the full
`SessionManager` API.

**Rationale:** This follows the sans-IO principle: all routing, timeout, and
state-machine logic is pure, deterministic, and testable without async.
The I/O layer is a trivial sleep loop.
No task queues, no task-per-connection.
Matches the MCP Python SDK's recommended 30-minute idle timeout with activity
push-back, but without the per-session `CancelScope` pattern.

**Default timeout:** 30 minutes (matches SDK recommendation).

## D016: Tool List Generated at Startup, Not Per Request

**Decision:** Generate the MCP tool list once at integration load time, not on
each `tools/list` request or session creation.
Regenerate when HA services change.

**Rationale:** `hass.services.async_services()` returns all registered services.
The set of services rarely changes at runtime — only when integrations are
loaded/unloaded or HA restarts.
Generating the tool list on every request is wasteful.

**Refresh trigger:** Listen for `EVENT_SERVICE_REGISTERED` and
`EVENT_SERVICE_REMOVED` events.
When either fires, regenerate the tool list.
This ensures the tool list stays current without polling.
