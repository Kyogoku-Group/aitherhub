"""
Event Detection
================
Detects events in the video based on transcript segments.

Input (from context):
    - ctx.segments: Semantically segmented transcript blocks
    - ctx.scenes: Scene boundaries (for context)

Output (to context):
    - ctx.events: Detected events
      [{"start": float, "end": float, "event_type": str, "confidence": float, "description": str}, ...]

Event Types:
    - product_show:     Product is being displayed or demonstrated
    - price_mention:    Price or discount is mentioned
    - call_to_action:   Viewer is urged to buy/click/follow
    - comment_reaction: Response to viewer comments

Strategy (v1):
    Rule-based keyword detection on transcript segments.
    Future versions will use LLM for deeper understanding.
"""
import os
import sys
import re
import json
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from worker.pipeline.pipeline_context import PipelineContext

logger = logging.getLogger("worker.pipeline.event_detection")


# =============================================================================
# Keyword patterns for rule-based event detection (Japanese + English)
# =============================================================================

EVENT_PATTERNS: dict[str, list[str]] = {
    "product_show": [
        r"この商品",
        r"こちらの商品",
        r"見てください",
        r"ご覧ください",
        r"紹介します",
        r"紹介していき",
        r"こちらが",
        r"これが",
        r"使ってみ",
        r"試してみ",
        r"開封",
        r"レビュー",
        r"商品名",
        r"ブランド",
        r"product",
        r"item",
        r"check this out",
    ],
    "price_mention": [
        r"\d+円",
        r"\d+,\d+円",
        r"¥\d+",
        r"\$\d+",
        r"値段",
        r"価格",
        r"お値段",
        r"セール",
        r"割引",
        r"半額",
        r"クーポン",
        r"お得",
        r"安い",
        r"コスパ",
        r"percent off",
        r"discount",
        r"sale",
        r"price",
        r"\d+%\s*off",
        r"タイムセール",
        r"限定価格",
    ],
    "call_to_action": [
        r"リンク",
        r"概要欄",
        r"プロフィール",
        r"フォロー",
        r"いいね",
        r"コメント.*ください",
        r"シェア",
        r"チャンネル登録",
        r"購入",
        r"買って",
        r"ポチ",
        r"カートに",
        r"今すぐ",
        r"お早めに",
        r"数量限定",
        r"残りわずか",
        r"click",
        r"subscribe",
        r"follow",
        r"buy now",
        r"link in",
        r"check out",
    ],
    "comment_reaction": [
        r"コメント.*ありがとう",
        r"質問.*いただ",
        r"聞かれ",
        r"リクエスト",
        r"みなさん.*から",
        r"視聴者.*さん",
        r"コメント欄",
        r"DM",
        r"メッセージ",
        r"someone asked",
        r"you guys asked",
        r"comment",
        r"request",
    ],
}


def _detect_events_rule_based(segments: list[dict]) -> list[dict]:
    """Detect events using keyword pattern matching.

    For each segment, check all event patterns and record matches.
    Confidence is based on the number of pattern matches.
    """
    events = []

    for seg in segments:
        text = seg.get("text", "").lower()
        start = seg.get("start", 0.0)
        end = seg.get("end", 0.0)

        if not text:
            continue

        for event_type, patterns in EVENT_PATTERNS.items():
            matches = []
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    matches.append(pattern)

            if matches:
                # Confidence: more matches = higher confidence, capped at 1.0
                confidence = min(len(matches) / 3.0, 1.0)

                events.append({
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "event_type": event_type,
                    "confidence": round(confidence, 3),
                    "description": f"Matched {len(matches)} patterns: {', '.join(matches[:3])}",
                })

    return events


def _detect_events_llm(segments: list[dict]) -> list[dict]:
    """Detect events using LLM analysis.

    Sends transcript segments to GPT for event classification.
    Falls back to rule-based if LLM is unavailable.
    """
    try:
        from openai import OpenAI
    except ImportError:
        return []

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return []

    # Build transcript text for LLM
    transcript_text = "\n".join(
        f"[{seg.get('start', 0):.1f}s - {seg.get('end', 0):.1f}s] {seg.get('text', '')}"
        for seg in segments[:50]  # Limit to first 50 segments to stay within token limits
    )

    if not transcript_text.strip():
        return []

    prompt = f"""以下はライブコマース動画のトランスクリプトです。
各セグメントから以下のイベントを検出してください：

- product_show: 商品を見せている・紹介している
- price_mention: 価格・割引・セールに言及
- call_to_action: 購入・フォロー・リンクへの誘導
- comment_reaction: 視聴者コメントへの反応

トランスクリプト:
{transcript_text}

JSON配列で回答してください。各要素は:
{{"start": float, "end": float, "event_type": str, "confidence": float, "description": str}}

イベントが見つからない場合は空配列[]を返してください。"""

    try:
        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "You are a video analysis expert. Respond only with valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=4000,
        )

        content = response.choices[0].message.content.strip()
        # Extract JSON from response
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        events = json.loads(content)

        if isinstance(events, list):
            # Validate and clean
            valid_types = {"product_show", "price_mention", "call_to_action", "comment_reaction"}
            cleaned = []
            for evt in events:
                if isinstance(evt, dict) and evt.get("event_type") in valid_types:
                    cleaned.append({
                        "start": round(float(evt.get("start", 0)), 3),
                        "end": round(float(evt.get("end", 0)), 3),
                        "event_type": evt["event_type"],
                        "confidence": round(float(evt.get("confidence", 0.5)), 3),
                        "description": str(evt.get("description", "")),
                    })
            return cleaned

    except Exception as e:
        logger.warning("[event_detection] LLM detection failed: %s", e)

    return []


def run_event_detection(ctx: PipelineContext) -> PipelineContext:
    """Pipeline step: Detect events in the video.

    Uses a hybrid approach:
        1. Rule-based detection (always runs)
        2. LLM-based detection (if available, merges results)

    Saves results to both ctx.events and the database.
    """
    if not ctx.segments and not ctx.transcript:
        logger.info("[event_detection] No segments/transcript for video %s", ctx.video_id)
        ctx.events = []
        return ctx

    # Use segments if available, fall back to transcript
    source = ctx.segments if ctx.segments else ctx.transcript

    # Rule-based detection (fast, always available)
    rule_events = _detect_events_rule_based(source)
    logger.info("[event_detection] Rule-based: %d events", len(rule_events))

    # LLM-based detection (slower, more accurate)
    llm_events = _detect_events_llm(source)
    logger.info("[event_detection] LLM-based: %d events", len(llm_events))

    # Merge: LLM events take priority, add rule-based events that don't overlap
    all_events = list(llm_events)
    for rule_evt in rule_events:
        # Check if there's an overlapping LLM event of the same type
        overlaps = False
        for llm_evt in llm_events:
            if (rule_evt["event_type"] == llm_evt["event_type"]
                    and abs(rule_evt["start"] - llm_evt["start"]) < 5.0):
                overlaps = True
                break
        if not overlaps:
            all_events.append(rule_evt)

    # Sort by start time
    all_events.sort(key=lambda x: x["start"])

    ctx.events = all_events
    logger.info(
        "[event_detection] Total %d events detected for video %s",
        len(all_events), ctx.video_id,
    )

    # Save to DB
    try:
        from worker.pipeline.pipeline_db import save_events
        save_events(ctx.video_id, all_events)
    except Exception as e:
        logger.warning("[event_detection] DB save failed (non-critical): %s", e)

    return ctx
