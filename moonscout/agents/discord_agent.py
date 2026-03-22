"""
discord_agent.py — DiscordAgent (Notifier)

Receives an IntelligenceReport broadcast from AnalystAgent, queries the full
TokenIntelligence document from MongoDB Atlas (PC-3), and posts a rich embed
to the configured Discord channel via Incoming Webhook.

Atlas Prize Track PC-3: get_latest_intelligence() is called before every post.
"""

import logging

import httpx
from uagents import Agent, Context, Protocol

from moonscout.config import settings
from moonscout.database import get_latest_intelligence
from moonscout.protocols import IntelligenceReport

# Own Protocol instance — same (name, version) as all other notifiers.
# Must NOT share the singleton from protocols.py (see protocols.py docstring).
notifier_protocol = Protocol(name="NotifierProtocol", version="1.0")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
agent = Agent(name="discord_agent", seed=settings.discord_agent_seed)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _score_colour(degen_score: float) -> int:
    """Return a Discord embed hex colour based on the Degen Score."""
    if degen_score >= 85:
        return 0x00FF88   # bright green — high conviction
    if degen_score >= 70:
        return 0xFFD700   # gold — solid pick
    return 0xFF6B35       # orange — borderline (shouldn't appear; threshold gates this)


def _build_embed(doc: dict) -> dict:
    """Build a Discord embed dict from a TokenIntelligence document."""
    mint = doc.get("mint_address", "")
    symbol = doc.get("symbol", "UNKNOWN")
    name = doc.get("name", "Unknown Token")
    degen = doc.get("degen_score", 0.0)
    rug_check = doc.get("rug_check", {})
    rug = rug_check.get("rug_score", 0.0)
    lp = rug_check.get("lp_locked", False)
    top_holder = rug_check.get("top_holder_pct", 0.0)
    freeze = rug_check.get("freeze_authority", True)
    mint_auth = rug_check.get("mint_authority", True)
    mode = doc.get("scorer_mode", "heuristic")

    return {
        "title": f"🚨 MoonScout: ${symbol}",
        "description": f"**{name}**\n`{mint}`",
        "color": _score_colour(degen),
        "url": f"https://solscan.io/token/{mint}",
        "fields": [
            {
                "name": "🎯 Degen Score",
                "value": f"`{degen:.1f} / 100`",
                "inline": True,
            },
            {
                "name": "☠️ Rug Score",
                "value": f"`{rug:.1f} / 100`",
                "inline": True,
            },
            {
                "name": "💧 LP",
                "value": "🔒 Locked" if lp else "🔓 Unlocked",
                "inline": True,
            },
            {
                "name": "🐋 Top Holder",
                "value": f"`{top_holder:.1f}%`",
                "inline": True,
            },
            {
                "name": "❄️ Freeze Auth",
                "value": "⚠️ Active" if freeze else "✅ Revoked",
                "inline": True,
            },
            {
                "name": "🪙 Mint Auth",
                "value": "⚠️ Active" if mint_auth else "✅ Revoked",
                "inline": True,
            },
            {
                "name": "🤖 Scorer",
                "value": f"`{mode}`",
                "inline": True,
            },
        ],
        "footer": {"text": "MoonScout • Powered by Fetch.ai uAgents + MongoDB Atlas"},
    }


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@agent.on_event("startup")
async def on_startup(ctx: Context) -> None:
    ctx.logger.info("DiscordAgent starting up (address: %s)", agent.address)


# ---------------------------------------------------------------------------
# Broadcast handler — IntelligenceReport from AnalystAgent  (PC-3)
# ---------------------------------------------------------------------------


@notifier_protocol.on_message(model=IntelligenceReport)
async def handle_report(ctx: Context, sender: str, msg: IntelligenceReport) -> None:
    ctx.logger.info(
        "Received IntelligenceReport: mint=%s score=%.1f from %s",
        msg.mint_address, msg.degen_score, sender,
    )

    # PC-3: fetch full document from Atlas before posting
    doc = await get_latest_intelligence(msg.mint_address)
    if doc is None:
        ctx.logger.error(
            "No TokenIntelligence document found in Atlas for %s — skipping Discord post.",
            msg.mint_address,
        )
        return

    embed = _build_embed(doc)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                settings.discord_webhook_url,
                json={"embeds": [embed]},
                timeout=10.0,
            )
            resp.raise_for_status()

        ctx.logger.info("Discord embed posted for %s.", msg.mint_address)

    except httpx.HTTPStatusError as exc:
        ctx.logger.error(
            "Discord webhook error %d for %s: %s",
            exc.response.status_code, msg.mint_address, exc.response.text,
        )
    except httpx.RequestError as exc:
        ctx.logger.error("Discord request error for %s: %s", msg.mint_address, exc)


# ---------------------------------------------------------------------------
# Register protocol — required to receive ctx.broadcast
# ---------------------------------------------------------------------------
agent.include(notifier_protocol)
