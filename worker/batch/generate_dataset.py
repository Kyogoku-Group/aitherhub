"""
generate_dataset.py  –  AI学習用データセット生成ジョブ v2
=====================================================
仕様:
  ① 目的変数: y_click (click_spike窓重複), y_order (order_spike窓重複), y_strong
  ② 1行 = 1 event (phase)
  ③ event × sales_moment は window ±150s で結合、距離減衰 weight
  ④ 正例:負例 = 1:3 サンプリング
  ⑤ 情報リーク防止: GMV/注文数/クリック数は特徴量に入れない

出力: train_click.jsonl / train_order.jsonl

特徴量 (v1):
  テキスト系: keyword flags (円/¥/割引/今だけ/残り/リンク/カート/タップ etc.)
              数字出現フラグ, text_length
  構造系:     event_type, event_duration, event_position_min
  商品系:     product_match, top_product_name_in_text
  CTA系:      cta_score, importance_score (AI生成なのでリークではない)

使い方:
  python generate_dataset.py --output-dir /tmp/datasets
  python generate_dataset.py --video-id abc-123 --output-dir /tmp/datasets
"""

import argparse
import json
import math
import os
import random
import re
import sys
import asyncio
from collections import defaultdict
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set")

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, echo=False)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

# ── Config ──
MOMENT_WINDOW_SEC = 150       # ±150s window for label matching
WEIGHT_DECAY_TAU = 60.0       # exp(-d/tau) decay constant
NEG_RATIO = 3                 # negative:positive ratio
RANDOM_SEED = 42

# ── Keyword flags for feature extraction ──
# 各キーワードグループ: (flag_name, [patterns])
KEYWORD_GROUPS = [
    ("kw_price",      [r"円", r"¥", r"\d+円", r"価格", r"値段", r"プライス"]),
    ("kw_discount",   [r"割引", r"割", r"OFF", r"オフ", r"セール", r"半額", r"お得", r"特別価格"]),
    ("kw_urgency",    [r"今だけ", r"限定", r"残り", r"ラスト", r"早い者勝ち", r"なくなり次第", r"本日限り"]),
    ("kw_cta",        [r"リンク", r"カート", r"タップ", r"クリック", r"押して", r"ポチ", r"購入", r"買って"]),
    ("kw_quantity",   [r"残り\d+", r"\d+個", r"\d+点", r"在庫", r"ストック"]),
    ("kw_comparison", [r"通常", r"定価", r"普通", r"比べ", r"違い", r"他と"]),
    ("kw_quality",    [r"品質", r"成分", r"効果", r"おすすめ", r"人気", r"ランキング"]),
    ("kw_number",     [r"\d{3,}"]),  # 3桁以上の数字 = 価格っぽい
]


def extract_keyword_flags(text_str: str) -> dict:
    """テキストからキーワードフラグを抽出."""
    if not text_str:
        return {g[0]: 0 for g in KEYWORD_GROUPS}
    flags = {}
    for flag_name, patterns in KEYWORD_GROUPS:
        matched = 0
        for pat in patterns:
            if re.search(pat, text_str, re.IGNORECASE):
                matched = 1
                break
        flags[flag_name] = matched
    return flags


def extract_text_features(text_str: str) -> dict:
    """テキスト長と数字出現フラグ."""
    if not text_str:
        return {"text_length": 0, "has_number": 0, "exclamation_count": 0}
    return {
        "text_length": len(text_str),
        "has_number": 1 if re.search(r"\d+", text_str) else 0,
        "exclamation_count": text_str.count("！") + text_str.count("!"),
    }


# ── DB Fetch Functions ──

async def fetch_phases(session, video_id=None, user_id=None):
    """Fetch video_phases with safe columns only (no GMV/order/click)."""
    conditions = []
    params = {}
    if video_id:
        conditions.append("vp.video_id = :video_id")
        params["video_id"] = video_id
    if user_id:
        conditions.append("vp.user_id = :user_id")
        params["user_id"] = user_id
    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    sql = text(f"""
        SELECT
            vp.video_id,
            vp.user_id,
            vp.phase_index,
            vp.phase_description,
            vp.time_start,
            vp.time_end,
            vp.cta_score,
            vp.sales_psychology_tags,
            vp.human_sales_tags,
            COALESCE(vp.importance_score, 0) as importance_score,
            vp.group_id
        FROM video_phases vp
        {where}
        ORDER BY vp.video_id, vp.phase_index
    """)
    result = await session.execute(sql, params)
    return result.fetchall()


async def fetch_sales_moments(session, video_id=None):
    """Fetch all sales moments."""
    params = {}
    where = ""
    if video_id:
        where = "WHERE video_id = :video_id"
        params["video_id"] = video_id

    sql = text(f"""
        SELECT video_id, video_sec, moment_type, confidence
        FROM video_sales_moments
        {where}
        ORDER BY video_id, video_sec
    """)
    result = await session.execute(sql, params)
    return result.fetchall()


async def fetch_product_stats(session, video_id=None):
    """Fetch product stats for product name matching."""
    params = {}
    where = ""
    if video_id:
        where = "WHERE video_id = :video_id"
        params["video_id"] = video_id

    sql = text(f"""
        SELECT video_id, product_name, product_clicks, gmv
        FROM video_product_stats
        {where}
        ORDER BY video_id, COALESCE(product_clicks, 0) DESC
    """)
    try:
        result = await session.execute(sql, params)
        return result.fetchall()
    except Exception:
        return []


async def fetch_video_durations(session, video_ids: list):
    """Fetch video durations for event_position normalization."""
    if not video_ids:
        return {}
    sql = text("""
        SELECT video_id, duration_seconds
        FROM videos
        WHERE video_id = ANY(:ids)
    """)
    try:
        result = await session.execute(sql, {"ids": video_ids})
        return {str(r.video_id): float(r.duration_seconds or 0) for r in result.fetchall()}
    except Exception:
        return {}


# ── Index Builders ──

def build_moments_index(moments_rows):
    """Build {video_id: [moment_dict, ...]}."""
    idx = defaultdict(list)
    for r in moments_rows:
        idx[str(r.video_id)].append({
            "video_sec": float(r.video_sec),
            "moment_type": r.moment_type,
            "confidence": r.confidence,
        })
    return dict(idx)


def build_product_names_index(product_rows):
    """Build {video_id: [product_name, ...]} (top products first)."""
    idx = defaultdict(list)
    for r in product_rows:
        name = r.product_name
        if name:
            idx[str(r.video_id)].append(name)
    return dict(idx)


# ── Label Computation ──

def compute_labels_v2(phase_start: float, phase_end: float, moments: list):
    """
    Compute labels with distance-weighted scoring.

    Returns:
      y_click: 1 if click_spike or strong within ±MOMENT_WINDOW_SEC
      y_order: 1 if order_spike or strong within ±MOMENT_WINDOW_SEC
      y_strong: 1 if strong within ±MOMENT_WINDOW_SEC
      weight_click: max distance-decay weight for click moments
      weight_order: max distance-decay weight for order moments
      nearest_click_sec: distance to nearest click/strong moment
      nearest_order_sec: distance to nearest order/strong moment
    """
    phase_mid = (phase_start + phase_end) / 2

    y_click = 0
    y_order = 0
    y_strong = 0
    weight_click = 0.0
    weight_order = 0.0
    nearest_click = None
    nearest_order = None

    for m in moments:
        sec = m["video_sec"]
        dist = abs(sec - phase_mid)

        if dist > MOMENT_WINDOW_SEC:
            continue

        w = math.exp(-dist / WEIGHT_DECAY_TAU)
        mtype = m["moment_type"]

        if mtype in ("click_spike", "strong"):
            y_click = 1
            weight_click = max(weight_click, w)
            if nearest_click is None or dist < nearest_click:
                nearest_click = dist

        if mtype in ("order_spike", "strong"):
            y_order = 1
            weight_order = max(weight_order, w)
            if nearest_order is None or dist < nearest_order:
                nearest_order = dist

        if mtype == "strong":
            y_strong = 1

    return {
        "y_click": y_click,
        "y_order": y_order,
        "y_strong": y_strong,
        "weight_click": round(weight_click, 4),
        "weight_order": round(weight_order, 4),
        "nearest_click_sec": round(nearest_click, 1) if nearest_click is not None else None,
        "nearest_order_sec": round(nearest_order, 1) if nearest_order is not None else None,
    }


def check_product_in_text(text_str: str, product_names: list) -> dict:
    """Check if top product names appear in phase text (partial match)."""
    if not text_str or not product_names:
        return {"product_match": 0, "product_match_top3": 0, "matched_product_count": 0}

    text_lower = text_str.lower()
    matched = 0
    matched_top3 = 0

    for i, name in enumerate(product_names):
        if not name:
            continue
        # Use first 6 chars for partial match (product names can be long)
        short_name = name[:6].lower().strip()
        if len(short_name) >= 2 and short_name in text_lower:
            matched += 1
            if i < 3:
                matched_top3 = 1

    return {
        "product_match": 1 if matched > 0 else 0,
        "product_match_top3": matched_top3,
        "matched_product_count": matched,
    }


def parse_json_field(raw):
    """Safely parse a JSON text field."""
    if not raw:
        return []
    try:
        if isinstance(raw, str):
            return json.loads(raw)
        return raw
    except (json.JSONDecodeError, TypeError):
        return []


# ── Main Generation ──

async def generate(output_dir: str, video_id=None, user_id=None):
    """Main dataset generation."""
    random.seed(RANDOM_SEED)

    async with AsyncSessionLocal() as session:
        print("[dataset] Fetching phases...")
        phases = await fetch_phases(session, video_id=video_id, user_id=user_id)
        print(f"[dataset] Found {len(phases)} phases")

        if not phases:
            print("[dataset] No phases found. Exiting.")
            return 0

        video_ids = list(set(str(r.video_id) for r in phases))
        print(f"[dataset] Spanning {len(video_ids)} videos")

        print("[dataset] Fetching sales moments...")
        try:
            moments_rows = await fetch_sales_moments(session, video_id=video_id)
            print(f"[dataset] Found {len(moments_rows)} sales moments")
        except Exception as e:
            print(f"[dataset] Warning: Could not fetch sales moments: {e}")
            moments_rows = []

        print("[dataset] Fetching product stats...")
        try:
            product_rows = await fetch_product_stats(session, video_id=video_id)
            print(f"[dataset] Found {len(product_rows)} product stats")
        except Exception as e:
            print(f"[dataset] Warning: Could not fetch product stats: {e}")
            product_rows = []

        print("[dataset] Fetching video durations...")
        durations = await fetch_video_durations(session, video_ids)

    await engine.dispose()

    # Build indexes
    moments_idx = build_moments_index(moments_rows)
    products_idx = build_product_names_index(product_rows)

    # ── Build all records ──
    all_records = []

    for r in phases:
        vid = str(r.video_id)
        phase_start = float(r.time_start) if r.time_start is not None else 0.0
        phase_end = float(r.time_end) if r.time_end is not None else 0.0
        duration = phase_end - phase_start

        if duration <= 0:
            continue

        # Tags
        tags = parse_json_field(r.sales_psychology_tags)
        human_tags = parse_json_field(r.human_sales_tags)
        event_type = tags[0] if tags else "UNKNOWN"

        # Description text for feature extraction
        desc = r.phase_description or ""

        # Labels
        video_moments = moments_idx.get(vid, [])
        labels = compute_labels_v2(phase_start, phase_end, video_moments)

        # Product match
        video_products = products_idx.get(vid, [])
        product_features = check_product_in_text(desc, video_products)

        # Keyword flags
        kw_flags = extract_keyword_flags(desc)

        # Text features
        text_feats = extract_text_features(desc)

        # Position in stream (minutes from start)
        video_duration = durations.get(vid, 0)
        event_position_min = round(phase_start / 60.0, 1)
        event_position_pct = round(phase_start / video_duration, 3) if video_duration > 0 else 0.0

        record = {
            # Identity (not features)
            "video_id": vid,
            "user_id": r.user_id,
            "phase_index": r.phase_index,

            # ── FEATURES (safe, no information leak) ──

            # Structure
            "event_type": event_type,
            "event_duration": round(duration, 1),
            "event_position_min": event_position_min,
            "event_position_pct": round(event_position_pct, 3),
            "tag_count": len(tags),

            # CTA / importance (AI-generated, not leaked)
            "cta_score": r.cta_score or 0,
            "importance_score": float(r.importance_score),

            # Text
            **text_feats,

            # Keywords
            **kw_flags,

            # Product
            **product_features,

            # Tags (for reference, not direct feature)
            "tags": tags,
            "human_tags": human_tags,
            "text": desc[:200],  # truncated for reference

            # ── LABELS ──
            **labels,
        }

        all_records.append(record)

    # ── Split into positive/negative and sample ──
    os.makedirs(output_dir, exist_ok=True)

    stats = {}
    for target in ["click", "order"]:
        y_key = f"y_{target}"
        w_key = f"weight_{target}"

        positives = [r for r in all_records if r[y_key] == 1]
        negatives = [r for r in all_records if r[y_key] == 0]

        n_pos = len(positives)
        n_neg = len(negatives)

        # Sample negatives to maintain ratio
        max_neg = n_pos * NEG_RATIO
        if n_neg > max_neg and max_neg > 0:
            negatives_sampled = random.sample(negatives, max_neg)
        else:
            negatives_sampled = negatives

        dataset = positives + negatives_sampled
        random.shuffle(dataset)

        # Write JSONL
        output_path = os.path.join(output_dir, f"train_{target}.jsonl")
        with open(output_path, "w", encoding="utf-8") as f:
            for rec in dataset:
                # Add sample_weight for training
                if rec[y_key] == 1:
                    rec["sample_weight"] = rec[w_key]
                else:
                    rec["sample_weight"] = 1.0
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        stats[target] = {
            "total": len(dataset),
            "positive": n_pos,
            "negative_sampled": len(negatives_sampled),
            "negative_total": n_neg,
            "path": output_path,
        }

        print(f"\n[dataset] {target}: {len(dataset)} records → {output_path}")
        print(f"  positive: {n_pos}, negative: {len(negatives_sampled)} (from {n_neg})")
        if n_pos > 0:
            print(f"  positive rate: {n_pos / len(dataset) * 100:.1f}%")

    # Also write combined stats
    stats_path = os.path.join(output_dir, "dataset_stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    print(f"\n[dataset] Stats → {stats_path}")

    return len(all_records)


def main():
    parser = argparse.ArgumentParser(description="Generate AI training dataset v2")
    parser.add_argument("--output-dir", "-o", default="/tmp/datasets",
                        help="Output directory for JSONL files")
    parser.add_argument("--video-id", default=None,
                        help="Filter by specific video ID")
    parser.add_argument("--user-id", type=int, default=None,
                        help="Filter by specific user ID")
    args = parser.parse_args()

    count = asyncio.run(generate(args.output_dir, video_id=args.video_id, user_id=args.user_id))
    if count == 0:
        print("[dataset] WARNING: No records generated.")
        sys.exit(1)


if __name__ == "__main__":
    main()
