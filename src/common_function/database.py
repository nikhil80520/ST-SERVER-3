"""
Database setup for IoT Device Management
Handles SQLAlchemy async engine, session management, and Redis connection
"""

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
import redis.asyncio as redis
from src.core.config import settings
import logging

logger = logging.getLogger(__name__)

# SQLAlchemy async engine
engine = None
AsyncSessionLocal = None

# Redis connection
redis_client = None

async def init_database():
    """Initialize database connections"""
    global engine, AsyncSessionLocal, redis_client
    
    try:
        # Initialize SQLAlchemy
        engine = create_async_engine(
            settings.db_url,
            echo=settings.debug,
            pool_pre_ping=True,
            pool_recycle=300
        )
        
        AsyncSessionLocal = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        logger.info(f"✅ Database connected: {settings.db_url.split('@')[1] if '@' in settings.db_url else settings.db_url}")
        
        # Initialize Redis
        redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        await redis_client.ping()
        logger.info(f"✅ Redis connected: {settings.redis_url}")
        
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {str(e)}")
        raise

async def close_database():
    """Close database connections"""
    global engine, redis_client
    
    if engine:
        await engine.dispose()
        logger.info("Database connections closed")
    
    if redis_client:
        await redis_client.close()
        logger.info("Redis connection closed")

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

async def get_redis():
    """Dependency to get Redis client"""
    return redis_client

# Create tables
async def create_tables():
    """Create all tables"""
    from app.models.iot_device import Base
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    logger.info("✅ IoT tables created successfully")
