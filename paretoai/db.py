from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlmodel import Session, SQLModel, create_engine

from .config import settings

def _prepare_db_url():
    """为数据库 URL 添加必要的连接参数（如 Supabase SSL）"""
    db_url = settings.db_url or ""
    if db_url.startswith("postgresql://") and "sslmode" not in db_url:
        # Supabase 需要 SSL 连接
        separator = "&" if "?" in db_url else "?"
        db_url = f"{db_url}{separator}sslmode=require"
    return db_url


def _get_engine_args():
    """根据数据库类型返回适当的引擎参数"""
    db_url = settings.db_url or ""
    if db_url.startswith("postgresql"):
        return {
            "pool_size": 5,
            "max_overflow": 10,
            "pool_pre_ping": True,
            "pool_recycle": 300,
            "connect_args": {
                "sslmode": "require",
            },
        }
    return {}

engine = create_engine(_prepare_db_url(), echo=False, **_get_engine_args())


def init_db() -> None:
    """初始化数据库，创建所有表"""
    SQLModel.metadata.create_all(engine)
    _ensure_schema()


def _ensure_schema() -> None:
    db_url = settings.db_url or ""
    if not db_url.startswith("sqlite"):
        return

    with engine.connect() as conn:
        # Check Creator table - add radar system columns
        rows = conn.exec_driver_sql("PRAGMA table_info(creator)").fetchall()
        existing_cols = {r[1] for r in rows}
        
        # Rename desc to description if desc exists
        if "desc" in existing_cols and "description" not in existing_cols:
            # SQLite doesn't support RENAME COLUMN directly in older versions
            # We'll add description column and copy data
            conn.exec_driver_sql("ALTER TABLE creator ADD COLUMN description TEXT")
            conn.exec_driver_sql("UPDATE creator SET description = desc")
            # Note: We keep desc column for backward compatibility, can be dropped later
        elif "description" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE creator ADD COLUMN description TEXT")
            
        if "followers" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE creator ADD COLUMN followers INTEGER")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_creator_followers ON creator (followers)")
        if "total_likes" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE creator ADD COLUMN total_likes INTEGER")
        if "avg_likes" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE creator ADD COLUMN avg_likes REAL")
        if "hit_rate" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE creator ADD COLUMN hit_rate REAL")
        if "dark_horse_index" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE creator ADD COLUMN dark_horse_index REAL")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_creator_dark_horse_index ON creator (dark_horse_index)")
        if "is_dark_horse" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE creator ADD COLUMN is_dark_horse INTEGER DEFAULT 0")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_creator_is_dark_horse ON creator (is_dark_horse)")
        if "is_scanned" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE creator ADD COLUMN is_scanned INTEGER DEFAULT 0")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_creator_is_scanned ON creator (is_scanned)")
        if "last_scanned_at" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE creator ADD COLUMN last_scanned_at TEXT")
        if "last_analysis_json" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE creator ADD COLUMN last_analysis_json TEXT")
        
        # Check Note table - add radar system columns
        rows = conn.exec_driver_sql("PRAGMA table_info(note)").fetchall()
        note_cols = {r[1] for r in rows}
        if "diagnosis_json" not in note_cols:
            conn.exec_driver_sql("ALTER TABLE note ADD COLUMN diagnosis_json TEXT")
        if "comments" not in note_cols:
            conn.exec_driver_sql("ALTER TABLE note ADD COLUMN comments INTEGER DEFAULT 0")
        if "collects" not in note_cols:
            conn.exec_driver_sql("ALTER TABLE note ADD COLUMN collects INTEGER DEFAULT 0")
        if "from_tag" not in note_cols:
            conn.exec_driver_sql("ALTER TABLE note ADD COLUMN from_tag TEXT")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_note_from_tag ON note (from_tag)")
        if "viral_score" not in note_cols:
            conn.exec_driver_sql("ALTER TABLE note ADD COLUMN viral_score REAL")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_note_viral_score ON note (viral_score)")
        if "dark_horse_index" not in note_cols:
            conn.exec_driver_sql("ALTER TABLE note ADD COLUMN dark_horse_index REAL")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_note_dark_horse_index ON note (dark_horse_index)")
        if "source" not in note_cols:
            conn.exec_driver_sql("ALTER TABLE note ADD COLUMN source TEXT DEFAULT 'manual'")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_note_source ON note (source)")
            conn.exec_driver_sql("UPDATE note SET source = 'radar' WHERE from_tag IS NOT NULL")
        if "xsec_token" not in note_cols:
            conn.exec_driver_sql("ALTER TABLE note ADD COLUMN xsec_token TEXT")
        
        # Check if TrendScout table exists, create if not
        tables = conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='trendscout'").fetchall()
        if not tables:
            conn.exec_driver_sql("""
                CREATE TABLE trendscout (
                    id TEXT PRIMARY KEY,
                    keyword TEXT NOT NULL,
                    niche_name TEXT NOT NULL,
                    heat_score INTEGER NOT NULL,
                    reasoning TEXT NOT NULL,
                    audience_tags TEXT,
                    representative_creators TEXT,
                    created_at TEXT,
                    raw_data_json TEXT
                )
            """)
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_trendscout_keyword ON trendscout (keyword)")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_trendscout_created_at ON trendscout (created_at)")
            
        conn.commit()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


# 别名，保持向后兼容
get_session = session_scope
