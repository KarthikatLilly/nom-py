"""
Dummy MCP client for testing nom-py end-to-end.

Run (after nom-py and dummy upstream are running):
    python cmd/client/main.py
"""
import asyncio
import json

import httpx

NOM_URL = "http://localhost:8001/mcp"


async def call(client: httpx.AsyncClient, payload: dict) -> dict:
    r = await client.post(NOM_URL, json=payload)
    return r.json()


async def main() -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        print("--- 1. initialize ---")
        print(json.dumps(await call(client, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize"
        }), indent=2))

        print("\n--- 2. tools/list ---")
        print(json.dumps(await call(client, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/list"
        }), indent=2))

        print("\n--- 3. tools/call: get_weather ---")
        print(json.dumps(await call(client, {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_weather", "arguments": {"location": "Hyderabad"}},
        }), indent=2))

        print("\n--- 4. tools/call: list_users ---")
        print(json.dumps(await call(client, {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "list_users", "arguments": {}},
        }), indent=2))

        print("\n--- 5. tools/call: delete_user ---")
        print(json.dumps(await call(client, {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "delete_user", "arguments": {"user_id": "alice"}},
        }), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
