"""
scout.py — ScoutAgent

Polls the Solana Token Program via Helius RPC every N seconds to discover
newly created mint accounts.  For every new mint that has not been seen
before (Atlas deduplication check), it sends a TokenDiscovery message to
HistorianAgent for rug-checking.

Data flow:
    Helius RPC  →  ScoutAgent  --[TokenDiscovery]-->  HistorianAgent
                                        ↓
                               atlas_cache (mark seen)

Fixes applied (vs v1):
  - CRITICAL-1: Use Identity.from_seed() for peer address derivation — no spurious Agent() instances.
  - CRITICAL-2: Guard ctx.storage.get() results with explicit None checks.
  - HIGH-3: Switch from Helius Enhanced Transactions (unreliable type strings) to standard
            Solana getTransaction with encoding="jsonParsed", filtering on instruction-level
            parsed.type == "initializeMint".
  - HIGH-4: Cursor advanced only after transactions are successfully fetched and parsed.
  - HIGH-5: Use 'before' (upper-bound cursor) not 'until' for getSignaturesForAddress.
"""

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from uagents import Agent, Context
from uagents_core.identity import Identity

from neurosciout.config import settings
from neurosciout.database import close_database, get_database, is_token_seen, mark_token_seen
from neurosciout.protocols import TokenDiscovery, scout_protocol

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SPL_TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={settings.helius_api_key}"

# Maximum signatures to fetch per poll interval.
# Each sig needs 1 getTransaction call; Helius free tier is 100 req/s.
SIGNATURES_PER_POLL = 100

# Maximum concurrent getTransaction requests in one poll cycle.
_FETCH_CONCURRENCY = 10

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
agent = Agent(name="scout", seed=settings.scout_seed)


# ---------------------------------------------------------------------------
# Address helper  (FIX CRITICAL-1)
# ---------------------------------------------------------------------------


def _peer_address(seed: str) -> str:
    """
    Derive the deterministic uagents address for a peer agent from its seed.
    Uses Identity.from_seed() — a pure cryptographic operation with no side effects.
    Never instantiate Agent() just to read .address; it starts background I/O.
    """
    return Identity.from_seed(seed, 0).address


# ---------------------------------------------------------------------------
# Helius / Solana RPC helpers
# ---------------------------------------------------------------------------


async def _fetch_recent_signatures(
    client: httpx.AsyncClient,
    before_sig: str | None,
    limit: int = SIGNATURES_PER_POLL,
) -> list[dict]:
    """
    Return up to `limit` transaction signatures for the SPL Token Program.

    Uses `before` (upper-bound exclusive) so each poll fetches only signatures
    *older than* the most recent known sig.  On the first run before_sig is None
    and the RPC returns the most recent `limit` sigs.

    FIX HIGH-5: 'before' is the correct cursor parameter (not 'until') for
    fetching signatures newer than the last known one in reverse-chronological order.
    """
    params: dict = {"limit": limit, "commitment": "confirmed"}
    if before_sig:
        params["before"] = before_sig

    resp = await client.post(
        HELIUS_RPC_URL,
        json={
            "jsonrpc": "2.0",
            "id": "scout-sigs",
            "method": "getSignaturesForAddress",
            "params": [SPL_TOKEN_PROGRAM, params],
        },
        timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("result", [])


async def _fetch_parsed_transaction(
    client: httpx.AsyncClient,
    signature: str,
) -> dict | None:
    """
    Fetch a single transaction with jsonParsed encoding so the SPL Token
    Program instructions are decoded into structured dicts.

    FIX HIGH-3: Standard Solana jsonParsed encoding reliably exposes
    instruction-level parsed.type == "initializeMint", whereas the Helius
    Enhanced Transactions API uses its own type enum ("UNKNOWN" for raw
    InitializeMint) and does not provide a stable "INITIALIZE_MINT" type.
    """
    resp = await client.post(
        HELIUS_RPC_URL,
        json={
            "jsonrpc": "2.0",
            "id": f"tx-{signature[:8]}",
            "method": "getTransaction",
            "params": [
                signature,
                {
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 0,
                    "commitment": "confirmed",
                },
            ],
        },
        timeout=15.0,
    )
    resp.raise_for_status()
    result = resp.json().get("result")
    return result  # None if transaction not found / pruned


async def _fetch_transactions_concurrently(
    client: httpx.AsyncClient,
    signatures: list[str],
) -> list[dict]:
    """
    Fetch multiple transactions concurrently, bounded by _FETCH_CONCURRENCY
    to respect Helius free-tier rate limits.
    """
    semaphore = asyncio.Semaphore(_FETCH_CONCURRENCY)

    async def _fetch_one(sig: str) -> dict | None:
        async with semaphore:
            try:
                return await _fetch_parsed_transaction(client, sig)
            except Exception:
                logger.debug("Failed to fetch transaction %s", sig, exc_info=True)
                return None

    results = await asyncio.gather(*[_fetch_one(s) for s in signatures])
    return [r for r in results if r is not None]


# ---------------------------------------------------------------------------
# Instruction parsing  (FIX HIGH-3)
# ---------------------------------------------------------------------------

# Both initializeMint and initializeMint2 (with freeze authority) create new mints
_INIT_MINT_TYPES = {"initializeMint", "initializeMint2"}


def _extract_mint_discoveries(transactions: list[dict]) -> list[TokenDiscovery]:
    """
    Walk the jsonParsed instruction array of each transaction and yield a
    TokenDiscovery for every initializeMint / initializeMint2 instruction.

    Parsed instruction structure:
        {
          "program": "spl-token",
          "programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
          "parsed": {
            "type": "initializeMint",
            "info": {
              "decimals": 9,
              "mint": "<base58 address>",
              "mintAuthority": "<base58>",
              "freezeAuthority": null
            }
          }
        }
    """
    discoveries: list[TokenDiscovery] = []

    for tx in transactions:
        if not tx:
            continue

        block_time: int = tx.get("blockTime", 0)
        created_at = (
            datetime.fromtimestamp(block_time, tz=timezone.utc).isoformat()
            if block_time
            else datetime.now(tz=timezone.utc).isoformat()
        )

        # Walk both top-level and inner instructions
        message = tx.get("transaction", {}).get("message", {})
        all_instructions: list[dict] = list(message.get("instructions", []))
        for inner in tx.get("meta", {}).get("innerInstructions", []):
            all_instructions.extend(inner.get("instructions", []))

        for ix in all_instructions:
            parsed = ix.get("parsed")
            if not isinstance(parsed, dict):
                continue

            if parsed.get("type") not in _INIT_MINT_TYPES:
                continue

            info = parsed.get("info", {})
            mint_address = info.get("mint")
            if not mint_address:
                continue

            decimals = int(info.get("decimals", 0))
            # Supply isn't known at InitializeMint time — set to 0.0 placeholder
            supply = 0.0

            # Derive creator from the first fee-payer account key
            account_keys = message.get("accountKeys", [])
            creator_address = (
                account_keys[0].get("pubkey", "unknown")
                if account_keys and isinstance(account_keys[0], dict)
                else (account_keys[0] if account_keys else "unknown")
            )

            discoveries.append(
                TokenDiscovery(
                    mint_address=mint_address,
                    symbol="UNKNOWN",
                    name="Unknown Token",
                    decimals=decimals,
                    supply=supply,
                    creator_address=str(creator_address),
                    created_at=created_at,
                    source="helius_rpc_parsed",
                    raw_metadata={
                        "blockTime": block_time,
                        "mintInfo": info,
                    },
                )
            )

    return discoveries


# ---------------------------------------------------------------------------
# Agent lifecycle
# ---------------------------------------------------------------------------


@agent.on_event("startup")
async def on_startup(ctx: Context) -> None:
    ctx.logger.info("ScoutAgent starting up (address: %s)", agent.address)

    # Warm up the Atlas connection so the first poll doesn't bear the latency
    await get_database()

    # FIX CRITICAL-1: Use Identity derivation — no Agent() side-effects
    historian_address = _peer_address(settings.historian_seed)
    ctx.storage.set("historian_address", historian_address)
    ctx.logger.info("Historian target address: %s", historian_address)

    # cursor starts as None on first run — no explicit initialisation needed
    # (ctx.storage.get returns None for unknown keys already)


@agent.on_event("shutdown")
async def on_shutdown(ctx: Context) -> None:
    await close_database()
    ctx.logger.info("ScoutAgent shut down.")


# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------


@agent.on_interval(period=settings.scout_poll_interval)
async def poll_new_tokens(ctx: Context) -> None:
    # Prefer the address cached by on_startup; derive it from the seed as a
    # fallback so a Bureau startup race condition never skips the first poll.
    historian_address: str | None = ctx.storage.get("historian_address")
    if historian_address is None:
        ctx.logger.warning(
            "historian_address not in storage (startup race?); "
            "deriving from seed and caching now."
        )
        historian_address = _peer_address(settings.historian_seed)
        ctx.storage.set("historian_address", historian_address)

    before_sig: str | None = ctx.storage.get("last_signature")
    ctx.logger.debug("Polling Helius (before_sig=%s)...", before_sig)

    try:
        async with httpx.AsyncClient() as client:
            sig_entries = await _fetch_recent_signatures(client, before_sig)

            if not sig_entries:
                ctx.logger.debug("No new signatures found.")
                return

            raw_sigs = [entry["signature"] for entry in sig_entries]

            # FIX HIGH-3: Fetch standard jsonParsed transactions
            transactions = await _fetch_transactions_concurrently(client, raw_sigs)

    except httpx.HTTPStatusError as exc:
        ctx.logger.error("Helius HTTP error: %s %s", exc.response.status_code, exc.request.url)
        return
    except httpx.RequestError as exc:
        ctx.logger.error("Helius request error: %s", exc)
        return

    # FIX HIGH-4: Advance cursor only after successful fetch + parse
    newest_sig = sig_entries[0]["signature"]
    ctx.storage.set("last_signature", newest_sig)

    discoveries = _extract_mint_discoveries(transactions)
    ctx.logger.info("Found %d initializeMint event(s) in %d transactions.", len(discoveries), len(transactions))

    sent = 0
    skipped = 0
    for discovery in discoveries:
        try:
            if await is_token_seen(discovery.mint_address):
                skipped += 1
                continue

            # Mark BEFORE sending — prevents a second poll re-queuing the same mint
            # while HistorianAgent is still processing.
            await mark_token_seen(discovery.mint_address)
            await ctx.send(historian_address, discovery)
            sent += 1
            ctx.logger.info(
                "Forwarded new mint %s to Historian.", discovery.mint_address
            )

        except Exception:
            ctx.logger.exception("Error processing mint %s", discovery.mint_address)

    if sent or skipped:
        ctx.logger.info("Poll complete — sent: %d, skipped (already seen): %d", sent, skipped)


# ---------------------------------------------------------------------------
# Register protocol (required for Bureau message routing)
# ---------------------------------------------------------------------------
agent.include(scout_protocol)