"""
connect_mailbox.py — Connect one agent at a time to Agentverse.

Usage:
    python connect_mailbox.py scout
    python connect_mailbox.py historian
    python connect_mailbox.py analyst
    python connect_mailbox.py telegram_agent
    python connect_mailbox.py discord_agent
    python connect_mailbox.py x_agent

Steps for each agent:
  1. Run the command above (keep it running)
  2. Open the printed Inspector URL in your browser
  3. Click Connect → select Mailbox
  4. Ctrl+C, then run the next agent
"""

import sys
import subprocess

AGENTS = {
    "scout":         ("neurosciout.agents.scout",         8001),
    "historian":     ("neurosciout.agents.historian",     8002),
    "analyst":       ("neurosciout.agents.analyst",       8003),
    "telegram_agent":("neurosciout.agents.telegram_agent",8004),
    "discord_agent": ("neurosciout.agents.discord_agent", 8005),
    "x_agent":       ("neurosciout.agents.x_agent",       8006),
}

if len(sys.argv) != 2 or sys.argv[1] not in AGENTS:
    print(f"Usage: python connect_mailbox.py <agent>")
    print(f"Agents: {', '.join(AGENTS)}")
    sys.exit(1)

name = sys.argv[1]
module, port = AGENTS[name]

# Print the inspector URL before launching
print(f"\n{'='*70}")
print(f"Open this URL in your browser to connect {name} to Agentverse:")
print(f"  https://agentverse.ai/inspect/?uri=http%3A%2F%2F127.0.0.1%3A{port}&address=")
print(f"  (address will be printed in the agent logs below)")
print(f"{'='*70}")
print("Click Connect → select Mailbox, then Ctrl+C when done.\n")

# Run the agent as a subprocess — clean event loop, no import-time conflicts
subprocess.run([sys.executable, "-c", f"from {module} import agent; agent.run()"])