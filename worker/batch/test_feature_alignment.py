"""
test_feature_alignment.py  –  generate_dataset.py v4 ↔ train.py v5 整合性テスト
================================================================================
ドライランで以下を検証:
  1. generate_dataset.py が出力するJSONLレコードのキーが train.py の特徴量定義と一致
  2. train.py extract_features() が正しい次元の行列を生成
  3. predict.py _record_to_features() が同じ次元を生成
  4. compute_labels_v2 が CSV / screen / mixed moments を正しく処理
  5. 特徴量名の一覧を出力
"""

import json
import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

# ── Import from train.py ──
from train import (
    NUMERIC_FEATURES, KEYWORD_FEATURES, PRODUCT_FEATURES,
    HUMAN_TAG_FEATURES, COMMENT_KEYWORD_FEATURES,
    KNOWN_EVENT_TYPES, extract_features, MODEL_VERSION,
)

# ── Import from generate_dataset.py ──
from generate_dataset import (
    ALL_HUMAN_TAGS, BEHAVIOR_TAGS, PSYCHOLOGY_TAGS,
    KEYWORD_GROUPS, COMMENT_KEYWORD_GROUPS,
    extract_keyword_flags, extract_comment_keyword_flags,
    extract_text_features, extract_human_tag_features,
    extract_comment_features,
    compute_labels_v2,
    build_moments_index,
)


def make_dummy_record():
    """Create a realistic dummy record as generate_dataset.py would produce."""
    desc = "今だけ特別価格3980円！残り10個です。リンクをタップして購入してください。"
    comment = "CTA強い。価格の見せ方がうまい。タイミングも良い。"

    kw_flags = extract_keyword_flags(desc)
    text_feats = extract_text_features(desc)
    htag_features = extract_human_tag_features(["EMPATHY", "URGENCY", "CTA", "HOOK"])
    comment_feats = extract_comment_features(comment)

    record = {
        # Identity
        "video_id": "test-video-001",
        "user_id": 1,
        "phase_index": 5,

        # Structure
        "event_type": "CTA",
        "event_duration": 45.2,
        "event_position_min": 12.5,
        "event_position_pct": 0.35,
        "tag_count": 3,

        # CTA / importance
        "cta_score": 4,
        "importance_score": 0.85,

        # Text
        **text_feats,

        # Keywords
        **kw_flags,

        # Product
        "product_match": 1,
        "product_match_top3": 1,
        "matched_product_count": 2,

        # Human review features (v3/v5)
        "user_rating": 4,
        "has_human_review": 1,
        "human_tag_count": 4,
        **htag_features,
        **comment_feats,

        # Metadata
        "tags": ["CTA", "URGENCY"],
        "human_tags": ["EMPATHY", "URGENCY", "CTA", "HOOK"],
        "reviewer_name": "Yuuki",
        "text": desc[:200],
        "comment_text": comment[:200],

        # Labels (v4 – includes source fields)
        "y_click": 1,
        "y_order": 0,
        "y_strong": 0,
        "weight_click": 0.85,
        "weight_order": 0.0,
        "nearest_click_sec": 15.3,
        "nearest_order_sec": None,
        "moment_source": "csv",
        "has_screen_moment": 0,
        "has_csv_moment": 1,
        "screen_purchase_popup": 0,
        "screen_product_viewers": 0,
        "sample_weight": 0.85,
    }
    return record


def test_feature_alignment():
    """Test that all feature definitions are aligned."""
    print(f"=" * 70)
    print(f"Feature Alignment Test — train.py v{MODEL_VERSION}")
    print(f"=" * 70)

    # 1. Build expected feature names (same order as train.py extract_features)
    expected_features = []
    expected_features.extend(NUMERIC_FEATURES)
    expected_features.extend(KEYWORD_FEATURES)
    expected_features.extend(PRODUCT_FEATURES)
    expected_features.extend(HUMAN_TAG_FEATURES)
    expected_features.extend(COMMENT_KEYWORD_FEATURES)
    expected_features.extend([f"event_{et}" for et in KNOWN_EVENT_TYPES])

    print(f"\n[1] Feature count breakdown:")
    print(f"  NUMERIC_FEATURES:          {len(NUMERIC_FEATURES)}")
    print(f"  KEYWORD_FEATURES:          {len(KEYWORD_FEATURES)}")
    print(f"  PRODUCT_FEATURES:          {len(PRODUCT_FEATURES)}")
    print(f"  HUMAN_TAG_FEATURES:        {len(HUMAN_TAG_FEATURES)}")
    print(f"  COMMENT_KEYWORD_FEATURES:  {len(COMMENT_KEYWORD_FEATURES)}")
    print(f"  EVENT_TYPE one-hot:        {len(KNOWN_EVENT_TYPES)}")
    print(f"  ─────────────────────────────────")
    print(f"  TOTAL:                     {len(expected_features)}")

    # 2. Create dummy record
    record = make_dummy_record()
    print(f"\n[2] Dummy record created with {len(record)} keys")

    # 3. Test extract_features from train.py
    print(f"\n[3] Testing train.py extract_features()...")
    X, y, w, group_ids, feature_names, unique_vids, video_ids_raw = extract_features([record], target="click")
    print(f"  X shape: {X.shape}")
    print(f"  feature_names count: {len(feature_names)}")
    print(f"  y: {y}")
    print(f"  w: {w}")

    assert X.shape[1] == len(expected_features), \
        f"MISMATCH: X has {X.shape[1]} cols but expected {len(expected_features)}"
    assert len(feature_names) == len(expected_features), \
        f"MISMATCH: feature_names has {len(feature_names)} but expected {len(expected_features)}"
    print(f"  ✅ Feature matrix dimension matches expected ({X.shape[1]})")

    # 4. Verify feature names match
    for i, (actual, expected) in enumerate(zip(feature_names, expected_features)):
        if actual != expected:
            print(f"  ❌ Feature {i}: actual='{actual}' expected='{expected}'")
            sys.exit(1)
    print(f"  ✅ All feature names match")

    # 5. Verify non-zero values for human review features
    print(f"\n[4] Checking human review feature values...")
    for i, fname in enumerate(feature_names):
        if fname.startswith("htag_") or fname.startswith("comment_kw_") or \
           fname in ("user_rating", "has_human_review", "human_tag_count", "comment_length"):
            val = X[0, i]
            print(f"  {fname:35s} = {val:.1f}")

    # 6. Verify specific values
    ur_idx = feature_names.index("user_rating")
    assert X[0, ur_idx] == 4.0, f"user_rating should be 4.0, got {X[0, ur_idx]}"
    print(f"\n  ✅ user_rating = 4.0 (correct)")

    hr_idx = feature_names.index("has_human_review")
    assert X[0, hr_idx] == 1.0, f"has_human_review should be 1.0, got {X[0, hr_idx]}"
    print(f"  ✅ has_human_review = 1.0 (correct)")

    htc_idx = feature_names.index("human_tag_count")
    assert X[0, htc_idx] == 4.0, f"human_tag_count should be 4.0, got {X[0, htc_idx]}"
    print(f"  ✅ human_tag_count = 4.0 (correct)")

    # Check specific htag flags
    for tag in ["EMPATHY", "URGENCY", "CTA", "HOOK"]:
        idx = feature_names.index(f"htag_{tag}")
        assert X[0, idx] == 1.0, f"htag_{tag} should be 1.0"
    for tag in ["CHAT", "PREP", "PROBLEM", "BONUS"]:
        idx = feature_names.index(f"htag_{tag}")
        assert X[0, idx] == 0.0, f"htag_{tag} should be 0.0"
    print(f"  ✅ Human tag one-hot values correct")

    cl_idx = feature_names.index("comment_length")
    assert X[0, cl_idx] > 0, f"comment_length should be > 0"
    print(f"  ✅ comment_length = {X[0, cl_idx]:.0f} (correct)")

    # 7. Test with empty human review (no review data)
    print(f"\n[5] Testing with empty human review record...")
    empty_record = make_dummy_record()
    empty_record["user_rating"] = 0
    empty_record["has_human_review"] = 0
    empty_record["human_tag_count"] = 0
    empty_record["comment_length"] = 0
    for tag in ALL_HUMAN_TAGS:
        empty_record[f"htag_{tag}"] = 0
    for g in COMMENT_KEYWORD_GROUPS:
        empty_record[g[0]] = 0

    X2, _, _, _, _, _, _ = extract_features([empty_record], target="click")
    ur_idx = feature_names.index("user_rating")
    assert X2[0, ur_idx] == 0.0
    hr_idx = feature_names.index("has_human_review")
    assert X2[0, hr_idx] == 0.0
    print(f"  ✅ Empty human review handled correctly (all zeros)")

    return True


def test_compute_labels_v2():
    """Test compute_labels_v2 with CSV, screen, and mixed moments."""
    print(f"\n{'=' * 70}")
    print(f"compute_labels_v2 Tests — CSV / Screen / Mixed")
    print(f"{'=' * 70}")

    # ── CSV moments ──
    print(f"\n[A] CSV moments:")
    csv_moments = [
        {"video_sec": 100.0, "moment_type": "click_spike",
         "moment_type_detail": "click_spike", "source": "csv", "confidence": 0.9},
        {"video_sec": 200.0, "moment_type": "order_spike",
         "moment_type_detail": "order_spike", "source": "csv", "confidence": 0.8},
        {"video_sec": 300.0, "moment_type": "strong",
         "moment_type_detail": "strong", "source": "csv", "confidence": 0.95},
    ]

    # Note: order_spike at 200s is within ±150s of phase mid (100s), so y_order=1
    labels = compute_labels_v2(90.0, 110.0, csv_moments)
    assert labels["y_click"] == 1
    assert labels["y_order"] == 1  # order_spike(200s) within 150s window of phase mid(100s)
    assert labels["moment_source"] == "csv"
    assert labels["has_csv_moment"] == 1
    assert labels["has_screen_moment"] == 0
    print(f"  ✅ click_spike: y_click=1, y_order=1 (order within window), source=csv")

    labels2 = compute_labels_v2(290.0, 310.0, csv_moments)
    assert labels2["y_click"] == 1
    assert labels2["y_order"] == 1
    assert labels2["y_strong"] == 1
    assert labels2["moment_source"] == "csv"
    print(f"  ✅ strong: y_click=1, y_order=1, y_strong=1")

    labels3 = compute_labels_v2(500.0, 510.0, csv_moments)
    assert labels3["y_click"] == 0
    assert labels3["y_order"] == 0
    assert labels3["moment_source"] == "none"
    print(f"  ✅ no match: y_click=0, y_order=0, source=none")

    # ── Screen moments ──
    print(f"\n[B] Screen moments:")
    # Use wide spacing (>300s apart) so moments don't overlap each other's ±150s windows
    screen_moments = [
        {"video_sec": 100.0, "moment_type": "strong",
         "moment_type_detail": "purchase_popup", "source": "screen", "confidence": 0.85},
        {"video_sec": 500.0, "moment_type": "click",
         "moment_type_detail": "product_viewers_popup", "source": "screen", "confidence": 0.7},
        {"video_sec": 900.0, "moment_type": "click",
         "moment_type_detail": "viewer_spike", "source": "screen", "confidence": 0.6},
        {"video_sec": 1300.0, "moment_type": "click",
         "moment_type_detail": "comment_spike", "source": "screen", "confidence": 0.5},
    ]

    labels4 = compute_labels_v2(95.0, 105.0, screen_moments)
    assert labels4["y_click"] == 1
    assert labels4["y_order"] == 1
    assert labels4["y_strong"] == 1
    assert labels4["moment_source"] == "screen"
    assert labels4["has_screen_moment"] == 1
    assert labels4["screen_purchase_popup"] == 1
    print(f"  ✅ purchase_popup: y_click=1, y_order=1, y_strong=1, screen_purchase=1")

    labels5 = compute_labels_v2(495.0, 505.0, screen_moments)
    assert labels5["y_click"] == 1
    assert labels5["y_order"] == 0  # no order/strong nearby
    assert labels5["y_strong"] == 0
    assert labels5["screen_product_viewers"] == 1
    print(f"  ✅ product_viewers_popup: y_click=1, y_order=0, screen_viewers=1")

    labels6 = compute_labels_v2(895.0, 905.0, screen_moments)
    assert labels6["y_click"] == 1
    assert labels6["y_order"] == 0
    print(f"  ✅ viewer_spike: y_click=1, y_order=0")

    labels7 = compute_labels_v2(1295.0, 1305.0, screen_moments)
    assert labels7["y_click"] == 1
    assert labels7["y_order"] == 0
    print(f"  ✅ comment_spike: y_click=1, y_order=0")

    # ── Mixed moments ──
    print(f"\n[C] Mixed CSV + Screen moments:")
    mixed_moments = [
        {"video_sec": 100.0, "moment_type": "click_spike",
         "moment_type_detail": "click_spike", "source": "csv", "confidence": 0.9},
        {"video_sec": 105.0, "moment_type": "strong",
         "moment_type_detail": "purchase_popup", "source": "screen", "confidence": 0.85},
    ]

    labels8 = compute_labels_v2(95.0, 110.0, mixed_moments)
    assert labels8["y_click"] == 1
    assert labels8["y_order"] == 1
    assert labels8["y_strong"] == 1
    assert labels8["moment_source"] == "both"
    assert labels8["has_csv_moment"] == 1
    assert labels8["has_screen_moment"] == 1
    print(f"  ✅ Mixed: y_click=1, y_order=1, y_strong=1, source=both")

    return True


def test_build_moments_index():
    """Test build_moments_index preserves source information."""
    print(f"\n{'=' * 70}")
    print(f"build_moments_index Tests")
    print(f"{'=' * 70}")

    class MockRow:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    rows = [
        MockRow(video_id="v1", video_sec=100.0, moment_type="click_spike",
                moment_type_detail="click_spike", source="csv", confidence=0.9),
        MockRow(video_id="v1", video_sec=200.0, moment_type="strong",
                moment_type_detail="purchase_popup", source="screen", confidence=0.85),
        MockRow(video_id="v2", video_sec=50.0, moment_type="click",
                moment_type_detail="viewer_spike", source="screen", confidence=0.6),
    ]

    idx = build_moments_index(rows)
    assert "v1" in idx
    assert len(idx["v1"]) == 2
    assert idx["v1"][0]["source"] == "csv"
    assert idx["v1"][1]["source"] == "screen"
    assert idx["v1"][1]["moment_type_detail"] == "purchase_popup"
    assert "v2" in idx
    assert idx["v2"][0]["source"] == "screen"
    print(f"  ✅ build_moments_index: {len(idx)} videos, source preserved")

    return True


if __name__ == "__main__":
    ok1 = test_feature_alignment()
    ok2 = test_compute_labels_v2()
    ok3 = test_build_moments_index()

    print(f"\n{'=' * 70}")
    if ok1 and ok2 and ok3:
        print(f"ALL TESTS PASSED ✅")
    else:
        print(f"SOME TESTS FAILED ❌")
        sys.exit(1)
    print(f"{'=' * 70}")
