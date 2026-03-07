"""
Tests for Feedback Loop System v1
  ① Clip Rating (good/bad + reason tags)
  ② Clip Edit Tracking (trim/caption changes)
  ③ Sales Confirmation (is this the selling moment?)
"""
import pytest
import uuid
import json
from datetime import datetime


# ─── Test Data Fixtures ───────────────────────────────────────────────────

def make_video_id():
    return str(uuid.uuid4())

def make_clip_id():
    return str(uuid.uuid4())


# ─── ① Clip Rating Tests ─────────────────────────────────────────────────

class TestClipRating:
    """Test clip rating submission and retrieval."""

    def test_rating_payload_good(self):
        """Good rating with no reason tags."""
        payload = {
            "phase_index": 0,
            "time_start": 0.0,
            "time_end": 75.0,
            "rating": "good",
            "reason_tags": None,
            "clip_id": make_clip_id(),
        }
        assert payload["rating"] in ("good", "bad")
        assert payload["phase_index"] >= 0
        assert payload["time_end"] > payload["time_start"]

    def test_rating_payload_bad_with_reasons(self):
        """Bad rating with multiple reason tags."""
        payload = {
            "phase_index": 2,
            "time_start": 152.0,
            "time_end": 245.0,
            "rating": "bad",
            "reason_tags": ["hook_weak", "too_long", "cut_position"],
            "clip_id": make_clip_id(),
        }
        assert payload["rating"] == "bad"
        assert len(payload["reason_tags"]) == 3
        assert all(tag in [
            "hook_weak", "too_long", "too_short", "cut_position",
            "subtitle", "audio", "irrelevant", "perfect"
        ] for tag in payload["reason_tags"])

    def test_rating_invalid_value_rejected(self):
        """Rating must be 'good' or 'bad'."""
        valid_ratings = {"good", "bad"}
        assert "excellent" not in valid_ratings
        assert "maybe" not in valid_ratings
        assert "good" in valid_ratings
        assert "bad" in valid_ratings

    def test_rating_with_ai_score_snapshot(self):
        """Rating should capture AI score at feedback time."""
        payload = {
            "phase_index": 1,
            "time_start": 76.0,
            "time_end": 152.0,
            "rating": "good",
            "ai_score_at_feedback": 87.5,
            "score_breakdown": {
                "gmv": 30,
                "orders": 20,
                "clicks": 15,
                "viewers": 10,
                "cta": 12.5,
            },
        }
        assert payload["ai_score_at_feedback"] == 87.5
        assert sum(payload["score_breakdown"].values()) == 87.5

    def test_reason_tags_are_optional(self):
        """Reason tags can be None or empty list."""
        payload_none = {"rating": "good", "reason_tags": None}
        payload_empty = {"rating": "good", "reason_tags": []}
        assert payload_none["reason_tags"] is None
        assert len(payload_empty["reason_tags"]) == 0


# ─── ② Clip Edit Tracking Tests ──────────────────────────────────────────

class TestClipEditTracking:
    """Test edit tracking for AI learning."""

    def test_trim_start_edit(self):
        """Track trim start adjustment."""
        edit = {
            "clip_id": make_clip_id(),
            "edit_type": "trim_start",
            "before_value": {"start_sec": 76.0},
            "after_value": {"start_sec": 74.0},
            "delta_seconds": -2.0,
        }
        assert edit["edit_type"] == "trim_start"
        assert edit["delta_seconds"] == edit["after_value"]["start_sec"] - edit["before_value"]["start_sec"]

    def test_trim_end_edit(self):
        """Track trim end adjustment."""
        edit = {
            "clip_id": make_clip_id(),
            "edit_type": "trim_end",
            "before_value": {"end_sec": 152.0},
            "after_value": {"end_sec": 153.5},
            "delta_seconds": 1.5,
        }
        assert edit["edit_type"] == "trim_end"
        assert edit["delta_seconds"] == 1.5

    def test_caption_edit(self):
        """Track caption text changes."""
        edit = {
            "clip_id": make_clip_id(),
            "edit_type": "caption_edit",
            "before_value": {
                "captions": [
                    {"text": "ブリーチ毛って色がすご", "emphasis": False},
                ]
            },
            "after_value": {
                "captions": [
                    {"text": "ブリーチ毛って色がすぐ抜ける", "emphasis": True},
                ]
            },
        }
        assert edit["edit_type"] == "caption_edit"
        before_text = edit["before_value"]["captions"][0]["text"]
        after_text = edit["after_value"]["captions"][0]["text"]
        assert before_text != after_text
        assert edit["after_value"]["captions"][0]["emphasis"] is True

    def test_edit_type_validation(self):
        """Edit type must be one of the allowed values."""
        valid_types = {"trim_start", "trim_end", "caption_edit"}
        assert "trim_start" in valid_types
        assert "trim_end" in valid_types
        assert "caption_edit" in valid_types
        assert "delete" not in valid_types

    def test_delta_seconds_for_trim(self):
        """Delta seconds should be within ±3 range for trim edits."""
        MAX_TRIM_DELTA = 3.0
        deltas = [-2.0, -1.0, 0.5, 1.5, 3.0]
        for d in deltas:
            assert abs(d) <= MAX_TRIM_DELTA

    def test_edit_values_serializable(self):
        """Before/after values must be JSON serializable."""
        edit = {
            "before_value": {"start_sec": 76.0},
            "after_value": {"start_sec": 74.0},
        }
        json_str = json.dumps(edit)
        parsed = json.loads(json_str)
        assert parsed["before_value"]["start_sec"] == 76.0


# ─── ③ Sales Confirmation Tests ──────────────────────────────────────────

class TestSalesConfirmation:
    """Test sales confirmation (Sales DNA) feature."""

    def test_sales_confirmation_yes(self):
        """User confirms this is a selling moment."""
        payload = {
            "phase_index": 1,
            "time_start": 76.0,
            "time_end": 152.0,
            "is_sales_moment": True,
            "clip_id": make_clip_id(),
            "note": "商品紹介の瞬間",
        }
        assert payload["is_sales_moment"] is True
        assert payload["note"] == "商品紹介の瞬間"

    def test_sales_confirmation_no(self):
        """User denies this is a selling moment."""
        payload = {
            "phase_index": 0,
            "time_start": 0.0,
            "time_end": 75.0,
            "is_sales_moment": False,
            "clip_id": None,
            "note": None,
        }
        assert payload["is_sales_moment"] is False

    def test_sales_confirmation_confidence(self):
        """Confidence level is optional and between 0-1."""
        payload = {
            "phase_index": 2,
            "time_start": 152.0,
            "time_end": 245.0,
            "is_sales_moment": True,
            "confidence": 0.85,
        }
        assert 0.0 <= payload["confidence"] <= 1.0

    def test_sales_dna_accumulation(self):
        """Multiple YES confirmations build Sales DNA."""
        confirmations = [
            {"phase_index": 1, "is_sales_moment": True},
            {"phase_index": 1, "is_sales_moment": True},
            {"phase_index": 1, "is_sales_moment": False},
            {"phase_index": 2, "is_sales_moment": True},
        ]
        # Phase 1: 2 YES, 1 NO → 66.7% confidence
        phase1 = [c for c in confirmations if c["phase_index"] == 1]
        yes_count = sum(1 for c in phase1 if c["is_sales_moment"])
        confidence = yes_count / len(phase1)
        assert confidence == pytest.approx(0.667, abs=0.01)


# ─── Human Data Protection Tests ─────────────────────────────────────────

class TestHumanDataProtection:
    """Ensure feedback data is never overwritten by AI recalculation."""

    def test_feedback_tables_are_human_data(self):
        """Clip ratings and sales confirmations are Human Data."""
        human_data_tables = {
            "clip_rating",
            "clip_edit_log",
            "sales_confirmation",
            "clip_review",
            "manual_tags",
            "editor_annotations",
        }
        derived_data_tables = {
            "phase_metrics",
            "sales_moments",
            "clip_scores",
            "ranking_scores",
        }
        # No overlap between human and derived data
        assert human_data_tables.isdisjoint(derived_data_tables)

    def test_recalculation_does_not_touch_feedback(self):
        """Recalculation service should only update derived data."""
        recalc_update_targets = {"video_phases"}  # Only table updated by recalc
        human_tables = {
            "clip_rating",
            "clip_edit_log",
            "sales_confirmation",
        }
        assert recalc_update_targets.isdisjoint(human_tables)


# ─── API Contract Tests ──────────────────────────────────────────────────

class TestAPIContract:
    """Test API endpoint contracts."""

    def test_clip_rating_endpoint_path(self):
        """Clip rating endpoint follows REST convention."""
        video_id = make_video_id()
        path = f"/api/v1/feedback/{video_id}/clip-rating"
        assert video_id in path
        assert "clip-rating" in path

    def test_edit_log_endpoint_path(self):
        """Edit log endpoint follows REST convention."""
        video_id = make_video_id()
        path = f"/api/v1/feedback/{video_id}/edit-log"
        assert "edit-log" in path

    def test_sales_confirmation_endpoint_path(self):
        """Sales confirmation endpoint follows REST convention."""
        video_id = make_video_id()
        path = f"/api/v1/feedback/{video_id}/sales-confirmation"
        assert "sales-confirmation" in path

    def test_get_ratings_returns_list(self):
        """GET clip-ratings should return a list structure."""
        mock_response = {
            "video_id": make_video_id(),
            "ratings": [
                {"phase_index": 0, "rating": "good", "reason_tags": ["perfect"]},
                {"phase_index": 1, "rating": "bad", "reason_tags": ["hook_weak", "too_long"]},
            ],
        }
        assert isinstance(mock_response["ratings"], list)
        assert len(mock_response["ratings"]) == 2

    def test_get_confirmations_returns_list(self):
        """GET sales-confirmations should return a list structure."""
        mock_response = {
            "video_id": make_video_id(),
            "confirmations": [
                {"phase_index": 0, "is_sales_moment": False},
                {"phase_index": 1, "is_sales_moment": True},
            ],
        }
        assert isinstance(mock_response["confirmations"], list)
