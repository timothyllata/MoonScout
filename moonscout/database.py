"""
database.py — MongoDB Atlas async utility for MoonScout.

Provides five public coroutines that cover all MongoDB Atlas Prize Track
compliance requirements:

    get_database()                  → AsyncIOMotorDatabase
    is_token_seen(mint_address)     → bool          (atlas_cache, PC-5)
    mark_token_seen(mint_address)   → None          (atlas_cache, PC-5/PC-6)
    save_intelligence(doc)          → str           (token_intelligence, PC-1/PC-7)
    get_latest_intelligence(mint)   → dict | None   (token_intelligence, PC-2/3/4)

IMPORTANT: Do NOT call get_database() at module-import time.
Call it inside an agent's on_event("startup") handler so the Motor client
is created inside the running uagents event loop, not before it starts.
"""

import asyncio
import logging
from datetime import datetime, timezone

import motor.motor_asyncio
from pymongo import DESCENDING, IndexModel, ASCENDING
from pymongo.errors import ConnectionFailure, DuplicateKeyError, NetworkTimeout

from moonscout.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level client — initialised lazily on first get_database() call.
# Shared across all agents that run in the same Bureau process.
# ---------------------------------------------------------------------------
_client: motor.motor_asyncio.AsyncIOMotorClient | None = None
_db: motor.motor_asyncio.AsyncIOMotorDatabase | None = None
# Lock prevents double-initialisation when multiple agents start concurrently.
_init_lock: asyncio.Lock | None = None

# Collection names as constants so they're easy to find during code review
# and visible to prize-track judges.
COLLECTION_CACHE = "atlas_cache"
COLLECTION_INTELLIGENCE = "token_intelligence"
DB_NAME = "moonscout"


# ---------------------------------------------------------------------------
# Connection factory
# ---------------------------------------------------------------------------


async def get_database() -> motor.motor_asyncio.AsyncIOMotorDatabase:
    """
    Return the shared Motor database handle, creating the client on first call.

    Also ensures Atlas indexes exist (idempotent — safe to call multiple times).
    The Atlas connection URI must use the mongodb+srv:// scheme (PC-10).
    The URI format is validated by pydantic-settings at startup; no check needed here.
    """
    global _client, _db, _init_lock

    # Fast path — already initialised
    if _db is not None:
        return _db

    # Lazy lock creation: asyncio.Lock() must be created inside a running loop.
    if _init_lock is None:
        _init_lock = asyncio.Lock()

    async with _init_lock:
        # Re-check under lock — another coroutine may have initialised while we waited.
        if _db is not None:
            return _db

        _client = motor.motor_asyncio.AsyncIOMotorClient(
            settings.mongodb_connection_uri,
            # Opt-in to async-safe UUIDs and datetimes
            uuidRepresentation="standard",
            # Surface server-side timeouts as Python exceptions after 10 s
            serverSelectionTimeoutMS=10_000,
        )
        _db = _client[DB_NAME]

        await _ensure_indexes(_db)
        logger.info("MongoDB Atlas connected — database: %s", DB_NAME)
        return _db


async def close_database() -> None:
    """
    Gracefully close the Motor client.
    Call from an agent's on_event("shutdown") handler.

    Note: AsyncIOMotorClient.close() is intentionally synchronous — Motor
    schedules the shutdown internally.  The function is async only so callers
    can use a consistent `await close_database()` pattern.
    """
    global _client, _db
    if _client is not None:
        _client.close()  # sync by Motor design — no await needed
        _client = None
        _db = None
        logger.info("MongoDB Atlas connection closed.")


# ---------------------------------------------------------------------------
# Index bootstrap (called once at startup)
# ---------------------------------------------------------------------------


async def _ensure_indexes(db: motor.motor_asyncio.AsyncIOMotorDatabase) -> None:
    """Create required Atlas indexes if they don't already exist."""

    # atlas_cache: unique index on mint_address for O(1) dedup lookups
    # TTL index expires entries after 30 days to cap free-tier storage
    await db[COLLECTION_CACHE].create_indexes(
        [
            IndexModel([("mint_address", ASCENDING)], unique=True, name="mint_address_unique"),
            IndexModel(
                [("seen_at", ASCENDING)],
                expireAfterSeconds=30 * 24 * 60 * 60,  # 30 days
                name="seen_at_ttl",
            ),
        ]
    )

    # token_intelligence: compound index for notifier queries (mint + recency)
    # plus a score index for future leaderboard / aggregation queries
    await db[COLLECTION_INTELLIGENCE].create_indexes(
        [
            IndexModel(
                [("mint_address", ASCENDING), ("scored_at", DESCENDING)],
                name="mint_scored_compound",
            ),
            IndexModel([("degen_score", DESCENDING)], name="degen_score_desc"),
        ]
    )

    logger.debug("Atlas indexes verified.")


# ---------------------------------------------------------------------------
# Deduplication — atlas_cache collection  (PC-5, PC-6)
# ---------------------------------------------------------------------------


async def is_token_seen(mint_address: str) -> bool:
    """
    Return True if this mint address has already been processed.
    Used by ScoutAgent before forwarding a TokenDiscovery to HistorianAgent.

    Complexity: O(1) — indexed find_one on atlas_cache.
    """
    db = await get_database()
    doc = await db[COLLECTION_CACHE].find_one(
        {"mint_address": mint_address},
        # Only fetch the _id field — we only need to know existence
        projection={"_id": 1},
    )
    return doc is not None


async def mark_token_seen(mint_address: str) -> None:
    """
    Insert the mint address into atlas_cache, marking it as seen.
    Silently ignores DuplicateKeyError — concurrent scouts won't crash.

    Call this BEFORE sending TokenDiscovery to HistorianAgent so that a
    second Scout poll during slow historian processing doesn't re-queue
    the same token.
    """
    db = await get_database()
    try:
        await db[COLLECTION_CACHE].insert_one(
            {
                "mint_address": mint_address,
                "seen_at": datetime.now(tz=timezone.utc),
            }
        )
        logger.debug("atlas_cache: marked %s as seen", mint_address)
    except DuplicateKeyError:
        # Another coroutine beat us — this is expected under concurrent scouts
        logger.debug("atlas_cache: %s already present (race condition, ignoring)", mint_address)
    except (ConnectionFailure, NetworkTimeout):
        # Atlas is unreachable — re-raise so the caller (ScoutAgent) can back off
        # rather than silently proceeding with a broken connection.
        logger.exception("atlas_cache: Atlas connection error marking %s", mint_address)
        raise
    except Exception:
        logger.exception("atlas_cache: unexpected error marking %s as seen", mint_address)


# ---------------------------------------------------------------------------
# Intelligence Hub — token_intelligence collection  (PC-1, PC-7)
# ---------------------------------------------------------------------------


async def save_intelligence(doc: dict) -> str:
    """
    Upsert a TokenIntelligence document into the token_intelligence collection.

    The doc dict must contain at minimum:
        mint_address  str   — used as the upsert key
        symbol        str
        name          str
        discovery     dict  — serialised TokenDiscovery
        rug_check     dict  — serialised RugCheckResult
        degen_score   float
        scored_at     datetime
        broadcast_sent bool

    Returns the stringified MongoDB _id of the upserted document.

    Called by AnalystAgent BEFORE ctx.broadcast so notifiers always find
    the document when they query Atlas.  (Atlas Prize Track PC-1)
    """
    db = await get_database()

    # Always work on a defensive copy — never mutate the caller's dict.
    payload = {**doc}
    if "scored_at" not in payload:
        payload["scored_at"] = datetime.now(tz=timezone.utc)

    result = await db[COLLECTION_INTELLIGENCE].update_one(
        {"mint_address": payload["mint_address"]},
        {"$set": payload},
        upsert=True,
    )

    # upserted_id is set on INSERT; on UPDATE it is None — fetch separately.
    if result.upserted_id is not None:
        doc_id = result.upserted_id
    else:
        fallback = await db[COLLECTION_INTELLIGENCE].find_one(
            {"mint_address": payload["mint_address"]}, projection={"_id": 1}
        )
        if fallback is None:
            raise RuntimeError(
                f"save_intelligence: document for {payload['mint_address']} "
                "vanished immediately after upsert — Atlas write may have failed."
            )
        doc_id = fallback["_id"]

    logger.info(
        "token_intelligence: saved %s (score=%.1f) id=%s",
        payload["mint_address"],
        payload.get("degen_score", 0.0),
        doc_id,
    )
    return str(doc_id)


# ---------------------------------------------------------------------------
# Notifier Query — token_intelligence collection  (PC-2, PC-3, PC-4)
# ---------------------------------------------------------------------------


async def get_latest_intelligence(mint_address: str) -> dict | None:
    """
    Fetch the most recently scored TokenIntelligence document for a mint.

    Called by TelegramAgent, DiscordAgent, and XAgent before posting to
    their respective platforms.  This Atlas read is the core of the
    "Notifier Query" prize track requirement (PC-2/3/4).

    Returns the raw MongoDB document dict, or None if not found.
    Callers must handle the None case gracefully (log + skip post).
    """
    db = await get_database()
    doc = await db[COLLECTION_INTELLIGENCE].find_one(
        {"mint_address": mint_address},
        sort=[("scored_at", DESCENDING)],
    )
    if doc is None:
        logger.warning("token_intelligence: no document found for %s", mint_address)
    return doc


async def mark_broadcast_sent(mint_address: str) -> None:
    """
    Targeted update — sets broadcast_sent=True on the token_intelligence document.
    Uses $set with only the changed field to avoid overwriting scored_at or other data.
    Called by AnalystAgent after a successful ctx.broadcast.
    """
    db = await get_database()
    await db[COLLECTION_INTELLIGENCE].update_one(
        {"mint_address": mint_address},
        {"$set": {"broadcast_sent": True}},
    )
    logger.debug("token_intelligence: marked broadcast_sent=True for %s", mint_address)
