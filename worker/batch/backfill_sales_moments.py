"""
backfill_sales_moments.py  –  既存動画のsales_momentsをDBに投入
==================================================================
Worker VM上で直接実行する。
全てasync関数を使い、イベントループ競合を回避。

使い方:
  python backfill_sales_moments.py                    # 全動画
  python backfill_sales_moments.py --video-id abc-123 # 特定動画
  python backfill_sales_moments.py --limit 5          # 最初の5動画
"""

import argparse
import asyncio
import os
import sys
import tempfile
import traceback

import requests as http_requests

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text as sa_text

from csv_slot_filter import detect_sales_moments
from db_ops import (
    ensure_sales_moments_table,      # async version
    bulk_insert_sales_moments,        # async version
)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set")

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, echo=False)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


def parse_trend_excel_safe(file_path: str):
    """Try to parse trend data from Excel file."""
    try:
        from excel_parser import parse_trend_excel
        return parse_trend_excel(file_path)
    except Exception as e:
        print(f"  [WARN] excel_parser failed: {e}")
        return None


async def backfill_all(video_id: str = None, limit: int = None):
    """Backfill sales_moments for existing videos."""

    # Ensure table exists (async version)
    try:
        await ensure_sales_moments_table()
        print("[backfill] video_sales_moments table ensured.")
    except Exception as e:
        print(f"[backfill] Table creation note: {e}")

    async with AsyncSessionLocal() as session:
        # First, check what columns exist
        try:
            col_check = await session.execute(sa_text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'videos' ORDER BY ordinal_position"
            ))
            cols = [r[0] for r in col_check.fetchall()]
            print(f"[backfill] videos columns: {cols[:20]}...")
        except Exception as e:
            print(f"[backfill] Column check failed: {e}")
            cols = []

        # Determine correct column names
        name_col = "original_filename" if "original_filename" in cols else "filename"
        has_trend_url = "excel_trend_blob_url" in cols
        has_time_offset = "time_offset_seconds" in cols

        if not has_trend_url:
            print("[backfill] ERROR: excel_trend_blob_url column not found in videos table.")
            print(f"[backfill] Available columns: {cols}")
            return

        # Build SQL dynamically
        select_cols = f"id, {name_col}"
        select_cols += ", excel_trend_blob_url"
        if has_time_offset:
            select_cols += ", time_offset_seconds"

        sql = f"""
            SELECT {select_cols}
            FROM videos
            WHERE status IN ('completed', 'DONE')
              AND excel_trend_blob_url IS NOT NULL
              AND excel_trend_blob_url != ''
        """
        if video_id:
            sql += f" AND id = '{video_id}'"
        sql += " ORDER BY created_at DESC"
        if limit:
            sql += f" LIMIT {limit}"

        print(f"[backfill] SQL: {sql[:200]}...")
        result = await session.execute(sa_text(sql))
        videos = result.fetchall()
        print(f"[backfill] Found {len(videos)} videos with trend data.")

        if len(videos) == 0:
            # Debug: check total videos and their trend URLs
            debug_sql = sa_text(
                "SELECT id, status, excel_trend_blob_url IS NOT NULL as has_trend "
                "FROM videos ORDER BY created_at DESC LIMIT 10"
            )
            debug_result = await session.execute(debug_sql)
            for r in debug_result.fetchall():
                print(f"  DEBUG: {r.id} status={r.status} has_trend={r.has_trend}")
            return

        success_count = 0
        skip_count = 0
        error_count = 0

        for v in videos:
            vid = str(v[0])
            filename = str(v[1]) if v[1] else "unknown"
            excel_url = v[2]
            time_offset = float(v[3]) if has_time_offset and len(v) > 3 and v[3] else 0.0

            print(f"\n[{vid[:8]}] {filename}")

            # Check if already has sales_moments
            try:
                check_sql = sa_text(
                    "SELECT COUNT(*) FROM video_sales_moments WHERE video_id = :vid"
                )
                check_result = await session.execute(check_sql, {"vid": vid})
                existing_count = check_result.scalar()
                if existing_count and existing_count > 0:
                    print(f"  Already has {existing_count} moments. Skipping.")
                    skip_count += 1
                    continue
            except Exception:
                pass  # Table might not exist yet

            # Download Excel
            try:
                resp = http_requests.get(excel_url, timeout=30)
                if resp.status_code != 200:
                    print(f"  [ERROR] Download failed: HTTP {resp.status_code}")
                    error_count += 1
                    continue
            except Exception as e:
                print(f"  [ERROR] Download failed: {e}")
                error_count += 1
                continue

            # Save to temp file and parse
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(resp.content)
                tmp_path = tmp.name

            try:
                trend_data = parse_trend_excel_safe(tmp_path)
                if trend_data is None or trend_data.empty:
                    print(f"  [SKIP] No trend data parsed.")
                    skip_count += 1
                    continue

                print(f"  Trend data: {len(trend_data)} rows, cols: {list(trend_data.columns)[:5]}")

                # Detect sales moments
                moments = detect_sales_moments(
                    trends=trend_data,
                    time_offset_seconds=time_offset,
                )

                if not moments:
                    print(f"  No moments detected.")
                    skip_count += 1
                    continue

                print(f"  Detected {len(moments)} moments")

                # Save to DB (async version)
                await bulk_insert_sales_moments(vid, moments)
                print(f"  ✅ Saved {len(moments)} moments to DB")
                success_count += 1

            except Exception as e:
                print(f"  [ERROR] Processing failed: {e}")
                traceback.print_exc()
                error_count += 1
            finally:
                os.unlink(tmp_path)

        print(f"\n{'='*60}")
        print(f"[backfill] DONE: success={success_count}, skip={skip_count}, error={error_count}")
        print(f"[backfill] Total videos: {len(videos)}")


def main():
    parser = argparse.ArgumentParser(description="Backfill sales_moments for existing videos")
    parser.add_argument("--video-id", default=None, help="Specific video ID")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of videos")
    args = parser.parse_args()

    asyncio.run(backfill_all(video_id=args.video_id, limit=args.limit))


if __name__ == "__main__":
    main()
