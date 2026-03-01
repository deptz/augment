"""Tests for SandboxGitOps (git operations in sandbox)."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.sandbox_git_ops import SandboxGitOps
from src.sandbox_client import SandboxGitError


@pytest.fixture
def mock_sandbox():
    """Mock sandbox with commands.run returning exit_code and logs."""
    sandbox = MagicMock()
    result = MagicMock()
    result.exit_code = 0
    result.logs.stdout = [MagicMock(text="https://bitbucket.org/ws/repo.git")]
    result.logs.stderr = []
    sandbox.commands.run = AsyncMock(return_value=result)
    return sandbox


def test_add_auth_to_url_no_credentials():
    """URL unchanged when username/password not provided."""
    ops = SandboxGitOps(MagicMock(), "/workspace/repo")
    url = "https://bitbucket.org/ws/repo.git"
    assert ops._add_auth_to_url(url, None, None) == url
    assert ops._add_auth_to_url(url, "u", None) == url
    assert ops._add_auth_to_url(url, None, "p") == url


def test_add_auth_to_url_https_injects_credentials():
    """HTTPS URL gets credentials injected."""
    ops = SandboxGitOps(MagicMock(), "/workspace/repo")
    url = "https://bitbucket.org/ws/repo.git"
    out = ops._add_auth_to_url(url, "user", "pass")
    assert out.startswith("https://")
    assert "user" in out and "pass" in out
    assert "bitbucket.org" in out


def test_sandbox_git_error():
    """SandboxGitError carries message."""
    with pytest.raises(SandboxGitError, match="Unsupported"):
        raise SandboxGitError("Unsupported remote URL: file:///local")
