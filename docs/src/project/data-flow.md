# Data Flow

This page describes how MCP requests flow through the system, from an external
MCP client down to Home Assistant service calls and back.
For the MCP protocol details see [MCP Protocol](mcp-protocol.md); for tool
generation specifics see [Tool Generation](tool-generation.md).

## Overview

```mermaid
flowchart TB
    client["MCP Client<br/>(Claude, opencode, etc.)"]
    view["HomeAssistantView<br/>requires_auth = True<br/>HA validates bearer token"]
    transport["AiohttpMCPTransport<br/>Validates headers, parses JSON,<br/>drives MCPServerSession (sans-IO),<br/>handles initialize handshake internally"]
    handler["MCPHandler (component layer)<br/>handle_tool_list() → cached tools<br/>handle_tool_call() → effect/continuation dispatch"]
    ha["Home Assistant Core<br/>hass.services.async_call()<br/>hass.states, registries, etc."]
    response["JSON-RPC response → HTTP response → MCP client"]

    client -->|"HTTPS POST (JSON-RPC)<br/>Authorization: Bearer"| view
    view --> transport
    transport -->|"delegates application events"| handler
    handler --> ha
    ha --> response
```

## Session Lifecycle

The MCP protocol requires a handshake before normal operation.
The sans-IO session enforces this via a state machine.

```mermaid
stateDiagram-v2
    [*] --> IDLE
    IDLE --> INITIALIZING : Receive initialize request
    INITIALIZING --> ACTIVE : Receive notifications/initialized
    ACTIVE --> ACTIVE : tools/list, tools/call
    ACTIVE --> CLOSED : DELETE request or session timeout
    CLOSED --> [*]
```

Messages received in the wrong state produce a JSON-RPC error response.
The session never performs I/O --- it only validates and emits events.

## Initialization Flow

```mermaid
sequenceDiagram
    participant Client
    participant Transport
    participant Session as Session (sans-IO)

    Client->>Transport: POST /api/hamster<br/>initialize request
    Transport->>Session: receive_message(msg)
    Note over Session: Validate state: IDLE<br/>Parse params<br/>Transition → INITIALIZING
    Session-->>Transport: [InitializeRequested]
    Transport->>Session: send_initialize_result()
    Session-->>Transport: JSON-RPC response
    Transport-->>Client: HTTP 200<br/>Mcp-Session-Id: id

    Client->>Transport: POST /api/hamster<br/>notifications/initialized
    Transport->>Session: receive_message(msg)
    Note over Session: Validate: INITIALIZING<br/>Transition → ACTIVE
    Session-->>Transport: [NotificationReceived]
    Transport-->>Client: HTTP 202 Accepted
```

## Tool List Flow

The tool list is generated once at integration load time and cached.
It is regenerated when `EVENT_SERVICE_REGISTERED` or `EVENT_SERVICE_REMOVED`
fires.
The transport delegates to the handler, which returns the cached list.

```mermaid
sequenceDiagram
    participant Client
    participant Transport as AiohttpMCPTransport
    participant Session as MCPServerSession (sans-IO)
    participant Handler as MCPHandler (component)

    Client->>Transport: POST /api/hamster<br/>tools/list
    Note over Transport: Validate headers<br/>Parse JSON body
    Transport->>Session: receive_message(msg)
    Note over Session: Validate state: ACTIVE<br/>Parse JSON-RPC
    Session-->>Transport: [ToolListRequested]

    Transport->>Handler: handle_tool_list()
    Note over Handler: Return cached tool list
    Handler-->>Transport: list[Tool]

    Transport->>Session: send_tools_list(tools)
    Session-->>Transport: JSON-RPC response
    Transport-->>Client: HTTP 200<br/>{"result":{"tools":[...]}}
```

## Tool Call Flow (with Effect/Continuation)

For tool calls that require I/O (most do --- they call HA services), the
handler uses the effect/continuation dispatch loop internally.
The transport delegates via `MCPHandler` and receives a finished result.

```mermaid
sequenceDiagram
    participant Client
    participant Transport as AiohttpMCPTransport
    participant Session as MCPServerSession (sans-IO)
    participant Handler as MCPHandler (component)
    participant HA as Home Assistant

    Client->>Transport: POST /api/hamster<br/>tools/call hamster_light__turn_on
    Note over Transport: Validate headers<br/>Parse JSON body
    Transport->>Session: receive_message(msg)
    Note over Session: Validate state: ACTIVE<br/>Parse JSON-RPC
    Session-->>Transport: [ToolCallRequested]

    Transport->>Handler: handle_tool_call(name, args)
    Note over Handler: call_tool(name, args)<br/>→ ServiceCall effect
    Handler->>HA: hass.services.async_call(...)
    HA-->>Handler: service result
    Note over Handler: resume(continuation, result)<br/>→ Done(CallToolResult)
    Handler-->>Transport: CallToolResult

    Transport->>Session: send_tool_result(result)
    Session-->>Transport: JSON-RPC response
    Transport-->>Client: HTTP 200<br/>{"result":{"content":[...]}}
```

## Tool Generation (Pure Function)

The `services_to_mcp_tools()` function lives in `hamster.mcp._core.tools` ---
it is pure (no I/O, no global state).
The component layer calls `hass.services.async_services()` and feeds the
result in.

```mermaid
flowchart LR
    input["HA service registry<br/>{light: {turn_on: {fields: {brightness: {selector: {number: {min: 0, max: 255}}}}}}}"]
    fn["services_to_mcp_tools()<br/><i>pure function</i>"]
    output["MCP tool definitions<br/>[{name: hamster_light__turn_on, inputSchema: {properties: {brightness: {type: number, minimum: 0, maximum: 255}}}}]"]

    input --> fn --> output
```

The tristate configuration is also passed in as data --- the function filters
based on Enabled/Dynamic/Disabled state per service.
