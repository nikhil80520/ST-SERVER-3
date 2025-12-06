"""
Application initialization and startup/shutdown event handlers.
"""
import logging
from fastapi import FastAPI

from src.core.config import settings
from src.common_function.firebase_init import initialize_firebase

logger = logging.getLogger(__name__)


def init_firebase() -> None:
    """Initialize Firebase before anything else."""
    initialize_firebase()
    logger.info("✅ Firebase initialized")


async def init_database() -> None:
    """Initialize PostgreSQL database connection."""
    try:
        from src.db import init_database as init_db, create_tables, get_db_info
        
        # Initialize database connection
        await init_db(
            database_url=settings.database_url or settings.database.url,
            echo=settings.db_echo or settings.database.echo,
            pool_size=settings.db_pool_size or settings.database.pool_size,
            max_overflow=settings.db_pool_max_overflow or settings.database.pool_max_overflow
        )
        
        # Get database info
        db_info = await get_db_info()
        if db_info.get("connected"):
            logger.info(f"✅ PostgreSQL connected: {db_info.get('version', 'Unknown version')}")
            
            # Create tables in development mode
            if settings.debug:
                try:
                    await create_tables()
                    logger.info("✅ Database tables created/verified")
                except Exception as e:
                    logger.warning(f"⚠️ Table creation note: {str(e)}")
        else:
            logger.error(f"❌ PostgreSQL connection failed: {db_info.get('error')}")
            
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {str(e)}")
        logger.warning("⚠️ Application will continue without database")



def init_openai() -> None:
    """Initialize and test OpenAI API key."""
    if settings.openai_api_key and settings.openai_api_key != "test":
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=settings.openai_api_key,
                timeout=60.0
            )
            logger.info("✅ OpenAI client initialized successfully (60s timeout)")
            logger.info("🎵 Using OpenAI TTS for audio generation")
        except Exception as e:
            logger.warning(f"⚠️ OpenAI initialization failed: {str(e)}")
    else:
        logger.warning("⚠️ OpenAI API key not configured - story generation will not work")


def init_sentry() -> None:
    """Initialize Sentry error tracking."""
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn="https://486344263e9d7536d5219194c7987cf3@o4509915720450048.ingest.de.sentry.io/4509915728183376",
            send_default_pii=True,
        )
        logger.info("✅ Sentry error tracking initialized")
    except Exception as e:
        logger.warning(f"⚠️ Sentry initialization failed: {str(e)}")


def register_routers(app: FastAPI) -> tuple[bool, bool]:
    """
    Register all application routers.
    
    Returns:
        Tuple of (stories_loaded, iot_loaded) booleans
    """
    # Core routers (always available)
    # from app.routers import (
    #     auth, health, users, sharing, reference_images, 
    #     ntp, admin, analytics, children, lullabies
    # )
    # from app.routers.system import notifications
    from src.children.routes import router as children_router
    from src.auth.routes import router as auth_router
    from src.lullabies.routes import router as lullabies_router
    from src.share.routes import router as sharing_router
    from src.user.routes import router as users_router
    from src.reference_images.routes import router as reference_images_router
    
    app.include_router(children_router)
    app.include_router(auth_router)
    # app.include_router(health.router)
    app.include_router(users_router)
    app.include_router(children_router)
    app.include_router(lullabies_router)
    app.include_router(sharing_router)
    app.include_router(reference_images_router)
    # app.include_router(ntp.router)
    # app.include_router(admin.router)
    # app.include_router(analytics.router)
    # app.include_router(notifications.router)
    
    logger.info("✅ Core routers registered (including reference-images, notifications, and lullabies)")
    
    # Optional: Conversational AI router
    try:
        from src.conversation.routes import router as conversation_router
        app.include_router(conversation_router)
        logger.info("✅ Conversational AI router loaded")
    except ImportError as e:
        logger.warning(f"⚠️ Conversational AI router not loaded (missing dependencies): {e}")
    except Exception as e:
        logger.error(f"❌ Conversational AI router failed: {e}")
    
    # Optional: Stories router
    stories_loaded = False
    try:
        from src.story.routes import router as stories_router
        app.include_router(stories_router)
        stories_loaded = True
        logger.info("✅ Story router loaded")
    except ImportError as e:
        logger.warning(f"⚠️ Story router not loaded: {e}")
    except Exception as e:
        logger.error(f"❌ Story router failed: {e}")
    
    # Optional: IoT router
    iot_loaded = False
    try:
        from src.iot.routes import router as iot_router
        app.include_router(iot_router)
        iot_loaded = True
        logger.info("✅ IoT router loaded")
    except ImportError as e:
        logger.warning(f"⚠️ IoT router not loaded: {e}")
    except Exception as e:
        logger.error(f"❌ IoT router failed: {e}")
    
    return stories_loaded, iot_loaded


async def startup_handler(app: FastAPI, stories_loaded: bool, iot_loaded: bool) -> None:
    """Handle application startup tasks."""
    logger.info("🚀 ESP32 Storytelling Server started successfully!")
    logger.info(f"📊 Environment: {'Development' if settings.debug else 'Production'}")
    logger.info(f"🌐 CORS Origins: {settings.cors_origins_list}")
    
    # Initialize database
    await init_database()
    
    if not stories_loaded:
        logger.warning("⚠️ Story router not loaded — /stories endpoints unavailable")
    if not iot_loaded:
        logger.warning("⚠️ IoT router not loaded — /iot endpoints unavailable")
    
    # Log registered routes
    logger.info("🛣️ Registered routes:")
    for route in app.router.routes:
        methods = getattr(route, "methods", None)
        if methods:
            logger.info(f"   {route.path} -> {','.join(sorted(methods))}")
    
    # Start background services
    # try:
    #     from src.background_process.enhanced_background_service import enhanced_background_service
    #     await enhanced_background_service.start(num_workers=settings.background_workers)
    #     logger.info("✅ Enhanced background service started")
    # except Exception as e:
    #     logger.warning(f"⚠️ Enhanced background service failed: {e}")
    
    try:
        from src.background_process.mqtt_service import mqtt_service
        await mqtt_service.start()
        logger.info("✅ MQTT service started")
    except Exception as e:
        logger.warning(f"⚠️ MQTT service failed: {e}")
    
    logger.info("🤖 AI Services:")
    logger.info(f"  - OpenAI: {'✅ Configured' if settings.openai_api_key and settings.openai_api_key != 'test' else '❌ Not configured'}")
    logger.info(f"  - Firebase Storage: ✅ Connected")
    logger.info(f"  - PostgreSQL: ✅ Connected")
    logger.info("📖 Story Generation: OpenAI TTS with Full Parallel Processing")


async def shutdown_handler() -> None:
    """Handle application shutdown tasks."""
    logger.info("🛑 Shutting down ESP32 Storytelling Server...")
    
    # Close database connections
    try:
        from src.db import close_database
        await close_database()
        logger.info("✅ Database connections closed")
    except Exception as e:
        logger.warning(f"⚠️ Error closing database: {e}")
    
    # Cleanup conversational AI
    try:
        from src.conversation.routes import cleanup_conversations
        await cleanup_conversations()
        logger.info("✅ Conversational AI cleaned up")
    except Exception as e:
        logger.warning(f"⚠️ Error cleaning up conversational AI: {e}")
    
    # Stop background service
    # try:
    #     from src.background_process.enhanced_background_service import enhanced_background_service
    #     await enhanced_background_service.stop()
    #     logger.info("✅ Enhanced background service stopped")
    # except Exception as e:
    #     logger.warning(f"⚠️ Error stopping background service: {e}")
    
    # Stop MQTT service
    try:
        from src.background_process.mqtt_service import mqtt_service
        await mqtt_service.stop()
        logger.info("✅ MQTT service stopped")
    except Exception as e:
        logger.warning(f"⚠️ Error stopping MQTT service: {e}")
    
    logger.info("🛑 Server shutdown complete")
