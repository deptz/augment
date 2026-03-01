"""Tests for retry_with_backoff."""
import asyncio
import pytest
from src.retry import retry_with_backoff, get_transient_exceptions


def test_retry_succeeds_first_try():
    """First attempt success returns immediately."""
    calls = []
    async def ok():
        calls.append(1)
        return 42
    out = asyncio.run(retry_with_backoff(lambda: ok(), max_retries=2))
    assert out == 42
    assert len(calls) == 1


def test_retry_retries_on_transient():
    """Retries on transient exception and then succeeds."""
    calls = []
    async def flaky():
        calls.append(1)
        if len(calls) < 2:
            raise ConnectionError("transient")
        return 43
    out = asyncio.run(retry_with_backoff(
        lambda: flaky(),
        max_retries=3,
        initial_backoff=0.01,
        transient_exceptions=(ConnectionError,),
    ))
    assert out == 43
    assert len(calls) == 2


def test_retry_raises_after_max_retries():
    """Raises last exception after all retries exhausted."""
    async def always_fail():
        raise TimeoutError("always")
    with pytest.raises(TimeoutError, match="always"):
        asyncio.run(retry_with_backoff(
            lambda: always_fail(),
            max_retries=2,
            initial_backoff=0.01,
            transient_exceptions=(TimeoutError,),
        ))


def test_get_transient_exceptions():
    """Returns a tuple of exception types."""
    t = get_transient_exceptions()
    assert isinstance(t, tuple)
    assert ConnectionError in t
    assert TimeoutError in t
