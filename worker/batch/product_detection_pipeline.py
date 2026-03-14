"""
product_detection_pipeline.py
─────────────────────────────
v4: 売上時間推定精度向上 + マージ・重複排除改善

v3からの改修点:
  1. detect_from_sales_data: 音声検出結果と照合して売上時間を推定
     - 均等分配（前5分）を廃止
     - 音声で確認済みの紹介区間に売上を紐付け
     - 音声未確認の場合はCSVスロット間隔ベースの狭い時間窓
  2. merge_all_exposures: 複数ソース確認時のconfidenceブースト
     - audio+sales二重確認で最高信頼度
     - ソース数に応じた段階的ブースト
  3. find_uncovered_gaps: 全ソースでギャップ判定
  4. post_filter_exposures: ソース数に応じたフィルタ緩和

アーキテクチャ:
  Phase 1: 音声トランスクリプトから商品言及時間帯を特定（API不要、即座）
  Phase 2: 売上データ（CSV）から売上発生時間帯を特定（API不要、即座）
           ★v4: 音声検出結果と照合して時間精度を向上
  Phase 3: 全ソースで特定できなかった「空白時間帯」のみ画像分析
  Phase 4: 全結果を統合・フィルタ・ブランド名補完
           ★v4: 信頼度計算を改善

入力:
  - frame_dir   : 1秒ごとに抽出されたフレーム画像のディレクトリ
  - product_list : [{"product_name": "...", "brand_name": "...", "image_url": "..."}, ...]
  - transcription_segments : Whisperの文字起こし結果 (任意)
  - excel_data   : Excelから読み込んだ売上データ (任意)

出力:
  - exposures : [{"product_name", "brand_name", "time_start", "time_end", "confidence"}, ...]
"""

import os
import re
import json
import time
import random
import base64
import asyncio
import logging
from collections import Counter
from functools import partial
from openai import AzureOpenAI, RateLimitError, APIError, APITimeoutError
from dotenv import load_dotenv
from decouple import config

load_dotenv()
logger = logging.getLogger("product_detection")

# ─── ENV & CLIENT ───────────────────────────────────────────
MAX_CONCURRENCY = 20

def env(key, default=None):
    return os.getenv(key) or config(key, default=default)

OPENAI_API_KEY = env("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = env("AZURE_OPENAI_ENDPOINT")
GPT5_API_VERSION = env("GPT5_API_VERSION")
GPT5_MODEL = env("GPT5_MODEL")

client = AzureOpenAI(
    api_key=OPENAI_API_KEY,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_version=GPT5_API_VERSION,
)


# ─── UTILS ──────────────────────────────────────────────────
def encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def safe_json_load(text: str):
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ─── PRODUCT NAME HELPER ─────────────────────────────────────────────
def _get_product_name(p: dict) -> str:
    """
    商品dictから商品名を柔軟に取得する。
    TikTok Seller Center等の様々なカラム名に対応。
    """
    # 直接キーで検索（優先順位順）
    direct_keys = [
        "product_name", "name", "商品名", "商品名称", "商品タイトル",
        "产品名称", "商品名稱", "Product Name", "Product Title",
        "sellercom_name", "seller_commodity_name",
        "상품명", "Tên sản phẩm", "ชื่อสินค้า", "Nama Produk",
    ]
    for key in direct_keys:
        val = p.get(key)
        if val and str(val).strip():
            return str(val).strip()

    # 部分一致で検索（キーに「商品」「product」「name」等を含むカラム）
    name_patterns = ["商品", "product", "name", "产品", "상품", "produk"]
    id_patterns = ["id", "code", "sku"]
    for key, val in p.items():
        if not val or not str(val).strip():
            continue
        key_lower = key.lower()
        if any(pat in key_lower for pat in id_patterns):
            continue
        if any(pat in key_lower for pat in name_patterns):
            return str(val).strip()

    # 最終フォールバック: 2番目のカラム（多くのCSVで商品名は2列目）
    keys = list(p.keys())
    if len(keys) >= 2:
        val = p.get(keys[1])
        if val and str(val).strip() and not str(val).strip().replace('.', '').isdigit():
            return str(val).strip()

    return ""


# ─── PRODUCT KEYWORD MAP ──────────────────────────────────────────────
def build_product_keyword_map(product_list: list[dict]) -> dict[str, list[str]]:
    """
    商品名からキーワードマップを構築。
    部分一致用に複数キーワードを生成する。
    """
    product_keywords: dict[str, list[str]] = {}
    for p in product_list:
        name = _get_product_name(p)
        if not name:
            continue
        keywords = []
        # フルネーム
        keywords.append(name.lower())
        # ブランド名
        brand = p.get("brand_name", p.get("brand", p.get("ブランド名", p.get("ブランド", ""))))
        if brand:
            keywords.append(brand.lower())
        # 商品名を分割してキーワード化（3文字以上の単語）
        words = re.split(r'[\s　・/\-]+', name)
        for w in words:
            w = w.strip().lower()
            skip_words = {'kyogoku', 'the', 'and', 'for', 'pro', '用', '式', '型'}
            if len(w) >= 3 and w not in skip_words:
                keywords.append(w)
        product_keywords[name] = list(set(keywords))
    return product_keywords


# ═══════════════════════════════════════════════════════════
# PHASE 1: 音声トランスクリプトから商品言及を検出（API不要）
# ═══════════════════════════════════════════════════════════
def detect_from_transcription(
    transcription_segments: list[dict],
    product_keywords: dict[str, list[str]],
    merge_gap: float = 15.0,
    min_duration: float = 5.0,
) -> list[dict]:
    """
    音声トランスクリプトから商品名の言及を検出し、
    連続する言及を統合してexposureセグメントを生成する。

    Returns: [{"product_name", "time_start", "time_end", "confidence", "source": "audio"}]
    """
    if not transcription_segments or not product_keywords:
        return []

    # 各商品の言及タイムスタンプを収集
    product_mentions: dict[str, list[tuple[float, float, int]]] = {}

    for seg in transcription_segments:
        text_lower = seg.get("text", "").lower()
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", 0)

        if not text_lower.strip():
            continue

        for product_name, keywords in product_keywords.items():
            match_count = 0
            for kw in keywords:
                if kw in text_lower and len(kw) >= 3:
                    match_count += 1

            if match_count > 0:
                if product_name not in product_mentions:
                    product_mentions[product_name] = []
                product_mentions[product_name].append((seg_start, seg_end, match_count))

    # 各商品について連続する言及を統合
    exposures = []
    for product_name, mentions in product_mentions.items():
        if not mentions:
            continue

        mentions.sort(key=lambda x: x[0])

        # 連続区間をグループ化
        seg_start = mentions[0][0]
        seg_end = mentions[0][1]
        total_matches = mentions[0][2]
        mention_count = 1

        for i in range(1, len(mentions)):
            m_start, m_end, m_count = mentions[i]
            if m_start - seg_end <= merge_gap:
                # 連続している → 延長
                seg_end = max(seg_end, m_end)
                total_matches += m_count
                mention_count += 1
            else:
                # ギャップ → 新しいセグメント
                duration = seg_end - seg_start
                if duration >= min_duration:
                    # confidence: 言及回数に基づく（多いほど高い）
                    conf = min(0.95, 0.60 + mention_count * 0.05 + total_matches * 0.02)
                    exposures.append({
                        "product_name": product_name,
                        "brand_name": "",
                        "time_start": max(0, seg_start - 5.0),  # 少し前から開始
                        "time_end": seg_end + 5.0,               # 少し後まで延長
                        "confidence": round(conf, 2),
                        "audio_confirmed": True,
                        "source": "audio",
                        "mention_count": mention_count,
                    })
                seg_start = m_start
                seg_end = m_end
                total_matches = m_count
                mention_count = 1

        # 最後のセグメント
        duration = seg_end - seg_start
        if duration >= min_duration:
            conf = min(0.95, 0.60 + mention_count * 0.05 + total_matches * 0.02)
            exposures.append({
                "product_name": product_name,
                "brand_name": "",
                "time_start": max(0, seg_start - 5.0),
                "time_end": seg_end + 5.0,
                "confidence": round(conf, 2),
                "audio_confirmed": True,
                "source": "audio",
                "mention_count": mention_count,
            })

    logger.info(
        "[PRODUCT-v4] Audio detection: found %d exposures for %d/%d products",
        len(exposures), len(product_mentions), len(product_keywords),
    )
    return exposures


# ═══════════════════════════════════════════════════════════
# PHASE 2: 売上データから商品露出時間帯を推定（v4: 音声照合ベース）
# ═══════════════════════════════════════════════════════════
def detect_from_sales_data(
    excel_data: dict | None,
    product_keywords: dict[str, list[str]],
    time_offset_seconds: float = 0,
    audio_exposures: list[dict] | None = None,
) -> list[dict]:
    """
    売上データ（CSV/Excel）から、売上が発生した時間帯に
    対応する商品の露出を推定する。

    v4改修:
    - 音声検出結果と照合し、音声で確認済みの紹介区間に売上を紐付ける
    - 音声で見つからない場合は、売上発生の直前のCSVスロットを参照して
      より狭い時間窓で推定（均等分配を廃止）
    - 複数スロットにまたがる売上は、注文数/GMVの重みで按分

    Returns: [{"product_name", "time_start", "time_end", "confidence", "source": "sales"}]
    """
    if not excel_data or not excel_data.get("has_trend_data"):
        return []

    trends = excel_data.get("trends", [])
    if not trends:
        return []

    try:
        from csv_slot_filter import _find_key, _parse_time_to_seconds, KPI_ALIASES
    except ImportError:
        logger.warning("[PRODUCT-v4] csv_slot_filter not available, skipping sales detection")
        return []

    sample = trends[0]
    time_key = _find_key(sample, KPI_ALIASES.get("time", []))
    product_name_key = _find_key(sample, KPI_ALIASES.get("product_name", []))
    order_key = _find_key(sample, KPI_ALIASES.get("order_count", []))
    gmv_key = _find_key(sample, KPI_ALIASES.get("gmv", []))

    if not time_key:
        logger.info("[PRODUCT-v4] No time column found in sales data")
        return []

    # ── CSVのタイムスロット間隔を推定 ──
    slot_times = []
    for entry in trends:
        t_sec = _parse_time_to_seconds(entry.get(time_key))
        if t_sec is not None:
            slot_times.append(t_sec)
    slot_times.sort()

    slot_interval = 60  # デフォルト1分
    if len(slot_times) >= 2:
        intervals = [slot_times[i+1] - slot_times[i] for i in range(len(slot_times)-1)]
        intervals = [iv for iv in intervals if iv > 0]
        if intervals:
            interval_counts = Counter(int(iv) for iv in intervals)
            slot_interval = interval_counts.most_common(1)[0][0]
            if slot_interval < 10:
                slot_interval = 60  # 異常値ガード

    logger.info("[PRODUCT-v4] Detected CSV slot interval: %d seconds", slot_interval)

    # ── 音声検出結果をインデックス化（商品名→時間区間リスト）──
    audio_index: dict[str, list[tuple[float, float]]] = {}
    if audio_exposures:
        for ae in audio_exposures:
            name = ae["product_name"]
            if name not in audio_index:
                audio_index[name] = []
            audio_index[name].append((ae["time_start"], ae["time_end"]))

    # ── 売上エントリを処理 ──
    exposures = []
    for entry in trends:
        t_sec = _parse_time_to_seconds(entry.get(time_key))
        if t_sec is None:
            continue

        # 動画内の時間に変換
        video_time = t_sec - time_offset_seconds
        if video_time < 0:
            continue

        # 注文/GMVチェック
        orders = 0
        if order_key:
            try:
                orders = int(float(entry.get(order_key, 0) or 0))
            except (ValueError, TypeError):
                orders = 0

        gmv = 0
        if gmv_key:
            try:
                gmv = float(entry.get(gmv_key, 0) or 0)
            except (ValueError, TypeError):
                gmv = 0

        if orders <= 0 and gmv <= 0:
            continue

        # 商品名の取得とマッチング
        product_name = None
        if product_name_key:
            raw_name = entry.get(product_name_key, "")
            if raw_name:
                product_name = str(raw_name).strip()

        if not product_name:
            continue

        matched_name = None
        for pname, keywords in product_keywords.items():
            for kw in keywords:
                if kw in product_name.lower() or product_name.lower() in kw:
                    matched_name = pname
                    break
            if matched_name:
                break

        if not matched_name:
            if product_name in product_keywords:
                matched_name = product_name

        if not matched_name:
            continue

        # ── v4: 音声検出結果と照合して時間を決定 ──
        audio_ranges = audio_index.get(matched_name, [])

        # 戦略1: 売上発生時刻の直前に音声で確認された紹介区間があるか
        # 売上は紹介の最中〜紹介後3分以内に発生するのが自然
        best_audio_match = None
        best_audio_distance = float('inf')
        for a_start, a_end in audio_ranges:
            if a_start <= video_time <= a_end + 180:
                distance = abs(video_time - (a_start + a_end) / 2)
                if distance < best_audio_distance:
                    best_audio_distance = distance
                    best_audio_match = (a_start, a_end)

        if best_audio_match:
            # 音声で確認済み → 音声区間をそのまま使い、confidenceをブースト
            exposures.append({
                "product_name": matched_name,
                "brand_name": "",
                "time_start": best_audio_match[0],
                "time_end": max(best_audio_match[1], video_time),
                "confidence": min(0.95, 0.80 + min(orders, 5) * 0.03),
                "audio_confirmed": True,
                "source": "sales",
                "sales_orders": orders,
                "sales_gmv": gmv,
                "sales_time": video_time,
            })
            logger.debug(
                "[PRODUCT-v4] Sales matched to audio: %s at %.0fs (audio: %.0f-%.0f)",
                matched_name, video_time, best_audio_match[0], best_audio_match[1],
            )
        else:
            # 戦略2: 音声で見つからない → CSVスロット単位で狭い時間窓を使用
            # 売上発生の「2スロット前〜1スロット後」を紹介時間と推定
            # （v3の「前5分」より大幅に狭い）
            lookback = min(slot_interval * 2, 180)  # 最大3分、通常は2スロット分
            exposures.append({
                "product_name": matched_name,
                "brand_name": "",
                "time_start": max(0, video_time - lookback),
                "time_end": video_time + slot_interval,
                "confidence": min(0.70, 0.50 + min(orders, 5) * 0.04),
                "audio_confirmed": False,
                "source": "sales",
                "sales_orders": orders,
                "sales_gmv": gmv,
                "sales_time": video_time,
            })
            logger.debug(
                "[PRODUCT-v4] Sales without audio match: %s at %.0fs (window: -%.0fs to +%.0fs)",
                matched_name, video_time, lookback, slot_interval,
            )

    # ── 同一商品の連続する売上スロットをマージ ──
    exposures = _merge_consecutive_sales(exposures, slot_interval)

    logger.info("[PRODUCT-v4] Sales detection: found %d exposures", len(exposures))
    return exposures


def _merge_consecutive_sales(exposures: list[dict], slot_interval: float) -> list[dict]:
    """同一商品の連続する売上スロットをマージ（v4新規）"""
    if not exposures:
        return []

    by_product: dict[str, list[dict]] = {}
    for exp in exposures:
        name = exp["product_name"]
        if name not in by_product:
            by_product[name] = []
        by_product[name].append(exp)

    merged = []
    for product_name, exps in by_product.items():
        exps.sort(key=lambda x: x.get("sales_time", x["time_start"]))

        current = exps[0].copy()
        current_orders = current.get("sales_orders", 0)
        current_gmv = current.get("sales_gmv", 0)

        for i in range(1, len(exps)):
            next_exp = exps[i]
            next_sales_time = next_exp.get("sales_time", next_exp["time_start"])
            curr_sales_time = current.get("sales_time", current["time_end"])

            if next_sales_time - curr_sales_time <= slot_interval * 2.5:
                current["time_end"] = max(current["time_end"], next_exp["time_end"])
                current["sales_time"] = next_sales_time
                current_orders += next_exp.get("sales_orders", 0)
                current_gmv += next_exp.get("sales_gmv", 0)
                current["confidence"] = min(0.95, current["confidence"] + 0.02)
                if next_exp.get("audio_confirmed"):
                    current["audio_confirmed"] = True
            else:
                current["sales_orders"] = current_orders
                current["sales_gmv"] = current_gmv
                merged.append(current)
                current = next_exp.copy()
                current_orders = current.get("sales_orders", 0)
                current_gmv = current.get("sales_gmv", 0)

        current["sales_orders"] = current_orders
        current["sales_gmv"] = current_gmv
        merged.append(current)

    merged.sort(key=lambda x: x["time_start"])
    return merged


# ═══════════════════════════════════════════════════════════
# PHASE 3: 空白時間帯のみ画像分析（最小限のAPI呼び出し）
# ═══════════════════════════════════════════════════════════
def find_uncovered_gaps(
    all_known_exposures: list[dict],
    total_duration: float,
    min_gap: float = 120.0,
) -> list[tuple[float, float]]:
    """
    全ソース（音声+売上）でカバーされていない時間帯（空白）を見つける。

    v4改修:
    - audio_exposuresだけでなく、全ソースの検出結果を考慮
    - 引数名をall_known_exposuresに変更
    """
    if not all_known_exposures:
        return [(0, total_duration)]

    sorted_exp = sorted(all_known_exposures, key=lambda x: x["time_start"])
    merged_ranges = []
    for exp in sorted_exp:
        start = exp["time_start"]
        end = exp["time_end"]
        if merged_ranges and start <= merged_ranges[-1][1] + 30:
            merged_ranges[-1] = (merged_ranges[-1][0], max(merged_ranges[-1][1], end))
        else:
            merged_ranges.append((start, end))

    gaps = []
    prev_end = 0
    for start, end in merged_ranges:
        if start - prev_end >= min_gap:
            gaps.append((prev_end, start))
        prev_end = end

    if total_duration - prev_end >= min_gap:
        gaps.append((prev_end, total_duration))

    return gaps


def build_product_detection_prompt(product_list: list[dict]) -> str:
    """商品リストを含むシステムプロンプトを構築する（v2と同じ高品質プロンプト）"""
    product_names = []
    for i, p in enumerate(product_list):
        name = _get_product_name(p) or f"Product_{i}"
        brand = p.get("brand_name", p.get("brand", p.get("ブランド名", p.get("ブランド", ""))))
        if brand:
            product_names.append(f"- {name} ({brand})")
        else:
            product_names.append(f"- {name}")

    product_list_str = "\n".join(product_names)

    prompt = f"""あなたはライブコマース動画の商品検出AIです。
以下は、このライブ配信で販売されている商品リストです：

{product_list_str}

このフレーム画像を分析して、**配信者が現在アクティブに紹介・説明している商品**を上記リストから特定してください。

【重要な判定基準 — 以下の状態の商品のみを検出してください】
- 配信者が手に持っている商品 → confidence: 0.85〜0.95
- 配信者がカメラに向けて見せている商品 → confidence: 0.80〜0.95
- 画面の中央に大きく映っている商品（クローズアップ） → confidence: 0.75〜0.90
- 配信者が指差している・触れている商品 → confidence: 0.70〜0.85

【除外すべきもの — 検出しないでください】
- 背景や棚に並んでいるだけの商品
- テーブルの上に置いてあるが、配信者が触れていない商品
- 画面の端に小さく映っているだけの商品
- 前の紹介で使った後、脇に置かれた商品
- 配信者の後ろに見える商品ディスプレイ

【判断のポイント】
- 配信者の手や腕の位置に注目する
- 商品が画面のどの位置にあるか（中央=紹介中の可能性高い、端=背景の可能性高い）
- 商品のサイズ（大きく映っている=紹介中、小さい=背景）
- 配信者の体の向き（商品に向いている=紹介中）

JSON形式で返してください：
{{
  "detected_products": [
    {{
      "product_name": "商品名（リストと完全一致）",
      "confidence": 0.0〜1.0,
      "detection_reason": "hand_holding|showing_camera|closeup|pointing|background_only"
    }}
  ]
}}

配信者が商品を紹介していない場合は空配列を返してください：
{{"detected_products": []}}"""
    return prompt


def detect_products_in_frame(image_path: str, prompt: str) -> list[dict]:
    """1フレームの商品検出（同期）"""
    img_b64 = encode_image(image_path)

    for attempt in range(5):
        try:
            resp = client.responses.create(
                model=GPT5_MODEL,
                input=[{
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": f"data:image/jpeg;base64,{img_b64}",
                        },
                    ],
                }],
                max_output_tokens=512,
            )
            data = safe_json_load(resp.output_text)
            if data and "detected_products" in data:
                results = []
                for det in data["detected_products"]:
                    reason = det.get("detection_reason", "")
                    if reason == "background_only":
                        continue
                    results.append(det)
                return results
            return []
        except (RateLimitError, APITimeoutError):
            sleep_time = (2 ** attempt) + random.uniform(0, 1)
            logger.warning("[PRODUCT] Rate limit, retry in %.1fs (attempt %d)", sleep_time, attempt + 1)
            time.sleep(sleep_time)
        except (APIError, Exception) as e:
            logger.warning("[PRODUCT] API error on %s: %s", os.path.basename(image_path), e)
            return []
    return []


async def detect_products_in_frame_async(
    image_path: str,
    prompt: str,
    sem: asyncio.Semaphore,
) -> list[dict]:
    """1フレームの商品検出（非同期ラッパー）"""
    async with sem:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            partial(detect_products_in_frame, image_path, prompt),
        )


def detect_from_images_for_gaps(
    frame_dir: str,
    product_list: list[dict],
    gaps: list[tuple[float, float]],
    sample_interval: int = 30,
    on_progress=None,
) -> list[dict]:
    """
    空白時間帯のみ画像分析を実行する。
    v2と同じ高品質プロンプトを使用するが、対象フレーム数を大幅に削減。
    """
    if not gaps:
        logger.info("[PRODUCT-v4] No gaps to analyze with images")
        return []

    files = sorted([f for f in os.listdir(frame_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
    if not files:
        return []

    # 空白時間帯のフレームインデックスを選択
    sample_indices = []
    for gap_start, gap_end in gaps:
        start_idx = max(0, int(gap_start))
        end_idx = min(len(files) - 1, int(gap_end))
        for idx in range(start_idx, end_idx + 1, sample_interval):
            if idx < len(files):
                sample_indices.append(idx)

    if not sample_indices:
        logger.info("[PRODUCT-v4] No frames to analyze in gaps")
        return []

    total_samples = len(sample_indices)
    logger.info(
        "[PRODUCT-v4] Image analysis for %d gaps: %d frames (interval=%ds)",
        len(gaps), total_samples, sample_interval,
    )

    prompt = build_product_detection_prompt(product_list)
    frame_detections: dict[int, list[dict]] = {}
    completed = [0]

    async def run_detection():
        sem = asyncio.Semaphore(MAX_CONCURRENCY)
        tasks = []

        for fidx in sample_indices:
            image_path = os.path.join(frame_dir, files[fidx])

            async def _detect(idx=fidx, path=image_path):
                result = await detect_products_in_frame_async(path, prompt, sem)
                frame_detections[idx] = result
                completed[0] += 1
                if on_progress and total_samples > 0:
                    pct = min(int(completed[0] / total_samples * 100), 100)
                    on_progress(pct)

            tasks.append(_detect())

        await asyncio.gather(*tasks)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                pool.submit(asyncio.run, run_detection()).result()
        else:
            loop.run_until_complete(run_detection())
    except RuntimeError:
        asyncio.run(run_detection())

    logger.info(
        "[PRODUCT-v4] Image detection complete: %d frames, %d had products",
        len(frame_detections),
        sum(1 for v in frame_detections.values() if v),
    )

    # フレーム検出結果をexposureに変換
    return merge_image_detections(frame_detections, sample_interval)


def merge_image_detections(
    frame_detections: dict[int, list[dict]],
    sample_interval: int = 30,
    min_duration: float = 8.0,
    confidence_threshold: float = 0.5,
) -> list[dict]:
    """フレームごとの画像検出結果を統合してexposureセグメントを生成する。"""
    if not frame_detections:
        return []

    sorted_frames = sorted(frame_detections.keys())
    product_frames: dict[str, list[tuple[int, float]]] = {}

    for fidx in sorted_frames:
        for det in frame_detections[fidx]:
            name = det.get("product_name", "")
            conf = det.get("confidence", 0.5)
            reason = det.get("detection_reason", "")
            if reason == "background_only":
                continue
            if not name or conf < confidence_threshold:
                continue
            if name not in product_frames:
                product_frames[name] = []
            product_frames[name].append((fidx, conf))

    exposures = []
    for product_name, frames in product_frames.items():
        if not frames:
            continue

        frames.sort(key=lambda x: x[0])
        gap_tolerance = sample_interval * 2 + 1
        segments = []
        seg_start = frames[0][0]
        seg_end = frames[0][0]
        seg_confs = [frames[0][1]]

        for i in range(1, len(frames)):
            fidx, conf = frames[i]
            if fidx - seg_end <= gap_tolerance:
                seg_end = fidx
                seg_confs.append(conf)
            else:
                segments.append((seg_start, seg_end, seg_confs))
                seg_start = fidx
                seg_end = fidx
                seg_confs = [conf]

        segments.append((seg_start, seg_end, seg_confs))

        for start_frame, end_frame, confs in segments:
            time_start = float(start_frame)
            time_end = float(end_frame + sample_interval)
            duration = time_end - time_start

            if duration < min_duration:
                continue

            avg_conf = sum(confs) / len(confs)
            exposures.append({
                "product_name": product_name,
                "brand_name": "",
                "time_start": time_start,
                "time_end": time_end,
                "confidence": round(avg_conf, 2),
                "audio_confirmed": False,
                "source": "image",
            })

    exposures.sort(key=lambda x: x["time_start"])
    return exposures


# ═══════════════════════════════════════════════════════════
# PHASE 4: 統合・フィルタ・補完（v4: 信頼度計算改善）
# ═══════════════════════════════════════════════════════════
def merge_all_exposures(
    audio_exposures: list[dict],
    sales_exposures: list[dict],
    image_exposures: list[dict],
) -> list[dict]:
    """
    3つのソースからのexposureを統合する。

    v4改修:
    - 複数ソースで確認された場合にconfidenceをブースト
    - audio+salesの二重確認は最高信頼度
    - ソース情報を保持して後段のフィルタで活用
    - time_startの精度: audioが最も正確、salesは売上時刻基準、imageは粗い
    """
    all_exposures = audio_exposures + sales_exposures + image_exposures

    if not all_exposures:
        return []

    # 商品ごとにグループ化
    by_product: dict[str, list[dict]] = {}
    for exp in all_exposures:
        name = exp["product_name"]
        if name not in by_product:
            by_product[name] = []
        by_product[name].append(exp)

    merged = []
    for product_name, exps in by_product.items():
        exps.sort(key=lambda x: x["time_start"])

        current = exps[0].copy()
        current_sources = {current.get("source", "unknown")}
        current_has_audio = current.get("audio_confirmed", False)
        current_has_sales = current.get("source") == "sales"
        current_sales_gmv = current.get("sales_gmv", 0)
        current_sales_orders = current.get("sales_orders", 0)

        for i in range(1, len(exps)):
            next_exp = exps[i]
            # 重複チェック（30秒以内のギャップはマージ）
            if next_exp["time_start"] <= current["time_end"] + 30:
                # ── マージ ──
                # time_start: audioソースの開始時刻を優先（最も正確）
                if next_exp.get("source") == "audio" and current.get("source") != "audio":
                    current["time_start"] = min(current["time_start"], next_exp["time_start"])
                current["time_end"] = max(current["time_end"], next_exp["time_end"])

                # ソース情報を収集
                next_source = next_exp.get("source", "unknown")
                current_sources.add(next_source)

                if next_exp.get("audio_confirmed"):
                    current_has_audio = True
                if next_source == "sales":
                    current_has_sales = True
                    current_sales_gmv += next_exp.get("sales_gmv", 0)
                    current_sales_orders += next_exp.get("sales_orders", 0)

                # ── v4: 信頼度計算 ──
                base_conf = max(current["confidence"], next_exp["confidence"])

                source_count = len(current_sources)
                if source_count >= 3:
                    source_bonus = 0.15  # audio + sales + image 三重確認
                elif source_count >= 2:
                    if current_has_audio and current_has_sales:
                        source_bonus = 0.12  # audio+sales は最も信頼性が高い
                    else:
                        source_bonus = 0.08
                else:
                    source_bonus = 0

                current["confidence"] = min(0.98, base_conf + source_bonus)

                if next_exp.get("audio_confirmed"):
                    current["audio_confirmed"] = True

            else:
                # ── 新しいセグメント ──
                current["source"] = "+".join(sorted(current_sources))
                current["source_count"] = len(current_sources)
                current["sales_gmv"] = current_sales_gmv
                current["sales_orders"] = current_sales_orders
                merged.append(current)

                current = next_exp.copy()
                current_sources = {current.get("source", "unknown")}
                current_has_audio = current.get("audio_confirmed", False)
                current_has_sales = current.get("source") == "sales"
                current_sales_gmv = current.get("sales_gmv", 0)
                current_sales_orders = current.get("sales_orders", 0)

        # 最後のセグメント
        current["source"] = "+".join(sorted(current_sources))
        current["source_count"] = len(current_sources)
        current["sales_gmv"] = current_sales_gmv
        current["sales_orders"] = current_sales_orders
        merged.append(current)

    merged.sort(key=lambda x: x["time_start"])
    return merged


def post_filter_exposures(
    exposures: list[dict],
    final_confidence_threshold: float = 0.45,
    min_final_duration: float = 8.0,
) -> list[dict]:
    """
    最終フィルタ

    v4改修:
    - 複数ソースで確認されたセグメントはフィルタを緩和
    - 売上データ付きのセグメントは保持しやすくする
    """
    filtered = []
    removed = []
    for exp in exposures:
        duration = exp["time_end"] - exp["time_start"]
        conf = exp.get("confidence", 0)
        source_count = exp.get("source_count", 1)
        has_sales = exp.get("sales_orders", 0) > 0 or exp.get("sales_gmv", 0) > 0

        # 複数ソース確認済み → フィルタ緩和
        if source_count >= 2:
            if conf >= 0.35 and duration >= 3.0:
                filtered.append(exp)
            else:
                removed.append(exp)
        # 売上データ付き → やや緩和
        elif has_sales:
            if conf >= 0.40 and duration >= 5.0:
                filtered.append(exp)
            else:
                removed.append(exp)
        # 音声確認済み
        elif exp.get("audio_confirmed"):
            if conf >= 0.40 and duration >= 5.0:
                filtered.append(exp)
            else:
                removed.append(exp)
        # 画像のみ
        else:
            if conf >= final_confidence_threshold and duration >= min_final_duration:
                filtered.append(exp)
            else:
                removed.append(exp)

    if removed:
        logger.info(
            "[PRODUCT-v4] Post-filter removed %d segments (kept %d)",
            len(removed), len(filtered),
        )

    return filtered


def fill_brand_names(exposures: list[dict], product_list: list[dict]) -> list[dict]:
    """product_listからbrand_nameとimage_urlを補完する"""
    name_to_info: dict[str, dict] = {}
    for p in product_list:
        name = _get_product_name(p)
        if name:
            name_to_info[name] = {
                "brand_name": p.get("brand_name", p.get("brand", p.get("ブランド名", p.get("ブランド", "")))),
                "image_url": p.get("image_url", p.get("product_image_url", "")),
            }

    for exp in exposures:
        info = name_to_info.get(exp["product_name"], {})
        exp["brand_name"] = info.get("brand_name", "")
        exp["product_image_url"] = info.get("image_url", "")

    return exposures


# ═══════════════════════════════════════════════════════════
# MAIN ENTRY POINT (v4)
# ═══════════════════════════════════════════════════════════
def detect_product_timeline(
    frame_dir: str,
    product_list: list[dict],
    transcription_segments: list[dict] | None = None,
    sample_interval: int = 5,  # 互換性のため残すが、v4では内部で最適化
    on_progress=None,
    excel_data: dict | None = None,
    time_offset_seconds: float = 0,
    duration_sec: float = 0,  # ★v4.1: フレームなしでも動作するよう追加
) -> list[dict]:
    """
    商品タイムライン検出のメインエントリポイント (v4.1)。

    v4.1改修:
      - フレーム画像がなくても音声・売上データから商品検出を実行
      - duration_sec引数を追加（フレームなし時のtotal_duration計算用）

    v4アーキテクチャ:
      1. 音声トランスクリプトから商品言及を検出（0秒、API不要）
      2. 売上データから商品露出を推定（0秒、API不要）
         ★v4: 音声検出結果と照合して時間精度を向上
      3. 全ソースで特定できなかった空白時間帯のみ画像分析
      4. 全結果を統合・フィルタ（★v4: 信頼度計算改善）

    Args:
        frame_dir: フレーム画像のディレクトリ
        product_list: 商品リスト
        transcription_segments: Whisper文字起こし結果
        sample_interval: (v4では内部最適化のため参考値)
        on_progress: 進捗コールバック (0-100)
        excel_data: Excelから読み込んだ売上データ
        time_offset_seconds: 動画の時間オフセット
        duration_sec: 動画の長さ（秒）。フレームがない場合に使用。

    Returns:
        exposures: [{"product_name", "brand_name", "time_start", "time_end",
                     "confidence", "product_image_url"}]
    """
    if not product_list:
        logger.warning("[PRODUCT-v4] No product list provided, skipping detection")
        return []

    # ★v4.1: フレームの有無を確認（Phase 3の画像分析でのみ必要）
    has_frames = False
    files = []
    try:
        if frame_dir and os.path.isdir(frame_dir):
            files = sorted([f for f in os.listdir(frame_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
            has_frames = len(files) > 0
    except Exception as e:
        logger.warning("[PRODUCT-v4] Error reading frame_dir %s: %s", frame_dir, e)

    # ★v4.1: total_durationの決定（優先順位: フレーム数 > duration_sec > 売上データ > トランスクリプト）
    if has_frames:
        total_duration = float(len(files))  # fps=1なのでフレーム数=秒数
    elif duration_sec > 0:
        total_duration = float(duration_sec)
    elif transcription_segments:
        # トランスクリプトの最後のセグメントからdurationを推定
        max_end = max((s.get("end", s.get("time_end", 0)) for s in transcription_segments), default=0)
        total_duration = float(max_end) if max_end > 0 else 0
    else:
        total_duration = 0

    # ★v4.2: excel_dataがあればtotal_duration=0でもPhase 2（売上データ検出）を実行
    has_excel = bool(excel_data and excel_data.get("has_trend_data"))
    if total_duration <= 0 and not has_frames and not has_excel:
        logger.warning("[PRODUCT-v4] No frames, no duration, and no excel data, skipping detection")
        return []
    if total_duration <= 0 and has_excel:
        # 売上データの時間範囲からdurationを推定
        try:
            from csv_slot_filter import _find_key, _parse_time_to_seconds, KPI_ALIASES
            trends = excel_data.get("trends", [])
            if trends:
                sample = trends[0]
                time_key = _find_key(sample, KPI_ALIASES.get("time", []))
                if time_key:
                    max_t = max((_parse_time_to_seconds(e.get(time_key)) or 0) for e in trends)
                    if max_t > 0:
                        total_duration = float(max_t)
                        logger.info("[PRODUCT-v4] Estimated duration from trend data: %.0f sec", total_duration)
        except Exception as _e:
            logger.warning("[PRODUCT-v4] Failed to estimate duration from trends: %s", _e)

    logger.info(
        "[PRODUCT-v4] Starting detection: %d frames (%.0f sec), %d products, has_frames=%s",
        len(files), total_duration, len(product_list), has_frames,
    )

    # キーワードマップを構築
    product_keywords = build_product_keyword_map(product_list)

    # ── PHASE 1: 音声検出（即座、API不要）──
    t0 = time.time()
    audio_exposures = []
    if transcription_segments:
        audio_exposures = detect_from_transcription(
            transcription_segments, product_keywords,
        )
    logger.info("[PRODUCT-v4] Phase 1 (audio): %d exposures in %.1fs", len(audio_exposures), time.time() - t0)

    if on_progress:
        on_progress(30)

    # ── PHASE 2: 売上データ検出（v4: 音声照合ベース）──
    t1 = time.time()
    sales_exposures = detect_from_sales_data(
        excel_data, product_keywords, time_offset_seconds,
        audio_exposures=audio_exposures,  # ★v4: 音声検出結果を渡す
    )
    logger.info("[PRODUCT-v4] Phase 2 (sales): %d exposures in %.1fs", len(sales_exposures), time.time() - t1)

    if on_progress:
        on_progress(50)

    # ── PHASE 3: 空白時間帯の画像分析（v4: 全ソースでギャップ判定）──
    t2 = time.time()
    image_exposures = []

    if has_frames and total_duration > 0:
        # ★v4.1: フレームがある場合のみ画像分析を実行
        all_known = audio_exposures + sales_exposures  # ★v4: salesも含めてギャップ判定
        gaps = find_uncovered_gaps(all_known, total_duration, min_gap=120.0)

        if gaps:
            total_gap_duration = sum(end - start for start, end in gaps)
            logger.info(
                "[PRODUCT-v4] Phase 3: %d gaps (total %.0f sec), analyzing with images",
                len(gaps), total_gap_duration,
            )

            def _on_image_progress(pct):
                if on_progress:
                    on_progress(50 + int(pct * 0.4))

            image_exposures = detect_from_images_for_gaps(
                frame_dir=frame_dir,
                product_list=product_list,
                gaps=gaps,
                sample_interval=30,
                on_progress=_on_image_progress,
            )
        else:
            logger.info("[PRODUCT-v4] Phase 3: No significant gaps, skipping image analysis")
    else:
        logger.info("[PRODUCT-v4] Phase 3: No frames available, skipping image analysis (audio+sales only)")

    logger.info("[PRODUCT-v4] Phase 3 (image): %d exposures in %.1fs", len(image_exposures), time.time() - t2)

    if on_progress:
        on_progress(90)

    # ── PHASE 4: 統合・フィルタ（v4: 信頼度計算改善）──
    exposures = merge_all_exposures(audio_exposures, sales_exposures, image_exposures)
    logger.info("[PRODUCT-v4] After merge: %d exposures", len(exposures))

    exposures = post_filter_exposures(exposures)
    logger.info("[PRODUCT-v4] After post-filter: %d exposures", len(exposures))

    exposures = fill_brand_names(exposures, product_list)

    if on_progress:
        on_progress(100)

    # サマリーログ
    total_time = time.time() - t0
    logger.info(
        "[PRODUCT-v4] COMPLETE: %d exposures (audio=%d, sales=%d, image=%d), "
        "total time=%.1fs, has_frames=%s",
        len(exposures),
        len(audio_exposures), len(sales_exposures), len(image_exposures),
        total_time, has_frames,
    )

    return exposures
