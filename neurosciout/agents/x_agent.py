"""
x_agent.py — XAgent (Notifier)

Receives an IntelligenceReport broadcast from AnalystAgent, queries the full
TokenIntelligence document from MongoDB Atlas (PC-4), and posts a tweet via
the X (Twitter) API v2 using OAuth 1.0a User Context.

Atlas Prize Track PC-4: get_latest_intelligence() is called before every post.

Rate limiting: X free tier allows ~17 posts per 24-hour window.
A module-level counter guards against exceeding this — alerts are logged
rather than silently dropped when the limit is approached.
"""

import logging
import time

import asyncio

import tweepy
from uagents import Agent, Context, Protocol

from neurosciout.config import settings
from neurosciout.database import get_latest_intelligence
from neurosciout.protocols import IntelligenceReport

# Own Protocol instance — same (name, version) as all other notifiers.
# Must NOT share the singleton from protocols.py (see protocols.py docstring).
notifier_protocol = Protocol(name="NotifierProtocol", version="1.0")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limit guard (X free tier: ~17 posts / 24 h)
# ---------------------------------------------------------------------------
_TWEET_DAILY_LIMIT = 15          # conservative — keep 2 in reserve
_WINDOW_SECONDS = 24 * 60 * 60

_tweet_count: int = 0
_window_start: float = time.time()


def _can_tweet() -> bool:
    global _tweet_count, _window_start
    now = time.time()
    if now - _window_start >= _WINDOW_SECONDS:
        _tweet_count = 0
        _window_start = now
    return _tweet_count < _TWEET_DAILY_LIMIT


def _record_tweet() -> None:
    global _tweet_count
    _tweet_count += 1


def _tweets_remaining() -> int:
    return max(0, _TWEET_DAILY_LIMIT - _tweet_count)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
agent = Agent(name="x_agent", seed=settings.x_agent_seed)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_tweet(doc: dict) -> str:
    """
    Format a tweet from a TokenIntelligence document.
    Must fit within 280 characters.
    """
    symbol = doc.get("symbol", "UNKNOWN")
    mint = doc.get("mint_address", "")
    degen = doc.get("degen_score", 0.0)
    rug_check = doc.get("rug_check", {})
    rug = rug_check.get("rug_score", 0.0)
    lp = rug_check.get("lp_locked", False)

    lp_str = "LP:locked" if lp else "LP:unlocked"
    solscan = f"https://solscan.io/token/{mint}"

    # Compact format to stay under 280 chars
    tweet = (
        f"[NeuroScout] ${symbol}\n"
        f"Degen: {degen:.0f}/100 | Rug: {rug:.0f}/100 | {lp_str}\n"
        f"{solscan}\n"
        f"#Solana #DeFi #NewToken"
    )

    # Truncate symbol if tweet is somehow still too long
    if len(tweet) > 280:
        tweet = tweet[:277] + "..."

    return tweet


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@agent.on_event("startup")
async def on_startup(ctx: Context) -> None:
    ctx.logger.info("XAgent starting up (address: %s)", agent.address)
    ctx.logger.info("Tweet rate limit: %d / 24h window.", _TWEET_DAILY_LIMIT)


# ---------------------------------------------------------------------------
# Broadcast handler — IntelligenceReport from AnalystAgent  (PC-4)
# ---------------------------------------------------------------------------


@notifier_protocol.on_message(model=IntelligenceReport)
async def handle_report(ctx: Context, sender: str, msg: IntelligenceReport) -> None:
    ctx.logger.info(
        "Received IntelligenceReport: mint=%s score=%.1f from %s",
        msg.mint_address, msg.degen_score, sender,
    )

    # Rate limit gate — log and skip rather than crash
    if not _can_tweet():
        ctx.logger.warning(
            "X rate limit reached (%d/day). Skipping tweet for %s. "
            "Window resets in ~%.0f minutes.",
            _TWEET_DAILY_LIMIT,
            msg.mint_address,
            (_WINDOW_SECONDS - (time.time() - _window_start)) / 60,
        )
        return

    # PC-4: fetch full document from Atlas before posting
    doc = await get_latest_intelligence(msg.mint_address)
    if doc is None:
        ctx.logger.error(
            "No TokenIntelligence document found in Atlas for %s — skipping tweet.",
            msg.mint_address,
        )
        return

    tweet_text = _format_tweet(doc)

    try:
        # tweepy 4.x has no AsyncClient — use synchronous Client in a thread executor
        # so we don't block the uagents event loop.
        client = tweepy.Client(
            consumer_key=settings.x_api_key,
            consumer_secret=settings.x_api_secret,
            access_token=settings.x_access_token,
            access_token_secret=settings.x_access_secret,
        )
        response = await asyncio.to_thread(client.create_tweet, text=tweet_text)
        tweet_id = response.data.get("id") if response.data else "unknown"
        _record_tweet()

        ctx.logger.info(
            "Tweet posted for %s (id=%s). Remaining today: %d.",
            msg.mint_address, tweet_id, _tweets_remaining(),
        )

    except tweepy.TweepyException as exc:
        ctx.logger.error("X API error for %s: %s", msg.mint_address, exc)
    except Exception:
        ctx.logger.exception("Unexpected error posting tweet for %s.", msg.mint_address)


# ---------------------------------------------------------------------------
# Register protocol — required to receive ctx.broadcast
# ---------------------------------------------------------------------------
agent.include(notifier_protocol)
