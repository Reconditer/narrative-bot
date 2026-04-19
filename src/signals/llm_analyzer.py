"""LLM-based narrative extraction using Claude Haiku.
Sends aggregated news/social text to Claude, parses structured JSON narratives.
"""
from __future__ import annotations
import json
import re
import uuid
from datetime import datetime, timedelta
from loguru import logger
import anthropic
from src.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MIN_CONFIDENCE
from src.db import Narrative, get_session

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=30.0)

NARRATIVE_PROMPT = """Analyze the following crypto news and social posts from the last 5 minutes.
Identify up to 5 emerging narratives. For each, return JSON in this exact format:
[
  {
    "narrative": "description of the narrative",
    "related_tickers": ["BTC", "ETH"],
    "stage": "early",
    "confidence": 7,
    "reasoning": "why this narrative matters"
  }
]

Rules:
- stage must be one of: "early", "building", "saturated"
- confidence must be 1-10
- Only include narratives where confidence >= 6
- related_tickers should be uppercase coin symbols (not USDT pairs)
- Return ONLY the JSON array, no markdown, no explanation

Posts to analyze:
"""


def _extract_json(text: str) -> list[dict]:
    """Parse JSON from Claude response, handling markdown wrapping."""
    text = text.strip()
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Try finding array in text
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    logger.warning(f"Could not parse JSON from LLM response: {text[:200]}")
    return []


def analyze_narratives(
    signals: list[dict], trending_symbols: list[str]
) -> list[dict]:
    """Send signals to Claude, parse narratives, boost confidence for trending coins."""
    if not signals:
        return []

    # Build text block from signals
    text_parts = []
    for sig in signals[:50]:  # cap at 50
        text_parts.append(f"[{sig['source']}] {sig['title']}")
        if sig.get("text"):
            text_parts.append(f"  {sig['text'][:200]}")
    full_text = NARRATIVE_PROMPT + "\n".join(text_parts)

    try:
        response = _client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": full_text}],
        )
        raw_text = ""
        for block in response.content:
            if block.type == "text":
                raw_text += block.text
    except Exception as e:
        logger.error(f"Claude API call failed: {e}")
        return []

    narratives = _extract_json(raw_text)
    if not narratives:
        return []

    # Boost confidence for trending coins
    trending_set = set(trending_symbols)
    for n in narratives:
        tickers = n.get("related_tickers", [])
        for t in tickers:
            if t.upper() in trending_set:
                n["confidence"] = min(10, n.get("confidence", 5) + 2)
                n["reasoning"] = n.get("reasoning", "") + f" [TRENDING on CoinGecko: {t}]"
                break

    # Filter by min confidence
    narratives = [n for n in narratives if n.get("confidence", 0) >= MIN_CONFIDENCE]

    # Store to DB
    batch_id = str(uuid.uuid4())
    s = get_session()
    try:
        for n in narratives:
            s.add(Narrative(
                narrative=n.get("narrative", ""),
                related_tickers=json.dumps(n.get("related_tickers", [])),
                stage=n.get("stage", "early"),
                confidence=n.get("confidence", 0),
                reasoning=n.get("reasoning", ""),
                batch_id=batch_id,
            ))
        s.commit()
        logger.info(f"Stored {len(narratives)} narratives (batch {batch_id[:8]})")
    finally:
        s.close()

    return narratives


def get_new_or_building_narratives() -> list[dict]:
    """Compare current narratives vs 1h ago — return NEW or early→building transitions."""
    s = get_session()
    try:
        now = datetime.utcnow()
        one_hour_ago = now - timedelta(hours=1)

        # Recent narratives (last 10 min)
        recent = s.query(Narrative).filter(
            Narrative.timestamp >= now - timedelta(minutes=10)
        ).all()

        # Old narratives (1h ago window)
        old = s.query(Narrative).filter(
            Narrative.timestamp >= one_hour_ago - timedelta(minutes=10),
            Narrative.timestamp <= one_hour_ago + timedelta(minutes=10),
        ).all()

        old_narratives = {n.narrative.lower().strip(): n.stage for n in old}

        results = []
        for n in recent:
            key = n.narrative.lower().strip()
            old_stage = old_narratives.get(key)

            is_new = old_stage is None
            is_building = old_stage == "early" and n.stage == "building"

            if is_new or is_building:
                tickers = json.loads(n.related_tickers) if n.related_tickers else []
                results.append({
                    "narrative": n.narrative,
                    "tickers": tickers,
                    "stage": n.stage,
                    "confidence": n.confidence,
                    "reasoning": n.reasoning,
                    "signal": "new" if is_new else "early_to_building",
                })

        return results
    finally:
        s.close()
