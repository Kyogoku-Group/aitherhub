-- =============================================================================
-- Migration: Video Processing Pipeline Tables
-- =============================================================================
-- Creates tables for the AI video understanding pipeline:
--   1. video_scenes       — Scene boundaries
--   2. video_transcripts  — Speech-to-text results
--   3. video_segments     — Semantically segmented transcript blocks
--   4. video_events       — Detected events (product_show, CTA, etc.)
--   5. video_sales_moments — High-conversion moment candidates
--
-- Run: psql $DATABASE_URL -f add_pipeline_tables_v1.sql
-- =============================================================================

-- 1. video_scenes
CREATE TABLE IF NOT EXISTS video_scenes (
    id              BIGSERIAL PRIMARY KEY,
    video_id        VARCHAR(255) NOT NULL,
    scene_index     INTEGER NOT NULL,
    start_time      DOUBLE PRECISION NOT NULL,
    end_time        DOUBLE PRECISION NOT NULL,
    duration        DOUBLE PRECISION GENERATED ALWAYS AS (end_time - start_time) STORED,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_video_scenes_video_index
        UNIQUE (video_id, scene_index)
);

CREATE INDEX IF NOT EXISTS idx_video_scenes_video_id
    ON video_scenes (video_id);

-- 2. video_transcripts
CREATE TABLE IF NOT EXISTS video_transcripts (
    id              BIGSERIAL PRIMARY KEY,
    video_id        VARCHAR(255) NOT NULL,
    segment_index   INTEGER NOT NULL,
    start_time      DOUBLE PRECISION NOT NULL,
    end_time        DOUBLE PRECISION NOT NULL,
    text            TEXT NOT NULL DEFAULT '',
    confidence      DOUBLE PRECISION DEFAULT 0.0,
    language        VARCHAR(10) DEFAULT 'ja',
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_video_transcripts_video_index
        UNIQUE (video_id, segment_index)
);

CREATE INDEX IF NOT EXISTS idx_video_transcripts_video_id
    ON video_transcripts (video_id);

-- 3. video_segments
CREATE TABLE IF NOT EXISTS video_segments (
    id              BIGSERIAL PRIMARY KEY,
    video_id        VARCHAR(255) NOT NULL,
    segment_index   INTEGER NOT NULL,
    start_time      DOUBLE PRECISION NOT NULL,
    end_time        DOUBLE PRECISION NOT NULL,
    text            TEXT NOT NULL DEFAULT '',
    topic           VARCHAR(255) DEFAULT '',
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_video_segments_video_index
        UNIQUE (video_id, segment_index)
);

CREATE INDEX IF NOT EXISTS idx_video_segments_video_id
    ON video_segments (video_id);

-- 4. video_events
CREATE TABLE IF NOT EXISTS video_events (
    id              BIGSERIAL PRIMARY KEY,
    video_id        VARCHAR(255) NOT NULL,
    event_type      VARCHAR(100) NOT NULL,
    start_time      DOUBLE PRECISION NOT NULL,
    end_time        DOUBLE PRECISION NOT NULL,
    confidence      DOUBLE PRECISION DEFAULT 0.0,
    description     TEXT DEFAULT '',
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_video_events_video_id
    ON video_events (video_id);

CREATE INDEX IF NOT EXISTS idx_video_events_type
    ON video_events (video_id, event_type);

-- 5. video_sales_moments
CREATE TABLE IF NOT EXISTS video_sales_moments (
    id              BIGSERIAL PRIMARY KEY,
    video_id        VARCHAR(255) NOT NULL,
    start_time      DOUBLE PRECISION NOT NULL,
    end_time        DOUBLE PRECISION NOT NULL,
    score           DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    reason          TEXT DEFAULT '',
    source          VARCHAR(50) DEFAULT 'pipeline',
    events          JSONB DEFAULT '[]',
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_video_sales_moments_video_id
    ON video_sales_moments (video_id);

CREATE INDEX IF NOT EXISTS idx_video_sales_moments_score
    ON video_sales_moments (video_id, score DESC);

-- 6. Pipeline run log (optional but useful for debugging)
CREATE TABLE IF NOT EXISTS video_pipeline_runs (
    id              BIGSERIAL PRIMARY KEY,
    video_id        VARCHAR(255) NOT NULL,
    worker_id       VARCHAR(255) DEFAULT '',
    status          VARCHAR(50) NOT NULL DEFAULT 'running',
    step_timings    JSONB DEFAULT '{}',
    errors          JSONB DEFAULT '{}',
    summary         JSONB DEFAULT '{}',
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_video_pipeline_runs_video_id
    ON video_pipeline_runs (video_id);
