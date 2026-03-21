# Open Questions

Pending design decisions to resolve during implementation.

## ~~Q001: `_io` Subpackage Naming~~ --- RESOLVED

Keeping `_io`.
Can revisit later if the stdlib shadow causes real problems.

## ~~Q002: MCP Tool Name Format~~ --- RESOLVED

Moved to [Decisions](decisions.md) as D012.

## ~~Q003: JSON-RPC Batch Requests~~ --- RESOLVED

JSON-RPC 2.0 §6 requires servers to handle arrays of Request objects.
MCP Streamable HTTP explicitly allows batch POST bodies.  Full batch
support is included in the implementation plan (Stage 2 and Stage 5).

## ~~Q004: Session Cleanup Strategy~~ --- RESOLVED

Moved to [Decisions](decisions.md) as D015.

## ~~Q005: Options Flow UX for Tristate Control~~ --- DEFERRED

Deferred.  With the meta-tool pattern (D017), there are no per-service tools
to enable/disable.  All HA services are accessible through the 4 fixed
meta-tools.  Per-service filtering via an options flow may be revisited as a
future addition if there's a need to restrict which services the LLM can
discover or invoke.

## ~~Q006: HA Service Call Error Mapping~~ --- RESOLVED

Resolved in the implementation plan (Stage 8).  `HamsterEffectHandler`
catches `ServiceNotFound`, `ServiceValidationError`, `HomeAssistantError`,
and generic `Exception`, formatting human-readable messages for the LLM.
Each is returned as `ServiceCallResult(success=False, error=...)`, which
`resume()` turns into `Done(CallToolResult(is_error=True))`.

## ~~Q007: Testing the HA Component~~ --- RESOLVED

Moved to [Decisions](decisions.md) as D013.

## ~~Q008: Tests in Wheel~~ --- RESOLVED

Moved to [Decisions](decisions.md) as D014.

## ~~Q009: Schema Fidelity vs. LLM Clarity~~ --- RESOLVED

Resolved by the meta-tool pattern (D017, D018, D019).  With meta-tools, there
are no per-service JSON Schemas to reshape.  `explain` shows raw HA
descriptions as-is (D018).  `call` separates target and data to match HA's
`async_call` signature (D019).  The LLM sees HA's native format and uses
`schema` to understand selector types when needed.

## Q010: Origin Header Validation Strategy

**Question:** How should the server validate the `Origin` header to prevent
DNS rebinding attacks?

**Context:** The MCP Streamable HTTP spec says servers SHOULD validate the
`Origin` header.  Common approaches:

- If `Origin` is absent → allow (non-browser clients don't send it).
- If `Origin` is present → check against an allowlist or compare to the
  request's `Host` header (same-origin check).

HA already enforces authentication (`requires_auth = True`), so DNS
rebinding without a valid bearer token accomplishes nothing.  Options:

1. Add `host` to `IncomingRequest`, do same-origin checking.
2. Skip Origin validation, rely on HA auth.  Document as a known
   limitation.
3. Reject all requests that have an `Origin` header (blocks browser-based
   clients entirely).

**No strong leaning yet.**

## Q011: Accept Header and SSE Support

**Question:** How should the `Accept` header be validated, and should we
require `text/event-stream`?

**Context:** The MCP spec says clients MUST include an `Accept` header
listing both `application/json` and `text/event-stream`.  Currently the
server doesn't produce SSE (GET returns 405), so requiring
`text/event-stream` checks a client obligation that doesn't affect server
behavior.

The current plan uses a simple compatibility check: accept headers
containing `application/json`, `application/*`, or `*/*` pass.  Full
RFC 7231 content negotiation (q-values, media-range parsing) is deferred.

When SSE support lands (see Q012), this should be revisited to decide
whether to also require `text/event-stream` in the Accept header.

**Leaning toward:** Keep the simple check for now.  Revisit with SSE.

## Q012: Server-Sent Events (SSE) Support

**Question:** Should the server support SSE for server-to-client
communication?

**Context:** MCP Streamable HTTP defines a GET endpoint for clients to
open an SSE stream and receive server-initiated messages.  Without SSE,
the server cannot:

- Push `notifications/tools/list_changed` when the tool list changes
  (#11).  Clients must poll via `tools/list` to detect updates.
- Push any server-initiated requests or notifications.
- Support the `listChanged` capability in `ServerCapabilities`.

The current v1 plan intentionally returns 405 for GET requests.  The
`ServerCapabilities` serialization omits `listChanged`, honestly
advertising the limitation.

**Related decisions:**

- GET → 405 is an intentional protocol decision, not "wrong method."
  When SSE lands, GET becomes the SSE endpoint.
- Accept header validation (Q011) should be revisited with SSE.

**No strong leaning yet.**

## Q013: Canceling In-Flight Tool Calls

**Question:** Should DELETE / session expiry cancel in-flight tool calls?

**Context:** When a session is terminated (via DELETE or idle timeout)
while a `tools/call` is being executed:

- The HTTP connection is still open (the handler hasn't returned yet).
- The HA service call may be mid-execution.
- JSON-RPC requires every request with an `id` to get a response.

Current plan: let in-flight effects complete and return their response.
`build_effect_response` is session-independent --- it builds the JSON-RPC
response without consulting session state.

This also affects `notifications/cancelled`: the MCP cancellation spec
allows clients to send this notification to request aborting a pending
request.  Currently, the server acknowledges the notification (202) but
does not act on it --- the in-flight service call continues.

**Options:**

1. Let in-flight work finish (current plan).  Simple, avoids
   partial-execution concerns.
2. Cancel on DELETE/expiry.  The transport's effect dispatch loop checks a
   cancellation set before calling `resume()`.  The in-flight
   `asyncio.Task` is cancelled.  A JSON-RPC error response is sent.
3. Support `notifications/cancelled` to allow clients to explicitly abort.

**No strong leaning yet.**

## Q014: `AudioContent` and `EmbeddedResource` Content Types

**Question:** Should the `Content` type union include `AudioContent` and
`EmbeddedResource`?

**Context:** MCP defines content types beyond text and image:

- `AudioContent`: `{"type": "audio", "data": "...", "mimeType": "..."}`.
  Structurally identical to `ImageContent` (base64 data + mime type).
- `EmbeddedResource`: `{"type": "resource", "resource": {...}}`.  More
  complex, wraps a resource object.

HA service calls don't currently return audio or embedded resources, so
these types aren't needed yet.  The `Content` union is intentionally
incomplete --- the implementation should include a comment noting this.

`AudioContent` would be a trivial addition (same shape as `ImageContent`).
`EmbeddedResource` can wait until there's a use case.

**Leaning toward:** Defer both.  Add `AudioContent` when a use case
emerges.  `EmbeddedResource` deferred longer.
