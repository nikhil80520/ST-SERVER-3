"""
pytest configuration and fixtures for all tests
"""
import os
import pytest

# Set environment variables before any app imports
os.environ["DEBUG"] = "true"
os.environ["ALLOW_LOCAL_AUTH_BYPASS"] = "true"

@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Setup test environment variables"""
    # Ensure test environment is configured
    os.environ["DEBUG"] = "true"
    os.environ["ALLOW_LOCAL_AUTH_BYPASS"] = "true"
    yield
    # Cleanup if needed
