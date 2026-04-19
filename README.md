# Narrative Momentum — Crypto Trading Experiment

**Hypothesis:** LLM-based real-time narrative detection in crypto news/social can predict cross-coin sector rotation faster than price-based indicators, generating alpha before sentiment is fully priced in.

## Architecture

3 bots run in parallel on **Binance Spot Testnet** with 1000 virtual USDT each:

| Bot | Strategy | Description |
|-----|----------|-------------|
| **Bot A** (NARRATIVE) | LLM Narrative Momentum | Ingests RSS + Reddit + CoinGecko, extracts narratives via Claude Haiku, trades on new/building narratives |
| **Bot B** (BASELINE_TA) | EMA(9/21) + RSI(14) | Classic technical analysis on BTC, ETH, SOL |
| **Bot C** (BENCHMARK) | Buy & Hold BTC | Buys BTC at t=0, holds for 7 days |

All share one SQLite database and Streamlit dashboard.

## Setup

### 1. Get API Keys

| Key | Where | Cost |
|-----|-------|------|
| Binance Testnet | [testnet.binance.vision](https://testnet.binance.vision) → GitHub Login → Generate HMAC_SHA256 Key | Free |
| Anthropic (Claude) | [console.anthropic.com](https://console.anthropic.com) | Free tier works |

**No paid APIs required.** Data sources (RSS, Reddit, CoinGecko) are all free and keyless.

### 2. Install

```bash
cd "Trading Bot"
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your keys
```

### 4. Backtest Bot B (optional)

```bash
python scripts/backtest_baseline.py
```

### 5. Run the Experiment (7 days)

```bash
# Option 1: tmux (recommended for 7-day run)
tmux new -s bots
python scripts/run_all.py
# Ctrl+B, D to detach — bots keep running

# Option 2: foreground
python scripts/run_all.py
```

### 6. Dashboard

In a separate terminal:
```bash
source .venv/bin/activate
streamlit run dashboard/app.py
# Opens at http://localhost:8501
```

## After 7 Days

```bash
python scripts/analyze_results.py
# Generates RESULTS.md with:
# - Total return, Sharpe ratio per bot
# - Win rate, avg win/loss
# - Most profitable narratives
# - LLM confidence vs profit correlation
```

## Project Structure

```
Trading Bot/
├── src/
│   ├── config.py              # Constants, env loading
│   ├── db.py                  # SQLAlchemy models
│   ├── exchange.py            # Binance testnet wrapper
│   ├── portfolio.py           # Position management, P&L
│   ├── bots/
│   │   ├── narrative.py       # Bot A — Narrative Momentum
│   │   ├── baseline_ta.py     # Bot B — EMA/RSI
│   │   └── benchmark.py       # Bot C — Buy & Hold
│   └── signals/
│       ├── ingest.py          # RSS + Reddit + CoinGecko fetchers
│       └── llm_analyzer.py    # Claude narrative extraction
├── scripts/
│   ├── run_all.py             # Launch all 3 bots
│   ├── backtest_baseline.py   # Backtest Bot B on 30d
│   └── analyze_results.py     # Post-experiment analysis
├── dashboard/
│   └── app.py                 # Streamlit dashboard
├── .env.example
├── requirements.txt
└── README.md
```

## Data Sources (all free, no keys)

- **RSS**: CoinDesk, CoinTelegraph, Decrypt, The Block, Bitcoin Magazine
- **Reddit**: r/CryptoCurrency, r/CryptoMoonShots, r/SatoshiStreetBets
- **CoinGecko**: Trending coins + category data

## Trading Rules

- Position size: 200 USDT per trade
- Max 3 concurrent positions (Bot A & B)
- Stop-loss: -3%
- Trailing take-profit: activates at +5%, trails 2% behind peak
- Force-close after 24h (narratives decay)

## Safety

⚠️ **TESTNET ONLY** — `TESTNET = True` is hardcoded in `config.py`. No mainnet code paths exist. All trades use Binance Spot Testnet virtual funds.
