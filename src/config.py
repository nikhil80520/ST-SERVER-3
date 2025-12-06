# ===== app/config.py - Use core/config.py instead =====
# This file is kept for backward compatibility
# New code should import from app.core.config

from src.core.config import settings, Settings

__all__ = ['settings', 'Settings']
