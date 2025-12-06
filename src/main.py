"""
Main application entry point - Refactored for clean architecture.
All middleware, initialization, and event handlers are in core modules.
"""
import os
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi import HTTPException, status

from src.common_function.firebase_init import get_firebase_info

# Configure logging
logging.basicConfig(level=logging.WARNING)
for logger_name in ["httpx", "httpcore", "asyncio", "aiohttp"]:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

# Import core modules
from src.core.config import settings
from src.core.middleware import setup_middleware
from src.core.app_init import (
    init_firebase, init_openai, init_sentry,
    register_routers, startup_handler, shutdown_handler
)

# Set app logging level
app_logger = logging.getLogger("app")
app_logger.setLevel(logging.INFO if settings.verbose_logging else logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.INFO if settings.verbose_logging else logging.WARNING)

# Initialize external services
init_firebase()
init_openai()
init_sentry()

# Initialize FastAPI app
app = FastAPI(
    title="ESP32 Storytelling Server - Optimized OpenAI Edition",
    version="3.0.0",
    description="Optimized FastAPI server for ESP32 storytelling device - OpenAI TTS with parallel processing"
)

# Setup middleware (CORS, logging, etc.)
setup_middleware(app, settings.cors_origins_list, settings.verbose_logging)

# Register all routers
stories_loaded, iot_loaded = register_routers(app)

# Startup event
@app.on_event("startup")
async def startup():
    """Application startup event."""
    await startup_handler(app, stories_loaded, iot_loaded)

# Shutdown event
@app.on_event("shutdown")
async def shutdown():
    """Application shutdown event."""
    await shutdown_handler()

@app.get("/health")
async def health_check():
    """Health check endpoint with Firebase and PostgreSQL status"""
    firebase_info = get_firebase_info()
    
    # Get database status
    database_info = {"connected": False, "error": "Not initialized"}
    try:
        from src.db import get_db_info
        database_info = await get_db_info()
    except Exception as e:
        database_info = {"connected": False, "error": str(e)}
    
    return {
        "status": "healthy",
        "firebase": {
            "initialized": firebase_info["initialized"],
            "firestore_available": firebase_info["firestore_available"],
            "storage_available": firebase_info["storage_available"],
            "credential_source": firebase_info["credential_source"]
        },
        "database": {
            "connected": database_info.get("connected", False),
            "version": database_info.get("version", "Unknown"),
            "pool_size": database_info.get("pool_size")
        }
    }

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "message": "ESP32 Storytelling Server API - Optimized OpenAI Edition",
        "version": "3.0.0",
        "docs": "/docs",
        "health": "/health",
        "status": "running",
        "ai_stack": "OpenAI TTS with Full Parallel Processing",
        "optimizations": {
            "parallel_processing": settings.max_concurrent_scenes,
            "batch_audio": settings.enable_batch_audio,
            "batch_images": settings.enable_batch_images,
            "parallel_uploads": settings.enable_parallel_uploads
        },
        "cors_origins": settings.cors_origins_list
    }

# Apple App Site Association for Universal Links
@app.get("/.well-known/apple-app-site-association")
async def apple_app_site_association():
    """Serve Apple App Site Association file for Universal Links."""
    aasa_path = os.path.join(os.path.dirname(__file__), "../.well-known/apple-app-site-association")
    if os.path.exists(aasa_path):
        return FileResponse(
            aasa_path,
            media_type="application/json",
            headers={
                "Content-Type": "application/json",
                "Cache-Control": "public, max-age=3600"
            }
        )
    return JSONResponse(status_code=404, content={"detail": "AASA file not found"})

# Favicon endpoint
@app.get("/favicon.ico")
async def favicon():
    """Serve favicon from known paths."""
    user_path = "/Users/sukhmansinghnarula/Documents/Code/Bern/App/finalApp/assets/images/owl-icon-512.png"
    if os.path.exists(user_path):
        return FileResponse(user_path, media_type="image/png")
    
    fallback = os.path.join(os.path.dirname(__file__), "../static/owl-icon-512.png")
    if os.path.exists(fallback):
        return FileResponse(fallback, media_type="image/png")
    
    return JSONResponse(status_code=404, content={"detail": "favicon not found"})

# Test pages
@app.get("/test-disable", response_class=HTMLResponse)
async def test_disable_page():
    """Serve test page for debugging disable functionality."""
    test_path = os.path.join(os.path.dirname(__file__), "../static/test-disable.html")
    try:
        with open(test_path, "r") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test page not found")

@app.get("/test-conversation", response_class=HTMLResponse)
async def test_conversation_page():
    """Serve test page for testing WebRTC conversational AI."""
    test_path = os.path.join(os.path.dirname(__file__), "../static/conversation-test.html")
    try:
        with open(test_path, "r") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation test page not found")

# Global OPTIONS handler - DISABLED (CORS middleware + router-specific OPTIONS handlers are sufficient)
# This catch-all was blocking all GET routes - FastAPI matches routes in order
# @app.options("/{path:path}")
# async def global_options_handler(path: str, request: Request):
#     """Handle preflight OPTIONS requests for any path."""
#     response = JSONResponse({"message": "OK"})
#     response.headers["Access-Control-Allow-Origin"] = "*"
#     response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH"
#     response.headers["Access-Control-Allow-Headers"] = "*"
#     response.headers["Access-Control-Allow-Credentials"] = "true"
#     response.headers["Access-Control-Max-Age"] = "86400"
#     return response

if __name__ == "__main__":
    import uvicorn
    
    # Validate required environment variables for production
    if not settings.debug:
        required_vars = [
            "OPENAI_API_KEY",
            "REPLICATE_API_TOKEN",
            "FIREBASE_CREDENTIALS_PATH",
            "FIREBASE_STORAGE_BUCKET"
        ]
        
        missing_vars = [var for var in required_vars if not os.getenv(var) or os.getenv(var) == "test"]
        
        if missing_vars:
            print(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
            print("Please set these environment variables before running the server.")
            print("💡 Tip: Set DEBUG=true for development/testing mode")
            exit(1)
    else:
        print("🧪 Running in debug mode - external services may not work")
    
    print("🔧 Starting optimized server...")
    print("⚡ Performance features enabled:")
    print(f"   - Parallel processing: {settings.max_concurrent_scenes} scenes")
    print(f"   - Batch audio: {settings.enable_batch_audio}")
    print(f"   - Batch images: {settings.enable_batch_images}")
    print(f"   - Parallel uploads: {settings.enable_parallel_uploads}")
    
    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )
