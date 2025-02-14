import asyncio
import math
import time
from datetime import datetime
from hil.framework import ZERO_TIMEDELTA, record, seconds
import pytest


async def test_record_sync_source():
    """
    Test that recording from a synchronous source collects data properly.
    """
    start_time = datetime.now()

    def sync_source():
        # Returns the elapsed seconds since start.
        return (datetime.now() - start_time).total_seconds()

    with record.from_sync_to_thread(sync_source) as rec:
        # Let it record for a bit.
        await asyncio.sleep(0.05)

    df = rec.to_polars()
    recorded_data = df.select(rec.name).to_series().to_list()

    print(df)  # for debugging

    # We should have some data recorded
    assert len(recorded_data) > 0, "Expected at least some data from the sync source"


async def test_record_async_source():
    """
    Test that recording from an async source also collects data properly.
    """

    async def async_source():
        # Just returns a count that increments every time
        await asyncio.sleep(0.01)
        return time.time()

    with record(async_source) as rec:
        await asyncio.sleep(0.05)

    df = rec.to_polars()
    recorded_data = df.select(rec.name).to_series().to_list()

    print(df)  # for debugging

    assert len(recorded_data) > 0, "Expected at least some data from the async source"


async def test_record_minimum_interval():
    """
    Verify that the record function enforces the minimum_interval if specified.
    """
    calls = 0

    def syncing_source():
        nonlocal calls
        calls += 1
        return calls

    with record.from_sync_to_thread(syncing_source, min_interval=seconds(0.05)) as rec:
        # Run for 0.2 seconds
        await asyncio.sleep(0.2)

    df = rec.to_polars()
    recorded_data = df.select(rec.name).to_series().to_list()

    print(df)  # for debugging

    # If minimum_interval=0.05, we expect around 4 or so calls in 0.2s (possibly 3-5).
    # We just ensure it's not too large, proving the interval was respected.
    assert len(recorded_data) < 10, f"Expected fewer calls, got: {len(recorded_data)}"


async def test_record_stop():
    """
    Ensure that the record can be stopped (cancel the background task) and that no new data is appended afterward.
    """
    counter = 0

    def source():
        nonlocal counter
        counter += 1
        return counter

    with record.from_sync_to_thread(source) as rec:
        # Let it record a bit
        await asyncio.sleep(0.05)

    count_before = len(rec.to_polars().select(rec.name).to_series().to_list())

    # The record context is now closed, wait again
    await asyncio.sleep(0.05)
    count_after = len(rec.to_polars().select(rec.name).to_series().to_list())

    # Confirm the count didn't change, meaning no new data after stopping
    assert count_after == count_before, (
        "Data should not be added after stopping the recorder"
    )


async def test_record_async_generator():
    """
    Test the async generator usage with an async test function.
    Also tests that the record can be stopped by their data running out.
    """

    async def source():
        for i in range(10):
            yield i

    # We'll try using approx_once_settled to see if it reaches near 5 within some tolerance
    with record.from_async_generator(source()) as trace:
        for i in range(10):
            assert await anext(trace) == i
        else:
            # The record should be closed now
            with pytest.raises(RuntimeError):
                await trace.new_data()

            # The record should be closed now
            try:
                await anext(trace)
            except StopAsyncIteration:
                pass
            else:
                pytest.fail("Expected StopAsyncIteration")

    assert len(trace.to_polars().select(trace.name).to_series().to_list()) == 10


# FIXME: failing decay test
async def test_record_approx_once_settled():
    """
    Test the approx_once_settled usage with an async test function.
    """

    async def decaying_source():
        for i in range(1000):
            # A rapidly converging value approaching 5
            yield (5 * (1 - math.e**-i))

    # We'll try using approx_once_settled to see if it reaches near 5 within some tolerance
    with record.from_async_generator(decaying_source()) as rec:
        # Give it a bit of time
        assert await rec.approx_once_settled(
            0.2, rel_tol=0.1, stability_lookback=ZERO_TIMEDELTA, timeout=seconds(3)
        )
