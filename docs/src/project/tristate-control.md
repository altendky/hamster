# Tristate Control

Placeholder --- to be written during Phase 6 implementation.

## Overview

Each HA service has a tristate exposure setting:

| State | Behavior |
| --- | --- |
| **Enabled** | Always exposed as an MCP tool |
| **Dynamic** | Exposed based on runtime discovery (the default) |
| **Disabled** | Never exposed |

## Configuration

Tristate settings are stored in the config entry's options and managed through
the HA options flow UI.

## Use Cases

- **Disable dangerous services** like `homeassistant.restart`,
  `homeassistant.stop`
- **Force-enable niche services** that might be filtered by default
- **Let most services auto-discover** without manual configuration
