-- =============================================================================
-- Migration: Upgrade video_clips table to formal job management
-- =============================================================================
-- This migration adds proper job state management columns to video_clips.
-- Instead of creating a separate clip_jobs table, we enhance the existing
-- video_clips table to serve as both the clip record and the job state tracker.
--
-- Run: psql $DATABASE_URL -f add_clip_jobs_v1.sql
-- =============================================================================

-- 1. Add job state management columns
ALTER TABLE video_clips
    ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 3,
    ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS worker_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS last_error_code VARCHAR(100),
    ADD COLUMN IF NOT EXISTS last_error_message TEXT,
    ADD COLUMN IF NOT EXISTS queue_message_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS enqueued_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS speed_factor DOUBLE PRECISION DEFAULT 1.0,
    ADD COLUMN IF NOT EXISTS duration_ms INTEGER;

-- 2. Add created_at / updated_at if missing
ALTER TABLE video_clips
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- 3. Update status column to support new states
-- Valid statuses: pending, queued, downloading, processing, uploading,
--                 completed, failed, retrying, dead
-- (No enum constraint — use CHECK constraint for flexibility)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'video_clips_status_check'
    ) THEN
        ALTER TABLE video_clips
            ADD CONSTRAINT video_clips_status_check
            CHECK (status IN (
                'pending', 'queued', 'downloading', 'processing',
                'uploading', 'completed', 'failed', 'retrying', 'dead'
            ));
    END IF;
EXCEPTION
    WHEN others THEN
        RAISE NOTICE 'Status check constraint already exists or conflict: %', SQLERRM;
END $$;

-- 4. Indexes for job management queries
CREATE INDEX IF NOT EXISTS idx_video_clips_status
    ON video_clips (status);

CREATE INDEX IF NOT EXISTS idx_video_clips_worker_id
    ON video_clips (worker_id)
    WHERE worker_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_video_clips_heartbeat_stale
    ON video_clips (heartbeat_at)
    WHERE status IN ('downloading', 'processing', 'uploading');

CREATE INDEX IF NOT EXISTS idx_video_clips_video_id_status
    ON video_clips (video_id, status);

CREATE INDEX IF NOT EXISTS idx_video_clips_created_at
    ON video_clips (created_at DESC);

-- 5. Create a view for monitoring stale/stuck clips
CREATE OR REPLACE VIEW v_stale_clip_jobs AS
SELECT
    id AS clip_id,
    video_id,
    status,
    worker_id,
    attempt_count,
    heartbeat_at,
    started_at,
    EXTRACT(EPOCH FROM (NOW() - heartbeat_at)) AS seconds_since_heartbeat,
    EXTRACT(EPOCH FROM (NOW() - started_at)) AS seconds_since_started,
    last_error_code,
    last_error_message
FROM video_clips
WHERE status IN ('downloading', 'processing', 'uploading')
  AND (
      heartbeat_at IS NULL
      OR heartbeat_at < NOW() - INTERVAL '5 minutes'
  );

-- 6. Create a view for dead-letter / failed clips
CREATE OR REPLACE VIEW v_dead_clip_jobs AS
SELECT
    id AS clip_id,
    video_id,
    status,
    attempt_count,
    max_attempts,
    last_error_code,
    last_error_message,
    created_at,
    finished_at
FROM video_clips
WHERE status IN ('dead', 'failed')
ORDER BY finished_at DESC NULLS LAST;
