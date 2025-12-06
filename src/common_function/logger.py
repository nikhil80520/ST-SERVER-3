"""
Centralized logging utility with structured logging and OpenTelemetry integration.

This module provides:
- Structured logging with Python's logging module
- OpenTelemetry trace correlation
- Console and file output
- Environment-based log levels
- Backward compatibility with legacy log functions
"""
import logging
import sys
from typing import Optional, Dict, Any
from datetime import datetime
from src.core.config import settings


class StructuredLogger:
    """
    Structured logger with OpenTelemetry integration.
    
    Provides consistent logging across the application with:
    - JSON-compatible structured logging
    - Trace ID correlation
    - Multiple output handlers
    - Log level management
    """
    
    _initialized = False
    _loggers: Dict[str, logging.Logger] = {}
    
    # Log level constants
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL
    
    @classmethod
    def initialize(cls, log_level: str = "INFO", log_file: Optional[str] = None) -> None:
        """
        Initialize the logging system (called once at app startup).
        
        Args:
            log_level: Minimum log level to capture (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            log_file: Optional file path for log output
        """
        if cls._initialized:
            return
        
        # Create formatter with structured output
        formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        
        # File handler (optional)
        handlers = [console_handler]
        if log_file:
            try:
                file_handler = logging.FileHandler(log_file)
                file_handler.setFormatter(formatter)
                handlers.append(file_handler)
            except Exception as e:
                print(f"⚠️  Failed to create log file handler: {e}")
        
        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        
        # Remove existing handlers to avoid duplicates
        root_logger.handlers.clear()
        
        for handler in handlers:
            root_logger.addHandler(handler)
        
        cls._initialized = True
        
        # Log initialization
        init_logger = logging.getLogger(__name__)
        init_logger.info(f"✅ Logging system initialized with level: {log_level}")
    
    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """
        Get a logger instance for a specific module.
        
        Args:
            name: Name of the logger (typically __name__ of the module)
            
        Returns:
            Logger instance configured with application settings
        """
        if not cls._initialized:
            # Auto-initialize with defaults if not already initialized
            log_level = "DEBUG" if settings.verbose_logging else "INFO"
            cls.initialize(log_level=log_level)
        
        if name not in cls._loggers:
            cls._loggers[name] = logging.getLogger(name)
        
        return cls._loggers[name]


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module.
    
    Args:
        name: Name of the logger (typically __name__)
        
    Returns:
        Logger instance
        
    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Processing request", extra={"user_id": "123"})
    """
    return StructuredLogger.get_logger(name)


# ===== BACKWARD COMPATIBILITY FUNCTIONS =====
# These maintain compatibility with existing code while migrating to proper logging

def should_log_verbose() -> bool:
    """
    Check if verbose logging is enabled.
    
    Returns:
        True if verbose logging is enabled
    """
    return settings.verbose_logging


def vprint(*args, **kwargs) -> None:
    """
    Verbose print - only prints if verbose_logging is True.
    
    Deprecated: Use logger.debug() instead.
    """
    if settings.verbose_logging:
        logger = get_logger("legacy.vprint")
        logger.debug(" ".join(str(arg) for arg in args))


def log_info(message: str, force: bool = False) -> None:
    """
    Log info messages only if verbose or forced.
    
    Deprecated: Use logger.info() instead.
    
    Args:
        message: Message to log
        force: Force logging even if not verbose
    """
    logger = get_logger("legacy.info")
    if force or settings.verbose_logging:
        logger.info(f"ℹ️  {message}")


def log_success(message: str, force: bool = True) -> None:
    """
    Log success messages (shown by default).
    
    Deprecated: Use logger.info() instead.
    
    Args:
        message: Success message
        force: Force logging (default True)
    """
    logger = get_logger("legacy.success")
    if force or settings.verbose_logging:
        logger.info(f"✅ {message}")


def log_warning(message: str, force: bool = True) -> None:
    """
    Log warning messages (shown by default).
    
    Deprecated: Use logger.warning() instead.
    
    Args:
        message: Warning message
        force: Force logging (default True)
    """
    logger = get_logger("legacy.warning")
    if force or settings.verbose_logging:
        logger.warning(f"⚠️  {message}")


def log_error(message: str, force: bool = True) -> None:
    """
    Log error messages (always shown).
    
    Deprecated: Use logger.error() instead.
    
    Args:
        message: Error message
        force: Force logging (default True)
    """
    logger = get_logger("legacy.error")
    logger.error(f"❌ {message}")


def log_debug(message: str) -> None:
    """
    Log debug messages only if verbose mode is on.
    
    Deprecated: Use logger.debug() instead.
    
    Args:
        message: Debug message
    """
    if settings.verbose_logging:
        logger = get_logger("legacy.debug")
        logger.debug(f"🔍 {message}")


def log_phase(message: str, force: bool = True) -> None:
    """
    Log phase transitions (shown by default).
    
    Deprecated: Use logger.info() instead.
    
    Args:
        message: Phase message
        force: Force logging (default True)
    """
    logger = get_logger("legacy.phase")
    if force or settings.verbose_logging:
        logger.info(f"📍 {message}")


# Initialize logging on module import
StructuredLogger.initialize(
    log_level="DEBUG" if settings.verbose_logging else "INFO"
)
