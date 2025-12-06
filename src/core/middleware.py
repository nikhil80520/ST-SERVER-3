"""
Centralized middleware configuration and registration.
"""
import json
import logging
from typing import Callable
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.routing import Match

logger = logging.getLogger(__name__)


def setup_cors_middleware(app: FastAPI, allowed_origins: list[str]) -> None:
    """
    Configure CORS middleware for React Native and web compatibility.
    
    Args:
        app: FastAPI application instance
        allowed_origins: List of allowed origins (use ["*"] for all)
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"],
        allow_headers=["*"],
        expose_headers=["*"],
        max_age=86400,  # 24 hours preflight cache
    )
    logger.info(f"✅ CORS middleware configured with origins: {allowed_origins}")


def create_request_logging_middleware(verbose_logging: bool = False) -> Callable:
    """
    Create middleware for request/response logging.
    
    Args:
        verbose_logging: Enable detailed request/response logging
    
    Returns:
        Middleware function
    """
    async def middleware(request: Request, call_next):
        # Log incoming request if verbose
        if verbose_logging:
            logger.info(f"🌐 {request.method} {request.url.path}")
            
            # Log request body for non-GET requests
            if request.method in ["POST", "PUT", "PATCH"]:
                body = await request.body()
                if body:
                    try:
                        body_json = json.loads(body.decode('utf-8'))
                        logger.info(f"📦 Body keys: {list(body_json.keys())}")
                    except:
                        logger.info(f"📦 Body: {len(body)} bytes")
                
                # Reconstruct request with body
                async def new_receive():
                    return {"type": "http.request", "body": body, "more_body": False}
                request._receive = new_receive
        
        # Handle preflight OPTIONS requests
        if request.method == "OPTIONS":
            response = JSONResponse({"message": "OK"})
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH"
            response.headers["Access-Control-Allow-Headers"] = "*"
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Max-Age"] = "86400"
            return response
        
        # Process the request
        try:
            response = await call_next(request)
            
            # Log 405 Method Not Allowed errors with diagnostics
            if response.status_code == 405:
                allowed = response.headers.get("allow", "<none>")
                logger.warning(f"🚫 Method not allowed: {request.method} {request.url.path} (Allow: {allowed})")
                
                # Inspect router to surface conflicting route definitions
                try:
                    scope_template = {
                        "type": "http",
                        "path": request.url.path,
                        "root_path": "",
                        "scheme": request.url.scheme or "http",
                    }
                    matching_paths = []
                    for route in request.app.router.routes:
                        methods = getattr(route, "methods", None)
                        if not methods:
                            continue
                        scope = dict(scope_template)
                        scope["method"] = next(iter(methods))
                        match, _ = route.matches(scope)
                        if match == Match.FULL:
                            path_repr = getattr(route, "path_format", getattr(route, "path", str(route)))
                            matching_paths.append((path_repr, ",".join(sorted(methods))))
                    
                    if matching_paths:
                        logger.warning("🧭 Routes sharing this path:")
                        for path_repr, methods in matching_paths:
                            logger.warning(f"   {path_repr} -> {methods}")
                except Exception as diag_error:
                    logger.warning(f"⚠️ Route diagnostic failure: {diag_error}")
            
            if verbose_logging:
                logger.info(f"✅ {response.status_code}")
            
            return response
        except Exception as e:
            logger.error(f"❌ Request error: {e}")
            raise
    
    return middleware


def setup_middleware(app: FastAPI, cors_origins: list[str], verbose_logging: bool = False) -> None:
    """
    Setup all application middleware.
    
    Args:
        app: FastAPI application instance
        cors_origins: List of allowed CORS origins
        verbose_logging: Enable verbose request/response logging
    """
    # Setup CORS
    setup_cors_middleware(app, cors_origins)
    
    # Setup request logging
    logging_middleware = create_request_logging_middleware(verbose_logging)
    app.middleware("http")(logging_middleware)
    
    logger.info("✅ All middleware configured successfully")
