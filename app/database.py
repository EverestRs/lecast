"""SQLAlchemy 数据库引擎与会话"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},  # timeout 即 SQLite busy_timeout
    echo=False,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI 依赖注入：获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """创建所有表（首次启动时）+ 执行轻量级迁移"""
    import app.models  # noqa: F401 — 确保模型被注册
    Base.metadata.create_all(bind=engine)
    _run_migrations()


def _run_migrations():
    """SQLite 兼容的列迁移 + 索引补建"""
    import logging
    from sqlalchemy import inspect, text

    logger = logging.getLogger(__name__)
    inspector = inspect(engine)

    def ensure_column(table: str, name: str, ddl: str):
        columns = {c["name"] for c in inspector.get_columns(table)}
        if name not in columns:
            logger.info("🔄 迁移：%s 表添加 %s 列", table, name)
            with engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                conn.commit()

    ensure_column("task", "status", "VARCHAR(20) NOT NULL DEFAULT 'uploaded'")
    ensure_column("task", "update_time", "DATETIME")
    ensure_column("task", "tts_voice", "VARCHAR(30) NOT NULL DEFAULT '冰糖'")
    ensure_column("section", "update_time", "DATETIME")
    for table in ("slide", "script", "tts"):
        ensure_column(table, "status", "VARCHAR(10) NOT NULL DEFAULT 'ok'")
        ensure_column(table, "update_time", "DATETIME")
    ensure_column("tts", "file_path", "VARCHAR(255)")

    # 索引补建（新建库由模型元数据建出，此处幂等兜底）
    with engine.connect() as conn:
        for table in ("section", "slide", "script", "tts"):
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{table}_task ON {table} (task_id)"))
        # task.task_id 唯一索引（存量查重后创建）
        dupes = conn.execute(
            text("SELECT task_id FROM task GROUP BY task_id HAVING COUNT(*) > 1")
        ).fetchall()
        if dupes:
            logger.warning("task.task_id 存在重复值 %s，跳过唯一索引创建", [d[0] for d in dupes][:5])
        else:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_task_taskid ON task (task_id)"))
        conn.commit()