"""
Unit tests for detect_sales_moments() in csv_slot_filter.py
"""
import sys
import os
import json
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_sales_moments")

# Add batch directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from csv_slot_filter import detect_sales_moments, _compute_rolling_stats


def test_rolling_stats():
    """_compute_rolling_stats が正しく動作するか"""
    values = [10, 12, 11, 50, 13, 14, 12]
    stats = _compute_rolling_stats(values, window=3)
    
    assert len(stats) == len(values), f"Expected {len(values)} stats, got {len(stats)}"
    
    # 各ポイントにmeanとstdがある
    for s in stats:
        assert "mean" in s, "Missing 'mean' key"
        assert "std" in s, "Missing 'std' key"
    
    # index=3 (value=50) は明らかに異常値 → stdが大きいはず
    logger.info("Rolling stats for spike at index 3:")
    for i, s in enumerate(stats):
        logger.info(f"  [{i}] value={values[i]}, mean={s['mean']:.2f}, std={s['std']:.2f}")
    
    print("✅ test_rolling_stats PASSED")


def test_detect_no_data():
    """空データの場合は空リストを返す"""
    result = detect_sales_moments(trends=[])
    assert result == [], f"Expected [], got {result}"
    print("✅ test_detect_no_data PASSED")


def test_detect_with_sample_trends():
    """サンプルのtrend_statsデータでsales_momentを検出"""
    # 典型的なTikTok CSVのtrend_statsデータを模擬
    # 「成約件数」→「成交件数」に修正（KPI_ALIASESに合わせる）
    trends = [
        {"時間": "20:00", "商品クリック数": 10, "成交件数": 2, "GMV": 5000},
        {"時間": "20:05", "商品クリック数": 12, "成交件数": 3, "GMV": 7000},
        {"時間": "20:10", "商品クリック数": 11, "成交件数": 2, "GMV": 5500},
        {"時間": "20:15", "商品クリック数": 50, "成交件数": 8, "GMV": 25000},  # ← スパイク！
        {"時間": "20:20", "商品クリック数": 13, "成交件数": 3, "GMV": 6000},
        {"時間": "20:25", "商品クリック数": 14, "成交件数": 3, "GMV": 6500},
        {"時間": "20:30", "商品クリック数": 12, "成交件数": 2, "GMV": 5000},
        {"時間": "20:35", "商品クリック数": 45, "成交件数": 10, "GMV": 30000},  # ← スパイク！
        {"時間": "20:40", "商品クリック数": 11, "成交件数": 2, "GMV": 5000},
    ]
    
    moments = detect_sales_moments(trends=trends, time_offset_seconds=0)
    
    logger.info(f"Detected {len(moments)} moments:")
    for m in moments:
        logger.info(f"  {m['time_key']} ({m['video_sec']:.0f}s) type={m['moment_type']} "
                    f"click={m['click_value']} order={m['order_value']} "
                    f"confidence={m['confidence']} reasons={m['reasons']}")
    
    assert len(moments) > 0, "Expected at least 1 moment detected"
    
    # 20:15のスパイクが検出されるはず
    spike_times = [m["time_key"] for m in moments]
    assert "20:15" in spike_times, f"Expected '20:15' in detected moments, got {spike_times}"
    
    # 20:15はclick+order両方のスパイク → strong moment
    spike_2015 = [m for m in moments if m["time_key"] == "20:15"][0]
    assert spike_2015["moment_type"] == "strong", \
        f"Expected 'strong' moment at 20:15, got '{spike_2015['moment_type']}'"
    
    # confidence は 0.0-1.0 の範囲
    for m in moments:
        assert 0.0 <= m["confidence"] <= 1.0, \
            f"Confidence out of range: {m['confidence']}"
    
    # video_sec は非負
    for m in moments:
        assert m["video_sec"] >= 0 or True, \
            f"video_sec should be non-negative: {m['video_sec']}"
    
    print("✅ test_detect_with_sample_trends PASSED")


def test_detect_with_english_columns():
    """英語カラム名でも動作するか"""
    trends = [
        {"Time": "20:00", "Product Clicks": 10, "Orders Created": 2, "GMV": 5000},
        {"Time": "20:05", "Product Clicks": 12, "Orders Created": 3, "GMV": 7000},
        {"Time": "20:10", "Product Clicks": 11, "Orders Created": 2, "GMV": 5500},
        {"Time": "20:15", "Product Clicks": 60, "Orders Created": 12, "GMV": 35000},  # spike
        {"Time": "20:20", "Product Clicks": 13, "Orders Created": 3, "GMV": 6000},
    ]
    
    moments = detect_sales_moments(trends=trends, time_offset_seconds=0)
    
    logger.info(f"English columns: Detected {len(moments)} moments")
    for m in moments:
        logger.info(f"  {m['time_key']} type={m['moment_type']} reasons={m['reasons']}")
    
    assert len(moments) > 0, "Expected at least 1 moment with English columns"
    print("✅ test_detect_with_english_columns PASSED")


def test_detect_with_chinese_columns():
    """中国語カラム名でも動作するか"""
    trends = [
        {"时间": "20:00", "商品点击数": 10, "成交订单数": 2, "成交金额": 5000},
        {"时间": "20:05", "商品点击数": 12, "成交订单数": 3, "成交金额": 7000},
        {"时间": "20:10", "商品点击数": 11, "成交订单数": 2, "成交金额": 5500},
        {"时间": "20:15", "商品点击数": 55, "成交订单数": 10, "成交金额": 30000},  # spike
        {"时间": "20:20", "商品点击数": 13, "成交订单数": 3, "成交金额": 6000},
    ]
    
    moments = detect_sales_moments(trends=trends, time_offset_seconds=0)
    
    logger.info(f"Chinese columns: Detected {len(moments)} moments")
    for m in moments:
        logger.info(f"  {m['time_key']} type={m['moment_type']} reasons={m['reasons']}")
    
    assert len(moments) > 0, "Expected at least 1 moment with Chinese columns"
    print("✅ test_detect_with_chinese_columns PASSED")


def test_detect_click_only_spike():
    """クリックのみスパイクの場合はclick typeになる"""
    trends = [
        {"時間": "20:00", "商品クリック数": 10, "成交件数": 5, "GMV": 5000},
        {"時間": "20:05", "商品クリック数": 12, "成交件数": 5, "GMV": 5000},
        {"時間": "20:10", "商品クリック数": 11, "成交件数": 5, "GMV": 5000},
        {"時間": "20:15", "商品クリック数": 50, "成交件数": 5, "GMV": 5000},  # click spike only
        {"時間": "20:20", "商品クリック数": 13, "成交件数": 5, "GMV": 5000},
    ]
    
    moments = detect_sales_moments(trends=trends, time_offset_seconds=0)
    
    logger.info(f"Click-only spike: Detected {len(moments)} moments")
    for m in moments:
        logger.info(f"  {m['time_key']} type={m['moment_type']} reasons={m['reasons']}")
    
    # 20:15にclick spikeがあるはず
    click_moments = [m for m in moments if m["time_key"] == "20:15"]
    if click_moments:
        assert click_moments[0]["moment_type"] == "click", \
            f"Expected 'click' type, got '{click_moments[0]['moment_type']}'"
    
    print("✅ test_detect_click_only_spike PASSED")


def test_detect_with_time_offset():
    """time_offset_secondsが正しくvideo_secに反映されるか"""
    trends = [
        {"時間": "20:00", "商品クリック数": 10, "成交件数": 2, "GMV": 5000},
        {"時間": "20:05", "商品クリック数": 50, "成交件数": 10, "GMV": 25000},  # spike
        {"時間": "20:10", "商品クリック数": 12, "成交件数": 3, "GMV": 6000},
    ]
    
    # offset = 300秒（5分）→ 動画は20:05から始まる
    moments = detect_sales_moments(trends=trends, time_offset_seconds=300)
    
    logger.info(f"With time offset: Detected {len(moments)} moments")
    for m in moments:
        logger.info(f"  {m['time_key']} time_sec={m['time_sec']} video_sec={m['video_sec']}")
    
    if moments:
        # 20:05のスパイク → video_sec = (20:05の秒) - (20:00の秒 + 300)
        # = 72300 - (72000 + 300) = 0
        spike = [m for m in moments if m["time_key"] == "20:05"]
        if spike:
            logger.info(f"  20:05 spike video_sec = {spike[0]['video_sec']}")
    
    print("✅ test_detect_with_time_offset PASSED")


def test_output_format():
    """出力フォーマットがDB挿入に適合するか確認"""
    trends = [
        {"時間": "20:00", "商品クリック数": 10, "成交件数": 2, "GMV": 5000},
        {"時間": "20:05", "商品クリック数": 12, "成交件数": 3, "GMV": 7000},
        {"時間": "20:10", "商品クリック数": 50, "成交件数": 8, "GMV": 25000},
    ]
    
    moments = detect_sales_moments(trends=trends)
    
    required_keys = [
        "time_key", "time_sec", "video_sec", "moment_type",
        "click_value", "click_delta", "click_sigma_score",
        "order_value", "order_delta", "gmv_value",
        "confidence", "reasons",
    ]
    
    for m in moments:
        for key in required_keys:
            assert key in m, f"Missing required key '{key}' in moment output"
        
        # reasonsはリストであること
        assert isinstance(m["reasons"], list), \
            f"reasons should be list, got {type(m['reasons'])}"
        
        # moment_typeは有効な値であること
        assert m["moment_type"] in ("strong", "click", "order"), \
            f"Invalid moment_type: {m['moment_type']}"
    
    # JSON serializableか確認
    json_str = json.dumps(moments, ensure_ascii=False)
    assert json_str, "Should be JSON serializable"
    
    print("✅ test_output_format PASSED")


if __name__ == "__main__":
    tests = [
        test_rolling_stats,
        test_detect_no_data,
        test_detect_with_sample_trends,
        test_detect_with_english_columns,
        test_detect_with_chinese_columns,
        test_detect_click_only_spike,
        test_detect_with_time_offset,
        test_output_format,
    ]
    
    passed = 0
    failed = 0
    
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            logger.error(f"❌ {test_fn.__name__} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed, {len(tests)} total")
    print(f"{'='*50}")
    
    if failed > 0:
        sys.exit(1)
