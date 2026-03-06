"""
Add source and moment_type_detail columns to video_sales_moments.

Enables dual-source sales moment tracking:
  - source='csv'    → from TikTok LIVE Analytics Excel (existing)
  - source='screen' → from screen recording OCR/Vision (new)

Also adds moment_type_detail for finer-grained classification:
  - purchase_popup, product_viewers_popup, viewer_spike, comment_spike (screen)
  - click_spike, order_spike, strong (csv - existing moment_type values)
"""

# --- Raw SQL migration (no Alembic dependency) ---
# Execute these statements against the production database.

UP_SQL = [
    # 1. Add source column (default='csv' for backward compat)
    """
    ALTER TABLE video_sales_moments
    ADD COLUMN IF NOT EXISTS source VARCHAR(20) DEFAULT 'csv' NOT NULL
    """,

    # 2. Add moment_type_detail for finer classification
    """
    ALTER TABLE video_sales_moments
    ADD COLUMN IF NOT EXISTS moment_type_detail VARCHAR(50)
    """,

    # 3. Index on source for filtered queries
    """
    CREATE INDEX IF NOT EXISTS ix_vsm_source
    ON video_sales_moments (source)
    """,

    # 4. Composite index for dataset generation queries
    """
    CREATE INDEX IF NOT EXISTS ix_vsm_video_source
    ON video_sales_moments (video_id, source)
    """,

    # 5. Backfill: set moment_type_detail = moment_type for existing rows
    """
    UPDATE video_sales_moments
    SET moment_type_detail = moment_type
    WHERE moment_type_detail IS NULL
    """,
]

DOWN_SQL = [
    "DROP INDEX IF EXISTS ix_vsm_video_source",
    "DROP INDEX IF EXISTS ix_vsm_source",
    "ALTER TABLE video_sales_moments DROP COLUMN IF EXISTS moment_type_detail",
    "ALTER TABLE video_sales_moments DROP COLUMN IF EXISTS source",
]


def upgrade(conn):
    """Run upgrade migration."""
    for sql in UP_SQL:
        conn.execute(sql)
    conn.commit()


def downgrade(conn):
    """Run downgrade migration."""
    for sql in DOWN_SQL:
        conn.execute(sql)
    conn.commit()


if __name__ == "__main__":
    print("Migration: add source/moment_type_detail to video_sales_moments")
    print("\nUP SQL:")
    for s in UP_SQL:
        print(s.strip())
    print("\nDOWN SQL:")
    for s in DOWN_SQL:
        print(s.strip())
