"""
historian.py — HistorianAgent

Receives a TokenDiscovery from ScoutAgent, queries the RugCheck.xyz public
API to gather on-chain risk signals, and forwards a RugCheckResult to
AnalystAgent for ML scoring.

Data flow:
    ScoutAgent --[TokenDiscovery]--> HistorianAgent --[RugCheckResult]--> AnalystAgent

Resilience:
    - In-memory LRU cache (500 entries) avoids redundant RugCheck calls.
    - If the RugCheck API is unavailable, a conservative fallback result is
      sent so the pipeline continues.

Fixes applied (vs v1):
  - CRITICAL-1: Use Identity.from_seed() for peer address derivation.
  - CRITICAL-2: Guard ctx.storage.get() with explicit None check.
  - HIGH-1: Eliminated model_copy() entirely — pass discovery directly into
            _parse_rugcheck_response() so there is no Pydantic v1/v2 ambiguity.
  - HIGH-2: Eliminated sentinel TokenDiscovery pattern — no invalid intermediate objects.
"""

import logging
from collections import OrderedDict

import httpx
from uagents import Agent, Context
from uagents_core.identity import Identity

from moonscout.config import settings
from moonscout.protocols import RugCheckResult, TokenDiscovery, historian_protocol

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RUGCHECK_API = "https://api.rugcheck.xyz/v1/tokens/{mint}/report"
RUGCHECK_TIMEOUT = 12.0  # seconds

# RugCheck aggregate score: above this value we flag the token as a rug
RUGCHECK_RUG_THRESHOLD = 500

# In-memory LRU cache — avoids redundant API calls for the same mint address
_CACHE_MAX = 500
_rug_cache: OrderedDict[str, RugCheckResult] = OrderedDict()

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
agent = Agent(name="historian", seed=settings.historian_seed)


# ---------------------------------------------------------------------------
# Address helper  (FIX CRITICAL-1)
# ---------------------------------------------------------------------------


def _peer_address(seed: str) -> str:
    """
    Pure cryptographic derivation of a peer agent's address from its seed.
    No background I/O — unlike Agent() construction.
    """
    return Identity.from_seed(seed, 0).address


# ---------------------------------------------------------------------------
# RugCheck.xyz helpers  (FIX HIGH-1, HIGH-2)
# ---------------------------------------------------------------------------


def _parse_rugcheck_response(
    discovery: TokenDiscovery,
    data: dict,
) -> RugCheckResult:
    """
    Extract structured risk signals from a RugCheck.xyz /report response.
    Accepts the original TokenDiscovery so it can be embedded directly —
    no sentinel object, no model_copy() needed.

    RugCheck response shape (simplified):
        {
          "score": int,          # aggregate risk score (higher = riskier)
          "topHolders": [...],   # [{pct: float, ...}, ...]
          "mintAuthority": str | null,
          "freezeAuthority": str | null,
          "lpLockedPct": float,  # 0–100
        }
    """
    score: int = data.get("score", 0)
    is_rug = score >= RUGCHECK_RUG_THRESHOLD

    # Normalise to 0–100 range for uniform downstream comparison
    rug_score = min(100.0, score / 10.0)

    # LP locked if lpLockedPct >= 50% (standard Solana degen threshold)
    lp_locked_pct: float = data.get("lpLockedPct", 0.0)
    lp_locked = lp_locked_pct >= 50.0

    # Top holder percentage — first entry in sorted topHolders list
    top_holders: list[dict] = data.get("topHolders", [])
    top_holder_pct = float(top_holders[0].get("pct", 0.0)) if top_holders else 0.0

    # Authority flags — non-null address means authority is still active (red flag)
    freeze_authority = data.get("freezeAuthority") is not None
    mint_authority = data.get("mintAuthority") is not None

    return RugCheckResult(
        mint_address=discovery.mint_address,
        symbol=discovery.symbol,
        is_rug=is_rug,
        rug_score=rug_score,
        lp_locked=lp_locked,
        top_holder_pct=top_holder_pct,
        freeze_authority=freeze_authority,
        mint_authority=mint_authority,
        discovery=discovery,  # real discovery embedded directly
    )


def _conservative_fallback(discovery: TokenDiscovery) -> RugCheckResult:
    """
    Return a conservative result when the RugCheck API is unavailable.
    All authority flags are True and rug_score is 50 — high caution without
    being a definitive rug call.  The Analyst's threshold gates broadcast.
    """
    return RugCheckResult(
        mint_address=discovery.mint_address,
        symbol=discovery.symbol,
        is_rug=False,
        rug_score=50.0,
        lp_locked=False,
        top_holder_pct=100.0,
        freeze_authority=True,
        mint_authority=True,
        discovery=discovery,
    )


def _cache_get(mint_address: str) -> RugCheckResult | None:
    if mint_address in _rug_cache:
        _rug_cache.move_to_end(mint_address)
        return _rug_cache[mint_address]
    return None


def _cache_set(mint_address: str, result: RugCheckResult) -> None:
    if mint_address in _rug_cache:
        _rug_cache.move_to_end(mint_address)
    _rug_cache[mint_address] = result
    if len(_rug_cache) > _CACHE_MAX:
        _rug_cache.popitem(last=False)  # evict oldest


# ---------------------------------------------------------------------------
# Agent lifecycle
# ---------------------------------------------------------------------------


@agent.on_event("startup")
async def on_startup(ctx: Context) -> None:
    ctx.logger.info("HistorianAgent starting up (address: %s)", agent.address)

    # FIX CRITICAL-1: pure address derivation, no Agent() side-effects
    analyst_address = _peer_address(settings.analyst_seed)
    ctx.storage.set("analyst_address", analyst_address)
    ctx.logger.info("Analyst target address: %s", analyst_address)


@agent.on_event("shutdown")
async def on_shutdown(ctx: Context) -> None:
    ctx.logger.info("HistorianAgent shut down.")


# ---------------------------------------------------------------------------
# Message handler — TokenDiscovery from ScoutAgent
# ---------------------------------------------------------------------------


@historian_protocol.on_message(model=TokenDiscovery)
async def handle_discovery(ctx: Context, sender: str, msg: TokenDiscovery) -> None:
    # Prefer the address cached by on_startup; derive from seed as a fallback
    # so a Bureau startup race condition never silently drops a TokenDiscovery.
    analyst_address: str | None = ctx.storage.get("analyst_address")
    if analyst_address is None:
        ctx.logger.warning(
            "analyst_address not in storage (startup race?); "
            "deriving from seed and caching now."
        )
        analyst_address = _peer_address(settings.analyst_seed)
        ctx.storage.set("analyst_address", analyst_address)

    ctx.logger.info(
        "Received TokenDiscovery: mint=%s symbol=%s from %s",
        msg.mint_address,
        msg.symbol,
        sender,
    )

    # --- Cache check ----------------------------------------------------------
    cached = _cache_get(msg.mint_address)
    if cached is not None:
        ctx.logger.debug("Cache hit for %s — reusing rug-check result.", msg.mint_address)
        # FIX HIGH-1/2: reconstruct with fresh discovery — no model_copy, no sentinel
        refreshed = RugCheckResult(
            mint_address=cached.mint_address,
            symbol=cached.symbol,
            is_rug=cached.is_rug,
            rug_score=cached.rug_score,
            lp_locked=cached.lp_locked,
            top_holder_pct=cached.top_holder_pct,
            freeze_authority=cached.freeze_authority,
            mint_authority=cached.mint_authority,
            discovery=msg,  # always use the freshest discovery
        )
        await ctx.send(analyst_address, refreshed)
        return

    # --- RugCheck.xyz API call ------------------------------------------------
    url = RUGCHECK_API.format(mint=msg.mint_address)
    result: RugCheckResult

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=RUGCHECK_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

        # FIX HIGH-1/2: discovery passed in directly — no sentinel, no model_copy
        result = _parse_rugcheck_response(msg, data)
        _cache_set(msg.mint_address, result)

        ctx.logger.info(
            "RugCheck: mint=%s rug_score=%.1f is_rug=%s lp_locked=%s",
            msg.mint_address,
            result.rug_score,
            result.is_rug,
            result.lp_locked,
        )

    except httpx.HTTPStatusError as exc:
        ctx.logger.warning(
            "RugCheck HTTP %d for %s — using conservative fallback.",
            exc.response.status_code,
            msg.mint_address,
        )
        result = _conservative_fallback(msg)

    except httpx.RequestError as exc:
        ctx.logger.warning(
            "RugCheck request error for %s (%s) — using conservative fallback.",
            msg.mint_address,
            exc,
        )
        result = _conservative_fallback(msg)

    # Forward to AnalystAgent regardless of success/fallback
    await ctx.send(analyst_address, result)
    ctx.logger.debug("Forwarded RugCheckResult for %s to Analyst.", msg.mint_address)


# ---------------------------------------------------------------------------
# Register protocol
# ---------------------------------------------------------------------------
agent.include(historian_protocol)