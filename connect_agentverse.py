"""
connect_agentverse.py — One-time mailbox registration for all 6 NeuroScout agents.

Run this ONCE after starting the Bureau to register each agent's mailbox with
Agentverse.  Subsequent Bureau starts will automatically reconnect.

Usage:
    python connect_agentverse.py

Requires AGENTVERSE_API_KEY in .env.
The Bureau must be running (python -m neurosciout.agents.run_all) in another terminal.
"""

import asyncio
import httpx
from neurosciout.config import settings

# Each agent's Inspector REST endpoint is served by the Bureau at port 8000.
# The /connect path is registered per-agent and routes to the correct handler.
BUREAU_URL = "http://localhost:8000"

AGENT_NAMES = ["scout", "historian", "analyst", "telegram_agent", "discord_agent", "x_agent"]


async def connect_all() -> None:
    if not settings.agentverse_api_key:
        print("ERROR: AGENTVERSE_API_KEY is not set in .env")
        return

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{BUREAU_URL}/connect",
            json={
                "user_token": settings.agentverse_api_key,
                "agent_type": "mailbox",
            },
        )
        if resp.status_code == 200:
            print(f"Mailbox connected: {resp.json()}")
        else:
            print(f"Connect failed ({resp.status_code}): {resp.text}")
            print(
                "\nFallback: open the Agent Inspector in your browser at "
                f"{BUREAU_URL} and paste your Agentverse API key to connect manually."
            )


if __name__ == "__main__":
    asyncio.run(connect_all())