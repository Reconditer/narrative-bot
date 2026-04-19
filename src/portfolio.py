"""Shared portfolio tracker — position management, P&L, equity snapshots."""
from __future__ import annotations
from datetime import datetime, timedelta
from loguru import logger
from src.config import (
    STARTING_CAPITAL, STOP_LOSS_PCT, TRAILING_TP_ACTIVATE,
    TRAILING_TP_TRAIL, MAX_HOLD_HOURS, MAX_POSITIONS,
)
from src.db import Decision, Portfolio as PortfolioSnap, Position, Trade, get_session
from src.exchange import Exchange


class PortfolioManager:
    """Manages positions, risk checks, and equity snapshots for a single bot."""

    def __init__(self, bot_id: str, exchange: Exchange) -> None:
        self.bot_id = bot_id
        self.exchange = exchange
        self.cash = STARTING_CAPITAL

    def open_position_count(self) -> int:
        s = get_session()
        try:
            return s.query(Position).filter(
                Position.bot_id == self.bot_id, Position.status == "OPEN"
            ).count()
        finally:
            s.close()

    def get_open_positions(self) -> list[Position]:
        s = get_session()
        try:
            return list(s.query(Position).filter(
                Position.bot_id == self.bot_id, Position.status == "OPEN").all())
        finally:
            s.close()

    def has_open_position(self, ticker: str) -> bool:
        s = get_session()
        try:
            return s.query(Position).filter(
                Position.bot_id == self.bot_id, Position.ticker == ticker,
                Position.status == "OPEN").first() is not None
        finally:
            s.close()

    async def open_position(self, ticker: str, usdt_amount: float,
                            narrative_text: str | None = None,
                            llm_reasoning: str | None = None,
                            llm_confidence: int | None = None,
                            volume_ratio: float | None = None,
                            signal_type: str = "narrative_new") -> bool:
        """Buy and record a new position. Returns True on success."""
        if self.open_position_count() >= MAX_POSITIONS:
            logger.warning(f"[{self.bot_id}] Max positions reached, skip {ticker}")
            return False
        if self.has_open_position(ticker):
            logger.info(f"[{self.bot_id}] Already in {ticker}, skip")
            return False

        try:
            price = await self.exchange.get_price(ticker)
            order = await self.exchange.market_buy(ticker, usdt_amount)
            qty = float(order.get("executedQty", usdt_amount / price))
            fill_price = float(order.get("fills", [{"price": str(price)}])[0]["price"])
        except Exception as e:
            logger.error(f"[{self.bot_id}] Buy {ticker} failed: {e}")
            return False

        s = get_session()
        try:
            now = datetime.utcnow()
            s.add(Trade(bot_id=self.bot_id, ticker=ticker, side="BUY",
                        price=fill_price, quantity=qty, usdt_amount=usdt_amount,
                        timestamp=now, order_id=str(order.get("orderId", ""))))
            s.add(Position(bot_id=self.bot_id, ticker=ticker, entry_price=fill_price,
                           quantity=qty, entry_time=now, peak_price=fill_price, status="OPEN"))
            s.add(Decision(bot_id=self.bot_id, ticker=ticker, decision="BUY",
                           price=fill_price, narrative_text=narrative_text,
                           llm_reasoning=llm_reasoning, llm_confidence=llm_confidence,
                           volume_ratio=volume_ratio, signal_type=signal_type, timestamp=now))
            self.cash -= usdt_amount
            s.commit()
            logger.info(f"[{self.bot_id}] Opened {ticker} @ {fill_price}, qty={qty}")
            return True
        finally:
            s.close()

    async def close_position(self, position_id: int, reason: str) -> None:
        """Close a position by selling on exchange."""
        s = get_session()
        try:
            pos = s.query(Position).get(position_id)
            if not pos or pos.status != "OPEN":
                return
            try:
                price = await self.exchange.get_price(pos.ticker)
                order = await self.exchange.market_sell(pos.ticker, pos.quantity)
                fill_price = float(order.get("fills", [{"price": str(price)}])[0]["price"])
            except Exception as e:
                logger.error(f"[{self.bot_id}] Sell {pos.ticker} failed: {e}")
                return

            now = datetime.utcnow()
            pnl = (fill_price - pos.entry_price) * pos.quantity
            pos.status = "CLOSED"
            pos.exit_price = fill_price
            pos.exit_time = now
            pos.pnl = pnl
            pos.close_reason = reason
            self.cash += fill_price * pos.quantity

            s.add(Trade(bot_id=self.bot_id, ticker=pos.ticker, side="SELL",
                        price=fill_price, quantity=pos.quantity,
                        usdt_amount=fill_price * pos.quantity,
                        timestamp=now, order_id=str(order.get("orderId", ""))))
            s.add(Decision(bot_id=self.bot_id, ticker=pos.ticker, decision="SELL",
                           price=fill_price, signal_type=reason, timestamp=now))
            s.commit()
            logger.info(f"[{self.bot_id}] Closed {pos.ticker} @ {fill_price}, PnL={pnl:.2f}, reason={reason}")
        finally:
            s.close()

    async def check_positions(self) -> None:
        """Check all open positions for SL, trailing TP, and 24h force-close."""
        positions = self.get_open_positions()
        for pos in positions:
            try:
                price = await self.exchange.get_price(pos.ticker)
            except Exception:
                continue

            change = (price - pos.entry_price) / pos.entry_price
            # Update peak price
            s = get_session()
            try:
                db_pos = s.query(Position).get(pos.id)
                if not db_pos:
                    continue
                if price > db_pos.peak_price:
                    db_pos.peak_price = price
                    s.commit()
                peak = db_pos.peak_price
            finally:
                s.close()

            # Stop-loss
            if change <= STOP_LOSS_PCT:
                await self.close_position(pos.id, "stop_loss")
                continue
            # Trailing take-profit
            if change >= TRAILING_TP_ACTIVATE:
                trail_drop = (peak - price) / peak
                if trail_drop >= TRAILING_TP_TRAIL:
                    await self.close_position(pos.id, "trailing_tp")
                    continue
            # Force-close after 24h
            age = datetime.utcnow() - pos.entry_time
            if age >= timedelta(hours=MAX_HOLD_HOURS):
                await self.close_position(pos.id, "force_close_24h")

    async def snapshot_equity(self) -> float:
        """Record current equity (cash + position values) to DB."""
        positions = self.get_open_positions()
        pos_value = 0.0
        for pos in positions:
            try:
                price = await self.exchange.get_price(pos.ticker)
                pos_value += price * pos.quantity
            except Exception:
                pos_value += pos.entry_price * pos.quantity
        equity = self.cash + pos_value
        s = get_session()
        try:
            s.add(PortfolioSnap(bot_id=self.bot_id, equity=equity,
                                cash=self.cash, positions_value=pos_value))
            s.commit()
        finally:
            s.close()
        return equity
