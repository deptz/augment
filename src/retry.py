"""
Retry with exponential backoff for transient sandbox/network failures.
"""
import asyncio
import logging
from typing import Callable, Tuple, Type

logger = logging.getLogger(__name__)


def get_transient_exceptions() -> Tuple[Type[Exception], ...]:
    """Return tuple of exception types considered transient (retryable)."""
    try:
        from .sandbox_client import SandboxTimeoutError, SandboxUnavailableError
        return (SandboxTimeoutError, SandboxUnavailableError, ConnectionError, TimeoutError, OSError)
    except ImportError:
        return (ConnectionError, TimeoutError, OSError)


async def retry_with_backoff(
    coro_factory: Callable[[], object],
    max_retries: int = 3,
    initial_backoff: float = 2.0,
    max_backoff: float = 30.0,
    backoff_multiplier: float = 2.0,
    transient_exceptions: Tuple[Type[Exception], ...] = (),
    cancellation_event: object = None,
):
    """
    Retry a coroutine with exponential backoff on transient failures.

    Args:
        coro_factory: Callable that returns a new coroutine each call (e.g. lambda: foo())
        max_retries: Maximum retry attempts (0 = no retries)
        initial_backoff: Initial wait in seconds
        max_backoff: Maximum wait between retries
        backoff_multiplier: Multiplier for backoff each attempt
        transient_exceptions: Exception types to retry (default: from sandbox_client + ConnectionError, TimeoutError)
        cancellation_event: Optional asyncio.Event; if set, abort retries

    Returns:
        Result of the coroutine.

    Raises:
        Last transient exception if all retries fail; re-raises non-transient exceptions immediately.
    """
    if not transient_exceptions:
        transient_exceptions = get_transient_exceptions()

    backoff = initial_backoff
    last_exception = None

    for attempt in range(max_retries + 1):
        if cancellation_event is not None and getattr(cancellation_event, "is_set", lambda: False)():
            raise asyncio.CancelledError("Cancelled during retry")

        try:
            coro = coro_factory()
            return await coro
        except transient_exceptions as e:
            last_exception = e
            if attempt < max_retries:
                logger.warning(
                    "Transient failure (attempt %s/%s), retrying in %.1fs: %s",
                    attempt + 1, max_retries + 1, backoff, e,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * backoff_multiplier, max_backoff)
            else:
                logger.error("All %s attempts failed: %s", max_retries + 1, e)
                raise
        except Exception:
            raise

    raise last_exception  # type: ignore[misc]
