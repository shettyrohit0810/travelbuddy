"""Database session and declarative base.

Schema ownership belongs to Alembic, not to `create_all()`. The app never creates
tables at import time -- migrations run before the server starts (see the compose
command). One owner for the schema, and it is the one with a version history.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
