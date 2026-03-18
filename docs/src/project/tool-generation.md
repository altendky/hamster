# Tool Generation

Placeholder --- to be written during Phase 5 implementation.

## Overview

Hamster generates MCP tools at runtime from `hass.services.async_services()`.
This function returns all registered HA services with their field schemas,
including selector types, descriptions, and required/optional markers.

## Selector to JSON Schema Mapping

HA uses "selectors" to describe field types.
These are mapped to JSON Schema types for MCP tool `inputSchema` definitions.

| HA Selector | JSON Schema |
| --- | --- |
| `entity` | `{"type": "string"}` (entity_id) |
| `number` | `{"type": "number", "minimum": ..., "maximum": ...}` |
| `select` | `{"type": "string", "enum": [...]}` |
| `boolean` | `{"type": "boolean"}` |
| `text` | `{"type": "string"}` |
| `target` | Object with entity_id/device_id/area_id properties |
| `object` | `{"type": "object"}` |
| `color_rgb` | Array of 3 integers |
| ... | ... |

## Target Handling

HA services use a `target` concept for specifying which entities, devices, or
areas to act on.
This needs special handling in the MCP tool schema to be usable by LLMs.
