"""
telegram_agent.py — TelegramAgent (Notifier)

Receives an IntelligenceReport broadcast from AnalystAgent, queries the full
TokenIntelligence document from MongoDB Atlas (PC-2), formats a MarkdownV2
message, and sends it to the configured Telegram chat via Bot API.

Atlas Prize Track PC-2: get_latest_intelligence() is called before every post.
"""

import logging
import re

import httpx
from uagents import Agent, Context, Protocol

from neurosciout.config import settings
from neurosciout.database import get_latest_intelligence
from neurosciout.protocols import IntelligenceReport

# Own Protocol instance — same (name, version) as the other notifiers and as
# the digest constant in protocols.py, so ctx.broadcast reaches this agent.
# Must NOT share the singleton from protocols.py: multiple agents registering
# handlers on the same Protocol object silently overwrite each other.
notifier_protocol = Protocol(name="NotifierProtocol", version="1.0")

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
agent = Agent(name="telegram_agent", seed=settings.telegram_agent_seed)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

# Characters that must be escaped in Telegram MarkdownV2 (full set per docs)
_MDV2_ESCAPE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!?\\])")


def _escape(text: str) -> str:
    """Escape a string for use inside Telegram MarkdownV2."""
    return _MDV2_ESCAPE.sub(r"\\\1", text)


def _format_message(doc: dict) -> str:
    """
    Build a MarkdownV2-formatted Telegram message from a TokenIntelligence doc.
    """
    symbol = _escape(doc.get("symbol", "UNKNOWN"))
    name = _escape(doc.get("name", "Unknown"))
    mint = _escape(doc.get("mint_address", ""))
    degen = doc.get("degen_score", 0.0)
    rug = doc.get("rug_check", {}).get("rug_score", 0.0)
    lp = doc.get("rug_check", {}).get("lp_locked", False)
    mode = _escape(doc.get("scorer_mode", "heuristic"))

    lp_str = "🔒 Locked" if lp else "🔓 Unlocked"
    score_bar = "🟢" * int(degen // 20) + "⬜" * (5 - int(degen // 20))

    return (
        f"🚨 *NeuroScout Alert* 🚨\n\n"
        f"🪙 *{symbol}* \\({name}\\)\n"
        f"`{mint}`\n\n"
        f"*Degen Score:* {score_bar} `{degen:.1f}/100`\n"
        f"*Rug Score:* `{rug:.1f}/100`\n"
        f"*LP:* {lp_str}\n"
        f"*Scorer:* `{mode}`\n\n"
        f"[View on Solscan](https://solscan\\.io/token/{mint})"
    )


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@agent.on_event("startup")
async def on_startup(ctx: Context) -> None:
    ctx.logger.info("TelegramAgent starting up (address: %s)", agent.address)


# ---------------------------------------------------------------------------
# Broadcast handler — IntelligenceReport from AnalystAgent  (PC-2)
# ---------------------------------------------------------------------------


@notifier_protocol.on_message(model=IntelligenceReport)
async def handle_report(ctx: Context, sender: str, msg: IntelligenceReport) -> None:
    ctx.logger.info(
        "Received IntelligenceReport: mint=%s score=%.1f from %s",
        msg.mint_address, msg.degen_score, sender,
    )

    # PC-2: fetch the full document from Atlas before posting
    doc = await get_latest_intelligence(msg.mint_address)
    if doc is None:
        ctx.logger.error(
            "No TokenIntelligence document found in Atlas for %s — skipping Telegram post.",
            msg.mint_address,
        )
        return

    text = _format_message(doc)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                TELEGRAM_API.format(token=settings.telegram_bot_token),
                json={
                    "chat_id": settings.telegram_chat_id,
                    "text": text,
                    "parse_mode": "MarkdownV2",
                    "disable_web_page_preview": False,
                },
                timeout=10.0,
            )
            resp.raise_for_status()

        ctx.logger.info("Telegram message sent for %s.", msg.mint_address)

    except httpx.HTTPStatusError as exc:
        ctx.logger.error(
            "Telegram API error %d for %s: %s",
            exc.response.status_code, msg.mint_address, exc.response.text,
        )
    except httpx.RequestError as exc:
        ctx.logger.error("Telegram request error for %s: %s", msg.mint_address, exc)


# ---------------------------------------------------------------------------
# Register protocol — required to receive ctx.broadcast
# ---------------------------------------------------------------------------
agent.include(notifier_protocol)
