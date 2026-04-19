"""Binance Testnet wrapper — async client with retry + backoff.
TESTNET IS HARDCODED. No mainnet code paths exist.
"""
from __future__ import annotations
import asyncio
from typing import Any
from binance import AsyncClient, BinanceAPIException
from loguru import logger
from src.config import BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET


class Exchange:
    """Async Binance Testnet client with retry logic."""

    def __init__(self) -> None:
        self._client: AsyncClient | None = None

    async def connect(self) -> None:
        assert TESTNET, "TESTNET must be True"
        self._client = await AsyncClient.create(
            api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET, testnet=True,
        )
        logger.info("Connected to Binance Testnet")

    async def close(self) -> None:
        if self._client:
            await self._client.close_connection()

    @property
    def client(self) -> AsyncClient:
        if not self._client:
            raise RuntimeError("Exchange not connected")
        return self._client

    async def get_price(self, symbol: str) -> float:
        t = await self._retry(self.client.get_symbol_ticker, symbol=symbol)
        return float(t["price"])

    async def get_klines(self, symbol: str, interval: str = "1h", limit: int = 100) -> list[dict]:
        raw = await self._retry(self.client.get_klines, symbol=symbol, interval=interval, limit=limit)
        return [{"open_time": k[0], "open": float(k[1]), "high": float(k[2]),
                 "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
                 "close_time": k[6], "quote_volume": float(k[7]), "trades": int(k[8])} for k in raw]

    async def get_1h_volume(self, symbol: str) -> float:
        klines = await self.get_klines(symbol, "1h", 1)
        return klines[-1]["quote_volume"] if klines else 0.0

    async def get_24h_avg_hourly_volume(self, symbol: str) -> float:
        klines = await self.get_klines(symbol, "1h", 24)
        return sum(k["quote_volume"] for k in klines) / max(len(klines), 1)

    async def get_1h_price_change(self, symbol: str) -> float:
        klines = await self.get_klines(symbol, "1h", 2)
        if len(klines) < 2 or klines[-2]["close"] == 0:
            return 0.0
        return (klines[-1]["close"] - klines[-2]["close"]) / klines[-2]["close"]

    async def market_buy(self, symbol: str, quote_qty: float) -> dict:
        order = await self._retry(
            self.client.order_market_buy, symbol=symbol, quoteOrderQty=round(quote_qty, 2))
        logger.info(f"BUY {symbol} for {quote_qty} USDT — order {order['orderId']}")
        return order

    async def market_sell(self, symbol: str, quantity: float) -> dict:
        info = await self.client.get_symbol_info(symbol)
        if info:
            for f in info.get("filters", []):
                if f["filterType"] == "LOT_SIZE":
                    step = float(f["stepSize"])
                    if step > 0:
                        prec = len(str(step).rstrip("0").split(".")[-1])
                        quantity = float(f"{quantity:.{prec}f}")
                    break
        order = await self._retry(
            self.client.order_market_sell, symbol=symbol, quantity=quantity)
        logger.info(f"SELL {symbol} qty={quantity} — order {order['orderId']}")
        return order

    async def get_balance(self, asset: str = "USDT") -> float:
        acct = await self._retry(self.client.get_account)
        for b in acct["balances"]:
            if b["asset"] == asset:
                return float(b["free"])
        return 0.0

    async def symbol_exists(self, symbol: str) -> bool:
        try:
            return (await self.client.get_symbol_info(symbol)) is not None
        except Exception:
            return False

    async def _retry(self, func, *args, retries: int = 3, base_delay: float = 1.0, **kwargs):
        last_err: Exception | None = None
        for attempt in range(retries):
            try:
                return await func(*args, **kwargs)
            except BinanceAPIException as e:
                last_err = e
                if e.code in (-1003, -1015):
                    await asyncio.sleep(base_delay * 2 ** attempt)
                else:
                    raise
            except Exception as e:
                last_err = e
                await asyncio.sleep(base_delay * 2 ** attempt)
        raise last_err  # type: ignore
