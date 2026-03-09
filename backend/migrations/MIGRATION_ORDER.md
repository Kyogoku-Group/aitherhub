# AitherHub Database Migrations

## 実行順序

以下の順序でマイグレーションを実行してください。
全て `IF NOT EXISTS` / `IF NOT EXISTS` を使用しているため、**冪等（何度実行しても安全）** です。

```bash
# 接続
export DATABASE_URL="your-database-url-here"

# Phase 3: Worker Stability — clip_jobs 正式化
psql "$DATABASE_URL" -f backend/migrations/add_clip_jobs_v1.sql

# Phase 4: Video Pipeline — パイプラインテーブル
psql "$DATABASE_URL" -f backend/migrations/add_pipeline_tables_v1.sql
```

## 各マイグレーションの内容

### add_clip_jobs_v1.sql (Phase 3)
- `video_clips` テーブルにジョブ管理カラムを追加
  - `heartbeat_at`, `worker_id`, `attempt_count`, `last_error_code` 等
- stalled job 検知用のインデックスとビュー

### add_pipeline_tables_v1.sql (Phase 4)
- 新規テーブル5つ + パイプライン実行ログ1つ
  - `video_scenes` — シーン境界
  - `video_transcripts` — 音声書き起こし
  - `video_segments` — 意味単位セグメント
  - `video_events` — イベント検出結果
  - `video_sales_moments` — 売れた瞬間候補
  - `video_pipeline_runs` — パイプライン実行ログ

## 後方互換性

- **add_clip_jobs_v1.sql**: 既存の `video_clips` テーブルにカラムを **追加** するだけ。既存データに影響なし。`ADD COLUMN IF NOT EXISTS` を使用。
- **add_pipeline_tables_v1.sql**: 全て **新規テーブル** の作成。`CREATE TABLE IF NOT EXISTS` を使用。既存テーブルに一切触れない。

## ロールバック

```bash
# Phase 4 ロールバック（パイプラインテーブル削除）
psql "$DATABASE_URL" -c "
DROP TABLE IF EXISTS video_pipeline_runs CASCADE;
DROP TABLE IF EXISTS video_sales_moments CASCADE;
DROP TABLE IF EXISTS video_events CASCADE;
DROP TABLE IF EXISTS video_segments CASCADE;
DROP TABLE IF EXISTS video_transcripts CASCADE;
DROP TABLE IF EXISTS video_scenes CASCADE;
"

# Phase 3 ロールバック（clip_jobs カラム削除）
psql "$DATABASE_URL" -c "
ALTER TABLE video_clips
    DROP COLUMN IF EXISTS attempt_count,
    DROP COLUMN IF EXISTS max_attempts,
    DROP COLUMN IF EXISTS heartbeat_at,
    DROP COLUMN IF EXISTS started_at,
    DROP COLUMN IF EXISTS finished_at,
    DROP COLUMN IF EXISTS worker_id,
    DROP COLUMN IF EXISTS last_error_code,
    DROP COLUMN IF EXISTS last_error_message,
    DROP COLUMN IF EXISTS queue_message_id,
    DROP COLUMN IF EXISTS enqueued_at,
    DROP COLUMN IF EXISTS speed_factor,
    DROP COLUMN IF EXISTS duration_ms;
DROP VIEW IF EXISTS v_stale_clip_jobs;
DROP VIEW IF EXISTS v_dead_clip_jobs;
"
```
