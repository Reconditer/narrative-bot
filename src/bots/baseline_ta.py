"""Bot B — BASELINE_TA: EMA(9/21) crossover + RSI(14) filter.
Uses manual EMA/RSI computation (no pandas-ta dependency).
"""
from __future__ import annotations
import asyncio
import pandas as pd
import numpy as np
from loguru import logger
from src.config import (
    TA_INTERVAL, TA_SYMBOLS, POSITION_SIZE,
    EMA_FAST, EMA_SLOW, RSI_PERIOD, RSI_OVERBOUGHT, RSI_OVERSOLD,
    EQUITY_SNAPSHOT_INTERVAL,
)
from src.exchange import Exchange
from src.portfolio import PortfolioManager

BOT_ID = "BASELINE_TA"


def _ema(series: pd.Series, period: int) -> pd.Series:
    """Compute EMA manually."""
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int) -> pd.Series:
    """Compute RSI manually."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_signals(klines: list[dict]) -> dict:
    """Compute EMA crossover and RSI from kline data."""
    df = pd.DataFrame(klines)
    if len(df) < EMA_SLOW + 5:
        return {"signal": "HOLD"}

    df["ema_fast"] = _ema(df["close"], EMA_FAST)
    df["ema_slow"] = _ema(df["close"], EMA_SLOW)
    df["rsi"] = _rsi(df["close"], RSI_PERIOD)
    df.dropna(inplace=True)
    if len(df) < 2:
        return {"signal": "HOLD"}

    curr = df.iloc[-1]
    prev = df.iloc[-2]

    cross_up = prev["ema_fast"] <= prev["ema_slow"] and curr["ema_fast"] > curr["ema_slow"]
    cross_down = prev["ema_fast"] >= prev["ema_slow"] and curr["ema_fast"] < curr["ema_slow"]
    rsi = curr["rsi"] if pd.notna(curr["rsi"]) else 50

    if cross_up and rsi < RSI_OVERSOLD:
        return {"signal": "BUY", "rsi": rsi}
    elif cross_down or rsi > RSI_OVERBOUGHT:
        return {"signal": "SELL", "rsi": rsi}
    return {"signal": "HOLD", "rsi": rsi}


async def run(exchange: Exchange) -> None:
    """Main loop for the Baseline TA bot."""
    portfolio = PortfolioManager(BOT_ID, exchange)
    logger.info(f"[{BOT_ID}] Starting with {portfolio.cash} USDT")

    # Initial equity snapshot
    await portfolio.snapshot_equity()

    snapshot_counter = 0
    while True:
        try:
            for symbol in TA_SYMBOLS:
                try:
                    klines = await exchange.get_klines(symbol, "1h", 50)
                    result = compute_signals(klines)
                    sig = result["signal"]

                    if sig == "BUY":
                        logger.info(f"[{BOT_ID}] BUY {symbol} (RSI={result.get('rsi', '?'):.1f})")
                        await portfolio.open_position(
                            ticker=symbol, usdt_amount=POSITION_SIZE,
                            signal_type="ema_cross_up",
                        )
                    elif sig == "SELL" and portfolio.has_open_position(symbol):
                        for pos in portfolio.get_open_positions():
                            if pos.ticker == symbol:
                                reason = "ema_cross_down" if result.get("rsi", 50) <= RSI_OVERBOUGHT else "rsi_overbought"
                                await portfolio.close_position(pos.id, reason)
                except Exception as e:
                    logger.error(f"[{BOT_ID}] Error on {symbol}: {e}")

            await portfolio.check_positions()

            snapshot_counter += TA_INTERVAL
            if snapshot_counter >= EQUITY_SNAPSHOT_INTERVAL:
                eq = await portfolio.snapshot_equity()
                logger.info(f"[{BOT_ID}] Equity: {eq:.2f} USDT")
                snapshot_counter = 0

        except Exception as e:
            logger.error(f"[{BOT_ID}] Loop error: {e}")

        await asyncio.sleep(TA_INTERVAL)
