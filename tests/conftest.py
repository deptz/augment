"""
Pytest configuration and fixtures
"""
import sys
from pathlib import Path

import pytest

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def pytest_configure(config):
    """Register custom marks."""
    config.addinivalue_line("markers", "integration: mark test as integration (requires external services)")




