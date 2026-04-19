"""SQLAlchemy models — shared SQLite database for all 3 bots."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.config import DATABASE_URL


class Base(DeclarativeBase):
    pass


class SignalRaw(Base):
    """Raw ingested news/social posts."""

    __tablename__ = "signals_raw"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    source = Column(String(50), nullable=False)  # rss:coindesk, reddit:CryptoCurrency, coingecko
    title = Column(Text, nullable=False)
    text = Column(Text, nullable=True)
    title_hash = Column(String(64), unique=True, nullable=False)  # SHA-256 for dedup


class Narrative(Base):
    """LLM-extracted narratives."""

    __tablename__ = "narratives"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    narrative = Column(Text, nullable=False)
    related_tickers = Column(Text, nullable=False)  # JSON array string
    stage = Column(String(20), nullable=False)  # early, building, saturated
    confidence = Column(Integer, nullable=False)
    reasoning = Column(Text, nullable=True)
    batch_id = Column(String(36), nullable=False, index=True)  # UUID grouping


class Decision(Base):
    """Every BUY/SELL decision with full reasoning chain."""

    __tablename__ = "decisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    bot_id = Column(String(20), nullable=False, index=True)
    ticker = Column(String(20), nullable=False)
    narrative_text = Column(Text, nullable=True)
    llm_reasoning = Column(Text, nullable=True)
    llm_confidence = Column(Integer, nullable=True)
    price = Column(Float, nullable=False)
    volume_ratio = Column(Float, nullable=True)
    decision = Column(String(10), nullable=False)  # BUY, SELL, HOLD
    signal_type = Column(String(30), nullable=True)  # narrative_new, ema_cross, stop_loss, etc.


class Trade(Base):
    """Executed trades on Binance testnet."""

    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(20), nullable=False, index=True)
    ticker = Column(String(20), nullable=False)
    side = Column(String(4), nullable=False)  # BUY, SELL
    price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    usdt_amount = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    order_id = Column(String(50), nullable=True)
    status = Column(String(20), nullable=False, default="FILLED")


class Position(Base):
    """Open and closed positions."""

    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(20), nullable=False, index=True)
    ticker = Column(String(20), nullable=False)
    entry_price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    entry_time = Column(DateTime, nullable=False)
    peak_price = Column(Float, nullable=False)  # for trailing stop
    status = Column(String(10), nullable=False, default="OPEN")  # OPEN, CLOSED
    exit_price = Column(Float, nullable=True)
    exit_time = Column(DateTime, nullable=True)
    pnl = Column(Float, nullable=True)
    close_reason = Column(String(30), nullable=True)  # stop_loss, trailing_tp, force_close, signal


class Portfolio(Base):
    """Equity snapshots over time."""

    __tablename__ = "portfolio"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(20), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    equity = Column(Float, nullable=False)
    cash = Column(Float, nullable=False)
    positions_value = Column(Float, nullable=False)


# ── Engine & Session ─────────────────────────────────────────────────

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)


def init_db() -> None:
    """Create all tables if they don't exist."""
    Base.metadata.create_all(engine)


def get_session() -> Session:
    """Return a new database session."""
    return SessionLocal()
