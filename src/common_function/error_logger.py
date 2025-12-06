import asyncio
import logging

logger = logging.getLogger("error_logger")

async def log_error_to_slack(exc: Exception, context: dict = None, level: str = "ERROR"):
    logger.error(f"[SLACK] {level}: {exc} | context: {context}")

async def log_warning(msg: str):
    logger.warning(f"[SLACK WARNING] {msg}")

async def log_info(msg: str):
    logger.info(f"[SLACK INFO] {msg}")

async def log_critical(msg: str):
    logger.critical(f"[SLACK CRITICAL] {msg}")
