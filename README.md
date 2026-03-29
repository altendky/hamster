# <img src="custom_components/hamster_mcp/brand/icon.svg" alt="Hamster icon" width="64"> Hamster MCP

[![HACS: Custom](https://img.shields.io/badge/HACS-Custom-orange)](https://hacs.xyz/)
[![HA: 2025.2+](https://img.shields.io/badge/HA-2025.2+-blue)](https://www.home-assistant.io/)
[![License: MIT OR Apache-2.0](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-blue)](LICENSE-MIT)
[![CI](https://github.com/altendky/hamster-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/altendky/hamster-mcp/actions/workflows/ci.yml)

Home Assistant MCP Server — exposes HA's full capabilities via the
[Model Context Protocol](https://modelcontextprotocol.io/).

## What Is This?

Hamster MCP is a Home Assistant custom component that runs an
[MCP](https://modelcontextprotocol.io/) server inside your HA instance.
It lets AI assistants and other MCP clients — such as Claude Desktop,
OpenCode, Cursor, or any tool that speaks the Model Context Protocol — interact
with your smart home: query states, call services, browse registries,
debug automations, and more.

Hamster MCP discovers all available services and their schemas automatically
at runtime — no static tool definitions to maintain.

The MCP endpoint is served by Home Assistant itself, so it is reachable
wherever your HA instance is.
If your HA is only accessible on your local network, MCP clients on
that network can connect.
If your HA is exposed externally (via Nabu Casa, a reverse proxy, etc.),
remote MCP clients such as Claude.ai and ChatGPT can connect as well.

## Status

**Beta.** Functional and ready for testing and feedback.

## Key Features

- **Dynamic tool generation** from `hass.services.async_services()` — no
  static tool definitions
- **Built-in HA authentication** via `HomeAssistantView` — no separate
  tokens or OAuth setup
- **Sans-IO protocol core** — fully testable without mocking
- **Three command groups** covering HA's full surface:
  - **Services** — all HA service actions (lights, climate, automations,
    media, notifications, etc.), dynamically discovered at runtime
  - **Hass** — WebSocket API commands for states, entity/device/area
    registries, templates, and config management
  - **Supervisor** — system-level access to logs, host info, add-ons,
    backups, and networking (available on HA OS / Supervised installs)

## Requirements

- Home Assistant 2025.2 or later
- Python 3.13 or later

## Installation

### HACS (Recommended)

1. Install [HACS](https://hacs.xyz/) if you haven't already.
2. Add this repository as a [custom repository](https://hacs.xyz/docs/faq/custom_repositories/) in HACS:
   - Go to HACS → Integrations → Menu (three dots) → Custom repositories
   - URL: `https://github.com/altendky/hamster-mcp`
   - Category: Integration
3. Search for "Hamster MCP" in HACS and install it.
4. Restart Home Assistant.
5. Add the integration via [Settings → Devices & Services](https://my.home-assistant.io/redirect/integrations/) → Add Integration → Hamster MCP.

### Manual Installation

1. Copy the `custom_components/hamster_mcp` directory to your Home Assistant
   `config/custom_components/` directory.
2. Restart Home Assistant.
3. Add the integration via [Settings → Devices & Services](https://my.home-assistant.io/redirect/integrations/) → Add Integration → Hamster MCP.

## Usage

Point your MCP client at your Home Assistant instance with these settings:

- **URL:** `https://<your-ha-host>/api/hamster_mcp`
- **Transport:** Streamable HTTP
- **Authentication:** MCP clients that support OAuth (such as OpenCode)
  will prompt you to log in through Home Assistant automatically.
  For clients that require a static token, create a
  [Long-Lived Access Token](https://www.home-assistant.io/docs/authentication/#your-account-profile)
  in your HA user profile and provide it as a Bearer token.

### Options

The integration works out of the box with no configuration.
Optional settings are available under the integration's **Configure** button:

- **Auto-fetch docs on startup** — automatically fetch WebSocket API
  documentation for richer tool descriptions (default: on)
- **Docs URL template** — URL for fetching WebSocket API docs; use
  `{ref}` as placeholder for the git ref
- **Git ref for docs** — branch, tag, or commit to fetch docs from
  (default: `master`)

## Documentation

See [docs/src/project/index.md](docs/src/project/index.md) for architecture,
principles, and design decisions.

## License

Licensed under either of:

- Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE))
- MIT License ([LICENSE-MIT](LICENSE-MIT))

at your option.
