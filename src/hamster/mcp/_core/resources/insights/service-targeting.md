# Service Targeting

How to specify which entities, devices, or areas a service call should act on.

## Overview

Service calls in Home Assistant use a **target** parameter to specify what the
service should act on.  Targets can reference entities directly by ID, or
indirectly via devices, areas, floors, or labels.  The HA core expands indirect
references at call time: an area target resolves to all entities in that area
that the service supports.

## Target Structure

The `target` object is passed in the `arguments.target` field of a `call` tool
invocation.  All fields are optional; combine them to narrow or broaden scope.

```json
{
  "target": {
    "entity_id": ["light.living_room", "light.kitchen"],
    "device_id": ["abc123"],
    "area_id": ["living_room"],
    "floor_id": ["ground_floor"],
    "label_id": ["downstairs"]
  }
}
```

### Fields

| Field       | Type                 | Description                                     |
| ----------- | -------------------- | ----------------------------------------------- |
| `entity_id` | `string \| [string]` | One or more entity IDs                          |
| `device_id` | `string \| [string]` | One or more device IDs (opaque hex strings)     |
| `area_id`   | `string \| [string]` | One or more area slugs (e.g. `"living_room"`)   |
| `floor_id`  | `string \| [string]` | One or more floor slugs (e.g. `"ground_floor"`) |
| `label_id`  | `string \| [string]` | One or more label slugs                         |

Each field accepts either a single string or an array of strings.

### Resolution Order

When multiple target fields are provided, HA resolves them with union semantics:
all entities matching **any** of the target fields are included.  Within each
indirect field (area, floor, label), the service's supported entity domain
filters which entities are selected.

For example, calling `light.turn_on` with `"area_id": "kitchen"` will only
affect `light.*` entities in the kitchen area, not `switch.*` or `sensor.*`
entities.

## Common Patterns

### Single Entity

```json
{
  "path": "services/light.turn_on",
  "arguments": {
    "target": {"entity_id": "light.living_room"},
    "data": {"brightness_pct": 80}
  }
}
```

### All Lights in an Area

```json
{
  "path": "services/light.turn_off",
  "arguments": {
    "target": {"area_id": "bedroom"}
  }
}
```

### Multiple Entities

```json
{
  "path": "services/light.turn_on",
  "arguments": {
    "target": {"entity_id": ["light.living_room", "light.hallway"]},
    "data": {"color_name": "warm_white"}
  }
}
```

### By Label

```json
{
  "path": "services/light.turn_off",
  "arguments": {
    "target": {"label_id": "vacation_mode"}
  }
}
```

## Discovering Valid Targets

Use the meta-tools to discover what can be targeted:

1. **Entity IDs** --- `call` with path `hass/config/entity_registry/list`
   returns the full entity registry.  Filter by `platform` or `area_id`.
2. **Device IDs** --- `call` with path `hass/config/device_registry/list`
   returns all devices with their `id`, `name`, and `area_id`.
3. **Area IDs** --- `call` with path `hass/config/area_registry/list`
   returns all areas with their `area_id` and `name`.
4. **Floor IDs** --- `call` with path `hass/config/floor_registry/list`
   returns all floors.
5. **Label IDs** --- `call` with path `hass/config/label_registry/list`
   returns all labels.
6. **Entity state** --- `call` with path `hass/get_states` returns all
   current entity states.

## Service-Specific Targeting

Some services have targeting constraints declared in their description.  Use
`explain` to see whether a service supports entity, device, or area targeting,
and which entity domains or integrations are accepted.

```text
explain services/light.turn_on
```

The output includes a **Target** section showing:

- Supported entity domains (e.g. `light`)
- Supported integrations
- Whether the service accepts entity, device, and/or area targets

## Data vs Target

- **`target`** specifies *what* to act on (entities, devices, areas).
- **`data`** specifies *how* to act (brightness, color, temperature, etc.).

These are separate fields in the `arguments` object:

```json
{
  "arguments": {
    "target": {"entity_id": "climate.thermostat"},
    "data": {"temperature": 22, "hvac_mode": "heat"}
  }
}
```

Do not mix target fields into `data` or vice versa.
