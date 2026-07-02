from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/mcp")
async def mcp_entry(request: Request):
    body = await request.json()
    method = body.get("method")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {
                    "tools": {"listChanged": False}
                },
                "serverInfo": {
                    "name": "nom-py",
                    "version": "0.1.0"
                }
            }
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "result": {"tools": []}
        }

    if method == "tools/call":
        return {
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "result": {
                "content": [
                    {"type": "text", "text": "NOM-py stub response"}
                ],
                "isError": False
            }
        }

    return {
        "jsonrpc": "2.0",
        "id": body.get("id"),
        "error": {"code": -32601, "message": f"Unknown method: {method}"}
    }