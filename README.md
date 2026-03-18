# Hamster

Home Assistant MCP Server --- exposes HA's full capabilities via the
[Model Context Protocol](https://modelcontextprotocol.io/).

## What Is This?

Hamster is a Home Assistant custom component that dynamically generates MCP
tools from HA's service registry at runtime.
Unlike other HA MCP projects that define tools statically, Hamster discovers
all available services and their schemas automatically.

## Status

**Pre-alpha.** Not yet functional.

## Key Features (Planned)

- **Dynamic tool generation** from `hass.services.async_services()` --- no
  static tool definitions
- **Built-in HA authentication** via `HomeAssistantView` --- no separate
  tokens or OAuth setup
- **Tristate tool control** --- enable, disable, or auto-discover each service
- **Sans-IO protocol core** --- fully testable without mocking
- **Full admin access** --- services, states, registries, automations,
  dashboards, supervisor (when available)

## Documentation

See [docs/src/project/index.md](docs/src/project/index.md) for architecture,
principles, and design decisions.

## License

Licensed under either of:

- Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE))
- MIT License ([LICENSE-MIT](LICENSE-MIT))

at your option.
