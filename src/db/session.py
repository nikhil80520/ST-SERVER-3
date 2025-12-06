"""
Database session management for PostgreSQL
"""
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
import logging

logger = logging.getLogger(__name__)

# Global engine and session factory
engine = None
AsyncSessionLocal = None


async def init_database(database_url: str, echo: bool = False, pool_size: int = 20, max_overflow: int = 10):
    """
    Initialize database connection
    
    Args:
        database_url: PostgreSQL connection string (postgresql+asyncpg://...)
        echo: Enable SQL query logging
        pool_size: Connection pool size
        max_overflow: Max overflow connections
    """
    global engine, AsyncSessionLocal
    
    try:
        # Create async engine
        engine = create_async_engine(
            database_url,
            echo=echo,
            pool_pre_ping=True,
            pool_recycle=3600,  # Recycle connections after 1 hour
            pool_size=pool_size,
            max_overflow=max_overflow,
        )
        
        # Create session factory
        AsyncSessionLocal = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
        
        # Log success (mask password in URL)
        masked_url = database_url.split('@')[-1] if '@' in database_url else database_url
        logger.info(f"✅ PostgreSQL connected: {masked_url}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {str(e)}")
        raise


async def create_tables():
    """
    Create all tables defined in models
    """
    from .models import Base
    
    if engine is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    logger.info("✅ Database tables created successfully")


async def drop_tables():
    """
    Drop all tables (use with caution!)
    """
    from .models import Base
    
    if engine is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    logger.info("⚠️ All database tables dropped")


async def close_database():
    """
    Close database connections
    """
    global engine
    
    if engine:
        await engine.dispose()
        logger.info("✅ Database connections closed")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency to get database session for FastAPI endpoints
    
    Usage:
        @app.get("/users")
        async def get_users(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(User))
            return result.scalars().all()
    """
    if AsyncSessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_db_info() -> dict:
    """
    Get database connection info for health checks
    """
    from sqlalchemy import text
    
    if engine is None:
        return {
            "connected": False,
            "error": "Database not initialized"
        }
    
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version()"))
            version = result.scalar()
            
            return {
                "connected": True,
                "version": version,
                "pool_size": engine.pool.size() if hasattr(engine.pool, 'size') else None,
            }
    except Exception as e:
        return {
            "connected": False,
            "error": str(e)
        }
