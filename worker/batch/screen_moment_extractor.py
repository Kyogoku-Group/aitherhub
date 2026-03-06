"""
screen_moment_extractor.py  –  画面収録からsales_momentを抽出する
================================================================

画面収録（screen_recording）のキーフレームをGPT-4o Visionに投げ、
TikTok LIVEのUIポップアップ・数値変化から「売れた瞬間」を検出する。

検出対象 (moment_type_detail):
  1. purchase_popup     – 「◯人が購入しました」ポップアップ
  2. product_viewers_popup – 「◯人が商品を閲覧中です」ポップアップ
  3. viewer_spike       – 視聴者数の急増（前フレーム比）
  4. comment_spike      – コメント数の急増（前フレーム比）

出力形式:
  csv_slot_filter.detect_sales_moments() と同じ dict 形式で返す。
  → bulk_insert_sales_moments(source="screen") でそのまま保存可能。

コスト制御:
  - フレームをサンプリング（デフォルト: 5秒間隔）
  - 最大30フレームに制限
  - GPT-4o Vision 1回 = 1フレーム（バッチ化しない）
"""

import os
import re
import json
import glob
import base64
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("process_video")

# ── Vision API Config ──
# Azure OpenAI を優先（既存パイプラインと同じ方式）、フォールバックでOpenAI
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
VISION_API_VERSION = os.getenv("VISION_API_VERSION", "2024-06-01")
VISION_MODEL = os.getenv("VISION_MODEL", "gpt-4o")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE")

_client = None


def _get_client():
    """Get or create the Vision API client (lazy initialization).

    Priority: Azure OpenAI (same as existing pipeline) > OpenAI (non-Azure).
    """
    global _client
    if _client is not None:
        return _client

    # Prefer Azure OpenAI (consistent with existing pipeline)
    if AZURE_OPENAI_KEY and AZURE_OPENAI_ENDPOINT:
        from openai import AzureOpenAI
        _client = AzureOpenAI(
            api_key=AZURE_OPENAI_KEY,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_version=VISION_API_VERSION,
        )
        return _client

    # Fallback: OpenAI (non-Azure)
    if OPENAI_API_KEY and not OPENAI_API_KEY.startswith("your-"):
        from openai import OpenAI
        _client = OpenAI(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_API_BASE if OPENAI_API_BASE else None,
        )
        return _client

    raise RuntimeError(
        "No Vision API credentials found. "
        "Set AZURE_OPENAI_KEY+AZURE_OPENAI_ENDPOINT or OPENAI_API_KEY."
    )


# ── Prompt ──

SCREEN_MOMENT_PROMPT = """あなたはTikTok LIVEの画面収録フレームを分析する専門家です。

このフレームから以下の情報を読み取ってください。
読み取れない項目はnullとしてください。

必ず以下のJSON形式で返してください:

{
    "purchase_popup": {
        "detected": true/false,
        "text": "◯人が購入しました（原文そのまま）",
        "count": <購入人数（数値）>
    },
    "product_viewers_popup": {
        "detected": true/false,
        "text": "◯人が商品を閲覧中です（原文そのまま）",
        "count": <閲覧人数（数値）>
    },
    "viewer_count": <リアルタイム視聴者数（数値）>,
    "comment_count_visible": <画面上に見えるコメント数（数値）>,
    "shopping_rank": <ショッピングランキング番号（数値）>,
    "product_card_visible": true/false,
    "product_name": "<表示されている商品名>",
    "product_price": "<表示されている価格>"
}

注意:
- 「購入しました」「bought」「已购买」等のポップアップを見逃さないでください
- 「閲覧中」「viewing」「正在浏览」等のポップアップも検出してください
- 数値は必ず数字で返してください（「1.2万」→ 12000）
- ポップアップが検出できない場合は detected: false としてください
"""


def _encode_frame(frame_path: str) -> str:
    """Encode frame image to base64."""
    with open(frame_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _extract_frame_data(frame_path: str) -> Optional[Dict]:
    """
    1フレームからポップアップ・数値データを抽出する。

    Returns:
        Extracted data dict, or None on failure.
    """
    try:
        image_data = _encode_frame(frame_path)

        response = _get_client().chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": SCREEN_MOMENT_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_data}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
            max_tokens=800,
            temperature=0.1,
        )

        content = response.choices[0].message.content
        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            data = json.loads(json_match.group())
            return data
        else:
            logger.warning("[SCREEN_MOMENT] No JSON in response for %s", frame_path)
            return None

    except Exception as e:
        logger.error("[SCREEN_MOMENT] Vision API error for %s: %s", frame_path, e)
        return None


def _get_frame_time_sec(frame_path: str, fps: float = 1.0) -> float:
    """
    フレームファイル名から動画内の秒数を推定する。

    対応パターン:
      - frame_000123.jpg → 123 / fps
      - keyframe_00045.jpg → 45 / fps
      - 直接秒数: frame_at_120s.jpg → 120
    """
    basename = os.path.basename(frame_path)

    # パターン1: frame_000123.jpg
    m = re.search(r"(?:frame|keyframe)[_-]?(\d+)", basename)
    if m:
        frame_num = int(m.group(1))
        return frame_num / fps

    # パターン2: frame_at_120s.jpg
    m = re.search(r"(\d+)s", basename)
    if m:
        return float(m.group(1))

    return 0.0


def detect_screen_moments(
    frame_dir: str,
    keyframes: Optional[List[int]] = None,
    fps: float = 1.0,
    sample_interval_sec: float = 5.0,
    max_frames: int = 30,
    viewer_spike_threshold: float = 0.3,
    comment_spike_threshold: float = 0.5,
) -> List[Dict]:
    """
    画面収録のフレームからsales_momentを検出する。

    Args:
        frame_dir: フレーム画像のディレクトリ
        keyframes: キーフレームのインデックスリスト（Noneなら全フレーム）
        fps: フレームレート（秒あたりフレーム数）
        sample_interval_sec: サンプリング間隔（秒）
        max_frames: Vision APIに送る最大フレーム数
        viewer_spike_threshold: 視聴者数スパイク判定の閾値（前フレーム比）
        comment_spike_threshold: コメント数スパイク判定の閾値（前フレーム比）

    Returns:
        list of moment dicts (csv_slot_filter.detect_sales_moments互換形式)
    """
    # フレームファイルを収集
    frame_paths = sorted(glob.glob(os.path.join(frame_dir, "*.jpg")))
    if not frame_paths:
        frame_paths = sorted(glob.glob(os.path.join(frame_dir, "*.png")))
    if not frame_paths:
        logger.warning("[SCREEN_MOMENT] No frames found in %s", frame_dir)
        return []

    # キーフレームが指定されている場合はフィルタ
    if keyframes is not None and len(keyframes) > 0:
        indexed_paths = {i: p for i, p in enumerate(frame_paths)}
        frame_paths = [indexed_paths[k] for k in keyframes if k in indexed_paths]

    # サンプリング: sample_interval_sec 間隔でフレームを選択
    sample_step = max(1, int(sample_interval_sec * fps))
    sampled = frame_paths[::sample_step]

    # 最大フレーム数に制限
    if len(sampled) > max_frames:
        step = len(sampled) // max_frames
        sampled = sampled[::step][:max_frames]

    logger.info(
        "[SCREEN_MOMENT] Processing %d frames (from %d total, sample_interval=%.1fs)",
        len(sampled), len(frame_paths), sample_interval_sec,
    )

    # 各フレームを解析
    frame_data_list: List[Tuple[float, Dict]] = []
    for path in sampled:
        time_sec = _get_frame_time_sec(path, fps)
        data = _extract_frame_data(path)
        if data:
            frame_data_list.append((time_sec, data))

    if not frame_data_list:
        logger.warning("[SCREEN_MOMENT] No valid frame data extracted")
        return []

    # ソート
    frame_data_list.sort(key=lambda x: x[0])

    # Moment検出
    moments = []
    prev_viewer = None
    prev_comment = None

    for i, (time_sec, data) in enumerate(frame_data_list):
        frame_moments = []

        # 1. purchase_popup 検出
        pp = data.get("purchase_popup", {})
        if isinstance(pp, dict) and pp.get("detected"):
            count = pp.get("count", 0)
            text_raw = pp.get("text", "")
            confidence = 0.85 if count and count > 0 else 0.6
            frame_moments.append({
                "moment_type": "strong",
                "moment_type_detail": "purchase_popup",
                "confidence": confidence,
                "reasons": [f"purchase_popup: {text_raw}", f"count={count}"],
                "click_value": count or 0,
                "order_value": count or 0,
            })

        # 2. product_viewers_popup 検出
        pvp = data.get("product_viewers_popup", {})
        if isinstance(pvp, dict) and pvp.get("detected"):
            count = pvp.get("count", 0)
            text_raw = pvp.get("text", "")
            confidence = 0.75 if count and count > 0 else 0.5
            frame_moments.append({
                "moment_type": "click",
                "moment_type_detail": "product_viewers_popup",
                "confidence": confidence,
                "reasons": [f"product_viewers: {text_raw}", f"count={count}"],
                "click_value": count or 0,
                "order_value": 0,
            })

        # 3. viewer_spike 検出
        viewer_count = data.get("viewer_count")
        if viewer_count is not None and isinstance(viewer_count, (int, float)):
            if prev_viewer is not None and prev_viewer > 0:
                delta = viewer_count - prev_viewer
                pct = delta / prev_viewer
                if pct >= viewer_spike_threshold:
                    frame_moments.append({
                        "moment_type": "click",
                        "moment_type_detail": "viewer_spike",
                        "confidence": min(1.0, 0.4 + pct * 0.3),
                        "reasons": [f"viewer_spike: {prev_viewer}→{viewer_count} (+{pct*100:.0f}%)"],
                        "click_value": viewer_count,
                        "order_value": 0,
                    })
            prev_viewer = viewer_count

        # 4. comment_spike 検出
        comment_count = data.get("comment_count_visible")
        if comment_count is not None and isinstance(comment_count, (int, float)):
            if prev_comment is not None and prev_comment > 0:
                delta = comment_count - prev_comment
                pct = delta / prev_comment
                if pct >= comment_spike_threshold:
                    frame_moments.append({
                        "moment_type": "click",
                        "moment_type_detail": "comment_spike",
                        "confidence": min(1.0, 0.3 + pct * 0.2),
                        "reasons": [f"comment_spike: {prev_comment}→{comment_count} (+{pct*100:.0f}%)"],
                        "click_value": 0,
                        "order_value": 0,
                    })
            prev_comment = comment_count

        # フレームのmomentをまとめて追加
        for fm in frame_moments:
            moments.append({
                "time_key": f"{time_sec:.0f}s",
                "time_sec": time_sec,
                "video_sec": time_sec,  # 画面収録は動画=タイムライン
                "moment_type": fm["moment_type"],
                "moment_type_detail": fm["moment_type_detail"],
                "click_value": fm.get("click_value", 0),
                "click_delta": 0,
                "click_sigma_score": 0,
                "order_value": fm.get("order_value", 0),
                "order_delta": 0,
                "gmv_value": 0,
                "confidence": round(fm["confidence"], 2),
                "reasons": fm["reasons"],
            })

    # 重複排除: 同じ秒に同じmoment_type_detailが複数ある場合、confidenceが高い方を残す
    seen = {}
    deduped = []
    for m in moments:
        key = (round(m["video_sec"]), m["moment_type_detail"])
        if key not in seen or m["confidence"] > seen[key]["confidence"]:
            seen[key] = m

    deduped = sorted(seen.values(), key=lambda x: x["video_sec"])

    logger.info(
        "[SCREEN_MOMENT] Detected %d moments from %d frames "
        "(purchase_popup=%d, product_viewers=%d, viewer_spike=%d, comment_spike=%d)",
        len(deduped),
        len(frame_data_list),
        sum(1 for m in deduped if m["moment_type_detail"] == "purchase_popup"),
        sum(1 for m in deduped if m["moment_type_detail"] == "product_viewers_popup"),
        sum(1 for m in deduped if m["moment_type_detail"] == "viewer_spike"),
        sum(1 for m in deduped if m["moment_type_detail"] == "comment_spike"),
    )

    return deduped
