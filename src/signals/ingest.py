"""Data ingestors — RSS feeds, Reddit JSON, CoinGecko trending.
All free, no API keys needed. Deduplicates by title hash.
"""
from __future__ import annotations
import asyncio
import hashlib
from datetime import datetime
from loguru import logger
import feedparser
import httpx
from src.config import (
    RSS_FEEDS, REDDIT_ENDPOINTS, REDDIT_USER_AGENT,
    REDDIT_THROTTLE_SECONDS, COINGECKO_TRENDING_URL,
    COINGECKO_CATEGORIES_URL, COINGECKO_THROTTLE_SECONDS,
)
from src.db import SignalRaw, get_session


def _hash_title(title: str) -> str:
    return hashlib.sha256(title.strip().lower().encode()).hexdigest()


class RSSIngestor:
    """Pull articles from crypto RSS feeds."""

    async def fetch(self) -> list[dict]:
        results = []
        for url in RSS_FEEDS:
            try:
                feed = await asyncio.to_thread(feedparser.parse, url)
                source = url.split("//")[1].split("/")[0].replace("www.", "")
                for entry in feed.entries[:15]:
                    title = entry.get("title", "").strip()
                    if not title:
                        continue
                    summary = entry.get("summary", entry.get("description", ""))
                    results.append({
                        "source": f"rss:{source}",
                        "title": title,
                        "text": summary[:500] if summary else "",
                        "title_hash": _hash_title(title),
                    })
            except Exception as e:
                logger.warning(f"RSS fetch failed for {url}: {e}")
        return results


class RedditIngestor:
    """Pull posts from Reddit JSON endpoints (no auth)."""

    async def fetch(self) -> list[dict]:
        results = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(
            headers=headers, timeout=15, follow_redirects=True
        ) as client:
            for sub_name, url in REDDIT_ENDPOINTS:
                # Use old.reddit.com to avoid blocks
                old_url = url.replace("www.reddit.com", "old.reddit.com")
                try:
                    resp = await client.get(old_url)
                    if resp.status_code in (403, 429):
                        logger.warning(f"Reddit blocked/limited on {sub_name} ({resp.status_code})")
                        await asyncio.sleep(5)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    for post in data.get("data", {}).get("children", []):
                        d = post.get("data", {})
                        title = d.get("title", "").strip()
                        if not title:
                            continue
                        selftext = d.get("selftext", "")[:400]
                        results.append({
                            "source": f"reddit:{sub_name}",
                            "title": title,
                            "text": selftext,
                            "title_hash": _hash_title(title),
                        })
                except Exception as e:
                    logger.warning(f"Reddit fetch failed for {sub_name}: {e}")
                await asyncio.sleep(REDDIT_THROTTLE_SECONDS)
        return results


class CoinGeckoIngestor:
    """Pull trending coins and category data from CoinGecko free API."""

    async def fetch_trending(self) -> list[str]:
        """Return list of trending coin symbols (uppercase)."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(COINGECKO_TRENDING_URL)
                resp.raise_for_status()
                data = resp.json()
                symbols = []
                for coin in data.get("coins", []):
                    item = coin.get("item", {})
                    sym = item.get("symbol", "").upper()
                    if sym:
                        symbols.append(sym)
                return symbols
        except Exception as e:
            logger.warning(f"CoinGecko trending failed: {e}")
            return []

    async def fetch_categories(self) -> list[dict]:
        """Return category changes for narrative context."""
        try:
            await asyncio.sleep(COINGECKO_THROTTLE_SECONDS)
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(COINGECKO_CATEGORIES_URL)
                resp.raise_for_status()
                cats = resp.json()
                # Top 10 by 24h change
                sorted_cats = sorted(
                    [c for c in cats if c.get("market_cap_change_24h")],
                    key=lambda c: abs(c.get("market_cap_change_24h", 0)),
                    reverse=True,
                )[:10]
                return [{"name": c["name"],
                         "change_24h": c.get("market_cap_change_24h", 0)}
                        for c in sorted_cats]
        except Exception as e:
            logger.warning(f"CoinGecko categories failed: {e}")
            return []


def store_signals(signals: list[dict]) -> int:
    """Store raw signals to DB, skipping duplicates. Returns count stored."""
    s = get_session()
    stored = 0
    try:
        for sig in signals:
            existing = s.query(SignalRaw).filter(
                SignalRaw.title_hash == sig["title_hash"]).first()
            if existing:
                continue
            s.add(SignalRaw(
                source=sig["source"], title=sig["title"],
                text=sig.get("text", ""), title_hash=sig["title_hash"],
            ))
            stored += 1
        s.commit()
        logger.info(f"Stored {stored} new signals (skipped {len(signals) - stored} dupes)")
    finally:
        s.close()
    return stored


async def ingest_all() -> tuple[list[dict], list[str]]:
    """Run all ingestors. Returns (all_signals, trending_symbols)."""
    rss = RSSIngestor()
    reddit = RedditIngestor()
    gecko = CoinGeckoIngestor()

    rss_signals, reddit_signals = await asyncio.gather(rss.fetch(), reddit.fetch())
    trending = await gecko.fetch_trending()

    all_signals = rss_signals + reddit_signals
    store_signals(all_signals)

    return all_signals, trending
