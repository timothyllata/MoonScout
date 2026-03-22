"""
run_all.py — MoonScout Bureau entry point.

Runs all 5 agents in a single asyncio process using uagents Bureau.
All agent logs appear in one terminal window — ideal for demo.

Import order matters:
  1. Notifier agents are imported FIRST so their @notifier_protocol.on_message
     decorators run before AnalystAgent reads notifier_protocol.digest.
  2. AnalystAgent is imported after notifiers for the same reason.
  3. Scout and Historian have no digest dependency — order is flexible.

Usage:
    python -m moonscout.agents.run_all
    # or via pyproject.toml script:
    moonscout
"""

import logging
import sys

from uagents import Bureau

# ---------------------------------------------------------------------------
# Logging — single handler so all 5 agents share one formatted output stream
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-22s] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
# Silence noisy third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Import agents
# CRITICAL: notifier agents BEFORE analyst so notifier_protocol.digest is stable
# ---------------------------------------------------------------------------
# Step 1 — register @notifier_protocol.on_message handlers (Discord only now)
from moonscout.agents.discord_agent import agent as discord_agent    # noqa: E402

# Step 2 — analyst reads notifier_protocol.digest at startup (safe now)
from moonscout.agents.analyst import agent as analyst_agent          # noqa: E402

# Step 3 — no digest dependency
from moonscout.agents.scout import agent as scout_agent              # noqa: E402
from moonscout.agents.historian import agent as historian_agent      # noqa: E402
from moonscout.agents.telegram_agent import agent as telegram_agent  # noqa: E402

# ---------------------------------------------------------------------------
# Bureau
# ---------------------------------------------------------------------------
bureau = Bureau(port=8000, endpoint="http://localhost:8000/submit")

bureau.add(scout_agent)
bureau.add(historian_agent)
bureau.add(analyst_agent)
bureau.add(discord_agent)
bureau.add(telegram_agent)


_AGENT_COUNT = 5  # scout, historian, analyst, discord, telegram


def main() -> None:
    logging.getLogger(__name__).info(
        "Starting MoonScout Bureau with %d agents...", _AGENT_COUNT
    )
    bureau.run()


if __name__ == "__main__":
    main()
