"""
protocols.py — MoonScout uagents message models and Protocol definitions.

All inter-agent communication is typed via uagents.Model subclasses.

## Protocol design rules (important)

1. Protocol.digest IS stable from construction — it is a SHA-256 hash of
   (name, version), NOT of registered handlers.  Import order does not affect
   digest stability.

2. NEVER register @some_protocol.on_message handlers on the Protocol singletons
   defined here.  If multiple agent modules register handlers on the same Protocol
   object, the last registration wins and earlier handlers are silently dropped.

3. Each agent that needs to RECEIVE a broadcast must create its OWN Protocol
   instance with the same (name, version) as the sender's target:

       # In the agent module — own instance, same name+version → same digest
       from uagents import Protocol
       notifier_protocol = Protocol(name="NotifierProtocol", version="1.0")
       @notifier_protocol.on_message(model=IntelligenceReport)
       async def handle_report(...): ...
       agent.include(notifier_protocol)

4. The singletons here are DIGEST REFERENCES only — used by the broadcasting
   agent (AnalystAgent) to get the target digest without registering any handlers.

Message flow:
    ScoutAgent  --[TokenDiscovery]-->  HistorianAgent      (scout_protocol)
    HistorianAgent --[RugCheckResult]--> AnalystAgent      (analyst_protocol)
    AnalystAgent --[IntelligenceReport]--> (broadcast)     (NotifierProtocol digest)
"""

from uagents import Model, Protocol


# ---------------------------------------------------------------------------
# Message Models
# ---------------------------------------------------------------------------


class TokenDiscovery(Model):
    """Emitted by ScoutAgent for each newly discovered Solana token mint."""

    mint_address: str
    symbol: str
    name: str
    decimals: int
    supply: float
    creator_address: str
    # ISO-8601 string — uagents Model doesn't serialize datetime natively
    created_at: str
    # Data source identifier, e.g. "helius_rpc" or "helius_webhook"
    source: str
    # Raw metadata dict from the RPC/webhook response for downstream use
    raw_metadata: dict


class RugCheckResult(Model):
    """
    Emitted by HistorianAgent after querying the RugCheck.xyz API.
    Carries the original TokenDiscovery forward so AnalystAgent has full context.
    """

    mint_address: str
    symbol: str
    is_rug: bool
    # 0–100: higher = more suspicious / likely rug
    rug_score: float
    lp_locked: bool
    # Percentage held by the single largest wallet (0.0–100.0)
    top_holder_pct: float
    # True = freeze authority still active (red flag)
    freeze_authority: bool
    # True = mint authority still active (red flag)
    mint_authority: bool
    # Pass the original discovery forward for ML feature construction
    discovery: TokenDiscovery


class IntelligenceReport(Model):
    """
    Broadcast by AnalystAgent to all registered notifier agents.
    Intentionally lightweight — notifiers re-fetch the full document from
    Atlas (get_latest_intelligence) before posting so they always have the
    most current data.  (MongoDB Atlas Prize Track PC-2/3/4)
    """

    mint_address: str
    symbol: str
    name: str
    # Degen Score produced by the ML layer (0–100)
    degen_score: float
    rug_score: float
    lp_locked: bool
    # Stringified MongoDB _id of the saved TokenIntelligence document
    intelligence_id: str


# ---------------------------------------------------------------------------
# Protocol Objects
# ---------------------------------------------------------------------------
# Each Protocol gets a deterministic digest derived from its (name, version).
# Agents broadcast on notifier_protocol.digest so all three notifier agents
# receive the IntelligenceReport regardless of their individual addresses.

# Digest-reference singletons — DO NOT register handlers on these objects.
# See module docstring for why each agent creates its own Protocol instance.
scout_protocol = Protocol(name="ScoutProtocol", version="1.0")
historian_protocol = Protocol(name="HistorianProtocol", version="1.0")
analyst_protocol = Protocol(name="AnalystProtocol", version="1.0")
notifier_protocol = Protocol(name="NotifierProtocol", version="1.0")

# Stable from construction — safe to read at import time
NOTIFIER_PROTOCOL_DIGEST: str = notifier_protocol.digest
