"""
Dummy upstream MCP server for testing nom-py.

Exposes 3 fake tools:
- get_weather (allowed)
- list_users  (allowed)
- delete_user (destructive — will be blocked in Phase 3)

Run:
    uvicorn cmd.upstream.main:app --reload --port 9001
"""
from fastapi import FastAPI, Request

app = FastAPI(title="dummy-mcp-upstream")

TOOLS = [
    {
        "name": "get_weather",
        "description": "Get current weather for a location",
        "inputSchema": {
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"],
        },
    },
    {
        "name": "list_users",
        "description": "List all users in the system",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "delete_user",
        "description": "Delete a user by ID (destructive)",
        "inputSchema": {
            "type": "object",
            "properties": {"user_id": {"type": "string"}},
            "required": ["user_id"],
        },
    },
]


@app.post("/mcp")
async def mcp_entry(request: Request):
    body = await request.json()
    method = body.get("method")
    msg_id = body.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "dummy-mcp-upstream",
                    "version": "0.1.0",
                },
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        params = body.get("params", {})
        tool_name = params.get("name")
        args = params.get("arguments", {})

        if tool_name == "get_weather":
            text = f"Weather in {args.get('location', 'unknown')}: 72°F, sunny."
        elif tool_name == "list_users":
            text = "Users: alice, bob, charlie"
        elif tool_name == "delete_user":
            text = f"User {args.get('user_id')} deleted."
        else:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32602, "message": f"Unknown tool: {tool_name}"},
            }

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method not supported: {method}"},
    }