# MoonScout

A real-time Solana token intelligence system built with the Fetch.ai uAgents framework. MoonScout discovers new token mints on-chain and from Telegram trading channels, assesses their risk using RugCheck.xyz, scores them with an XGBoost ML model, persists intelligence to MongoDB Atlas, and delivers alerts to Discord.

---

## Architecture

MoonScout runs as a Bureau of 5 autonomous agents communicating via typed uAgents protocols:

```
ScoutAgent       ──[TokenDiscovery]──►
TelegramAgent    ──[TokenDiscovery]──► HistorianAgent ──[RugCheckResult]──► AnalystAgent ──► DiscordAgent
                                                                                  │
                                                                            MongoDB Atlas
```

| Agent | Role |
|-------|------|
| **ScoutAgent** | Polls Helius RPC every 120s for new SPL Token and Token-2022 mints |
| **TelegramAgent** | Monitors Telegram channels via Telethon for mint addresses |
| **HistorianAgent** | Calls RugCheck.xyz API for on-chain risk signals |
| **AnalystAgent** | Scores tokens with XGBoost (AUC 0.985), saves to Atlas, alerts Discord |
| **DiscordAgent** | Posts rich embeds to a Discord webhook |

---

## Features

- Dual discovery: on-chain RPC polling + Telegram social signal scraping
- XGBoost ML model trained on 5 risk features with 98.5% AUC
- Heuristic fallback scorer if model file is unavailable
- MongoDB Atlas deduplication — no token is processed twice
- Colour-coded Discord alerts (green / yellow / orange by score)
- Weights & Biases experiment tracking for the ML model
- Flask frontend displaying live token intelligence feed

---

## Requirements

- Python 3.11+
- MongoDB Atlas account (free tier works)
- Helius API key (free tier)
- Telegram account + API credentials (my.telegram.org)
- Discord webhook URL

---

## Setup

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/timothyllata/MoonScout.git
cd MoonScout
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
```

### 2. Install dependencies

```bash
pip install -e .
```

### 3. Configure environment variables

Copy the example below into a `.env` file in the project root:

```env
# MongoDB Atlas (must use mongodb+srv:// URI)
MONGODB_CONNECTION_URI=mongodb+srv://<user>:<pass>@<cluster>.mongodb.net/

# Helius RPC
HELIUS_API_KEY=your_helius_api_key
SCOUT_POLL_INTERVAL=120

# Telegram (user-account API — from my.telegram.org)
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_CHANNELS=channel1,channel2
TELEGRAM_SESSION_NAME=moonscout_telegram

# Discord
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# uAgents seeds (any random secret strings)
SCOUT_SEED=your_scout_seed
HISTORIAN_SEED=your_historian_seed
ANALYST_SEED=your_analyst_seed
TELEGRAM_AGENT_SEED=your_telegram_seed
DISCORD_AGENT_SEED=your_discord_seed

# ML scoring threshold (0–100)
DEGEN_SCORE_THRESHOLD=70.0
```

### 4. Authenticate Telegram (first run only)

```bash
python test_telegram.py
```

Follow the prompts to enter your phone number and the code sent to your Telegram app. This saves a session file so subsequent runs are silent.

### 5. Train the XGBoost model

```bash
python -m moonscout.ml.train
```

Generates `moonscout/ml/model.bst`. The AnalystAgent automatically uses XGBoost mode when this file exists, falling back to the heuristic scorer otherwise.

---

## Running

### Agents (the backend pipeline)

```bash
python -m moonscout.agents.run_all
```

### Frontend (live token feed)

In a second terminal:

```bash
python app.py
```

Open `http://127.0.0.1:5000` in your browser.

---

## ML Model

The DegenScorer uses a two-tier strategy:

- **Tier 1 — Heuristic**: Weighted formula, always available, zero cold-start
- **Tier 2 — XGBoost**: Binary classifier trained on 5 RugCheck features

| Feature | Description |
|---------|-------------|
| `rug_score` | RugCheck.xyz aggregate risk score (0–100) |
| `lp_locked` | Liquidity pool locked status |
| `top_holder_pct` | % of supply held by largest wallet |
| `freeze_authority` | Creator can freeze token accounts |
| `mint_authority` | Creator can mint unlimited supply |

Training results: **AUC 0.985 · Accuracy 92.8%** on held-out test set.

Experiment tracking: [wandb.ai/tllata-uci/moonscout](https://wandb.ai/tllata-uci/moonscout)

---

## Project Structure

```
moonscout/
├── agents/
│   ├── scout.py          # On-chain mint discovery
│   ├── telegram_agent.py # Telegram channel scraper
│   ├── historian.py      # RugCheck.xyz risk assessment
│   ├── analyst.py        # ML scoring + Atlas persistence
│   ├── discord_agent.py  # Discord webhook notifier
│   └── run_all.py        # Bureau entrypoint
├── ml/
│   ├── scorer.py         # DegenScorer (heuristic + XGBoost)
│   └── train.py          # Synthetic data generator + XGBoost trainer
├── config.py             # Pydantic settings (validated at startup)
├── database.py           # MongoDB Atlas async utilities
└── protocols.py          # uAgents message models
app.py                    # Flask frontend
```

---

## Built With

- [Fetch.ai uAgents](https://fetch.ai) — multi-agent framework
- [MongoDB Atlas](https://www.mongodb.com/atlas) — cloud database
- [RugCheck.xyz](https://rugcheck.xyz) — Solana token risk API
- [Helius](https://helius.dev) — Solana RPC
- [Telethon](https://github.com/LonamiWebs/Telethon) — Telegram client
- [XGBoost](https://xgboost.readthedocs.io) — ML model
- [Weights & Biases](https://wandb.ai) — ML experiment tracking
