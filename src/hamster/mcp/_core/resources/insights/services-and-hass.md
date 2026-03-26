# Services and Hass Groups

How the `services` and `hass` groups relate, and when to use each for
calling Home Assistant services.

## Overview

Home Assistant services (actions like `light.turn_on`, `climate.set_temperature`)
are accessible through two different tool groups:

- **`services` group** --- Individual entries per service with rich metadata
  (field descriptions, selector types, target specifications).
- **`hass` group** --- Generic WebSocket commands including `call_service`,
  which can invoke any service but with sparse metadata.

Both groups can accomplish the same service calls.  They differ in the
metadata they expose and the granularity of their entries.

## When to Use Each

### Prefer `services/` paths

Use `services/<domain>.<service>` for most service calls:

```json
{
  "path": "services/light.turn_on",
  "arguments": {
    "target": {"entity_id": "light.living_room"},
    "data": {"brightness_pct": 80}
  }
}
```

The services group provides:

- **Per-service `explain` output** with field descriptions and selector types
- **Per-service `schema` output** showing required/optional fields and constraints
- **`search` support** to find services by keyword across all domains
- **Target specifications** showing which entity domains and integrations a
  service supports

### Fall back to `hass/call_service`

Use `hass/call_service` when:

- The services group is disabled in the integration configuration
- You need to call a service that is not yet reflected in the services index
  (e.g., immediately after a new integration loads)

```json
{
  "path": "hass/call_service",
  "arguments": {
    "domain": "light",
    "service": "turn_on",
    "service_data": {"brightness_pct": 80},
    "target": {"entity_id": "light.living_room"}
  }
}
```

## Discovering Available Services

### With the services group

Use `search` with a path filter to find services:

```json
{
  "path": "services",
  "query": "turn on"
}
```

Use `explain` to see full details for a specific service:

```json
{
  "path": "services/light.turn_on"
}
```

### Without the services group

The `hass/get_services` WebSocket command lists all registered services and
their descriptions.  This command is available regardless of whether the
services group is enabled:

```json
{
  "path": "hass/get_services",
  "arguments": {}
}
```

The response includes domain, service names, and field descriptions, but
in a single bulk response rather than individual searchable entries.

## Metadata Comparison

| Capability                  | `services/` group         | `hass/call_service`       |
| --------------------------- | ------------------------- | ------------------------- |
| Per-service `explain`       | Yes                       | No (single generic entry) |
| Per-service `schema`        | Yes (with selectors)      | No                        |
| Searchable by keyword       | Yes                       | No                        |
| Target specifications       | Yes (domain, integration) | No                        |
| Field descriptions          | Yes                       | Via `hass/get_services`   |
| Can call any service        | Yes (indexed services)    | Yes                       |
