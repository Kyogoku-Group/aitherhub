-- ============================================================
-- Feedback Loop System v1 Migration
-- ============================================================
-- Purpose: Enable Human-in-the-Loop AI improvement
--   ① Clip Rating (good/bad + reason tags)
--   ② Clip Edit Tracking (before/after diffs)
--   ③ Sales Confirmation (is this the selling moment?)
-- ============================================================

-- ① Extend clip_feedback: add rating + reason_tags columns
-- (existing table has adopted/rejected; we add good/bad quick rating)
ALTER TABLE clip_feedback
  ADD COLUMN IF NOT EXISTS rating VARCHAR(10) DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS reason_tags JSONB DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS user_id INTEGER DEFAULT NULL;

COMMENT ON COLUMN clip_feedback.rating IS 'Quick rating: good | bad';
COMMENT ON COLUMN clip_feedback.reason_tags IS 'Array of reason tags: ["hook_weak","too_long","cut_position","subtitle"]';
COMMENT ON COLUMN clip_feedback.user_id IS 'User who submitted the feedback';

-- ② clip_edit_log: track every edit a user makes to an AI-generated clip
CREATE TABLE IF NOT EXISTS clip_edit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id UUID NOT NULL,
  video_id UUID NOT NULL,
  user_id INTEGER DEFAULT NULL,
  -- Edit type: trim_start | trim_end | caption_edit | re_export
  edit_type VARCHAR(50) NOT NULL,
  -- Before/after values (JSON for flexibility)
  before_value JSONB NOT NULL DEFAULT '{}',
  after_value JSONB NOT NULL DEFAULT '{}',
  -- Delta (for numeric edits like trim)
  delta_seconds FLOAT DEFAULT NULL,
  -- Timestamps
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_clip_edit_log_clip_id ON clip_edit_log(clip_id);
CREATE INDEX IF NOT EXISTS ix_clip_edit_log_video_id ON clip_edit_log(video_id);
CREATE INDEX IF NOT EXISTS ix_clip_edit_log_edit_type ON clip_edit_log(edit_type);

COMMENT ON TABLE clip_edit_log IS 'Tracks every user edit to AI-generated clips. Training signal for AI improvement.';

-- ③ sales_confirmation: user confirms whether a clip captures the selling moment
CREATE TABLE IF NOT EXISTS sales_confirmation (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id UUID DEFAULT NULL,
  video_id UUID NOT NULL,
  phase_index INTEGER NOT NULL,
  -- Time range of the clip/candidate
  time_start FLOAT NOT NULL,
  time_end FLOAT NOT NULL,
  -- Confirmation: true = yes this is a selling moment, false = no
  is_sales_moment BOOLEAN NOT NULL,
  -- Optional confidence level from user (1-5)
  confidence INTEGER DEFAULT NULL,
  -- Optional note
  note TEXT DEFAULT NULL,
  -- User info
  user_id INTEGER DEFAULT NULL,
  reviewer_name VARCHAR(100) DEFAULT NULL,
  -- Timestamps
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_sales_confirmation_video_id ON sales_confirmation(video_id);
CREATE INDEX IF NOT EXISTS ix_sales_confirmation_clip_id ON sales_confirmation(clip_id);
CREATE INDEX IF NOT EXISTS ix_sales_confirmation_is_sales ON sales_confirmation(is_sales_moment);
CREATE UNIQUE INDEX IF NOT EXISTS ix_sales_confirmation_video_phase
  ON sales_confirmation(video_id, phase_index);

COMMENT ON TABLE sales_confirmation IS 'User confirmation of whether a clip captures the actual selling moment. Core training data for Sales DNA.';
