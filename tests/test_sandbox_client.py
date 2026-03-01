"""Tests for SandboxClient and sandbox exception hierarchy."""
import pytest

from src.sandbox_client import (
    SandboxClientError,
    SandboxUnavailableError,
    SandboxTimeoutError,
    SandboxResultError,
    SandboxGitError,
)


def test_sandbox_exception_hierarchy():
    """All sandbox exceptions inherit from SandboxClientError."""
    assert issubclass(SandboxUnavailableError, SandboxClientError)
    assert issubclass(SandboxTimeoutError, SandboxClientError)
    assert issubclass(SandboxResultError, SandboxClientError)
    assert issubclass(SandboxGitError, SandboxClientError)


def test_sandbox_unavailable_error_message():
    e = SandboxUnavailableError("Server unreachable")
    assert str(e) == "Server unreachable"
    assert isinstance(e, SandboxClientError)


def test_sandbox_client_requires_sdk():
    """SandboxClient raises when OpenSandbox SDK is not installed."""
    try:
        import opensandbox.sandbox  # noqa: F401
        pytest.skip("OpenSandbox SDK is installed")
    except ImportError:
        pass
    from src.sandbox_client import SandboxClient
    with pytest.raises(SandboxUnavailableError) as exc_info:
        SandboxClient(domain="localhost:8080")
    assert "not installed" in str(exc_info.value) or "Failed" in str(exc_info.value)
