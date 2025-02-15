"""
`any` must take a series of async iterators, and yield when ANY of them yield.
It should keep yielding from them until ALL of them have been exhausted, unless
one raises an exception (other than StopAsyncIteration).
"""

import asyncio
from typing import AsyncGenerator, AsyncIterator
import collections.abc
import pytest


async def any_ready(*iterators: AsyncIterator) -> AsyncGenerator[None, None]:
    # Create an initial task for each async iterator's __anext__ call.
    tasks = {asyncio.create_task(it.__anext__()): it for it in iterators}
    try:
        # Continue until all iterators are exhausted.
        while tasks:
            # Wait until any of the scheduled tasks completes.
            done, _ = await asyncio.wait(
                tasks.keys(), return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                it = tasks.pop(task)
                try:
                    # Get the result (or handle StopAsyncIteration/other exceptions)
                    task.result()
                except StopAsyncIteration:
                    # This iterator is exhausted, no rescheduling.
                    continue
                except Exception:
                    # If an exception occurs, cancel all pending tasks and re-raise.
                    for pending in tasks:
                        pending.cancel()
                    raise
                else:
                    # Yield as soon as any iterator yields a value.
                    yield None
                    # Re-schedule the iterator for its next value.
                    tasks[asyncio.create_task(it.__anext__())] = it

    finally:
        for task in tasks:
            task.cancel()


class async_iter(collections.abc.AsyncIterator):
    def __init__(self, values: list[float]):
        self.values = values
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.values):
            raise StopAsyncIteration
        v = self.values[self.index]
        self.index += 1
        await asyncio.sleep(v / 1000)
        return v


async def test_any_basic():
    """Test that any_ready yields in the correct order based on timing."""
    results = []
    async for _ in any_ready(
        async_iter([3, 6]),  # yields at 3ms, 9ms
        async_iter([1, 2]),  # yields at 1ms, 3ms
        async_iter([2, 5]),  # yields at 2ms, 7ms
    ):
        results.append(len(results))

    # We expect 6 yields total, in the order determined by sleep times
    assert len(results) == 6
    assert results == [0, 1, 2, 3, 4, 5]


async def test_any_empty():
    """Test that any_ready works with no iterators."""
    results = []
    async for _ in any_ready():
        results.append(True)
    assert len(results) == 0


async def test_any_single():
    """Test that any_ready works with a single iterator."""
    results = []
    async for _ in any_ready(async_iter([1, 2, 3])):
        results.append(len(results))
    assert len(results) == 3


async def test_any_error_handling():
    """Test that any_ready properly handles errors."""

    class ErrorIterator(collections.abc.AsyncIterator):
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise ValueError("Test error")

    with pytest.raises(ValueError, match="Test error"):
        async for _ in any_ready(
            async_iter([1, 2, 3]), ErrorIterator(), async_iter([4, 5, 6])
        ):
            pass


async def test_any_early_stop():
    """Test that any_ready can be broken out of early."""
    results = []
    async for _ in any_ready(
        async_iter([1, 2, 3, 4, 5]),
        async_iter([2, 3, 4, 5, 6]),
    ):
        results.append(len(results))
        if len(results) >= 3:
            break

    assert len(results) == 3
