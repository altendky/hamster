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
    transport["AiohttpMCPTransport<br/>Validates headers, parses JSON,<br/>passes to MCPServerSession"]
    session["MCPServerSession (sans-IO)<br/>Validates state, parses JSON-RPC,<br/>emits events"]
    dispatch["Event dispatch<br/>InitializeRequested → build result<br/>ToolListRequested → return cached tools<br/>ToolCallRequested → service call"]
    ha["Home Assistant Core<br/>hass.services.async_call()<br/>hass.states, registries, etc."]
    response["JSON-RPC response → HTTP response → MCP client"]

    client -->|"HTTPS POST (JSON-RPC)<br/>Authorization: Bearer"| view
    view --> transport
    transport --> session
    session --> dispatch
    dispatch --> ha
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
The `tools/list` handler simply returns the cached list.

```mermaid
sequenceDiagram
    participant Client
    participant Transport
    participant Session
    participant Component

    Client->>Transport: POST tools/list
    Transport->>Session: receive_message()
    Note over Session: State: ACTIVE
    Session-->>Transport: [ToolListRequested]
    Transport->>Component: handle event
    Note over Component: Return cached tool list
    Component-->>Transport: tool list
    Transport->>Session: send_tools_list()
    Session-->>Transport: JSON-RPC response
    Transport-->>Client: HTTP 200<br/>{"result":{"tools":[...]}}
```

## Tool Call Flow (with Effect/Continuation)

For tool calls that require I/O (most do --- they call HA services), the
component layer uses the effect/continuation dispatch loop.

```mermaid
sequenceDiagram
    participant Client
    participant Transport
    participant Session
    participant Component
    participant HA as HA Core

    Client->>Transport: POST tools/call<br/>hamster_light__turn_on
    Transport->>Session: receive_message()
    Note over Session: State: ACTIVE
    Session-->>Transport: [ToolCallRequested]
    Transport->>Component: handle event

    Note over Component: call_tool() → ServiceCall effect
    Component->>HA: hass.services.async_call()
    HA-->>Component: service result
    Note over Component: resume() → Done

    Component-->>Transport: tool result
    Transport->>Session: send_tool_result()
    Session-->>Transport: JSON-RPC response
    Transport-->>Client: HTTP 200<br/>{"result":{"content":[...]}}
```

## Tool Generation (Pure Function)

The `services_to_mcp_tools()` function is pure --- it has no I/O dependencies.
The I/O layer calls `hass.services.async_services()` and feeds the result in.

```mermaid
flowchart LR
    input["HA service registry<br/>{light: {turn_on: {fields: {brightness: {selector: {number: {min: 0, max: 255}}}}}}}"]
    fn["services_to_mcp_tools()<br/><i>pure function</i>"]
    output["MCP tool definitions<br/>[{name: hamster_light__turn_on, inputSchema: {properties: {brightness: {type: number, minimum: 0, maximum: 255}}}}]"]

    input --> fn --> output
```

The tristate configuration is also passed in as data --- the function filters
based on Enabled/Dynamic/Disabled state per service.
