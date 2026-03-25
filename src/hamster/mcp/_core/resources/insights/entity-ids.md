# Entity IDs

Conventions for Home Assistant entity identifiers, how to discover them, and
common pitfalls.

## Format

Every entity in Home Assistant has an ID of the form:

```text
<domain>.<object_id>
```

- **domain** --- The integration or entity type (e.g. `light`, `switch`,
  `sensor`, `binary_sensor`, `climate`, `cover`, `media_player`).
- **object_id** --- A slug identifying the specific entity, typically derived
  from the device or entity name (e.g. `living_room_ceiling`,
  `front_door_lock`).

Examples:

- `light.living_room`
- `sensor.outdoor_temperature`
- `binary_sensor.front_door`
- `climate.hvac`
- `cover.garage_door`
- `media_player.living_room_speaker`

## Naming Conventions

Object IDs are **slugified** from the entity or device name:

- Lowercase
- Spaces and special characters replaced with underscores
- Consecutive underscores collapsed
- Leading/trailing underscores stripped

A device named "Living Room Ceiling Light" typically produces the entity ID
`light.living_room_ceiling_light`.

## Discovery

### Entity Registry

The most reliable way to discover entity IDs is via the entity registry:

```json
{
  "path": "hass/config/entity_registry/list",
  "arguments": {}
}
```

This returns all registered entities with fields including:

- `entity_id` --- The canonical ID (e.g. `light.living_room`)
- `name` --- User-assigned friendly name (may differ from the default)
- `original_name` --- The name provided by the integration
- `platform` --- The integration that created it (e.g. `hue`, `zwave_js`)
- `device_id` --- The device this entity belongs to (if any)
- `area_id` --- The area this entity is assigned to (if any)
- `labels` --- Labels applied to this entity
- `disabled_by` --- If set, the entity is disabled
- `hidden_by` --- If set, the entity is hidden from the UI

### Current States

To see all entities with their current state and attributes:

```json
{
  "path": "hass/get_states",
  "arguments": {}
}
```

Each entry includes:

- `entity_id`
- `state` --- Current state value (e.g. `"on"`, `"off"`, `"23.5"`,
  `"unavailable"`)
- `attributes` --- Domain-specific attributes (e.g. `brightness`,
  `temperature`, `friendly_name`)
- `last_changed` --- When the state last changed
- `last_updated` --- When the state was last updated

## Special States

All entities can have these special state values:

- `unavailable` --- The entity exists but cannot be reached
- `unknown` --- The entity exists but its state is not yet known

These are not errors; they indicate the entity's current availability.

## Entity Categories

Entities have an optional `entity_category` that indicates their role:

- **(none)** --- Primary entity, shown in the UI by default
- `config` --- Configuration entity (e.g. a setting toggle)
- `diagnostic` --- Diagnostic entity (e.g. signal strength, firmware version)

When looking for entities to control, focus on entities without a category.
Diagnostic and config entities are typically not targets for service calls.

## Common Domains

| Domain            | Description                 | Typical services                    |
|------------------ |---------------------------- |------------------------------------ |
| `light`           | Lights                      | `turn_on`, `turn_off`, `toggle`     |
| `switch`          | Switches                    | `turn_on`, `turn_off`, `toggle`     |
| `sensor`          | Sensors (read-only)         | (none --- sensors have no services) |
| `binary_sensor`   | On/off sensors (read-only)  | (none)                              |
| `climate`         | Thermostats, HVAC           | `set_temperature`, `set_hvac_mode`  |
| `cover`           | Blinds, garage doors        | `open_cover`, `close_cover`         |
| `media_player`    | Media devices               | `play_media`, `volume_set`          |
| `fan`             | Fans                        | `turn_on`, `set_percentage`         |
| `lock`            | Locks                       | `lock`, `unlock`                    |
| `automation`      | Automations                 | `trigger`, `turn_on`, `turn_off`    |
| `script`          | Scripts                     | `turn_on` (or call by entity ID)    |
| `scene`           | Scenes                      | `turn_on`                           |
| `input_boolean`   | Virtual toggles             | `turn_on`, `turn_off`, `toggle`     |
| `input_number`    | Virtual number inputs       | `set_value`                         |
| `input_select`    | Virtual dropdowns           | `select_option`                     |
| `input_text`      | Virtual text inputs         | `set_value`                         |
| `input_datetime`  | Virtual date/time inputs    | `set_datetime`                      |

## Resolving Friendly Names

Users typically refer to entities by their friendly name (e.g. "Living Room
Light") rather than by entity ID.  To resolve a friendly name to an entity ID:

1. Query the entity registry or states list
2. Match on `attributes.friendly_name` (from states) or `name` /
   `original_name` (from the registry)
3. Use the corresponding `entity_id`

Friendly names are not guaranteed to be unique.  When ambiguous, use the entity
registry to disambiguate by area, device, or platform.
