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

## ~~Q017: `call_tool()` Error Mechanism for Unknown Tool Name~~ --- RESOLVED

Moved to [Decisions](decisions.md) as D020 (part of the `call_tool()` contract
change).

Return `Done(CallToolResult(is_error=True))` for unknown tool names instead of
raising `ValueError`.  `call_tool()` already uses this pattern for "service not
found in index."  Since the service index can change between the session's
tool-name validation and `call_tool()` execution, unknown-name is a data
condition, not a violated invariant.  The function's contract becomes "returns
`ToolEffect` for all inputs" with no exception paths.  The session still
validates tool names first to produce a proper `INVALID_PARAMS` JSON-RPC error,
but `call_tool()` handles it gracefully either way.

## ~~Q018: `ServerCapabilities` Type Structure~~ --- RESOLVED

Moved to [Decisions](decisions.md) as D020.

## ~~Q019: Logging Strategy~~ --- RESOLVED

Moved to [Decisions](decisions.md) as D021.

## ~~Q010: Origin Header Validation Strategy~~ --- RESOLVED

Moved to [Decisions](decisions.md) as D022.

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

**Decision:** Missing `Accept` header (`None`) is treated as `*/*` for
developer convenience (curl, testing tools).  The MCP spec requires
clients to send `Accept` but does not require servers to enforce it.
Empty string `Accept: ""` is still rejected with 406.

When SSE support lands (see Q012), this should be revisited to decide
whether to also require `text/event-stream` in the Accept header.

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

## ~~Q015: Content-Type Parameter Stripping Responsibility~~ --- RESOLVED

Moved to [Decisions](decisions.md) as D023.

## Q016: Batch Request Containing `initialize` --- Error Format

**Question:** When an `initialize` message appears inside a JSON-RPC
batch array, what is the exact error response?

**Context:** Stage 5 says "`initialize` MUST NOT appear in a batch" and
the test says `SendResponse(400)`.  But there are multiple possible
behaviors:

1. Reject the entire batch with HTTP 400 before processing any messages.
2. Process other messages normally and return a per-item JSON-RPC error
   for the `initialize` message.
3. Return a single JSON-RPC error response (not an array) for the whole
   batch.

Session creation mid-batch creates ambiguity: subsequent messages in the
same batch would lack a session ID context.  Option 2 would require
processing other messages either with no session or with the
newly-created session, both of which are problematic.

**Leaning toward:** Option 1 --- reject the entire batch with HTTP 400
and a JSON-RPC `INVALID_REQUEST` error body.  This is the simplest
behavior and avoids ambiguity about session state for other messages in
the batch.

## Q020: Batch Requests Containing `tools/call`

**Question:** Should multiple `tools/call` requests in a batch be processed
sequentially or concurrently?

**Context:** A batch request can contain multiple `tools/call` requests,
each of which produces a `RunEffects` result requiring I/O dispatch.  The
transport must process all of them and collect responses into a JSON array.

Options:

1. **Sequential** --- process each `RunEffects` in order.  Simple, no
   concurrency concerns.  If one fails, subsequent calls still run.
2. **Concurrent** --- spawn all effect dispatches concurrently, gather
   results.  More complex: need to handle partial failures, correlate
   responses to request IDs correctly.
3. **Reject** --- batches containing `tools/call` are not supported.
   Return an error for the whole batch or per-item errors.

**v1 decision:** Sequential processing.  Simplest approach, avoids
concurrency complexity.  Concurrent processing can be revisited if there's
a demonstrated need for parallel tool execution within a single batch.

**Leaning toward:** Keep sequential for now.  Revisit if performance
becomes a concern.

## Q021: Request Body Size Limits

**Question:** Should the server enforce a maximum request body size?

**Context:** Without a limit, a malicious client could send very large
POST bodies, consuming memory. HA's HTTP server may have its own limits,
but these aren't documented or guaranteed.

**Options:**

1. Enforce a limit in the transport (e.g., 1MB) before reading the body.
2. Rely on HA's HTTP server limits (if any).
3. Document as a known limitation for v1.

**No strong leaning yet.**

## Q022: Maximum Concurrent Sessions

**Question:** Should the server limit the number of concurrent sessions?

**Context:** Without a limit, a malicious client could create thousands of
sessions, consuming memory. Each session is lightweight (state machine +
timestamps), but unbounded growth is a concern.

**Options:**

1. Add a configurable max session count (e.g., 100). New `initialize`
   requests return an error when the limit is reached.
2. Rely on HA auth and external rate limiting.
3. Document as a known limitation for v1.

**No strong leaning yet.**

## Q023: Monitoring and Metrics

**Question:** Should the integration expose operational metrics?

**Context:** For production deployments, operators may want visibility into:

- Active session count
- Requests per second / minute
- Index size (number of services)
- Index rebuild frequency

**Options:**

1. Expose metrics via HA's statistics/sensor infrastructure.
2. Log periodic summaries at INFO level.
3. Defer to v2.

**Leaning toward:** Defer to v2.

## Q024: Tool Argument Type Validation

**Question:** Should `call_tool()` validate argument types beyond checking
that domain/service exist in the index?

**Context:** Arguments come from the LLM and may have wrong types (e.g.,
`domain` as int instead of string, `target.entity_id` as string instead of
array). Currently, these would fail downstream in HA's `async_call()` or
produce Python type errors.

**Options:**

1. Add explicit type validation in `call_tool()`, returning
   `Done(CallToolResult(is_error=True))` for malformed arguments.
2. Rely on HA's validation and Python type errors (caught by effect
   handler).
3. Document expected types clearly in `explain` output and trust the LLM.

**Leaning toward:** Option 2 for v1, revisit if LLM errors are common.
