"""
Dummy MCP client for testing nom-py end-to-end with different users.

Run:
    python cmd/client/main.py
"""
import asyncio
import json

import httpx

NOM_URL = "http://localhost:8001/mcp"


async def call(client: httpx.AsyncClient, payload: dict, token: str | None = None) -> dict:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = await client.post(NOM_URL, json=payload, headers=headers)
    return r.json()


async def scenario(client: httpx.AsyncClient, label: str, token: str | None):
    print(f"\n{'='*60}")
    print(f"  SCENARIO: {label}  (token={token or 'NONE'})")
    print("="*60)

    print("\n--- initialize ---")
    print(json.dumps(await call(client, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize"
    }, token), indent=2))

    print("\n--- tools/list ---")
    print(json.dumps(await call(client, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/list"
    }, token), indent=2))

    for tool_id, (name, args) in enumerate([
        ("get_weather", {"location": "Hyderabad"}),
        ("list_users", {}),
        ("delete_user", {"user_id": "alice"}),
    ], start=3):
        print(f"\n--- tools/call: {name} ---")
        print(json.dumps(await call(client, {
            "jsonrpc": "2.0",
            "id": tool_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }, token), indent=2))


async def main() -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        await scenario(client, "NO TOKEN", None)
        await scenario(client, "ALICE (developers + analysts)", "tok-alice")
        await scenario(client, "BOB (analysts only)", "tok-bob")
        await scenario(client, "INVALID TOKEN", "tok-nobody")


if __name__ == "__main__":
    asyncio.run(main())