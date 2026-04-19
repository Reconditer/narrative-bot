"""Spawn all 3 bots as concurrent asyncio tasks.
Usage: python scripts/run_all.py
"""
from __future__ import annotations
import asyncio
import signal
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from src.config import LOG_DIR
from src.db import init_db
from src.exchange import Exchange
from src.bots import narrative, baseline_ta, benchmark

# ── Logging setup ────────────────────────────────────────────────────
logger.remove()
logger.add(sys.stderr, level="INFO",
           format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}")
logger.add(LOG_DIR / "trading.log", rotation="50 MB", retention="7 days",
           level="DEBUG",
           format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}")


async def main() -> None:
    init_db()
    logger.info("Database initialized")

    exchange = Exchange()
    await exchange.connect()

    # Create shared exchange instances for each bot
    ex_a = Exchange()
    await ex_a.connect()
    ex_b = Exchange()
    await ex_b.connect()
    ex_c = Exchange()
    await ex_c.connect()

    # Print starting balance
    balance = await exchange.get_balance("USDT")
    logger.info(f"Testnet USDT balance: {balance}")

    tasks = [
        asyncio.create_task(narrative.run(ex_a), name="Bot_A_NARRATIVE"),
        asyncio.create_task(baseline_ta.run(ex_b), name="Bot_B_BASELINE_TA"),
        asyncio.create_task(benchmark.run(ex_c), name="Bot_C_BENCHMARK"),
    ]

    logger.info("All 3 bots launched — Ctrl+C to stop")

    # Graceful shutdown
    stop = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received")
        stop.set()
        for t in tasks:
            t.cancel()

    loop = asyncio.get_event_loop()
    for sig_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig_name, _signal_handler)

    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        pass
    finally:
        await exchange.close()
        await ex_a.close()
        await ex_b.close()
        await ex_c.close()
        logger.info("All bots stopped, connections closed")


if __name__ == "__main__":
    asyncio.run(main())
