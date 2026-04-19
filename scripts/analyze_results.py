"""Post-experiment analysis — run after 7 days to generate RESULTS.md.
Usage: python scripts/analyze_results.py
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from datetime import datetime
from src.db import Decision, Portfolio, Position, Trade, get_session, init_db

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def analyze():
    init_db()
    s = get_session()
    try:
        bots = ["NARRATIVE", "BASELINE_TA", "BENCHMARK"]
        report = ["# Narrative Bot Experiment — Results\n"]
        report.append(f"Generated: {datetime.utcnow().isoformat()}\n")
        report.append("## Per-Bot Summary\n")
        report.append("| Bot | Start | End | Return | Sharpe | Trades | Win Rate | Avg Win | Avg Loss |")
        report.append("|-----|-------|-----|--------|--------|--------|----------|---------|----------|")

        for bot in bots:
            snaps = s.query(Portfolio).filter(Portfolio.bot_id == bot).order_by(Portfolio.timestamp).all()
            positions = s.query(Position).filter(Position.bot_id == bot, Position.status == "CLOSED").all()
            trades = s.query(Trade).filter(Trade.bot_id == bot).all()

            start_eq = snaps[0].equity if snaps else 1000
            end_eq = snaps[-1].equity if snaps else 1000
            total_return = (end_eq - start_eq) / start_eq if start_eq > 0 else 0

            # Sharpe from equity snapshots
            if len(snaps) > 1:
                returns = []
                for i in range(1, len(snaps)):
                    r = (snaps[i].equity - snaps[i-1].equity) / snaps[i-1].equity
                    returns.append(r)
                ret_arr = np.array(returns)
                sharpe = (ret_arr.mean() / ret_arr.std()) * np.sqrt(288) if ret_arr.std() > 0 else 0  # 288 = 5min intervals/day
            else:
                sharpe = 0

            pnls = [p.pnl for p in positions if p.pnl is not None]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]
            win_rate = len(wins) / len(pnls) * 100 if pnls else 0
            avg_win = np.mean(wins) if wins else 0
            avg_loss = np.mean(losses) if losses else 0

            report.append(
                f"| {bot} | {start_eq:.0f} | {end_eq:.2f} | {total_return*100:.2f}% | "
                f"{sharpe:.2f} | {len(trades)} | {win_rate:.0f}% | "
                f"{avg_win:.2f} | {avg_loss:.2f} |"
            )

        # ── Bot A Narrative Analysis ─────────────────────────────
        report.append("\n## Bot A (NARRATIVE) — Narrative Analysis\n")

        decisions = s.query(Decision).filter(
            Decision.bot_id == "NARRATIVE", Decision.decision == "BUY"
        ).all()

        if decisions:
            # Group by narrative
            narrative_stats: dict[str, list[float]] = {}
            for d in decisions:
                narr = (d.narrative_text or "unknown")[:80]
                # Find matching closed position
                pos = s.query(Position).filter(
                    Position.bot_id == "NARRATIVE",
                    Position.ticker == d.ticker,
                    Position.status == "CLOSED",
                    Position.entry_time >= d.timestamp,
                ).first()
                pnl = pos.pnl if pos and pos.pnl is not None else 0
                narrative_stats.setdefault(narr, []).append(pnl)

            report.append("### Most Profitable Narratives\n")
            report.append("| Narrative | Trades | Total PnL | Avg PnL |")
            report.append("|-----------|--------|-----------|---------|")
            sorted_narr = sorted(narrative_stats.items(), key=lambda x: sum(x[1]), reverse=True)
            for narr, pnls in sorted_narr[:10]:
                report.append(f"| {narr} | {len(pnls)} | {sum(pnls):.2f} | {np.mean(pnls):.2f} |")

            # Confidence vs profit correlation
            report.append("\n### LLM Confidence vs Profit\n")
            conf_pnl = []
            for d in decisions:
                if d.llm_confidence is not None:
                    pos = s.query(Position).filter(
                        Position.bot_id == "NARRATIVE", Position.ticker == d.ticker,
                        Position.status == "CLOSED", Position.entry_time >= d.timestamp,
                    ).first()
                    if pos and pos.pnl is not None:
                        conf_pnl.append((d.llm_confidence, pos.pnl))

            if len(conf_pnl) > 2:
                confs, pnls = zip(*conf_pnl)
                corr = np.corrcoef(confs, pnls)[0, 1]
                report.append(f"Correlation between LLM confidence and trade PnL: **{corr:.3f}**\n")
                if corr > 0.3:
                    report.append("> Higher confidence predictions were more profitable ✅\n")
                elif corr < -0.1:
                    report.append("> ⚠️ Confidence was inversely correlated — LLM overconfidence may be a problem\n")
                else:
                    report.append("> Confidence showed weak correlation with outcomes\n")
            else:
                report.append("Not enough closed positions to calculate correlation.\n")
        else:
            report.append("No narrative trades were executed.\n")

        # ── Write report ─────────────────────────────────────────
        report_text = "\n".join(report)
        out_path = PROJECT_ROOT / "RESULTS.md"
        out_path.write_text(report_text)
        print(f"\nResults written to {out_path}")
        print(report_text)

    finally:
        s.close()


if __name__ == "__main__":
    analyze()
