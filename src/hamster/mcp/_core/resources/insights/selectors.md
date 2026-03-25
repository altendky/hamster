# Selectors

Selector types define the expected value format for service call fields.  Use
`schema` with a service path to see the selectors for its fields, or
`schema` with `services/selector/<type>` to get details on a specific selector
type.

## Overview

When you `explain` or `schema` a service, each field includes a selector that
describes what kind of value it expects.  Selectors are the bridge between
the HA UI (which renders appropriate input widgets) and the API (which expects
correctly typed values).

## Common Selector Types

### Boolean

```json
{"selector": {"boolean": {}}}
```

Expects: `true` or `false`

### Number

```json
{"selector": {"number": {"min": 0, "max": 255, "step": 1, "mode": "slider"}}}
```

Expects: A numeric value within the specified range.  If `step` is `1` and
no fractional bounds exist, an integer is expected.

### Text

```json
{"selector": {"text": {"multiline": false}}}
```

Expects: A string value.

### Select (Dropdown)

```json
{"selector": {"select": {"options": ["option_a", "option_b", "option_c"]}}}
```

Expects: One of the listed option values (string).

Options can also be objects with `value` and `label` keys; use the `value`
field in the API call.

### Entity

```json
{"selector": {"entity": {"domain": "light", "multiple": true}}}
```

Expects: An entity ID string (or array if `multiple` is true).  The `domain`
field constrains which entity domains are valid.

Note: Entity selectors in `data` fields are different from the `target`
parameter.  Some services use entity selectors in data fields for
secondary entity references (e.g., "play media from this source entity").

### Device

```json
{"selector": {"device": {"integration": "hue"}}}
```

Expects: A device ID string.  The `integration` field constrains which
integrations are valid.

### Area

```json
{"selector": {"area": {"entity": {"domain": "light"}}}}
```

Expects: An area ID string.  Optional filters constrain which areas are
shown based on the entities or devices they contain.

### Target

```json
{"selector": {"target": {"entity": {"domain": "light"}}}}
```

Expects: A target object (see the Service Targeting insight document).
This is the most common way services declare their targeting requirements.

### Color Temperature

```json
{"selector": {"color_temp": {"min_mireds": 153, "max_mireds": 500}}}
```

Expects: An integer value in mireds (micro reciprocal degrees).  Lower values
are cooler (bluer), higher values are warmer (yellower).

### Color (RGB)

```json
{"selector": {"color_rgb": {}}}
```

Expects: An array of three integers `[R, G, B]`, each 0--255.

### Date / Time / DateTime

```json
{"selector": {"date": {}}}
{"selector": {"time": {}}}
{"selector": {"datetime": {}}}
```

Expects:

- `date`: `"YYYY-MM-DD"` string
- `time`: `"HH:MM:SS"` string
- `datetime`: `"YYYY-MM-DD HH:MM:SS"` string

### Duration

```json
{"selector": {"duration": {}}}
```

Expects: An object with optional `hours`, `minutes`, `seconds` keys:

```json
{"hours": 1, "minutes": 30, "seconds": 0}
```

### Object

```json
{"selector": {"object": {}}}
```

Expects: Any JSON object.  Used for free-form structured data.

### Template

```json
{"selector": {"template": {}}}
```

Expects: A Jinja2 template string that HA will render at execution time.

Example: `"{{ states('sensor.temperature') | float > 25 }}"`

## Using Schema to Explore Selectors

To see all details for a specific selector type:

```json
{
  "path": "services/selector/duration"
}
```

To see the field selectors for a specific service:

```json
{
  "path": "services/climate.set_temperature"
}
```

The schema output shows each field's selector type, constraints (min/max,
options, domain filters), and whether the field is required.
