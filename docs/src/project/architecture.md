# Architecture

## Layer Design

```mermaid
block-beta
    columns 1
    block:deploy["Deployment Layer"]
        d1["custom_components/hamster/<br/>HACS shim — thin re-exports + HA data files"]
    end
    block:app["Application Layer"]
        a1["hamster.component<br/>HA integration — config flow, views, effect dispatch"]
    end
    block:integration["Integration Layer"]
        i1["hamster.mcp._io<br/>aiohttp Streamable HTTP transport adapter"]
    end
    block:core["Core Layer"]
        c1["hamster.mcp._core<br/>sans-IO MCP protocol + tool generation<br/>No I/O — no global state"]
    end

    d1 --> a1
    a1 --> i1
    i1 --> c1
```

See [Data Flow](data-flow.md) for sequence diagrams showing how MCP requests
flow through each layer.

## Package Layout

```text
hamster/
├── src/
│   └── hamster/
│       ├── __init__.py
│       ├── mcp/                          # MCP protocol submodule
│       │   ├── __init__.py               # Public API re-exports
│       │   ├── _core/                    # Sans-IO protocol core
│       │   │   ├── __init__.py
│       │   │   ├── events.py             # Protocol events + tool effect/continuation types
│       │   │   ├── session.py            # Server session + state machine
│       │   │   ├── jsonrpc.py            # JSON-RPC 2.0 parsing/building
│       │   │   ├── tools.py              # Tool generation, call_tool(), resume()
│       │   │   └── types.py              # MCP data types (Tool, Content, etc.)
│       │   ├── _io/                      # I/O adapters
│       │   │   ├── __init__.py
│       │   │   └── aiohttp.py            # aiohttp Streamable HTTP transport
│       │   └── _tests/
│       │       └── ...
│       └── component/                    # HA custom component
│           ├── __init__.py               # async_setup_entry, async_unload_entry
│           ├── config_flow.py            # Config + options flows
│           ├── const.py                  # DOMAIN, defaults
│           ├── http.py                   # HomeAssistantView + MCPHandler + effect dispatch
│           └── _tests/
│               └── ...
├── custom_components/
│   └── hamster/                          # HACS deployment shim
│       ├── __init__.py                   # Re-exports from hamster.component
│       ├── config_flow.py                # Re-exports
│       ├── manifest.json
│       ├── strings.json
│       └── translations/en.json
├── docs/
│   ├── mkdocs.yml
│   └── src/
├── hacs.json
├── brand/icon.png
├── pyproject.toml
├── mise.toml
├── .pre-commit-config.yaml
├── AGENTS.md
├── README.md
├── LICENSE-MIT
└── LICENSE-APACHE
```

## Module Descriptions

| Module | Layer | Purpose |
| --- | --- | --- |
| `hamster.mcp._core.types` | Core | MCP data types: `Tool`, `Content`, `ServerInfo`, `ServerCapabilities` |
| `hamster.mcp._core.jsonrpc` | Core | JSON-RPC 2.0 message parsing and response building |
| `hamster.mcp._core.events` | Core | Protocol events (`InitializeRequested`, `ToolCallRequested`, etc.) and tool effect/continuation types (`Done`, `ServiceCall`, `FormatServiceResponse`) |
| `hamster.mcp._core.session` | Core | `MCPServerSession` --- sans-IO session with state machine |
| `hamster.mcp._core.tools` | Core | Pure tool generation (`services_to_mcp_tools`), `call_tool()`, `resume()` |
| `hamster.mcp._io.aiohttp` | Integration | `AiohttpMCPTransport` --- bridges aiohttp requests to `MCPServerSession` |
| `hamster.component` | Application | HA integration entry point (`async_setup_entry`, `async_unload_entry`) |
| `hamster.component.config_flow` | Application | Config flow (setup) + options flow (tristate control) |
| `hamster.component.http` | Application | `HamsterMCPView` --- `HomeAssistantView` subclass, wires transport + HA auth. `HamsterMCPHandler` --- implements `MCPHandler`, runs effect dispatch loop. |
| `hamster.component.const` | Application | Domain constant, defaults |
| `custom_components/hamster/` | Deployment | HACS shim --- thin re-exports so HA can discover the integration |

## Handler Protocol

The I/O transport must delegate application-specific work (listing tools,
executing tool calls) to the component layer.
The transport is kept HA-independent for testability, so it delegates via the
`MCPHandler` protocol rather than calling HA APIs directly.

```mermaid
flowchart TB
    subgraph component["hamster.component"]
        view["HamsterMCPView\n(HomeAssistantView)"]
        handler["HamsterMCPHandler"]
        dispatch["Effect / continuation\ndispatch loop"]
    end

    subgraph io["hamster.mcp._io"]
        transport["AiohttpMCPTransport"]
        protocol["«Protocol» MCPHandler\nhandle_tool_list()\nhandle_tool_call()"]
    end

    subgraph core["hamster.mcp._core"]
        session["MCPServerSession\n(sans-IO state machine)"]
    end

    view --> transport
    transport --> session
    transport -.->|delegates| protocol
    handler -.->|implements| protocol
    handler --> dispatch
```

Defined in `hamster.mcp._io`, implemented by `hamster.component`:

```python
class MCPHandler(Protocol):
    async def handle_tool_list(self) -> list[Tool]: ...
    async def handle_tool_call(
        self, name: str, arguments: dict[str, object],
    ) -> CallToolResult: ...
```

### Responsibility Split

The transport handles MCP protocol concerns internally and delegates
application concerns to the handler:

| Concern | Owner | Layer |
| --- | --- | --- |
| HTTP header validation | Transport | `_io` |
| JSON body parsing | Transport | `_io` |
| JSON-RPC framing | Session | `_core` |
| Session state machine | Session | `_core` |
| Session ID lookup | Transport | `_io` |
| Initialize handshake | Transport | `_io` |
| Tool listing | **Handler** | `component` |
| Tool execution | **Handler** | `component` |

### Two-Level Dispatch

Protocol events and tool effects are dispatched at different layers:

1. **Protocol events** --- `MCPServerSession.receive_message()` emits events
   (`InitializeRequested`, `ToolListRequested`, `ToolCallRequested`).
   The transport handles protocol events internally and delegates
   application events to the handler via `MCPHandler`.

2. **Tool effects** --- `handle_tool_call()` uses the effect/continuation
   pattern internally (see [Principles](principles.md)).
   `call_tool()` returns a `ToolEffect`, the handler runs a dispatch loop,
   and `resume()` produces the next effect until `Done`.

The transport never sees tool effects.
The handler never sees protocol events.

## Distribution

The project produces two artifacts from a single repository:

| Artifact | Mechanism | Contains |
| --- | --- | --- |
| `hamster` on PyPI | `pip install hamster` | `hamster.mcp` + `hamster.component` (the library) |
| `custom_components/hamster/` via HACS | HACS git clone | Thin shim files + `manifest.json` + UI strings |

The `manifest.json` declares `"requirements": ["hamster>=0.1.0"]`, so when HA
loads the custom component it automatically pip-installs the library.

## Why a Custom Component

The decision to build as a custom component (not an external server or add-on)
was driven by one critical capability: only code running inside HA can access
`hass.services.async_services()`, which returns service schemas with field
definitions.

The external REST API (`/api/services`) lists services but does **not** include
schemas.
The WebSocket API may include some schema info but is less complete.

Additional benefits:

- Built-in HA auth via `requires_auth=True` on `HomeAssistantView`
- Direct access to entity/device/area registries
- Access to `async_should_expose()` for respecting HA's entity exposure settings
- Single deployment (no separate server process)
- No network hop for API calls

Trade-offs accepted:

- HA restart required for code changes (slower dev iteration)
- Must use HA's Python version and not conflict with HA's pinned dependencies
- Runs in HA's event loop (bugs could impact HA stability)

## Existing HA MCP Landscape

| Project | Type | Tools | Discovery | Auth |
| --- | --- | --- | --- | --- |
| `mcp_server` (official) | Core component | ~20 | Dynamic via intents | OAuth |
| `ha-mcp` (community) | Standalone/add-on | 95+ | Static | Token |
| `hass-mcp-server` (ganhammar) | Custom component | 21 | Static | OAuth |
| `mcp-assist` | Custom component | 11 | Index pattern | IP whitelist |
| **Hamster** | Custom component | All HA services | **Dynamic from schemas** | HA built-in |

Hamster's unique position: dynamic tool generation from service schemas, built-in
HA auth, full admin access, tristate tool control.
No existing project combines all of these.
