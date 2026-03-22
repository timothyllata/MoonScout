"""
analyst.py — AnalystAgent

Receives a RugCheckResult from HistorianAgent, runs the DegenScorer (heuristic
or XGBoost), persists a full TokenIntelligence document to MongoDB Atlas, and
broadcasts an IntelligenceReport to all registered notifier agents.

Data flow:
    HistorianAgent --[RugCheckResult]--> AnalystAgent
                                              │
                              ┌───────────────┼────────────────┐
                              ▼               ▼                ▼
                        Atlas save       ctx.broadcast    (threshold gate)
                    (token_intelligence) (notifier_protocol)

Atlas Prize Track:
    PC-1 — save_intelligence() called BEFORE ctx.broadcast.
    PC-7 — full TokenIntelligence document (scout data + rug-check + score).
"""

import logging
from datetime import datetime, timezone

from uagents import Agent, Context

from neurosciout.config import settings
from neurosciout.database import get_database, mark_broadcast_sent, save_intelligence
from neurosciout.ml.scorer import DegenScorer
from neurosciout.protocols import (
    NOTIFIER_PROTOCOL_DIGEST,
    IntelligenceReport,
    RugCheckResult,
    analyst_protocol,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
agent = Agent(name="analyst", seed=settings.analyst_seed)

# Scorer is instantiated at module level so the model file is loaded once
# when this module is imported (inside bureau.run() startup), not per message.
_scorer: DegenScorer | None = None


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@agent.on_event("startup")
async def on_startup(ctx: Context) -> None:
    global _scorer
    ctx.logger.info("AnalystAgent starting up (address: %s)", agent.address)

    # Warm Atlas connection
    await get_database()

    # Load scorer — logs whether it's using XGBoost or heuristic mode
    _scorer = DegenScorer()
    ctx.logger.info("DegenScorer ready (mode: %s)", _scorer.mode)
    ctx.logger.info("Notifier broadcast digest: %s", NOTIFIER_PROTOCOL_DIGEST)


@agent.on_event("shutdown")
async def on_shutdown(ctx: Context) -> None:
    ctx.logger.info("AnalystAgent shut down.")


# ---------------------------------------------------------------------------
# Message handler — RugCheckResult from HistorianAgent
# ---------------------------------------------------------------------------


@analyst_protocol.on_message(model=RugCheckResult)
async def handle_rug_check(ctx: Context, sender: str, msg: RugCheckResult) -> None:
    if _scorer is None:
        ctx.logger.error("Scorer not initialised — startup incomplete. Dropping %s.", msg.mint_address)
        return

    ctx.logger.info(
        "Received RugCheckResult: mint=%s rug_score=%.1f lp_locked=%s from %s",
        msg.mint_address, msg.rug_score, msg.lp_locked, sender,
    )

    # --- Score ----------------------------------------------------------------
    degen_score = _scorer.score(
        rug_score=msg.rug_score,
        lp_locked=msg.lp_locked,
        top_holder_pct=msg.top_holder_pct,
        freeze_authority=msg.freeze_authority,
        mint_authority=msg.mint_authority,
        is_rug=msg.is_rug,
    )

    ctx.logger.info(
        "DegenScore for %s: %.1f (threshold: %.1f, mode: %s)",
        msg.mint_address, degen_score, settings.degen_score_threshold, _scorer.mode,
    )

    if degen_score < settings.degen_score_threshold:
        ctx.logger.info(
            "Score %.1f below threshold %.1f — dropping %s.",
            degen_score, settings.degen_score_threshold, msg.mint_address,
        )
        return

    # --- Build TokenIntelligence document -------------------------------------
    intelligence_doc = {
        "mint_address": msg.mint_address,
        "symbol": msg.symbol,
        "name": msg.discovery.name,
        "discovery": {
            "mint_address": msg.discovery.mint_address,
            "symbol": msg.discovery.symbol,
            "name": msg.discovery.name,
            "decimals": msg.discovery.decimals,
            "supply": msg.discovery.supply,
            "creator_address": msg.discovery.creator_address,
            "created_at": msg.discovery.created_at,
            "source": msg.discovery.source,
            "raw_metadata": msg.discovery.raw_metadata,
        },
        "rug_check": {
            "is_rug": msg.is_rug,
            "rug_score": msg.rug_score,
            "lp_locked": msg.lp_locked,
            "top_holder_pct": msg.top_holder_pct,
            "freeze_authority": msg.freeze_authority,
            "mint_authority": msg.mint_authority,
        },
        "degen_score": degen_score,
        "scorer_mode": _scorer.mode,
        "scored_at": datetime.now(tz=timezone.utc),
        "broadcast_sent": False,  # updated to True after successful broadcast
    }

    # --- Atlas save (PC-1) — MUST happen before broadcast ---------------------
    try:
        intelligence_id = await save_intelligence(intelligence_doc)
    except Exception:
        ctx.logger.exception(
            "Failed to save TokenIntelligence for %s — aborting broadcast.",
            msg.mint_address,
        )
        return

    ctx.logger.info(
        "Saved TokenIntelligence to Atlas: id=%s mint=%s",
        intelligence_id, msg.mint_address,
    )

    # --- Build IntelligenceReport (lightweight — notifiers re-query Atlas) ----
    report = IntelligenceReport(
        mint_address=msg.mint_address,
        symbol=msg.symbol,
        name=msg.discovery.name,
        degen_score=degen_score,
        rug_score=msg.rug_score,
        lp_locked=msg.lp_locked,
        intelligence_id=intelligence_id,
    )

    # --- Broadcast to all registered notifier agents -------------------------
    # NOTIFIER_PROTOCOL_DIGEST is stable from module import (digest = hash of name+version).
    # Each notifier agent creates its own Protocol(name="NotifierProtocol", version="1.0")
    # instance so their handlers don't overwrite each other on a shared object.
    try:
        await ctx.broadcast(NOTIFIER_PROTOCOL_DIGEST, report)
        ctx.logger.info(
            "Broadcast IntelligenceReport for %s (score=%.1f) via NotifierProtocol.",
            msg.mint_address, degen_score,
        )
    except Exception:
        ctx.logger.exception("Broadcast failed for %s.", msg.mint_address)
        return

    # Targeted $set — only updates broadcast_sent, leaves scored_at intact
    try:
        await mark_broadcast_sent(msg.mint_address)
    except Exception:
        ctx.logger.warning("Could not mark broadcast_sent for %s (non-fatal).", msg.mint_address)


# ---------------------------------------------------------------------------
# Register protocol — AnalystAgent receives RugCheckResult via analyst_protocol
# ---------------------------------------------------------------------------
agent.include(analyst_protocol)
