"""Bot A — NARRATIVE: LLM-based narrative momentum strategy."""
from __future__ import annotations
import asyncio
from loguru import logger
from src.config import (
    NARRATIVE_INTERVAL, POSITION_SIZE, EQUITY_SNAPSHOT_INTERVAL,
    MAX_1H_PRICE_CHANGE, MIN_VOLUME_RATIO,
)
from src.exchange import Exchange
from src.portfolio import PortfolioManager
from src.signals.ingest import ingest_all
from src.signals.llm_analyzer import analyze_narratives, get_new_or_building_narratives

BOT_ID = "NARRATIVE"


async def run(exchange: Exchange) -> None:
    """Main loop for the Narrative bot."""
    portfolio = PortfolioManager(BOT_ID, exchange)
    logger.info(f"[{BOT_ID}] Starting with {portfolio.cash} USDT")

    snapshot_counter = 0
    while True:
        try:
            # 1. Ingest data
            logger.info(f"[{BOT_ID}] Ingesting signals...")
            signals, trending = await ingest_all()
            logger.info(f"[{BOT_ID}] Got {len(signals)} signals, {len(trending)} trending")

            # 2. Run LLM narrative extraction (sync call wrapped)
            if signals:
                narratives = await asyncio.to_thread(
                    analyze_narratives, signals, trending
                )
                logger.info(f"[{BOT_ID}] Extracted {len(narratives)} narratives")

            # 3. Get actionable signals (new or building)
            actionable = await asyncio.to_thread(get_new_or_building_narratives)
            logger.info(f"[{BOT_ID}] {len(actionable)} actionable narratives")

            # 4. Evaluate each ticker
            for narrative in actionable:
                for ticker_symbol in narrative["tickers"]:
                    symbol = ticker_symbol.upper() + "USDT"
                    try:
                        # Check if pair exists on Binance
                        if not await exchange.symbol_exists(symbol):
                            continue

                        # Check 1h price change < 15%
                        price_change = await exchange.get_1h_price_change(symbol)
                        if price_change > MAX_1H_PRICE_CHANGE:
                            logger.info(f"[{BOT_ID}] {symbol} +{price_change:.1%} > 15%, skip (chasing)")
                            continue

                        # Check volume ratio (skip on testnet if volume is 0)
                        vol_1h = await exchange.get_1h_volume(symbol)
                        vol_avg = await exchange.get_24h_avg_hourly_volume(symbol)
                        if vol_avg > 0:
                            vol_ratio = vol_1h / vol_avg
                            if vol_ratio < MIN_VOLUME_RATIO:
                                logger.info(f"[{BOT_ID}] {symbol} vol ratio {vol_ratio:.1f} < {MIN_VOLUME_RATIO}, skip")
                                continue
                        else:
                            vol_ratio = 0.0  # testnet — no volume data, proceed anyway
                            logger.debug(f"[{BOT_ID}] {symbol} no volume data (testnet), proceeding")

                        # All checks passed → BUY
                        logger.info(f"[{BOT_ID}] BUY signal: {symbol} (narrative: {narrative['narrative'][:60]})")
                        await portfolio.open_position(
                            ticker=symbol,
                            usdt_amount=POSITION_SIZE,
                            narrative_text=narrative["narrative"],
                            llm_reasoning=narrative["reasoning"],
                            llm_confidence=narrative["confidence"],
                            volume_ratio=vol_ratio,
                            signal_type=f"narrative_{narrative['signal']}",
                        )
                    except Exception as e:
                        logger.error(f"[{BOT_ID}] Error evaluating {symbol}: {e}")

            # 5. Check existing positions for SL/TP/force-close
            await portfolio.check_positions()

            # 6. Equity snapshot
            snapshot_counter += NARRATIVE_INTERVAL
            if snapshot_counter >= EQUITY_SNAPSHOT_INTERVAL:
                eq = await portfolio.snapshot_equity()
                logger.info(f"[{BOT_ID}] Equity: {eq:.2f} USDT")
                snapshot_counter = 0

        except Exception as e:
            logger.error(f"[{BOT_ID}] Loop error: {e}")

        await asyncio.sleep(NARRATIVE_INTERVAL)
