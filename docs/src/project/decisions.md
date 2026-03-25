# Decisions

Resolved design decisions with rationale.

## D001: Custom Component (Not External Server or Add-on)

**Decision:** Build as an HA custom component.

**Rationale:** Only code running inside HA can access
`async_get_all_descriptions()` which returns service descriptions with field
definitions, selectors, and target configuration.
The external REST API lists services but does not include field schemas.
This is the single capability that enables the meta-tool pattern.

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

## ~~D012: Tool Name Format~~ --- SUPERSEDED

Superseded by D017.  Per-service tool names are no longer generated.
The 4 fixed meta-tool names are hardcoded constants
(`hamster_services_search`, `hamster_services_explain`,
`hamster_services_call`, `hamster_services_schema`).

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
sessions and handle any other pending timed events (e.g. index rebuild
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

See `src/hamster/mcp/_core/session.py` for the full `SessionManager`
implementation.

**Rationale:** This follows the sans-IO principle: all routing, timeout, and
state-machine logic is pure, deterministic, and testable without async.
The I/O layer is a trivial sleep loop.
No task queues, no task-per-connection.
Matches the MCP Python SDK's recommended 30-minute idle timeout with activity
push-back, but without the per-session `CancelScope` pattern.

**Default timeout:** 30 minutes (matches SDK recommendation).

## D016: Service Index Built at Startup, Not Per Request

**Decision:** Build the `ServiceIndex` once at integration load time, not on
each `tools/call` request.  Rebuild when HA services change.  The MCP tool
list itself is constant (4 fixed tools).

**Rationale:** `async_get_all_descriptions()` loads and parses `services.yaml`
files from disk.  The set of services rarely changes at runtime --- only when
integrations are loaded/unloaded or HA restarts.  Building the index on every
request is wasteful.

**Refresh trigger:** Listen for `EVENT_SERVICE_REGISTERED` and
`EVENT_SERVICE_REMOVED` events.
When either fires, rebuild the `ServiceIndex`.
This ensures the index stays current without polling.

## D017: Meta-Tool Pattern Over Per-Service Tool Generation

**Decision:** Expose 4 fixed MCP tools (`hamster_services_search`,
`hamster_services_explain`, `hamster_services_call`,
`hamster_services_schema`) that let the LLM discover and invoke any HA
service dynamically.  Do not generate one MCP tool per HA service.

**Rationale:** A typical HA instance has hundreds of services.  Generating one
MCP tool per service inflates the tool list that the LLM must process on every
turn, consuming context window and degrading performance.  The meta-tool
pattern (modeled after onshape-mcp) keeps the tool count constant at 4
regardless of how many HA services exist.

The LLM uses `search` to find relevant services, `explain` to read their
field/selector details, and `call` to invoke them.  `schema` documents
selector types so the LLM knows what input format each selector expects.
Three of the four tools are pure computation (no I/O); only `call` produces
a `ServiceCall` effect.

**Trade-off accepted:** The LLM needs 2--3 round trips (search → explain →
call) instead of a single tool call.  This is acceptable because the context
savings from not listing hundreds of tools far outweigh the extra round trips.

**Alternative considered:** Dynamic tool registration (LLM discovers a service,
then it's added as a real MCP tool via `tools/list_changed`).  Rejected
because the benefit over a well-designed generic `call` tool is marginal ---
the schema information is already in the conversation context from the
`explain` step, and each dynamically-added tool still inflates the tool list
for subsequent turns.

## D018: Raw HA Descriptions in Explain Output

**Decision:** The `hamster_services_explain` tool returns HA service
descriptions as-is (fields with selectors in their native format).  The
`hamster_services_schema` tool documents selector types separately.

**Rationale:** Avoids a translation layer between HA's selector format and
some intermediate representation.  The LLM sees exactly what HA defines.
If the LLM doesn't understand a selector type (e.g., `duration`), it uses
`schema` to look up what that selector expects.  This keeps `explain`
simple and accurate while still providing full type information on demand.

**Alternative considered:** Translating selectors to JSON Schema or annotated
descriptions inline.  Rejected because it adds complexity and risks lossy
translation.  The raw format is already human-readable (YAML-like key/value
pairs with clear structure).

## D019: Separate Target and Data in Service Calls

**Decision:** The `hamster_services_call` tool accepts `target` and `data` as
separate parameters.  The `ServiceCall` effect carries both fields
independently.  `EffectHandler.execute_service_call()` passes `target` to
`hass.services.async_call()` as a separate keyword argument.

**Rationale:** This matches HA's own `async_call(domain, service, service_data,
target=target)` signature.  HA's target contains the 5 target property keys
(`entity_id`, `device_id`, `area_id`, `floor_id`, `label_id`) which are
semantically distinct from service field data.  Keeping them separate makes
the API clear and avoids the LLM needing to know which keys are target
properties vs. field values.

**Alternative considered:** Flat dict mixing target and field data (HA can
extract target keys from `service_data` internally).  Rejected because the
separation is clearer for LLM comprehension and matches the upstream API.

## D020: `ToolsCapability` Dataclass and `call_tool()` Return Contract

**Decision (capabilities):** Model `ServerCapabilities.tools` as
`ToolsCapability | None` instead of `bool`.

```python
@dataclass(frozen=True)
class ToolsCapability:
    list_changed: bool = False

@dataclass(frozen=True)
class ServerCapabilities:
    tools: ToolsCapability | None = field(
        default_factory=ToolsCapability,
    )
```

Serialization:

- `ToolsCapability(list_changed=False)` → `{"tools": {}}`.
- `ToolsCapability(list_changed=True)` → `{"tools": {"listChanged": true}}`.
- `None` → `{}` (tools not supported).

**Rationale:** Trivial extra work now, avoids a breaking change when SSE
support lands (Q012) and `listChanged` needs to be advertised.  Honestly
represents the MCP protocol's capability structure.

**Decision (`call_tool()`):** `call_tool()` returns
`Done(CallToolResult(is_error=True))` for unknown tool names instead of
raising `ValueError`.

**Rationale:** `call_tool()` already returns `Done(is_error=True)` for
"service not found in index" --- a similar "not found" condition.  The
service index can change between the session's tool-name validation and
`call_tool()` execution, so unknown-name is a data condition, not a
violated invariant.  The function's contract becomes "returns `ToolEffect`
for all inputs" with no exception paths.

The session still validates tool names before dispatching and returns
`INVALID_PARAMS` at the JSON-RPC level --- that check remains as a
protocol courtesy.  `call_tool()` handles the case gracefully either way.

**Alternatives considered:**

- `ValueError` for unknown tool name (original plan).  Rejected because
  the race between index updates and request handling means "unknown" is
  a runtime data condition, not a programming error.
- Dedicated `ToolNotFound` effect type.  Rejected as unnecessary ceremony
  for a case that should rarely occur.

## D021: Logging Guidance

**Decision:** Level-based logging guidance with a read/write tool split.
Not prescriptive log-point specs --- implementation guidance only.

| Level | What |
| --- | --- |
| **DEBUG** | Read-only tool calls (`search`, `explain`, `schema` --- arguments and results), individual request handling, effect dispatch details |
| **INFO** | Session created, session expired, index rebuilt (with service count), `hamster_services_call` invocations (domain, service, target summary) |
| **WARNING** | Client errors (bad headers, unknown session ID, rejected requests) |
| **ERROR** | Unexpected failures only (`HamsterEffectHandler` catch-all) |

**Rationale:** `hamster_services_call` mutates state (turns on lights,
opens locks), so operators need default-level visibility into what the LLM
is doing.  Read-only discovery tools (`search`, `explain`, `schema`) are
DEBUG to avoid noise in production.

Formal log-point specs are too rigid and drift from implementation.
Pure implementer discretion risks inconsistency.  Level-based guidance
strikes the balance.

**Alternative considered:** Logging all tool calls at INFO.  Rejected
because the LLM typically makes several `search`/`explain` round-trips
per user request, which would be noisy at the default level.

**Correlation:** Log messages should include session ID and JSON-RPC
request ID where available, enabling request tracing without additional
infrastructure.  Example:

```python
_LOGGER.info("[session=%s req=%s] tools/call %s.%s", session_id, request_id, domain, service)
```

## D022: Origin Header Validation (Same-Origin Check)

**Decision:** Validate the `Origin` header using same-origin checking.

**Rationale:** The MCP Streamable HTTP spec says servers **MUST** validate
the `Origin` header to prevent DNS rebinding attacks.  This is a hard
requirement, not a SHOULD.

**Implementation:**

- Add `host` field to `IncomingRequest` (from the `Host` header).
- If `Origin` header is absent, allow the request (non-browser clients
  like curl and MCP CLI tools don't send `Origin`).
- If `Origin` header is present, extract the host portion (scheme, host,
  and optional port) and compare to the `Host` header.  If they don't
  match, reject with `SendResponse(403)`.

**Example:**

- `Host: homeassistant.local:8123`, `Origin: http://homeassistant.local:8123` → allowed
- `Host: homeassistant.local:8123`, `Origin: http://evil.com` → rejected (403)
- `Host: homeassistant.local:8123`, `Origin: (absent)` → allowed

**Alternative considered:** Relying solely on HA's bearer token auth.
Rejected because DNS rebinding can trick a browser into sending
authenticated requests to an attacker-controlled origin, and the MCP spec
requires Origin validation regardless of other auth mechanisms.

## D023: Content-Type Parameter Stripping (Defensive)

**Decision:** The sans-IO core defensively strips Content-Type parameters
(e.g., `; charset=utf-8`) rather than requiring the transport to normalize.

**Rationale:** Defense-in-depth. The cost is negligible (simple string
split on `;` and strip). While aiohttp's `request.content_type` already
strips parameters, other transports might not. Core tests can exercise
parameter stripping directly without relying on transport behavior.

**Implementation:** In `receive_request()`, before comparing Content-Type
to `"application/json"`, split on `;` and take the first part:

```python
media_type = (content_type or "").split(";")[0].strip()
if media_type != "application/json":
    return SendResponse(415, ...)
```

## D024: Multi-Source Architecture

**Decision:** Expose HA capabilities through three distinct source groups:
`services`, `hass`, and `supervisor`.  Each group has its own discovery
mechanism and enrichment sources.  Commands are identified by
`<group>/<path>` (e.g., `services/light.turn_on`, `hass/get_states`).

**Rationale:**

- **Services** provide the richest metadata via `async_get_all_descriptions()`
  but only cover actions, not queries.
- **WebSocket commands** (`hass` group) cover queries (states, registries,
  history, logs) that services don't expose.  Discoverable at runtime via
  `hass.data["websocket_api"]`.
- **Supervisor** provides capabilities unavailable through HA's internal
  APIs (full logs, add-on management, backups).  Only available on HA OS /
  Supervised installs.

The three groups are complementary rather than overlapping.  While
`hass/call_service` could technically call any service, the `services`
group provides richer metadata for the same operations.  Both are exposed
to allow exploration of which approach works better for LLM interaction.

**Path format:** `<group>/<path>` makes the source explicit in every
command reference, avoiding ambiguity and allowing group-level filtering.

**Alternative considered:** Merging all sources into a single flat
namespace.  Rejected because the discovery mechanisms and metadata
richness differ significantly between sources.  Explicit grouping makes
the architecture clearer.

## D025: WebSocket Commands as Primary Query Interface

**Decision:** The `hass` group exposes HA's WebSocket command registry as
the primary interface for queries (states, registries, history, config).

**Rationale:** WebSocket commands are the superset for read operations:

- ~100% of read operations are available via WebSocket
- ~15% are available via REST API
- Registries, statistics, logbook, system_log are WebSocket-only

The REST API is largely redundant with WebSocket and not discoverable at
runtime.  WebSocket commands are discoverable via `hass.data["websocket_api"]`.

**Filtering:** Only subscription commands (`subscribe_*`, `unsubscribe_*`)
and auth commands are excluded.  Everything else is exposed, including
"admin" operations like logs and registry mutations.

**Enrichment:** WebSocket commands lack rich runtime metadata (HA
maintainers have intentionally kept them undocumented for flexibility).
Documentation from the `developers.home-assistant` GitHub repo provides
command descriptions.  Service descriptions from `async_get_all_descriptions()`
enrich the `call_service` command specifically.

## D026: Service Descriptions as Metadata Enrichment

**Decision:** Service descriptions from `async_get_all_descriptions()`
are used to enrich the `hass/call_service` command, not as a separate
primary interface.

**Rationale:** Services and WebSocket commands are different interfaces
to overlapping data:

- Services = actions (turn on, turn off) with rich metadata
- WebSocket = queries + actions with sparse metadata

For `call_service` specifically, the service description metadata
(field descriptions, selectors, targets) is invaluable for LLM
comprehension.  This metadata is attached to the `hass/call_service`
command's `explain` output.

The `services` group is retained as a parallel interface because it
provides a more direct mapping for action-oriented workflows.  Over time,
usage patterns will inform whether both groups remain useful.

## D027: GitHub Docs Enrichment Strategy

**Decision:** Documentation for WebSocket commands is fetched from the
`master` branch of `home-assistant/developers.home-assistant` on user
request and cached.

**Rationale:**

- The docs repo has no version tags, so version matching is approximate.
- `master` branch represents "current stable" documentation.
- User-triggered refresh avoids startup latency and network failures
  blocking HA startup.
- On version mismatch (cached version != running HA), commands report
  "description unavailable" but remain callable via schema.

**Trade-offs accepted:**

- Documentation may drift from running HA version.
- Users must manually refresh after HA upgrades.
- Network access required for initial fetch.

**Future considerations:** Alternative strategies (date-based matching,
bundling at Hamster release, local docs path for dev installs) are
documented in open questions Q025-Q027.

**Relationship to D018:** This enrichment *supplements* the raw HA
descriptions from D018, not replaces them.  Service descriptions from
`async_get_all_descriptions()` remain the primary metadata for the
`services` group.  GitHub docs provide additional context for the `hass`
group where runtime metadata is sparse.

## D028: Supervisor Group Availability Detection

**Decision:** The `supervisor` group is hidden when the Supervisor is
unavailable.  Detection is via environment variables and integration
presence.

**Rationale:** Supervisor is only available on HA OS and Supervised
installs.  Exposing unavailable commands would confuse users and LLMs.

**Implementation:**

- Check for `SUPERVISOR` and `SUPERVISOR_TOKEN` environment variables
- Check for `hassio` integration presence
- If unavailable, supervisor commands don't appear in search results
- Attempts to explain/execute return clear "Supervisor not available" errors

**Graceful degradation:** The `services` and `hass` groups work
independently of Supervisor availability.

## D029: `hass` Group Naming

**Decision:** The WebSocket command group is named `hass`, not `ws` or
other alternatives.

**Rationale:** "ws" refers to the WebSocket protocol, but Hamster accesses
the underlying command registry directly (not via WebSocket).  "hass" is
the conventional name for the Home Assistant core object in HA's codebase
(`hass` is the variable name used everywhere for the `HomeAssistant`
instance).  It accurately represents that these are core HA commands.

**Alternatives considered:**

- `ws` --- Protocol name, not the data being accessed
- `api` --- Too generic, could conflict with REST API terminology
- `core` --- Could conflict with `supervisor/core/logs`
- `ha` --- Short but `hass` is more established in HA developer parlance

## D030: Tool Renaming for Multi-Source Architecture

**Decision:** Rename tools from `hamster_services_*` to generic names with
path-based addressing:

- `hamster_services_search` → `search`
- `hamster_services_explain` → `explain`
- `hamster_services_call` → `call`
- `hamster_services_schema` → `schema`

MCP clients prefix tool names with the server name ("hamster"), so clients
see these as `hamster_search`, `hamster_explain`, etc.

**Rationale:** The multi-source architecture (D024) uses a unified
`<group>/<path>` addressing scheme.  Generic tool names with path
parameters allow the same 4 tools to work across all groups.
Group-specific tool names would require 12 tools (4 per group) and
complicate the interface.

**Trade-off accepted:** This is a breaking change for any existing clients
using the `hamster_services_*` names.  Acceptable since the project is in
early development.

## D031: SourceGroup Protocol Design

**Decision:** Define a `SourceGroup` protocol with methods: `search()`,
`explain()`, `schema()`, `has_command()`, `parse_call_args()`, plus an
`available` property.

**Rationale:** A protocol (structural subtyping) rather than an abstract
base class allows groups to be implemented independently without
inheritance coupling.  The method set covers the four operations needed
by the MCP tools:

- `search()` for `search`
- `explain()` for `explain`
- `schema()` for `schema`
- `has_command()` + `parse_call_args()` for `call`

The `available` property (default `True`) allows groups like `supervisor`
to indicate they are unavailable on certain installations.

Each group implements these methods according to its data source
semantics.  The `GroupRegistry` dispatches to groups without knowing
their internals.

**Alternative considered:** Abstract base class with shared
implementation.  Rejected because the three groups have fundamentally
different data sources and don't share meaningful implementation.

## D032: Effect Type Extensions for Multi-Source Architecture

**Decision:** Extend the effect/continuation pattern (D002) with new
effect types for each group:

- `ServiceCall` (existing) for `services` group
- `HassCommand` (new) for `hass` group
- `SupervisorCall` (new) for `supervisor` group

Each effect type has a corresponding continuation type and result type.

**Rationale:** The sans-IO architecture requires explicit effect types
for each kind of I/O.  Each group's commands invoke different HA
subsystems:

- Services: `hass.services.async_call()`
- Hass commands: WebSocket handler invocation via internal adapter
- Supervisor: HTTP calls to Supervisor API via `HassIO.send_command()`

Separate effect types maintain the clean separation between pure protocol
logic and I/O execution.

**Alternative considered:** Generic `ExecuteCommand` effect with group
discriminator.  Rejected because it would push group-specific logic into
the effect handler, violating the separation of concerns.
