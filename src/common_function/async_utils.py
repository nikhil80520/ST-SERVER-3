"""
Async utilities for handling event loops in threaded contexts
"""
import asyncio
from typing import Optional


def get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    """
    Safely get or create an event loop, handling various threading scenarios.
    
    This function handles:
    - Running loops (from async context)
    - Existing loops (from main thread)
    - No loop (from worker threads)
    
    Returns:
        asyncio.AbstractEventLoop: The current or newly created event loop
    """
    try:
        # First, try to get the running loop (we're in async context)
        loop = asyncio.get_running_loop()
        return loop
    except RuntimeError:
        # No running loop, try to get the current loop
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("Loop is closed")
            return loop
        except RuntimeError:
            # No loop exists or it's closed, create a new one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop
