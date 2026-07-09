from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_runtime_columns()


def ensure_runtime_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("jobs"):
        return
    columns = {column["name"] for column in inspector.get_columns("jobs")}
    with engine.begin() as connection:
        if "processing_mode" not in columns:
            connection.execute(
                text("ALTER TABLE jobs ADD COLUMN processing_mode VARCHAR(20) NOT NULL DEFAULT 'premium'")
            )
        if "ai_provider" not in columns:
            connection.execute(text("ALTER TABLE jobs ADD COLUMN ai_provider VARCHAR(80)"))
        if "ai_model" not in columns:
            connection.execute(text("ALTER TABLE jobs ADD COLUMN ai_model VARCHAR(255)"))
        if "model_option_id" not in columns:
            connection.execute(text("ALTER TABLE jobs ADD COLUMN model_option_id VARCHAR(255)"))
        if "cleanup_preset" not in columns:
            connection.execute(text("ALTER TABLE jobs ADD COLUMN cleanup_preset VARCHAR(40)"))
