"""
Sales Moment Detection
=======================
Detects high-conversion "sales moments" — the exact moments in a
live commerce video where purchases are most likely to occur.

Input (from context):
    - ctx.segments: Transcript segments
    - ctx.events: Detected events
    - ctx.scenes: Scene boundaries

Output (to context):
    - ctx.sales_moments: Ranked list of sales moment candidates
      [{"start": 42, "end": 50, "score": 0.91, "reason": "...", "events": [...]}, ...]

Strategy:
    Sales moments are identified by combining multiple signals:
    1. Event clustering: Regions with dense events (product_show + price_mention + CTA)
    2. Transcript energy: Segments with persuasive language patterns
    3. Scene dynamics: Rapid scene changes often indicate product demos
    4. LLM scoring: GPT evaluates candidate regions for sales potential

Scoring:
    - Base score from event density (0.0 - 0.5)
    - Bonus for event type combinations (up to +0.3)
    - LLM adjustment (up to +0.2)
    - Final score capped at 1.0
"""
import os
import sys
import json
import logging
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from worker.pipeline.pipeline_context import PipelineContext

logger = logging.getLogger("worker.pipeline.sales_moment_detection")

# Detection parameters
WINDOW_SIZE = 15.0         # Sliding window size in seconds
WINDOW_STEP = 5.0          # Step size for sliding window
MIN_SCORE = 0.3            # Minimum score to qualify as a sales moment
MAX_MOMENTS = 10           # Maximum number of sales moments to return
MERGE_THRESHOLD = 10.0     # Merge moments within this distance (seconds)

# Event type weights for scoring
EVENT_WEIGHTS = {
    "product_show": 0.25,
    "price_mention": 0.30,
    "call_to_action": 0.35,
    "comment_reaction": 0.10,
}

# Bonus for event type combinations
COMBO_BONUSES = {
    frozenset({"product_show", "price_mention"}): 0.10,
    frozenset({"price_mention", "call_to_action"}): 0.15,
    frozenset({"product_show", "price_mention", "call_to_action"}): 0.25,
}


def _score_window(
    window_start: float,
    window_end: float,
    events: list[dict],
    segments: list[dict],
) -> tuple[float, str, list[dict]]:
    """Score a time window for sales moment potential.

    Returns (score, reason, matching_events).
    """
    # Find events in this window
    window_events = [
        e for e in events
        if e["start"] >= window_start - 2.0 and e["end"] <= window_end + 2.0
    ]

    if not window_events:
        return 0.0, "", []

    # Base score: weighted sum of event types
    event_types = set()
    type_counts = defaultdict(int)
    for e in window_events:
        etype = e.get("event_type", "")
        event_types.add(etype)
        type_counts[etype] += 1

    base_score = 0.0
    for etype, count in type_counts.items():
        weight = EVENT_WEIGHTS.get(etype, 0.05)
        # Diminishing returns for multiple events of same type
        base_score += weight * min(count, 3)

    base_score = min(base_score, 0.5)

    # Combo bonus
    combo_bonus = 0.0
    for combo, bonus in COMBO_BONUSES.items():
        if combo.issubset(event_types):
            combo_bonus = max(combo_bonus, bonus)

    # Transcript energy: check if segments in this window have persuasive language
    energy_bonus = 0.0
    window_text = ""
    for seg in segments:
        if seg.get("start", 0) >= window_start and seg.get("end", 0) <= window_end:
            window_text += " " + seg.get("text", "")

    if window_text:
        # Simple heuristic: exclamation marks, urgency words
        import re
        urgency_patterns = [
            r"今だけ", r"限定", r"お早めに", r"残り", r"ラスト",
            r"特別", r"チャンス", r"見逃", r"急い",
            r"！", r"!", r"すごい", r"やばい", r"最高",
        ]
        urgency_count = sum(
            1 for p in urgency_patterns
            if re.search(p, window_text, re.IGNORECASE)
        )
        energy_bonus = min(urgency_count * 0.05, 0.15)

    total_score = min(base_score + combo_bonus + energy_bonus, 1.0)

    # Build reason
    reasons = []
    for etype in sorted(event_types):
        reasons.append(f"{etype}({type_counts[etype]})")
    if combo_bonus > 0:
        reasons.append(f"combo+{combo_bonus:.2f}")
    if energy_bonus > 0:
        reasons.append(f"urgency+{energy_bonus:.2f}")

    reason = ", ".join(reasons)

    return round(total_score, 3), reason, window_events


def _detect_sales_moments_sliding_window(
    events: list[dict],
    segments: list[dict],
    video_duration: float,
) -> list[dict]:
    """Detect sales moments using a sliding window approach."""
    if not events:
        return []

    # Determine scan range
    max_time = video_duration if video_duration > 0 else max(
        (e.get("end", 0) for e in events), default=300.0
    )

    candidates = []
    t = 0.0
    while t < max_time:
        window_end = t + WINDOW_SIZE
        score, reason, window_events = _score_window(t, window_end, events, segments)

        if score >= MIN_SCORE:
            candidates.append({
                "start": round(t, 3),
                "end": round(window_end, 3),
                "score": score,
                "reason": reason,
                "events": [
                    {"event_type": e["event_type"], "start": e["start"]}
                    for e in window_events
                ],
            })

        t += WINDOW_STEP

    # Sort by score descending
    candidates.sort(key=lambda x: x["score"], reverse=True)

    # Merge overlapping candidates
    merged = []
    for cand in candidates:
        # Check if this overlaps with an already selected moment
        overlaps = False
        for selected in merged:
            if abs(cand["start"] - selected["start"]) < MERGE_THRESHOLD:
                # Keep the higher-scored one
                if cand["score"] > selected["score"]:
                    selected.update(cand)
                overlaps = True
                break

        if not overlaps:
            merged.append(cand)

        if len(merged) >= MAX_MOMENTS:
            break

    # Re-sort by start time
    merged.sort(key=lambda x: x["start"])

    return merged


def _refine_with_llm(
    candidates: list[dict],
    segments: list[dict],
) -> list[dict]:
    """Optionally refine sales moment scores using LLM.

    Sends candidate moments with surrounding transcript to GPT
    for a more nuanced evaluation.
    """
    if not candidates:
        return candidates

    try:
        from openai import OpenAI
    except ImportError:
        return candidates

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return candidates

    # Build context for LLM
    moments_text = ""
    for i, cand in enumerate(candidates[:5]):  # Limit to top 5
        # Find transcript around this moment
        nearby_text = " ".join(
            seg.get("text", "")
            for seg in segments
            if seg.get("start", 0) >= cand["start"] - 5
            and seg.get("end", 0) <= cand["end"] + 5
        )
        moments_text += f"\nMoment {i+1} [{cand['start']:.1f}s - {cand['end']:.1f}s] (score={cand['score']}):\n"
        moments_text += f"  Events: {cand['reason']}\n"
        moments_text += f"  Transcript: {nearby_text[:200]}\n"

    prompt = f"""以下はライブコマース動画から検出された「売れた瞬間」候補です。
各候補のスコアを0.0〜1.0で再評価してください。

評価基準：
- 商品紹介 + 価格提示 + 購入誘導が揃っている = 高スコア
- 視聴者の購買意欲を刺激する表現がある = 高スコア
- 単なる雑談や挨拶 = 低スコア

候補:
{moments_text}

JSON配列で回答してください:
[{{"index": 0, "adjusted_score": 0.85, "reason": "..."}}]"""

    try:
        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "You are a live commerce analysis expert. Respond only with valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=2000,
        )

        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        adjustments = json.loads(content)

        if isinstance(adjustments, list):
            for adj in adjustments:
                idx = adj.get("index", -1)
                if 0 <= idx < len(candidates):
                    new_score = float(adj.get("adjusted_score", candidates[idx]["score"]))
                    candidates[idx]["score"] = round(min(max(new_score, 0.0), 1.0), 3)
                    if adj.get("reason"):
                        candidates[idx]["reason"] += f" | LLM: {adj['reason']}"

    except Exception as e:
        logger.warning("[sales_moment_detection] LLM refinement failed: %s", e)

    return candidates


def run_sales_moment_detection(ctx: PipelineContext) -> PipelineContext:
    """Pipeline step: Detect sales moments in the video.

    Combines event clustering, transcript analysis, and optional LLM scoring
    to identify the most likely high-conversion moments.

    Saves results to both ctx.sales_moments and the database.
    """
    if not ctx.events and not ctx.segments:
        logger.info("[sales_moment_detection] No events/segments for video %s", ctx.video_id)
        ctx.sales_moments = []
        return ctx

    # Detect candidates using sliding window
    candidates = _detect_sales_moments_sliding_window(
        ctx.events, ctx.segments, ctx.video_duration,
    )
    logger.info("[sales_moment_detection] Found %d candidates", len(candidates))

    # Refine with LLM
    if candidates:
        candidates = _refine_with_llm(candidates, ctx.segments)
        # Re-sort by score after LLM adjustment
        candidates.sort(key=lambda x: x["score"], reverse=True)

    ctx.sales_moments = candidates

    for i, sm in enumerate(candidates):
        logger.info(
            "[sales_moment_detection] #%d: %.1fs-%.1fs score=%.3f reason=%s",
            i + 1, sm["start"], sm["end"], sm["score"], sm["reason"],
        )

    # Save to DB
    try:
        from worker.pipeline.pipeline_db import save_sales_moments
        save_sales_moments(ctx.video_id, candidates)
    except Exception as e:
        logger.warning("[sales_moment_detection] DB save failed (non-critical): %s", e)

    return ctx
