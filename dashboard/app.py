"""Streamlit dashboard — live P&L, equity curves, trade log, narrative timeline.
Usage: streamlit run dashboard/app.py
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st
import pandas as pd
from datetime import datetime
from src.db import Decision, Narrative, Portfolio, Position, Trade, get_session, init_db

st.set_page_config(page_title="Narrative Bot Dashboard", layout="wide",
                   page_icon="📈")

# Auto-refresh every 30 seconds
st.markdown(
    '<meta http-equiv="refresh" content="30">',
    unsafe_allow_html=True,
)

init_db()

# ── Custom CSS ───────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .metric-card {
        background: linear-gradient(135deg, #1a1f2e 0%, #2d1b4e 100%);
        border-radius: 12px; padding: 20px; margin: 8px 0;
        border: 1px solid rgba(139, 92, 246, 0.3);
    }
    .metric-value { font-size: 28px; font-weight: 700; color: #e2e8f0; }
    .metric-label { font-size: 13px; color: #94a3b8; margin-bottom: 4px; }
    .positive { color: #34d399; }
    .negative { color: #f87171; }
</style>
""", unsafe_allow_html=True)


def get_data():
    s = get_session()
    try:
        portfolios = pd.read_sql(s.query(Portfolio).statement, s.bind) if s.query(Portfolio).count() > 0 else pd.DataFrame()
        trades = pd.read_sql(s.query(Trade).statement, s.bind) if s.query(Trade).count() > 0 else pd.DataFrame()
        decisions = pd.read_sql(s.query(Decision).statement, s.bind) if s.query(Decision).count() > 0 else pd.DataFrame()
        narratives = pd.read_sql(s.query(Narrative).statement, s.bind) if s.query(Narrative).count() > 0 else pd.DataFrame()
        positions = pd.read_sql(s.query(Position).statement, s.bind) if s.query(Position).count() > 0 else pd.DataFrame()
        return portfolios, trades, decisions, narratives, positions
    finally:
        s.close()


portfolios, trades, decisions, narratives, positions = get_data()

# ── Header ───────────────────────────────────────────────────────────
st.title("📈 Narrative Momentum — Trading Experiment")
st.caption(f"Last refresh: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

tab1, tab2, tab3 = st.tabs(["📊 Overview", "📋 Trade Log", "🧠 Narratives"])

# ── TAB 1: Overview ──────────────────────────────────────────────────
with tab1:
    bots = ["NARRATIVE", "BASELINE_TA", "BENCHMARK"]
    cols = st.columns(3)
    for i, bot in enumerate(bots):
        with cols[i]:
            if not portfolios.empty and bot in portfolios["bot_id"].values:
                bot_df = portfolios[portfolios["bot_id"] == bot].sort_values("timestamp")
                latest = bot_df.iloc[-1]["equity"]
                start = bot_df.iloc[0]["equity"]
                ret = (latest - start) / start * 100 if start > 0 else 0
                color = "positive" if ret >= 0 else "negative"
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">{bot}</div>
                    <div class="metric-value">${latest:,.2f}</div>
                    <div class="{color}">{ret:+.2f}%</div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">{bot}</div>
                    <div class="metric-value">$1,000.00</div>
                    <div class="metric-label">Waiting for data...</div>
                </div>
                """, unsafe_allow_html=True)

    st.subheader("Equity Curves")
    if not portfolios.empty:
        chart_data = portfolios.pivot_table(
            index="timestamp", columns="bot_id", values="equity"
        )
        st.line_chart(chart_data)
    else:
        st.info("No equity data yet — bots are starting up.")

    # Open positions
    st.subheader("Open Positions")
    if not positions.empty:
        open_pos = positions[positions["status"] == "OPEN"]
        if not open_pos.empty:
            st.dataframe(open_pos[["bot_id", "ticker", "entry_price", "quantity",
                                   "entry_time", "peak_price"]],
                         width="stretch")
        else:
            st.info("No open positions.")
    else:
        st.info("No position data yet.")

# ── TAB 2: Trade Log ─────────────────────────────────────────────────
with tab2:
    st.subheader("All Trades")
    if not trades.empty:
        bot_filter = st.multiselect("Filter by bot", bots, default=bots)
        filtered = trades[trades["bot_id"].isin(bot_filter)].sort_values("timestamp", ascending=False)
        st.dataframe(filtered[["timestamp", "bot_id", "ticker", "side", "price",
                                "quantity", "usdt_amount", "status"]],
                     width="stretch")
    else:
        st.info("No trades yet.")

    st.subheader("Closed Positions")
    if not positions.empty:
        closed = positions[positions["status"] == "CLOSED"].sort_values("exit_time", ascending=False)
        if not closed.empty:
            st.dataframe(closed[["bot_id", "ticker", "entry_price", "exit_price",
                                  "pnl", "close_reason", "entry_time", "exit_time"]],
                         width="stretch")
        else:
            st.info("No closed positions yet.")

# ── TAB 3: Narrative Timeline ────────────────────────────────────────
with tab3:
    st.subheader("🧠 Detected Narratives")
    if not narratives.empty:
        narr_display = narratives.sort_values("timestamp", ascending=False).head(50)
        for _, row in narr_display.iterrows():
            stage_emoji = {"early": "🌱", "building": "🔥", "saturated": "📉"}.get(row["stage"], "❓")
            confidence_bar = "🟢" * min(row["confidence"], 10) + "⚪" * (10 - min(row["confidence"], 10))
            st.markdown(f"""
            **{stage_emoji} {row['narrative']}**
            - Tickers: `{row['related_tickers']}` | Stage: {row['stage']} | Confidence: {confidence_bar}
            - {row['reasoning'][:200] if row['reasoning'] else 'No reasoning'}
            - _{row['timestamp']}_
            ---
            """)
    else:
        st.info("No narratives detected yet — waiting for first analysis cycle.")

    st.subheader("Buy Decisions with Reasoning")
    if not decisions.empty:
        buy_decs = decisions[decisions["decision"] == "BUY"].sort_values("timestamp", ascending=False).head(20)
        if not buy_decs.empty:
            for _, row in buy_decs.iterrows():
                st.markdown(f"""
                **{row['bot_id']} → BUY {row['ticker']}** @ ${row['price']:.4f}
                - Signal: {row.get('signal_type', 'N/A')} | Confidence: {row.get('llm_confidence', 'N/A')}
                - Volume ratio: {row.get('volume_ratio', 'N/A')}
                - Narrative: {row.get('narrative_text', 'N/A')[:150] if row.get('narrative_text') else 'N/A'}
                - Reasoning: {row.get('llm_reasoning', 'N/A')[:200] if row.get('llm_reasoning') else 'N/A'}
                ---
                """)
