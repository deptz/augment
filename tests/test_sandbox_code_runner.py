"""Tests for SandboxCodeRunner."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.sandbox_code_runner import SandboxCodeRunner
from src.sandbox_client import SandboxClient, SandboxResultError


def test_build_env_includes_workspace_and_llm_keys():
    """_build_env sets OPENCODE_WORKSPACE and forwards LLM keys from llm_config."""
    client = MagicMock(spec=SandboxClient)
    runner = SandboxCodeRunner(client, llm_config={"openai_api_key": "sk-test", "provider": "openai"})
    env = runner._build_env()
    assert env["OPENCODE_WORKSPACE"] == "/workspace/repo"
    assert env.get("OPENAI_API_KEY") == "sk-test"
    assert env.get("LLM_PROVIDER") == "openai"


def test_build_env_filters_empty_values():
    """_build_env does not include keys with empty values."""
    client = MagicMock(spec=SandboxClient)
    runner = SandboxCodeRunner(client, llm_config={})
    env = runner._build_env()
    assert "OPENCODE_WORKSPACE" in env
    assert "PYTHON_VERSION" in env
    for k, v in env.items():
        assert v, f"Expected non-empty value for {k}"


def test_extract_json_returns_raw_when_starts_with_brace():
    """_extract_json returns content as-is when it starts with { or [."""
    client = MagicMock(spec=SandboxClient)
    runner = SandboxCodeRunner(client)
    assert runner._extract_json('{"a": 1}') == '{"a": 1}'
    assert runner._extract_json('[1, 2]') == '[1, 2]'


def test_extract_json_extracts_from_markdown_code_block():
    """_extract_json extracts JSON from ```json ... ``` block."""
    client = MagicMock(spec=SandboxClient)
    runner = SandboxCodeRunner(client)
    content = 'Some text\n```json\n{"plan": true}\n```'
    assert runner._extract_json(content) == '{"plan": true}'


def test_check_cancelled_raises_when_event_set():
    """_check_cancelled raises CancelledError when event is set."""
    client = MagicMock(spec=SandboxClient)
    runner = SandboxCodeRunner(client)
    ev = MagicMock()
    ev.is_set = lambda: True
    try:
        runner._check_cancelled(ev)
        assert False, "Expected CancelledError"
    except asyncio.CancelledError:
        pass


def test_check_cancelled_no_op_when_event_not_set():
    """_check_cancelled does nothing when event is None or not set."""
    client = MagicMock(spec=SandboxClient)
    runner = SandboxCodeRunner(client)
    runner._check_cancelled(None)
    ev = MagicMock()
    ev.is_set = lambda: False
    runner._check_cancelled(ev)


def test_read_result_raises_when_file_missing():
    """_read_result raises SandboxResultError when read_file fails."""
    client = MagicMock(spec=SandboxClient)
    runner = SandboxCodeRunner(client)
    sandbox = MagicMock()
    sandbox.files.read_file = AsyncMock(side_effect=FileNotFoundError("no file"))
    try:
        asyncio.run(runner._read_result(sandbox, "/workspace/repo"))
        assert False, "Expected SandboxResultError"
    except SandboxResultError as e:
        assert "result.json" in str(e) or "did not produce" in str(e)


def test_read_result_returns_parsed_json():
    """_read_result parses JSON and returns dict."""
    client = MagicMock(spec=SandboxClient)
    runner = SandboxCodeRunner(client)
    sandbox = MagicMock()
    sandbox.files.read_file = AsyncMock(return_value='{"summary": "ok", "plan": {}}')
    result = asyncio.run(runner._read_result(sandbox, "/workspace/repo"))
    assert result == {"summary": "ok", "plan": {}}


def test_read_result_extracts_json_from_markdown():
    """_read_result extracts and parses JSON from markdown-wrapped content."""
    client = MagicMock(spec=SandboxClient)
    runner = SandboxCodeRunner(client)
    sandbox = MagicMock()
    sandbox.files.read_file = AsyncMock(return_value='Output:\n```json\n{"x": 1}\n```')
    result = asyncio.run(runner._read_result(sandbox, "/workspace/repo"))
    assert result == {"x": 1}
