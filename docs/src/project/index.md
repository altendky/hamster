# Hamster

A Home Assistant custom component that exposes HA's full capabilities via the
Model Context Protocol (MCP).
The project emphasizes testability through sans-IO design principles and
runtime dynamic tool generation.

## What Makes Hamster Different

Every existing HA MCP project defines tools statically in code.
Hamster generates them at runtime from `hass.services.async_services()`, which
returns service schemas including field definitions, descriptions, and required
parameters.
No existing project does this.

Running as a custom component inside HA gives direct access to:

- Service schemas with field definitions (not available via REST API)
- Built-in HA authentication (`requires_auth=True` on `HomeAssistantView`)
- Entity, device, and area registries
- Exposure settings (`async_should_expose()`)
- Supervisor, HACS, and other internal APIs (when available)

## Documentation

### Core Design

- [Principles](principles.md) --- Sans-IO philosophy, testability goals, import rules
- [Architecture](architecture.md) --- Layer design, package structure, module layout
- [Data Flow](data-flow.md) --- MCP protocol flow, effect/continuation dispatch

### Features

- [MCP Protocol](mcp-protocol.md) --- Streamable HTTP transport, JSON-RPC, session lifecycle
- [Tool Generation](tool-generation.md) --- Dynamic tools from HA service schemas
- [Tristate Control](tristate-control.md) --- Enabled/Dynamic/Disabled service model
- [Configuration](configuration.md) --- Config flow, options flow

### Infrastructure

- [CI](ci.md) --- GitHub Actions, coverage, validation
- [Development](development.md) --- Local development, pre-commit hooks, testing
- [Release](release.md) --- PyPI + HACS distribution

### Project Management

- [Decisions](decisions.md) --- Resolved design decisions
- [Open Questions](open-questions.md) --- Pending decisions, deferred items
