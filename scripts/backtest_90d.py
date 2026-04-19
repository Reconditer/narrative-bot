"""Backtest Bot B on 90 days of historical 1h data."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd, numpy as np
from src.config import (EMA_FAST, EMA_SLOW, RSI_PERIOD, RSI_OVERBOUGHT,
                         RSI_OVERSOLD, TA_SYMBOLS, STARTING_CAPITAL,
                         POSITION_SIZE, STOP_LOSS_PCT)
from src.exchange import Exchange

def _ema(s, p): return s.ewm(span=p, adjust=False).mean()
def _rsi(s, p):
    d = s.diff(); g = d.where(d > 0, 0.0); l = -d.where(d < 0, 0.0)
    ag = g.ewm(com=p-1, min_periods=p).mean()
    al = l.ewm(com=p-1, min_periods=p).mean()
    return 100 - 100 / (1 + ag / al.replace(0, np.nan))

def backtest(klines, symbol):
    df = pd.DataFrame(klines)
    df["ef"] = _ema(df["close"], EMA_FAST)
    df["es"] = _ema(df["close"], EMA_SLOW)
    df["rsi"] = _rsi(df["close"], RSI_PERIOD)
    df.dropna(inplace=True)
    trades, pos = [], None
    for i in range(1, len(df)):
        c, p = df.iloc[i], df.iloc[i - 1]
        cup = p["ef"] <= p["es"] and c["ef"] > c["es"]
        cdn = p["ef"] >= p["es"] and c["ef"] < c["es"]
        rsi = c["rsi"]
        if pos is None and cup and rsi < RSI_OVERSOLD:
            pos = {"entry": c["close"], "sym": symbol}
        elif pos:
            ch = (c["close"] - pos["entry"]) / pos["entry"]
            if ch <= STOP_LOSS_PCT:
                trades.append({"sym": symbol, "pnl": ch, "reason": "SL"})
                pos = None
            elif cdn or rsi > RSI_OVERBOUGHT:
                trades.append({"sym": symbol, "pnl": ch, "reason": "signal"})
                pos = None
    if pos:
        ch = (df.iloc[-1]["close"] - pos["entry"]) / pos["entry"]
        trades.append({"sym": symbol, "pnl": ch, "reason": "EOD"})
    return trades

async def main():
    ex = Exchange()
    await ex.connect()
    all_trades = []
    for sym in TA_SYMBOLS:
        # Fetch 2 batches of 1000 for ~83 days coverage
        k1 = await ex.get_klines(sym, "1h", 1000)
        if k1:
            start = k1[0]["open_time"]
            raw = await ex.client.get_klines(
                symbol=sym, interval="1h", limit=1000, endTime=start - 1)
            k0 = [{"open_time": k[0], "open": float(k[1]), "high": float(k[2]),
                    "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
                    "close_time": k[6], "quote_volume": float(k[7]),
                    "trades": int(k[8])} for k in raw]
            klines = k0 + k1
        else:
            klines = k1
        days = len(klines) / 24
        print(f"{sym}: {len(klines)} candles ({days:.0f} days)")
        t = backtest(klines, sym)
        all_trades.extend(t)
        print(f"  {len(t)} trades")
    await ex.close()

    if not all_trades:
        print("\nNo trades generated.")
        return

    pnls = [t["pnl"] for t in all_trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    eq = STARTING_CAPITAL
    for t in all_trades:
        eq += min(POSITION_SIZE, eq) * t["pnl"]
    ret = (eq - STARTING_CAPITAL) / STARTING_CAPITAL
    ra = np.array(pnls)
    sharpe = (ra.mean() / ra.std()) * np.sqrt(365) if ra.std() > 0 else 0

    print()
    print("=" * 60)
    print("BACKTEST — Bot B (EMA/RSI) — ~90 DAYS")
    print("=" * 60)
    print(f"Trades:       {len(all_trades)}")
    print(f"Win rate:     {len(wins) / len(all_trades) * 100:.1f}%")
    if wins:
        print(f"Avg win:      +{np.mean(wins) * 100:.2f}%")
    if losses:
        print(f"Avg loss:     {np.mean(losses) * 100:.2f}%")
    print(f"Max loss:     {min(pnls) * 100:.2f}%")
    print(f"Best trade:   +{max(pnls) * 100:.2f}%")
    print(f"Total return: {ret * 100:+.2f}%")
    print(f"Final equity: {eq:.2f} USDT")
    print(f"Sharpe ratio: {sharpe:.2f}")
    print()
    print("Per symbol:")
    for sym in TA_SYMBOLS:
        st = [t for t in all_trades if t["sym"] == sym]
        if st:
            sw = [t for t in st if t["pnl"] > 0]
            net = sum(t["pnl"] for t in st)
            print(f"  {sym}: {len(st)} trades, {len(sw)}/{len(st)} wins "
                  f"({len(sw)/len(st)*100:.0f}%), net {net*100:+.2f}%")

if __name__ == "__main__":
    asyncio.run(main())
