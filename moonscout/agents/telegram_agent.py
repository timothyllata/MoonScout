"""
telegram_agent.py — TelegramAgent (Scraper)

Monitors configured Telegram channels for Solana token mint addresses using
Telethon (user-account client). Discovered mints are deduplicated via Atlas
and forwarded to HistorianAgent as TokenDiscovery messages, feeding into the
same pipeline as ScoutAgent.

Data flow:
    Telegram channels → TelegramAgent --[TokenDiscovery]--> HistorianAgent
                                               ↓
                                      atlas_cache (mark seen)

First-run auth:
    Telethon will prompt for your phone number and a one-time Telegram code.
    After that, the session is saved to <TELEGRAM_SESSION_NAME>.session and
    subsequent runs are fully silent.

Configure channels in .env:
    TELEGRAM_CHANNELS=solanatradingalpha,pumpfun_calls
"""

import asyncio
import logging
import re
from datetime import datetime, timezone

from telethon import TelegramClient, events
from uagents import Agent, Context
from uagents_core.identity import Identity

from moonscout.config import settings
from moonscout.database import close_database, get_database, is_token_seen, mark_token_seen
from moonscout.protocols import TokenDiscovery

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mint extraction patterns
# ---------------------------------------------------------------------------

# Priority 1: pump.fun URLs — mint is in the path
_PUMPFUN_RE = re.compile(r"pump\.fun/(?:coin/)?([1-9A-HJ-NP-Za-km-z]{43,44})")

# Priority 2: DexScreener URLs
_DEXSCREENER_RE = re.compile(r"dexscreener\.com/solana/([1-9A-HJ-NP-Za-km-z]{43,44})")

# Priority 3: raw base58 Solana address (word-boundary anchored to reduce false positives)
_SOLANA_ADDR_RE = re.compile(r"\b([1-9A-HJ-NP-Za-km-z]{43,44})\b")

# ---------------------------------------------------------------------------
# Shared queue — Telethon handler enqueues mints; on_interval drains them
# ---------------------------------------------------------------------------
_mint_queue: asyncio.Queue[str] = asyncio.Queue()

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
agent = Agent(name="telegram_agent", seed=settings.telegram_agent_seed)

_telethon_task: asyncio.Task | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _peer_address(seed: str) -> str:
    return Identity.from_seed(seed, 0).address


def _extract_mints(text: str) -> list[str]:
    """
    Extract Solana mint addresses from a Telegram message.
    URL patterns take priority — they are unambiguous and produce fewer
    false positives than scanning for raw base58 strings.
    """
    found: set[str] = set()

    for pattern in (_PUMPFUN_RE, _DEXSCREENER_RE):
        for m in pattern.finditer(text):
            found.add(m.group(1))

    # Only scan for raw addresses when no URL match was found
    if not found:
        for m in _SOLANA_ADDR_RE.finditer(text):
            found.add(m.group(1))

    return list(found)


# ---------------------------------------------------------------------------
# Telethon background task
# ---------------------------------------------------------------------------


async def _run_telethon(channels: list[str]) -> None:
    """
    Connect to Telegram as a user and stream new messages from `channels`.
    Runs until cancelled by on_shutdown.
    """
    client = TelegramClient(
        settings.telegram_session_name,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )

    # start() handles interactive phone + OTP auth on first run; silent thereafter
    await client.start()

    @client.on(events.NewMessage(chats=channels))
    async def _on_message(event: events.NewMessage.Event) -> None:
        text: str = event.raw_text or ""
        mints = _extract_mints(text)
        for mint in mints:
            logger.debug("Telethon: queuing mint %s from chat %s", mint, event.chat_id)
            await _mint_queue.put(mint)

    logger.info(
        "TelegramAgent: Telethon connected — monitoring %d channel(s): %s",
        len(channels),
        channels,
    )
    await client.run_until_disconnected()


# ---------------------------------------------------------------------------
# Agent lifecycle
# ---------------------------------------------------------------------------


@agent.on_event("startup")
async def on_startup(ctx: Context) -> None:
    global _telethon_task

    ctx.logger.info("TelegramAgent (scraper) starting up (address: %s)", agent.address)

    await get_database()

    historian_address = _peer_address(settings.historian_seed)
    ctx.storage.set("historian_address", historian_address)
    ctx.logger.info("Historian target address: %s", historian_address)

    channels = [c.strip() for c in settings.telegram_channels.split(",") if c.strip()]
    if not channels:
        ctx.logger.warning(
            "TELEGRAM_CHANNELS is empty — TelegramAgent is idle. "
            "Add channel usernames to .env to start scraping."
        )
        return

    _telethon_task = asyncio.create_task(_run_telethon(channels))
    ctx.logger.info("Telethon task started for: %s", channels)


@agent.on_event("shutdown")
async def on_shutdown(ctx: Context) -> None:
    global _telethon_task
    if _telethon_task and not _telethon_task.done():
        _telethon_task.cancel()
    await close_database()
    ctx.logger.info("TelegramAgent shut down.")


# ---------------------------------------------------------------------------
# Queue drain — runs every 5 s, forwards discovered mints to HistorianAgent
# ---------------------------------------------------------------------------


@agent.on_interval(period=5.0)
async def drain_queue(ctx: Context) -> None:
    historian_address: str | None = ctx.storage.get("historian_address")
    if historian_address is None:
        return

    sent = 0
    while not _mint_queue.empty():
        mint = _mint_queue.get_nowait()
        try:
            if await is_token_seen(mint):
                continue

            await mark_token_seen(mint)

            discovery = TokenDiscovery(
                mint_address=mint,
                symbol="UNKNOWN",
                name="Unknown Token",
                decimals=0,
                supply=0.0,
                creator_address="unknown",
                created_at=datetime.now(tz=timezone.utc).isoformat(),
                source="telegram_scraper",
                raw_metadata={},
            )

            await ctx.send(historian_address, discovery)
            sent += 1
            ctx.logger.info("Forwarded mint %s to Historian.", mint)

        except Exception:
            ctx.logger.exception("Error processing mint %s from Telegram queue.", mint)

    if sent:
        ctx.logger.info("Drain complete — forwarded %d mint(s) to Historian.", sent)
