"""
Column Normalizer テスト

実際のExcelデータ形式でスコアリングが正しく動作するか検証する。
"""
import sys
import os

# テスト実行時のパス設定
sys.path.insert(0, os.path.dirname(__file__))

from column_normalizer import (
    find_best_column,
    detect_all_columns,
    log_detection_result,
    check_critical_metrics,
    find_key_scored,
    _score_column,
    _normalize_col,
    _load_mapping,
    reload_mapping,
    SCORE_EXACT_MATCH,
    SCORE_WORD_BOUNDARY,
    SCORE_SYNONYM_MATCH,
    SCORE_CORE_KEYWORD,
    SCORE_EXCLUDE_PENALTY,
    SCORE_NUMERIC_BONUS,
    SCORE_THRESHOLD,
)

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def test_normalize_col():
    """正規化テスト"""
    print("\n=== test_normalize_col ===")
    cases = [
        ("GMV", "gmv"),
        ("Order Count", "order_count"),
        ("  Viewer Count  ", "viewer_count"),
        ("live_workbench_metric_likes", "live_workbench_metric_likes"),
        ("gmv_metric_name_short_ui", "gmv_metric_name_short_ui"),
        ("千次观看成交金额", "千次观看成交金额"),
    ]
    for inp, expected in cases:
        result = _normalize_col(inp)
        status = "PASS" if result == expected else "FAIL"
        print(f"  {status}: _normalize_col({inp!r}) = {result!r} (expected {expected!r})")


def test_scoring_exact_match():
    """完全一致テスト"""
    print("\n=== test_scoring_exact_match ===")
    mapping = _load_mapping()

    # "GMV" は gmv の include リストに完全一致
    config = mapping["gmv"]
    score = _score_column("GMV", config, sample_value=1000)
    expected = SCORE_EXACT_MATCH + SCORE_NUMERIC_BONUS
    status = "PASS" if score == expected else "FAIL"
    print(f"  {status}: _score_column('GMV', gmv_config) = {score} (expected {expected})")

    # "gmv" も完全一致
    score = _score_column("gmv", config, sample_value=1000)
    status = "PASS" if score == expected else "FAIL"
    print(f"  {status}: _score_column('gmv', gmv_config) = {score} (expected {expected})")


def test_scoring_word_boundary():
    """単語境界一致テスト"""
    print("\n=== test_scoring_word_boundary ===")
    mapping = _load_mapping()
    config = mapping["gmv"]

    # "gmv_metric_name_short_ui" は gmv が単語境界で一致
    score = _score_column("gmv_metric_name_short_ui", config, sample_value=1000)
    # gmv は include にも完全一致で入っている → EXACT_MATCH ではなく
    # gmv_metric_name_short_ui は include に完全一致で入っている → EXACT_MATCH
    print(f"  INFO: _score_column('gmv_metric_name_short_ui', gmv_config) = {score}")
    status = "PASS" if score >= SCORE_THRESHOLD else "FAIL"
    print(f"  {status}: score >= THRESHOLD ({SCORE_THRESHOLD})")

    # "some_gmv_total" は gmv が単語境界で一致するが、includeにはない
    # ただし core_keywords に "gmv" があるので CORE_KEYWORD で拾える
    score2 = _score_column("some_gmv_total", config, sample_value=500)
    print(f"  INFO: _score_column('some_gmv_total', gmv_config) = {score2}")


def test_scoring_exclude():
    """除外語テスト"""
    print("\n=== test_scoring_exclude ===")
    mapping = _load_mapping()
    config = mapping["gmv"]

    # "gmv_growth_rate" は gmv にマッチするが、"rate" と "growth" が除外語
    score = _score_column("gmv_growth_rate", config, sample_value=0.5)
    print(f"  INFO: _score_column('gmv_growth_rate', gmv_config) = {score}")
    # gmv が単語境界一致(+80) + rate除外(-50) + 数値(+10) = 40 → ギリギリ閾値
    status = "PASS" if score < SCORE_EXACT_MATCH else "FAIL"
    print(f"  {status}: score < EXACT_MATCH (exclude penalty applied)")

    # "gmv_rate" は gmv にマッチするが "rate" が除外語
    score2 = _score_column("gmv_rate", config, sample_value=0.1)
    print(f"  INFO: _score_column('gmv_rate', gmv_config) = {score2}")


def test_sellercompass_format():
    """SellerCompass API形式のExcelデータでの検出テスト（今回の問題の再現）"""
    print("\n=== test_sellercompass_format ===")

    # 問題のビデオの実際のカラム名
    sellercompass_entry = {
        "time": "18:00",
        "gmv_metric_name_short_ui": 15000,
        "live_workbench_metric_orders_new": 25,
        "live_dashboard_follower_analytics_viewer": 1200,
        "live_workbench_metric_likes": 500,
        "live_workbench_metric_comments": 80,
        "live_workbench_metric_shares": 30,
        "seller_screen_live_core_data_new_followers": 15,
        "live_workbench_metric_product_clicks": 200,
        "ctor_metric_name_short_ui": 0.05,
        "live_workbench_basic_core_data_gpm": 3500,
    }

    result = detect_all_columns(sellercompass_entry)
    log_detection_result(result, video_id="test-sellercompass")

    detected = result["detected"]
    missing = result["missing"]

    critical_ok, critical_missing = check_critical_metrics(result)

    print(f"\n  Detected: {len(detected)} metrics")
    for k, v in detected.items():
        print(f"    {k} -> {v}")

    print(f"  Missing: {len(missing)} metrics: {missing}")
    print(f"  Critical OK: {critical_ok}")
    if critical_missing:
        print(f"  Critical Missing: {critical_missing}")

    # 重要メトリクスが全て検出されるべき
    expected_detected = {
        "gmv": "gmv_metric_name_short_ui",
        "order_count": "live_workbench_metric_orders_new",
        "viewer_count": "live_dashboard_follower_analytics_viewer",
        "like_count": "live_workbench_metric_likes",
    }

    all_pass = True
    for metric, expected_col in expected_detected.items():
        actual = detected.get(metric)
        status = "PASS" if actual == expected_col else "FAIL"
        if actual != expected_col:
            all_pass = False
        print(f"  {status}: {metric} -> {actual} (expected {expected_col})")

    return all_pass


def test_chinese_format():
    """従来の中国語形式のExcelデータでの検出テスト（既存動作の後方互換）"""
    print("\n=== test_chinese_format ===")

    chinese_entry = {
        "时间": "18:00",
        "成交金额": 15000,
        "成交件数": 25,
        "观看人数": 1200,
        "点赞数": 500,
        "评论数": 80,
        "分享次数": 30,
        "新增粉丝数": 15,
        "商品点击量": 200,
        "点击成交转化率": 0.05,
        "千次观看成交金额": 3500,
    }

    result = detect_all_columns(chinese_entry)
    log_detection_result(result, video_id="test-chinese")

    detected = result["detected"]
    critical_ok, critical_missing = check_critical_metrics(result)

    expected_detected = {
        "gmv": "成交金额",
        "order_count": "成交件数",
        "viewer_count": "观看人数",
        "like_count": "点赞数",
    }

    all_pass = True
    for metric, expected_col in expected_detected.items():
        actual = detected.get(metric)
        status = "PASS" if actual == expected_col else "FAIL"
        if actual != expected_col:
            all_pass = False
        print(f"  {status}: {metric} -> {actual} (expected {expected_col})")

    print(f"  Critical OK: {critical_ok}")
    return all_pass


def test_japanese_format():
    """日本語形式のExcelデータでの検出テスト"""
    print("\n=== test_japanese_format ===")

    japanese_entry = {
        "時間": "18:00",
        "売上": 15000,
        "注文": 25,
        "視聴者数": 1200,
        "いいね数": 500,
        "コメント数": 80,
        "シェア数": 30,
        "新規フォロワー数": 15,
        "商品クリック数": 200,
    }

    result = detect_all_columns(japanese_entry)
    log_detection_result(result, video_id="test-japanese")

    detected = result["detected"]
    critical_ok, critical_missing = check_critical_metrics(result)

    expected_detected = {
        "gmv": "売上",
        "order_count": "注文",
        "viewer_count": "視聴者数",
        "like_count": "いいね数",
    }

    all_pass = True
    for metric, expected_col in expected_detected.items():
        actual = detected.get(metric)
        status = "PASS" if actual == expected_col else "FAIL"
        if actual != expected_col:
            all_pass = False
        print(f"  {status}: {metric} -> {actual} (expected {expected_col})")

    print(f"  Critical OK: {critical_ok}")
    return all_pass


def test_english_format():
    """英語形式のExcelデータでの検出テスト"""
    print("\n=== test_english_format ===")

    english_entry = {
        "Time": "18:00",
        "GMV": 15000,
        "Orders": 25,
        "Viewers": 1200,
        "Likes": 500,
        "Comments": 80,
        "Shares": 30,
        "New Followers": 15,
        "Product Clicks": 200,
        "GPM": 3500,
    }

    result = detect_all_columns(english_entry)
    log_detection_result(result, video_id="test-english")

    detected = result["detected"]
    critical_ok, critical_missing = check_critical_metrics(result)

    expected_detected = {
        "gmv": "GMV",
        "order_count": "Orders",
        "viewer_count": "Viewers",
        "like_count": "Likes",
    }

    all_pass = True
    for metric, expected_col in expected_detected.items():
        actual = detected.get(metric)
        status = "PASS" if actual == expected_col else "FAIL"
        if actual != expected_col:
            all_pass = False
        print(f"  {status}: {metric} -> {actual} (expected {expected_col})")

    print(f"  Critical OK: {critical_ok}")
    return all_pass


def test_unknown_format():
    """未知の形式（将来の新フォーマット）での検出テスト"""
    print("\n=== test_unknown_format ===")

    # 将来SellerCompassが列名を変えた場合のシミュレーション
    future_entry = {
        "timestamp_utc": "18:00:00",
        "total_gmv_amount": 15000,
        "confirmed_orders_count": 25,
        "concurrent_viewer_number": 1200,
        "total_likes_received": 500,
        "user_comments_total": 80,
    }

    result = detect_all_columns(future_entry)
    log_detection_result(result, video_id="test-future")

    detected = result["detected"]
    missing = result["missing"]
    candidates = result["candidates"]

    print(f"\n  Detected: {len(detected)} metrics")
    for k, v in detected.items():
        print(f"    {k} -> {v}")
    print(f"  Missing: {len(missing)} metrics: {missing}")
    for m in missing:
        cands = candidates.get(m, [])
        if cands:
            print(f"    {m} candidates: {cands}")

    # この場合、部分一致やコアキーワードで一部は拾えるはず
    # gmv → total_gmv_amount (core_keyword "gmv" がヒット)
    # order_count → confirmed_orders_count (core_keyword "order" がヒット)
    # viewer_count → concurrent_viewer_number (core_keyword "viewer" がヒット)
    # like_count → total_likes_received (core_keyword "like" がヒット)
    critical_ok, critical_missing = check_critical_metrics(result)
    print(f"  Critical OK: {critical_ok}")
    if critical_missing:
        print(f"  Critical Missing: {critical_missing}")


def test_trap_columns():
    """罠カラム（gmv_rate等）を誤選択しないテスト"""
    print("\n=== test_trap_columns ===")

    trap_entry = {
        "time": "18:00",
        "gmv_rate": 0.05,           # 罠: これはGMVではなくGMV変化率
        "gmv_growth_pct": 12.5,     # 罠: GMV成長率
        "actual_gmv": 15000,        # 正解: 実際のGMV
        "order_cancel_rate": 0.02,  # 罠: 注文キャンセル率
        "total_orders": 25,         # 正解: 注文数
        "viewer_avg_duration": 120, # 罠: 平均視聴時間
        "peak_viewers": 1500,       # 罠: ピーク視聴者（excludeにpeak）
        "current_viewers": 1200,    # 正解に近い: 現在の視聴者
    }

    result = detect_all_columns(trap_entry)
    log_detection_result(result, video_id="test-trap")

    detected = result["detected"]

    # gmv_rate ではなく actual_gmv が選ばれるべき
    gmv_col = detected.get("gmv")
    print(f"\n  gmv detected: {gmv_col}")
    status = "PASS" if gmv_col == "actual_gmv" else "FAIL"
    print(f"  {status}: gmv should be 'actual_gmv', not 'gmv_rate' or 'gmv_growth_pct'")

    # order_cancel_rate ではなく total_orders が選ばれるべき
    order_col = detected.get("order_count")
    print(f"  order_count detected: {order_col}")
    status = "PASS" if order_col == "total_orders" else "FAIL"
    print(f"  {status}: order_count should be 'total_orders', not 'order_cancel_rate'")


def test_backward_compat_find_key_scored():
    """旧 _find_key 互換のfind_key_scoredテスト"""
    print("\n=== test_backward_compat_find_key_scored ===")

    entry = {
        "gmv_metric_name_short_ui": 15000,
        "live_workbench_metric_orders_new": 25,
        "time": "18:00",
    }

    # 旧スタイルの呼び出し
    gmv_key = find_key_scored(entry, ["gmv", "GMV", "成交金额", "gmv_metric_name_short_ui"])
    print(f"  gmv_key = {gmv_key}")
    status = "PASS" if gmv_key == "gmv_metric_name_short_ui" else "FAIL"
    print(f"  {status}: find_key_scored for gmv")

    order_key = find_key_scored(entry, ["成交件数", "订单数", "orders", "live_workbench_metric_orders_new"])
    print(f"  order_key = {order_key}")
    status = "PASS" if order_key == "live_workbench_metric_orders_new" else "FAIL"
    print(f"  {status}: find_key_scored for orders")


# ======================================================
# MAIN
# ======================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Column Normalizer Test Suite")
    print("=" * 60)

    # 設定ファイルを読み込み
    reload_mapping()

    test_normalize_col()
    test_scoring_exact_match()
    test_scoring_word_boundary()
    test_scoring_exclude()

    # 各フォーマットのテスト
    sc_pass = test_sellercompass_format()
    cn_pass = test_chinese_format()
    jp_pass = test_japanese_format()
    en_pass = test_english_format()
    test_unknown_format()
    test_trap_columns()
    test_backward_compat_find_key_scored()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    results = {
        "SellerCompass format": sc_pass,
        "Chinese format": cn_pass,
        "Japanese format": jp_pass,
        "English format": en_pass,
    }
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {status}: {name}")

    all_critical = all(results.values())
    print(f"\n  Overall: {'ALL CRITICAL TESTS PASSED' if all_critical else 'SOME TESTS FAILED'}")
    sys.exit(0 if all_critical else 1)
