# MCP Protocol

Hamster implements the
[Model Context Protocol](https://modelcontextprotocol.io/specification/2025-03-26)
Streamable HTTP transport.
The implementation is direct --- no MCP SDK dependency.

## Transport: Streamable HTTP

A single HTTP endpoint at `/api/hamster` handles all MCP communication.

| Method | Purpose | Response |
| --- | --- | --- |
| **POST** | All client-to-server JSON-RPC messages | 200 (JSON) or 202 (notification) |
| **GET** | Server-initiated SSE stream (optional) | 405 (not supported initially) |
| **DELETE** | Session termination | 200 or 405 |

### Why Not SSE?

The initial implementation responds only with `Content-Type: application/json`.
SSE streaming is optional per the spec and adds complexity.
It can be added later for streaming progress during long tool calls.

## JSON-RPC 2.0

All messages use JSON-RPC 2.0 framing:

- **Requests** have `jsonrpc`, `id`, `method`, `params`
- **Responses** have `jsonrpc`, `id`, `result` or `error`
- **Notifications** have `jsonrpc`, `method`, `params` (no `id`)

## Message Types

### Initialization

The client must initialize before any other operation:

1. Client sends `initialize` request with protocol version and capabilities
2. Server responds with its own capabilities and server info
3. Client sends `notifications/initialized` notification
4. Server transitions to ACTIVE state

### Tool Operations

| Method | Direction | Purpose |
| --- | --- | --- |
| `tools/list` | Client → Server | List available tools (paginated via cursor) |
| `tools/call` | Client → Server | Invoke a tool by name with arguments |

### Utility Methods

| Method | Direction | Purpose |
| --- | --- | --- |
| `ping` | Client → Server | Liveness check; returns `{"result": {}}` |

`ping` is handled in all session states (IDLE, INITIALIZING, ACTIVE).
In CLOSED state, it returns a JSON-RPC error.

### Errors

Two levels of error reporting:

- **Protocol errors** (JSON-RPC error response): malformed requests, wrong
  state, unknown methods
- **Tool errors** (success at protocol level, `isError: true` in result):
  service call failures the LLM can act on

Standard JSON-RPC error codes: `-32700` (parse error), `-32600` (invalid
request), `-32601` (method not found), `-32602` (invalid params),
`-32603` (internal error).

## Headers

### Client Must Send

| Header | When | Value |
| --- | --- | --- |
| `Accept` | Every POST | `application/json, text/event-stream` |
| `Content-Type` | Every POST | `application/json` |
| `Mcp-Session-Id` | After initialization | Session ID from server |

### Server Returns

| Header | When | Value |
| --- | --- | --- |
| `Content-Type` | Every response | `application/json` |
| `Mcp-Session-Id` | On initialize response | Generated session ID |

### Server Validates

| Header | Purpose |
| --- | --- |
| `Origin` | DNS rebinding protection |
| `Mcp-Session-Id` | Session association (400 if missing post-init) |

## Session Management

- Server generates a cryptographically random session ID on initialization
- Client must include `Mcp-Session-Id` on all subsequent requests
- Missing session ID after initialization → 400 Bad Request
- Unknown session ID → 404 Not Found (client must re-initialize)
- Sessions are stored in memory, keyed by ID
- Abandoned sessions are cleaned up after a configurable timeout

## Authentication

Hamster uses Home Assistant's built-in authentication.
The `HomeAssistantView` is registered with `requires_auth = True`, which means
HA automatically validates Bearer tokens before the request reaches our code.

No separate OAuth setup, no API tokens, no secret URLs.
The MCP client simply uses a
[Long-Lived Access Token](https://developers.home-assistant.io/docs/auth_api/#long-lived-access-token)
from HA.
