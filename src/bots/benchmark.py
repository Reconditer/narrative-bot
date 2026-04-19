"""Bot C — BENCHMARK: Buy 1000 USDT of BTC at t=0, hold forever."""
from __future__ import annotations
import asyncio
from loguru import logger
from src.config import STARTING_CAPITAL, EQUITY_SNAPSHOT_INTERVAL
from src.exchange import Exchange
from src.portfolio import PortfolioManager

BOT_ID = "BENCHMARK"


async def run(exchange: Exchange) -> None:
    """Buy BTC once at start, then just snapshot equity periodically."""
    portfolio = PortfolioManager(BOT_ID, exchange)
    logger.info(f"[{BOT_ID}] Starting — buying {STARTING_CAPITAL} USDT of BTC")

    # Buy BTC at t=0
    try:
        await portfolio.open_position(
            ticker="BTCUSDT",
            usdt_amount=STARTING_CAPITAL,
            signal_type="benchmark_buy_hold",
        )
        logger.info(f"[{BOT_ID}] Bought BTC — now holding")
    except Exception as e:
        logger.error(f"[{BOT_ID}] Initial BTC buy failed: {e}")

    # Snapshot equity forever
    while True:
        try:
            eq = await portfolio.snapshot_equity()
            logger.info(f"[{BOT_ID}] Equity: {eq:.2f} USDT")
        except Exception as e:
            logger.error(f"[{BOT_ID}] Snapshot error: {e}")
        await asyncio.sleep(EQUITY_SNAPSHOT_INTERVAL)
