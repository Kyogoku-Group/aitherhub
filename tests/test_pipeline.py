"""
Pipeline Integration Tests
============================
Tests the pipeline framework, context, and individual step logic
without requiring actual video files or external services.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from worker.pipeline.pipeline_context import PipelineContext
from worker.pipeline.pipeline_runner import PipelineRunner
from worker.pipeline.pipeline_metrics import log_pipeline_metrics


def test_pipeline_context():
    """Test PipelineContext creation and summary."""
    ctx = PipelineContext(video_id="test-001", video_path="/tmp/test.mp4")
    assert ctx.video_id == "test-001"
    assert ctx.scenes == []
    assert ctx.transcript == []
    assert not ctx.has_error()

    ctx.scenes = [{"start": 0, "end": 5, "scene_index": 0}]
    ctx.errors["test_step"] = "test error"
    assert ctx.has_error()

    summary = ctx.summary()
    assert summary["scenes_count"] == 1
    assert summary["errors"]["test_step"] == "test error"
    print("  PASS  test_pipeline_context")


def test_pipeline_runner_basic():
    """Test PipelineRunner executes steps in order."""
    execution_order = []

    def step_a(ctx):
        execution_order.append("a")
        ctx.extra["step_a"] = True
        return ctx

    def step_b(ctx):
        execution_order.append("b")
        assert ctx.extra.get("step_a") is True  # step_a ran first
        ctx.extra["step_b"] = True
        return ctx

    runner = PipelineRunner()
    runner.add_step("step_a", step_a)
    runner.add_step("step_b", step_b)
    assert runner.step_count == 2

    ctx = PipelineContext(video_id="test-002")
    result = runner.run(ctx)

    assert execution_order == ["a", "b"]
    assert result.extra["step_a"] is True
    assert result.extra["step_b"] is True
    assert "step_a" in result.step_timings
    assert "step_b" in result.step_timings
    assert "_total" in result.step_timings
    print("  PASS  test_pipeline_runner_basic")


def test_pipeline_runner_critical_failure():
    """Test that critical step failure stops the pipeline."""
    execution_order = []

    def step_ok(ctx):
        execution_order.append("ok")
        return ctx

    def step_fail(ctx):
        execution_order.append("fail")
        raise RuntimeError("Critical failure!")

    def step_after(ctx):
        execution_order.append("after")
        return ctx

    runner = PipelineRunner()
    runner.add_step("step_ok", step_ok, critical=True)
    runner.add_step("step_fail", step_fail, critical=True)
    runner.add_step("step_after", step_after, critical=True)

    ctx = PipelineContext(video_id="test-003")
    result = runner.run(ctx)

    assert execution_order == ["ok", "fail"]  # step_after should NOT run
    assert "step_fail" in result.errors
    assert "step_after" not in result.step_timings
    print("  PASS  test_pipeline_runner_critical_failure")


def test_pipeline_runner_non_critical_failure():
    """Test that non-critical step failure allows pipeline to continue."""
    execution_order = []

    def step_fail(ctx):
        execution_order.append("fail")
        raise RuntimeError("Non-critical failure!")

    def step_after(ctx):
        execution_order.append("after")
        return ctx

    runner = PipelineRunner()
    runner.add_step("step_fail", step_fail, critical=False)
    runner.add_step("step_after", step_after, critical=True)

    ctx = PipelineContext(video_id="test-004")
    result = runner.run(ctx)

    assert execution_order == ["fail", "after"]  # step_after SHOULD run
    assert "step_fail" in result.errors
    print("  PASS  test_pipeline_runner_non_critical_failure")


def test_transcript_segmentation_logic():
    """Test transcript segmentation with mock data."""
    from worker.pipeline.pipeline_steps.transcript_segmentation import _merge_and_segment

    transcript = [
        {"start": 0.0, "end": 2.0, "text": "こんにちは"},
        {"start": 2.1, "end": 4.0, "text": "今日は商品を紹介します"},
        {"start": 4.2, "end": 6.0, "text": "こちらの商品は"},
        # Gap > 1.5s
        {"start": 10.0, "end": 12.0, "text": "お値段は"},
        {"start": 12.5, "end": 14.0, "text": "3000円です"},
    ]

    scenes = [{"start": 0, "end": 8}, {"start": 8, "end": 15}]
    from worker.pipeline.pipeline_steps.transcript_segmentation import _get_scene_boundaries
    boundaries = _get_scene_boundaries(scenes)

    segments = _merge_and_segment(transcript, boundaries)

    assert len(segments) >= 2  # Should split at the gap
    assert all("segment_index" in s for s in segments)
    assert all("text" in s for s in segments)
    print(f"  PASS  test_transcript_segmentation_logic ({len(segments)} segments)")


def test_event_detection_rule_based():
    """Test rule-based event detection with mock segments."""
    from worker.pipeline.pipeline_steps.event_detection import _detect_events_rule_based

    segments = [
        {"start": 0, "end": 5, "text": "この商品を紹介します"},
        {"start": 10, "end": 15, "text": "お値段は3000円です"},
        {"start": 20, "end": 25, "text": "リンクは概要欄にあります"},
        {"start": 30, "end": 35, "text": "コメントありがとうございます"},
        {"start": 40, "end": 45, "text": "今日はいい天気ですね"},  # No event
    ]

    events = _detect_events_rule_based(segments)

    event_types = {e["event_type"] for e in events}
    assert "product_show" in event_types
    assert "price_mention" in event_types
    assert "call_to_action" in event_types
    assert "comment_reaction" in event_types
    assert all(0 <= e["confidence"] <= 1.0 for e in events)
    print(f"  PASS  test_event_detection_rule_based ({len(events)} events, types={event_types})")


def test_sales_moment_detection_logic():
    """Test sales moment detection with mock events and segments."""
    from worker.pipeline.pipeline_steps.sales_moment_detection import _detect_sales_moments_sliding_window

    events = [
        {"start": 10, "end": 15, "event_type": "product_show", "confidence": 0.8},
        {"start": 12, "end": 17, "event_type": "price_mention", "confidence": 0.9},
        {"start": 14, "end": 19, "event_type": "call_to_action", "confidence": 0.7},
        {"start": 50, "end": 55, "event_type": "comment_reaction", "confidence": 0.5},
    ]

    segments = [
        {"start": 10, "end": 20, "text": "この商品は今だけ3000円！今すぐ購入してください"},
        {"start": 50, "end": 55, "text": "コメントありがとう"},
    ]

    moments = _detect_sales_moments_sliding_window(events, segments, 60.0)

    assert len(moments) >= 1
    # The cluster around 10-19s should have the highest score
    best = moments[0]
    assert best["score"] >= 0.3
    assert best["start"] <= 15
    print(f"  PASS  test_sales_moment_detection_logic ({len(moments)} moments, best_score={best['score']})")


def test_pipeline_metrics():
    """Test pipeline metrics logging."""
    ctx = PipelineContext(video_id="test-metrics")
    ctx.step_timings = {
        "scene_detection": 2.5,
        "speech_extraction": 1.2,
        "speech_to_text": 15.3,
        "_total": 19.0,
    }
    ctx.scenes = [{"start": 0, "end": 5}]
    ctx.transcript = [{"start": 0, "end": 2, "text": "test"}]

    summary = log_pipeline_metrics(ctx)
    assert summary["total_time_s"] == 19.0
    assert summary["scenes_count"] == 1
    print("  PASS  test_pipeline_metrics")


if __name__ == "__main__":
    passed = 0
    failed = 0

    tests = [
        test_pipeline_context,
        test_pipeline_runner_basic,
        test_pipeline_runner_critical_failure,
        test_pipeline_runner_non_critical_failure,
        test_transcript_segmentation_logic,
        test_event_detection_rule_based,
        test_sales_moment_detection_logic,
        test_pipeline_metrics,
    ]

    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"  FAIL  {test_fn.__name__}: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'=' * 60}")

    if failed > 0:
        sys.exit(1)
