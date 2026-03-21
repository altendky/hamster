# Tool Generation

## Overview

Hamster uses a **meta-tool pattern** (modeled after
[onshape-mcp](https://github.com/altendky/onshape-mcp)) instead of generating
one MCP tool per HA service.  Four fixed tools let the LLM discover and invoke
any HA service dynamically (see
[D017](decisions.md#d017-meta-tool-pattern-over-per-service-tool-generation)).

| Tool | Purpose | I/O? |
| --- | --- | --- |
| `hamster_services_search` | Find services by keyword/domain | Pure |
| `hamster_services_explain` | Full field/target/selector details for a service | Pure |
| `hamster_services_call` | Invoke a service with target + data | `ServiceCall` effect |
| `hamster_services_schema` | Describe what a selector type expects | Pure |

## ServiceIndex

The `ServiceIndex` is built from the output of
`homeassistant.helpers.service.async_get_all_descriptions()`.  This function
returns service descriptions with fields, selectors, target configuration, and
response metadata --- the same data the HA frontend uses.

The index is built once at integration load time and rebuilt when
`EVENT_SERVICE_REGISTERED` or `EVENT_SERVICE_REMOVED` fires.  Construction is
pure (no I/O); only the `async_get_all_descriptions()` call is async.

### Search

`search(query, *, domain=None)` performs case-insensitive substring matching
against pre-computed search text (domain, service name, description, field
names).  Returns compact summaries of matching services.

### Explain

`explain(domain, service)` returns the raw HA service description for a single
service: name, description, target config, and all fields with their selectors
as HA defines them.  No translation --- selectors are shown in their native
format.  The LLM uses `hamster_services_schema` to look up what each selector
type means.

## Selector Descriptions

HA uses [selectors](https://www.home-assistant.io/docs/blueprint/selectors/)
to describe field input types.  There are 40 registered selector types.
Rather than translating selectors to JSON Schema (as the previous per-service
tool design required), the meta-tool pattern exposes them as-is via `explain`
and documents their expected input formats via `schema`.

The `SELECTOR_DESCRIPTIONS` mapping in `_core/tools.py` provides a
human-readable description of each selector type's expected input format.
Examples:

| Selector | Expected input |
| --- | --- |
| `boolean` | `true` or `false` |
| `number` | Numeric value (may have min/max/step from selector config) |
| `text` | String value |
| `select` | One of the options listed in selector config |
| `duration` | Dict with optional keys: `days`, `hours`, `minutes`, `seconds`, `milliseconds` |
| `color_rgb` | Array of 3 integers `[R, G, B]`, each 0--255 |
| `entity` | Entity ID string (e.g. `light.living_room`) |
| `target` | Dict with optional keys: `entity_id`, `device_id`, `area_id`, `floor_id`, `label_id` |
| `location` | Dict with `latitude`, `longitude` (numbers), optional `radius` |
| `date` | String `YYYY-MM-DD` |
| `time` | String `HH:MM:SS` |
| `datetime` | String `YYYY-MM-DD HH:MM:SS` |
| `object` | Arbitrary JSON object |
| `template` | Jinja2 template string |

## Target Handling

HA services use a `target` concept for specifying which entities, devices,
areas, floors, or labels to act on.  The `hamster_services_call` tool accepts
`target` as a separate parameter from `data`
(see [D019](decisions.md#d019-separate-target-and-data-in-service-calls)).

HA accepts 5 target property keys (all optional, each a string or array of
strings):

| Key | Description |
| --- | --- |
| `entity_id` | Entity IDs |
| `device_id` | Device registry IDs |
| `area_id` | Area registry IDs |
| `floor_id` | Floor registry IDs |
| `label_id` | Label registry IDs |

Resolution hierarchy: `label_id` → entities/devices/areas; `floor_id` → areas
→ devices → entities; `area_id` → devices → entities; `device_id` → entities.

## Typical LLM Interaction

```text
LLM: hamster_services_search(query="light")
→ light.turn_on — Turn on a light (has target)
  light.turn_off — Turn off a light (has target)
  light.toggle — Toggle a light (has target)

LLM: hamster_services_explain(domain="light", service="turn_on")
→ name: Turn on
  description: Turn on a light.
  target: {entity: {domain: light}}
  fields:
    transition: {selector: {number: {min: 0, max: 300, unit: seconds}}}
    brightness_pct: {selector: {number: {min: 0, max: 100, unit: %}}}
    color_temp_kelvin: {selector: {color_temp: {unit: kelvin, ...}}}
    rgb_color: {selector: {color_rgb: }}
    ...

LLM: hamster_services_call(
    domain="light", service="turn_on",
    target={"entity_id": ["light.living_room"]},
    data={"brightness_pct": 75})
→ Success
```
