"""Backtest Bot B (EMA/RSI strategy) on 30 days of historical 1h data.
Uses manual EMA/RSI computation (no pandas-ta dependency).
Usage: python scripts/backtest_baseline.py
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import numpy as np
from src.config import (
    EMA_FAST, EMA_SLOW, RSI_PERIOD, RSI_OVERBOUGHT, RSI_OVERSOLD,
    TA_SYMBOLS, STARTING_CAPITAL, POSITION_SIZE, STOP_LOSS_PCT,
)
from src.exchange import Exchange


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def backtest_symbol(klines: list[dict], symbol: str) -> list[dict]:
    df = pd.DataFrame(klines)
    df["ema_fast"] = _ema(df["close"], EMA_FAST)
    df["ema_slow"] = _ema(df["close"], EMA_SLOW)
    df["rsi"] = _rsi(df["close"], RSI_PERIOD)
    df.dropna(inplace=True)

    trades = []
    position = None

    for i in range(1, len(df)):
        curr = df.iloc[i]
        prev = df.iloc[i - 1]
        cross_up = prev["ema_fast"] <= prev["ema_slow"] and curr["ema_fast"] > curr["ema_slow"]
        cross_down = prev["ema_fast"] >= prev["ema_slow"] and curr["ema_fast"] < curr["ema_slow"]
        rsi = curr["rsi"]

        if position is None and cross_up and rsi < RSI_OVERSOLD:
            position = {"entry": curr["close"], "symbol": symbol}
        elif position is not None:
            change = (curr["close"] - position["entry"]) / position["entry"]
            if change <= STOP_LOSS_PCT:
                trades.append({"symbol": symbol, "entry": position["entry"],
                               "exit": curr["close"], "pnl_pct": change, "reason": "stop_loss"})
                position = None
            elif cross_down or rsi > RSI_OVERBOUGHT:
                trades.append({"symbol": symbol, "entry": position["entry"],
                               "exit": curr["close"], "pnl_pct": change, "reason": "signal"})
                position = None

    if position is not None:
        last = df.iloc[-1]["close"]
        change = (last - position["entry"]) / position["entry"]
        trades.append({"symbol": symbol, "entry": position["entry"],
                       "exit": last, "pnl_pct": change, "reason": "end_of_data"})
    return trades


async def main():
    exchange = Exchange()
    await exchange.connect()

    all_trades = []
    for symbol in TA_SYMBOLS:
        print(f"\nFetching 30d 1h klines for {symbol}...")
        klines = await exchange.get_klines(symbol, "1h", 720)
        print(f"  Got {len(klines)} candles")
        trades = backtest_symbol(klines, symbol)
        all_trades.extend(trades)
        print(f"  {len(trades)} trades")

    await exchange.close()

    if not all_trades:
        print("\nNo trades generated — market may be too flat.")
        return

    print("\n" + "=" * 60)
    print("BACKTEST RESULTS — Bot B (BASELINE_TA) — 30 days")
    print("=" * 60)

    pnls = [t["pnl_pct"] for t in all_trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    equity = STARTING_CAPITAL
    returns = []
    for t in all_trades:
        trade_size = min(POSITION_SIZE, equity)
        pnl = trade_size * t["pnl_pct"]
        equity += pnl
        returns.append(t["pnl_pct"])

    total_return = (equity - STARTING_CAPITAL) / STARTING_CAPITAL
    if returns:
        ret_arr = np.array(returns)
        sharpe = (ret_arr.mean() / ret_arr.std()) * np.sqrt(365) if ret_arr.std() > 0 else 0
    else:
        sharpe = 0

    print(f"\nTotal trades:  {len(all_trades)}")
    print(f"Win rate:      {len(wins)/len(all_trades)*100:.1f}%")
    print(f"Avg win:       {np.mean(wins)*100:.2f}%" if wins else "Avg win:       N/A")
    print(f"Avg loss:      {np.mean(losses)*100:.2f}%" if losses else "Avg loss:      N/A")
    print(f"Total return:  {total_return*100:.2f}%")
    print(f"Final equity:  {equity:.2f} USDT")
    print(f"Sharpe ratio:  {sharpe:.2f}")

    print("\nTrades by symbol:")
    for symbol in TA_SYMBOLS:
        sym_trades = [t for t in all_trades if t["symbol"] == symbol]
        if sym_trades:
            sym_pnl = sum(t["pnl_pct"] for t in sym_trades)
            print(f"  {symbol}: {len(sym_trades)} trades, net {sym_pnl*100:.2f}%")


if __name__ == "__main__":
    asyncio.run(main())
