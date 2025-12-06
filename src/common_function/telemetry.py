"""
OpenTelemetry configuration for distributed tracing and metrics.

This module sets up OpenTelemetry instrumentation for:
- FastAPI automatic instrumentation
- HTTP client tracing
- Database operation tracing
- Custom span creation
- Trace exporters (Console, OTLP)
"""
from typing import Optional
import logging
from contextlib import contextmanager

# OpenTelemetry imports (will be optional dependencies)
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
    )
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    trace = None

from src.core.config import settings
from src.common_function.logger import get_logger

logger = get_logger(__name__)


class TelemetryConfig:
    """
    OpenTelemetry configuration and initialization.
    
    Provides distributed tracing capabilities for the application with:
    - Automatic instrumentation for FastAPI
    - HTTP client instrumentation
    - Custom span creation
    - Multiple exporters (console, OTLP)
    
    Constants:
        SERVICE_NAME: Name of this service in traces
        EXPORT_TO_CONSOLE: Whether to export traces to console (dev mode)
        EXPORT_TO_OTLP: Whether to export to OTLP endpoint (production)
    """
    
    # Service configuration
    SERVICE_NAME_VALUE = "storyteller-api"
    EXPORT_TO_CONSOLE = settings.verbose_logging  # Console export in dev mode
    EXPORT_TO_OTLP = False  # Set to True when OTLP endpoint is configured
    
    # OTLP endpoint (configure for production)
    OTLP_ENDPOINT = "http://localhost:4318"  # Default OTLP HTTP endpoint
    
    _initialized = False
    _tracer_provider: Optional[any] = None
    _tracer: Optional[any] = None
    
    @classmethod
    def initialize(cls, app=None) -> None:
        """
        Initialize OpenTelemetry tracing.
        
        Args:
            app: FastAPI application instance (optional, for automatic instrumentation)
        """
        if not OTEL_AVAILABLE:
            logger.warning(
                "⚠️  OpenTelemetry not available. Install with: "
                "pip install opentelemetry-api opentelemetry-sdk "
                "opentelemetry-instrumentation-fastapi "
                "opentelemetry-instrumentation-requests "
                "opentelemetry-instrumentation-httpx"
            )
            return
        
        if cls._initialized:
            logger.debug("OpenTelemetry already initialized")
            return
        
        try:
            # Create resource with service name
            resource = Resource(attributes={
                SERVICE_NAME: cls.SERVICE_NAME_VALUE
            })
            
            # Create tracer provider
            cls._tracer_provider = TracerProvider(resource=resource)
            
            # Add console exporter for development
            if cls.EXPORT_TO_CONSOLE:
                console_processor = BatchSpanProcessor(ConsoleSpanExporter())
                cls._tracer_provider.add_span_processor(console_processor)
                logger.info("✅ OpenTelemetry console exporter enabled")
            
            # Add OTLP exporter for production (if configured)
            if cls.EXPORT_TO_OTLP:
                try:
                    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                    otlp_exporter = OTLPSpanExporter(endpoint=f"{cls.OTLP_ENDPOINT}/v1/traces")
                    otlp_processor = BatchSpanProcessor(otlp_exporter)
                    cls._tracer_provider.add_span_processor(otlp_processor)
                    logger.info(f"✅ OpenTelemetry OTLP exporter enabled: {cls.OTLP_ENDPOINT}")
                except ImportError:
                    logger.warning(
                        "⚠️  OTLP exporter not available. "
                        "Install with: pip install opentelemetry-exporter-otlp-proto-http"
                    )
            
            # Set global tracer provider
            trace.set_tracer_provider(cls._tracer_provider)
            
            # Get tracer for this service
            cls._tracer = trace.get_tracer(cls.SERVICE_NAME_VALUE)
            
            # Instrument FastAPI (if app provided)
            if app is not None:
                FastAPIInstrumentor.instrument_app(app)
                logger.info("✅ FastAPI instrumented with OpenTelemetry")
            
            # Instrument HTTP clients
            RequestsInstrumentor().instrument()
            HTTPXClientInstrumentor().instrument()
            logger.info("✅ HTTP clients instrumented with OpenTelemetry")
            
            cls._initialized = True
            logger.info(f"✅ OpenTelemetry initialized for service: {cls.SERVICE_NAME_VALUE}")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize OpenTelemetry: {e}", exc_info=True)
    
    @classmethod
    def get_tracer(cls):
        """
        Get the tracer instance.
        
        Returns:
            Tracer instance for creating spans
        """
        if not cls._initialized:
            cls.initialize()
        return cls._tracer
    
    @classmethod
    @contextmanager
    def trace_span(cls, name: str, attributes: Optional[dict] = None):
        """
        Context manager for creating a traced span.
        
        Args:
            name: Name of the span
            attributes: Optional attributes to add to the span
            
        Yields:
            Span instance
            
        Example:
            >>> with TelemetryConfig.trace_span("story_generation", {"user_id": "123"}):
            ...     generate_story()
        """
        if not OTEL_AVAILABLE or not cls._initialized:
            # No-op if OpenTelemetry not available
            yield None
            return
        
        tracer = cls.get_tracer()
        if tracer is None:
            yield None
            return
        
        with tracer.start_as_current_span(name) as span:
            if attributes:
                for key, value in attributes.items():
                    span.set_attribute(key, str(value))
            yield span


def trace_operation(operation_name: str, **attributes):
    """
    Decorator for tracing a function/method.
    
    Args:
        operation_name: Name of the operation to trace
        **attributes: Additional attributes to add to the span
        
    Example:
        >>> @trace_operation("generate_story", service="story_service")
        ... async def generate_story(story_id: str):
        ...     # Story generation logic
        ...     pass
    """
    def decorator(func):
        async def async_wrapper(*args, **kwargs):
            with TelemetryConfig.trace_span(operation_name, attributes):
                return await func(*args, **kwargs)
        
        def sync_wrapper(*args, **kwargs):
            with TelemetryConfig.trace_span(operation_name, attributes):
                return func(*args, **kwargs)
        
        # Return appropriate wrapper based on function type
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


# Convenience function for creating spans
def create_span(name: str, attributes: Optional[dict] = None):
    """
    Create a new span for tracing an operation.
    
    Args:
        name: Name of the span
        attributes: Optional attributes
        
    Returns:
        Context manager for the span
        
    Example:
        >>> with create_span("database_query", {"table": "stories"}):
        ...     db.query(...)
    """
    return TelemetryConfig.trace_span(name, attributes)
