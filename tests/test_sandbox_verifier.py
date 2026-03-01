"""Tests for SandboxVerifier."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.sandbox_verifier import SandboxVerifier


def test_verify_no_commands_returns_passed():
    """When no test/lint/build/security_scan commands are set, verify returns passed=True."""
    verifier = SandboxVerifier(
        test_command=None,
        lint_command=None,
        build_command=None,
        security_scan_command=None,
    )
    sandbox = MagicMock()
    result = asyncio.run(verifier.verify(sandbox))
    assert result["passed"] is True
    assert result["test_results"] is None
    assert result["lint_results"] is None
    assert result["build_results"] is None
    assert result.get("security_scan_results") is None
    assert "No verification" in result["summary"]
    sandbox.commands.run.assert_not_called()


@pytest.fixture
def mock_sandbox_all_exit_zero():
    """Sandbox that returns exit_code=0 for all commands."""
    sandbox = MagicMock()
    async def run(_cmd):
        r = MagicMock()
        r.exit_code = 0
        r.logs.stdout = [MagicMock(text="ok")]
        r.logs.stderr = []
        return r
    sandbox.commands.run = AsyncMock(side_effect=run)
    return sandbox


def test_verify_with_commands_calls_run(mock_sandbox_all_exit_zero):
    """With test_command set, verify runs setup and test and returns passed."""
    verifier = SandboxVerifier(
        test_command="pytest",
        lint_command=None,
        build_command=None,
        security_scan_command=None,
        setup_commands=["pip install -r requirements.txt 2>/dev/null || true"],
    )
    result = asyncio.run(verifier.verify(mock_sandbox_all_exit_zero))
    assert result["passed"] is True
    assert result["test_results"] is not None
    assert result["test_results"]["exit_code"] == 0
    assert result.get("security_scan_results") is None
    assert mock_sandbox_all_exit_zero.commands.run.call_count >= 2  # setup + test
