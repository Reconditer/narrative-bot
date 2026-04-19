"""Bot A — NARRATIVE: LLM-based narrative momentum strategy.

v2 Upgrades:
- Dynamic position sizing (confidence-based)
- 4h EMA trend confirmation before entry
- Sentiment decay detection (sell when narrative peaks)
"""
from __future__ import annotations
import asyncio
import pandas as pd
from loguru import logger
from src.config import (
    NARRATIVE_INTERVAL, EQUITY_SNAPSHOT_INTERVAL,
    MAX_1H_PRICE_CHANGE, MIN_VOLUME_RATIO,
    CONFIRM_4H_UPTREND, EMA_FAST, EMA_SLOW,
    get_position_size,
)
from src.exchange import Exchange
from src.portfolio import PortfolioManager
from src.signals.ingest import ingest_all
from src.signals.llm_analyzer import analyze_narratives, get_new_or_building_narratives

BOT_ID = "NARRATIVE"


async def _check_4h_uptrend(exchange: Exchange, symbol: str) -> bool:
    """Confirm 4h EMA9 > EMA21 (multi-timeframe filter)."""
    if not CONFIRM_4H_UPTREND:
        return True
    try:
        klines = await exchange.get_klines(symbol, "4h", 30)
        if len(klines) < EMA_SLOW + 2:
            return True  # not enough data, allow trade
        closes = pd.Series([k["close"] for k in klines])
        ema_fast = closes.ewm(span=EMA_FAST, adjust=False).mean().iloc[-1]
        ema_slow = closes.ewm(span=EMA_SLOW, adjust=False).mean().iloc[-1]
        uptrend = ema_fast > ema_slow
        if not uptrend:
            logger.info(f"[{BOT_ID}] {symbol} 4h downtrend (EMA9={ema_fast:.2f} < EMA21={ema_slow:.2f}), skip")
        return uptrend
    except Exception as e:
        logger.warning(f"[{BOT_ID}] 4h check failed for {symbol}: {e}")
        return True  # fail open


async def run(exchange: Exchange) -> None:
    """Main loop for the Narrative bot."""
    portfolio = PortfolioManager(BOT_ID, exchange)
    logger.info(f"[{BOT_ID}] Starting with {portfolio.cash} USDT")

    # Initial equity snapshot
    await portfolio.snapshot_equity()

    # Track last-seen narrative stages for decay detection
    _last_stages: dict[str, str] = {}

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

            # ── SENTIMENT DECAY: check if any held narrative peaked ─────
            for narrative in actionable:
                narr_key = narrative["narrative"][:50]
                prev_stage = _last_stages.get(narr_key)
                curr_stage = narrative["stage"]
                _last_stages[narr_key] = curr_stage

                if prev_stage in ("building", "early") and curr_stage == "peaking":
                    # Narrative shifted to peaking — sell related positions
                    for ticker in narrative["tickers"]:
                        symbol = ticker.upper() + "USDT"
                        if portfolio.has_open_position(symbol):
                            for pos in portfolio.get_open_positions():
                                if pos.ticker == symbol:
                                    logger.info(f"[{BOT_ID}] DECAY SELL {symbol} — narrative peaked")
                                    await portfolio.close_position(pos.id, "narrative_decay")

            # 4. Evaluate each ticker for BUY
            for narrative in actionable:
                confidence = narrative["confidence"]
                for ticker_symbol in narrative["tickers"]:
                    symbol = ticker_symbol.upper() + "USDT"
                    try:
                        # Check if pair exists on Binance
                        if not await exchange.symbol_exists(symbol):
                            continue

                        # Already holding this?
                        if portfolio.has_open_position(symbol):
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
                            vol_ratio = 0.0

                        # ── 4h TREND CONFIRMATION ───────────────────────
                        if not await _check_4h_uptrend(exchange, symbol):
                            continue

                        # ── DYNAMIC POSITION SIZING ─────────────────────
                        size = get_position_size(confidence)

                        # All checks passed → BUY
                        logger.info(
                            f"[{BOT_ID}] BUY {symbol} | conf={confidence} | "
                            f"size={size} USDT | narrative: {narrative['narrative'][:60]}"
                        )
                        await portfolio.open_position(
                            ticker=symbol,
                            usdt_amount=size,
                            narrative_text=narrative["narrative"],
                            llm_reasoning=narrative["reasoning"],
                            llm_confidence=confidence,
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
