"""
Database engine and session management for async SQLAlchemy.
Provides async_engine and get_session dependency.
"""
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from src.core.config import settings


# Primary database engine
async_engine = create_async_engine(
    url=settings.database_url or settings.database.url,
    pool_pre_ping=True,
    echo_pool=True
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield an async SQLAlchemy session with automatic rollback on errors.
    
    Usage in FastAPI endpoints:
        from fastapi import Depends
        from src.db.main import get_session
        
        @router.get("/users")
        async def get_users(session: AsyncSession = Depends(get_session)):
            result = await session.execute(select(User))
            return result.scalars().all()
    """
    async with AsyncSession(async_engine) as session:
        try:
            yield session
        except Exception:
            try:
                await session.rollback()
            except Exception:
                pass
            raise
