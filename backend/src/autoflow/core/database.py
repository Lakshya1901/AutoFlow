"""
AutoFlow Database Configuration
Async SQLAlchemy engine, session factory, and base model class.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime

from sqlalchemy import JSON, DateTime, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from autoflow.core.config import get_settings


def _create_engine() -> object:
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,       # Detect stale connections
        pool_recycle=3600,         # Recycle connections after 1 hour
        echo=settings.db_echo,
    )


# Global engine and session factory — created once at startup
engine = _create_engine()

AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,       # Avoid lazy-loading after commit
    autocommit=False,
    autoflush=False,
)


# JSONB on Postgres (indexable), plain JSON elsewhere (SQLite in tests)
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(AsyncAttrs, DeclarativeBase):
    """
    Base model with common fields shared by all entities.

    All AutoFlow models inherit from this class.
    Provides: uuid primary key, created_at, updated_at.
    """

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id}>"


async def get_db() -> AsyncGenerator[AsyncSession]:
    """
    FastAPI dependency that provides a database session per request.

    Usage:
        @router.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_tables() -> None:
    """Create all tables. Used in testing; migrations handle production."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_tables() -> None:
    """Drop all tables. Used in testing only."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
