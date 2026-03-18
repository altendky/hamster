# Open Questions

Pending design decisions to resolve during implementation.

## ~~Q001: `_io` Subpackage Naming~~ --- RESOLVED

Keeping `_io`.
Can revisit later if the stdlib shadow causes real problems.

## ~~Q002: MCP Tool Name Format~~ --- RESOLVED

Moved to [Decisions](decisions.md) as D012.

## ~~Q003: JSON-RPC Batch Requests~~ --- DEFERRED

Deferred.
No known MCP client sends batch requests.
The spec does not require servers to support them.
Can add later if a client needs it.

## ~~Q004: Session Cleanup Strategy~~ --- RESOLVED

Moved to [Decisions](decisions.md) as D015.

## Q005: Options Flow UX for Tristate Control

**Question:** How should the options flow present hundreds of HA services for
enable/disable control?

**Context:** A typical HA instance has 200+ services.
Showing all of them in a single form is unusable.
Options: group by domain, search/filter, only show non-default (overridden)
services, multi-step flow.

**No strong leaning yet.**

## Q006: HA Service Call Error Mapping

**Question:** How should HA service call exceptions be mapped to MCP tool error
content?

**Context:** HA service calls can raise `ServiceNotFound`,
`ServiceValidationError`, `HomeAssistantError`, or generic exceptions.
MCP tool errors are `{"content": [{"type": "text", "text": "..."}], "isError": true}`.
The error message should be useful to the LLM.

**Leaning toward:** Catch known exception types, format human-readable messages.
Include the exception class name and message.

## ~~Q007: Testing the HA Component~~ --- RESOLVED

Moved to [Decisions](decisions.md) as D013.

## ~~Q008: Tests in Wheel~~ --- RESOLVED

Moved to [Decisions](decisions.md) as D014.
