"""
stdio bridge — makes nom-py look like a stdio MCP server to Claude Desktop.

Claude Desktop spawns this script. It reads JSON-RPC messages from stdin,
POSTs them to nom-py's /mcp endpoint, and writes responses to stdout.

Design invariants (must not be violated):
  - stdout is used ONLY for MCP JSON-RPC response bodies, one per line.
  - stderr is used for all logs. Never write anything else to stdout.
  - Notifications (no "id" field) MUST NOT produce any stdout output.
  - If nom-py fails, requests get a synthesized JSON-RPC error;
    notifications still get nothing.

Environment variables:
  NOM_URL   — nom-py endpoint (default: http://localhost:8001/mcp)
  NOM_TOKEN — bearer token used for the Authorization header. Empty means
              anonymous; only 'initialize' and notifications will pass.
"""
import asyncio
import json
import os
import sys

import httpx

NOM_URL = os.environ.get("NOM_URL", "http://localhost:8001/mcp")
NOM_TOKEN = os.environ.get("NOM_TOKEN", "")


def log(msg: str) -> None:
    """Log to stderr so it never pollutes the MCP stream on stdout."""
    sys.stderr.write(f"[stdio-bridge] {msg}\n")
    sys.stderr.flush()


def write_stdout(payload: dict) -> None:
    """Write a single JSON line to stdout and flush."""
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


async def bridge() -> None:
    log(f"starting bridge to {NOM_URL}")
    log(f"token: {'set' if NOM_TOKEN else 'anonymous'}")

    headers = {"Content-Type": "application/json"}
    if NOM_TOKEN:
        headers["Authorization"] = f"Bearer {NOM_TOKEN}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        loop = asyncio.get_event_loop()

        while True:
            # Read one line from stdin (blocking read via thread executor)
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                log("stdin closed, exiting")
                return

            line = line.strip()
            if not line:
                continue

            # Parse the JSON-RPC request
            try:
                request = json.loads(line)
            except json.JSONDecodeError as e:
                log(f"invalid JSON from stdin: {e}")
                continue

            is_notification = "id" not in request
            method = request.get("method", "?")
            req_id = request.get("id")
            log(
                f"→ {method} "
                f"{'(notification)' if is_notification else f'id={req_id}'}"
            )

            # POST to nom-py
            try:
                r = await client.post(NOM_URL, json=request, headers=headers)
            except httpx.HTTPError as e:
                log(f"POST failed: {e}")
                if not is_notification:
                    write_stdout({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32000,
                            "message": f"bridge upstream error: {e}",
                        },
                    })
                continue

            # Notifications: nom-py returns 204, we write nothing
            if is_notification:
                log(f"← notification ack (status={r.status_code}, no stdout)")
                continue

            # Requests: expect a JSON body
            try:
                response = r.json()
            except json.JSONDecodeError:
                log(f"nom-py returned non-JSON body: {r.text[:200]}")
                write_stdout({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32000,
                        "message": "bridge received non-JSON from nom-py",
                    },
                })
                continue

            write_stdout(response)
            log(f"← id={response.get('id')}")


if __name__ == "__main__":
    try:
        asyncio.run(bridge())
    except KeyboardInterrupt:
        log("interrupted")