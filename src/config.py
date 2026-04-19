"""Configuration — loads .env, defines all constants.

Testnet is HARDCODED. No mainnet code paths exist.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Load .env from project root (local dev only, ignored on Railway) ─
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env", override=False)

def _require_env(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        raise RuntimeError(f"Missing required env var: {key}")
    return val

# ── Binance Testnet ──────────────────────────────────────────────────
TESTNET = True  # HARDCODED — never change
BINANCE_API_KEY = _require_env("BINANCE_API_KEY")
BINANCE_API_SECRET = _require_env("BINANCE_API_SECRET")
BINANCE_TESTNET_URL = "https://testnet.binance.vision"

# ── Anthropic (Claude) ──────────────────────────────────────────────
ANTHROPIC_API_KEY = _require_env("ANTHROPIC_API_KEY")
CLAUDE_MODEL = "claude-haiku-4-5"  # fast + cheap for 5-min narrative cycles

# ── Trading Parameters ──────────────────────────────────────────────
STARTING_CAPITAL = 1000.0       # USDT per bot
POSITION_SIZE = 200.0           # USDT per trade
MAX_POSITIONS = 3               # concurrent open positions
STOP_LOSS_PCT = -0.03           # -3%
TRAILING_TP_ACTIVATE = 0.05    # +5% activates trailing stop
TRAILING_TP_TRAIL = 0.02       # trails 2% behind peak
MAX_HOLD_HOURS = 24             # force-close after 24h

# ── Narrative Bot Filters ────────────────────────────────────────────
MAX_1H_PRICE_CHANGE = 0.15     # don't chase >15% pumps
MIN_VOLUME_RATIO = 0.1         # lowered for testnet (real volume is near-zero)
MIN_CONFIDENCE = 6             # LLM confidence threshold

# ── Polling Intervals (seconds) ─────────────────────────────────────
NARRATIVE_INTERVAL = 300        # 5 min
TA_INTERVAL = 60                # 1 min
EQUITY_SNAPSHOT_INTERVAL = 300  # 5 min

# ── Baseline TA Parameters ──────────────────────────────────────────
EMA_FAST = 9
EMA_SLOW = 21
RSI_PERIOD = 14
RSI_OVERBOUGHT = 80
RSI_OVERSOLD = 70  # buy filter: RSI must be below this
TA_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

# ── Data Sources ─────────────────────────────────────────────────────
RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
    "https://www.theblock.co/rss.xml",
    "https://bitcoinmagazine.com/.rss/full/",
    # Additional crypto news for broader coverage
    "https://cryptoslate.com/feed/",
    "https://www.newsbtc.com/feed/",
    "https://u.today/rss",
    "https://ambcrypto.com/feed/",
    "https://www.investing.com/rss/news_301.rss",  # crypto section
]

# Reddit JSON is blocked (403) as of 2025 — disabled
REDDIT_ENDPOINTS: list[tuple[str, str]] = []

COINGECKO_TRENDING_URL = "https://api.coingecko.com/api/v3/search/trending"
COINGECKO_CATEGORIES_URL = "https://api.coingecko.com/api/v3/coins/categories"

REDDIT_USER_AGENT = "narrative-bot/1.0"
REDDIT_THROTTLE_SECONDS = 2.0
COINGECKO_THROTTLE_SECONDS = 2.0

# ── Database ─────────────────────────────────────────────────────────
# Railway: use Volume mount for persistent storage
_DATA_DIR = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", str(_PROJECT_ROOT)))
DB_PATH = _DATA_DIR / "trading.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

# ── Logging ──────────────────────────────────────────────────────────
LOG_DIR = _DATA_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
