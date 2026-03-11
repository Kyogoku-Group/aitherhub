-- ============================================================
-- Subtitle Feedback & Style Preferences v1 Migration
-- ============================================================
-- Purpose: Store user feedback on subtitle styles for AI learning
--   1. subtitle_feedback: user votes + tags on subtitle styles
--   2. subtitle_style_prefs: per-clip subtitle style & position
-- ============================================================

-- 1. subtitle_feedback: stores user feedback on subtitle styles
CREATE TABLE IF NOT EXISTS subtitle_feedback (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  video_id UUID NOT NULL,
  clip_id UUID DEFAULT NULL,
  user_id INTEGER DEFAULT NULL,
  -- Style that was active when feedback was given
  subtitle_style VARCHAR(50) NOT NULL DEFAULT 'box',
  -- Vote: up | down
  vote VARCHAR(10) DEFAULT NULL,
  -- Tags: array of feedback tags
  tags JSONB DEFAULT '[]'::jsonb,
  -- Subtitle position at time of feedback
  position_x FLOAT DEFAULT 50,
  position_y FLOAT DEFAULT 85,
  -- Video metadata for AI context
  video_genre VARCHAR(100) DEFAULT NULL,
  ai_recommended_style VARCHAR(50) DEFAULT NULL,
  -- Timestamps
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_subtitle_feedback_video_id ON subtitle_feedback(video_id);
CREATE INDEX IF NOT EXISTS ix_subtitle_feedback_clip_id ON subtitle_feedback(clip_id);
CREATE INDEX IF NOT EXISTS ix_subtitle_feedback_user_id ON subtitle_feedback(user_id);
CREATE INDEX IF NOT EXISTS ix_subtitle_feedback_style ON subtitle_feedback(subtitle_style);

COMMENT ON TABLE subtitle_feedback IS 'User feedback on subtitle styles. Training data for AI style recommendation.';

-- 2. subtitle_style_prefs: per-clip subtitle style & position preferences
ALTER TABLE video_clips
  ADD COLUMN IF NOT EXISTS subtitle_style VARCHAR(50) DEFAULT 'box',
  ADD COLUMN IF NOT EXISTS subtitle_position_x FLOAT DEFAULT 50,
  ADD COLUMN IF NOT EXISTS subtitle_position_y FLOAT DEFAULT 85;

COMMENT ON COLUMN video_clips.subtitle_style IS 'Selected subtitle style preset: simple|box|outline|pop|gradient';
COMMENT ON COLUMN video_clips.subtitle_position_x IS 'Subtitle X position as percentage (0-100)';
COMMENT ON COLUMN video_clips.subtitle_position_y IS 'Subtitle Y position as percentage (0-100)';
