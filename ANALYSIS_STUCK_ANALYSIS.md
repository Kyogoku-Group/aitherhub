# Analysis Stuck at 0% - Root Cause

## Finding

The `process_job()` function in `worker/entrypoints/queue_worker.py` handles these job types:
- `generate_clip` → `_run_clip_job()`
- `video_pipeline` → `_run_pipeline_job()`
- `live_capture` → `_run_live_capture_job()`
- `live_monitor` → `_run_live_monitor_job()`
- default → `_run_video_job()` (legacy)

**There is NO handler for `live_analysis` job type!**

The backend's `live_analysis.py` endpoint enqueues a job with `job_type: "live_analysis"`.
The worker receives it but falls through to the default `_run_video_job()` handler,
which is the legacy video analysis pipeline — NOT the live analysis pipeline.

## Fix needed

Add `elif job_type == "live_analysis":` case in `process_job()` that calls
the `LiveAnalysisPipeline` from `app.services.live_analysis_pipeline` or
a new `_run_live_analysis_job()` function.
