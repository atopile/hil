import asyncio
import logging
from datetime import datetime
import math
from typing import AsyncGenerator

from hil.framework import any_ready, ever, Recorder, seconds

logger = logging.getLogger(__name__)


async def source_1() -> AsyncGenerator[float, None]:
    values = list(range(1, 10)) + [10] * 10
    for v in values:
        await asyncio.sleep(0.01)
        yield v


async def source_2() -> float:
    await asyncio.sleep(0.02)
    return 2.0


async def test_demo(record: Recorder):
    with record.from_async_generator(source_1()) as t1, record(source_2) as t2:
        async for _ in any_ready(t1, t2, timeout=seconds(1)):
            logger.info(f"something's ready! {datetime.now()}")


async def test_demo_assert_ever(record: Recorder):
    # condition first
    with record.from_async_generator(source_1()) as trace_1:
        assert await ever(
            trace_1.rolling_minimum(seconds(0.05)) > 5, timeout=seconds(1)
        )

    # condition last
    with record.from_async_generator(source_1()) as trace_1:
        assert await (trace_1.rolling_minimum(seconds(0.05)) > 5).ever(seconds(1))

    # direct polars
    with record.from_async_generator(source_1()) as trace_1:
        # test that the measured value is consistently >=5, for at least 0.5s and 2 samples
        assert await trace_1.ever(
            # minimum over 0.5s is >=5
            (
                trace_1.value.rolling_min_by(
                    trace_1.timestamp,
                    window_size=seconds(0.05),
                    min_samples=2,
                )
                >= 5
            )
            # only when we have 0.5s of data
            .filter(trace_1.elapsed_time > 0.05)
            # only need to see it once
            .any(),
            timeout=seconds(1),
        )


async def test_demo_assert_always(record: Recorder):
    with record.from_async_generator(source_1()) as trace_1:
        assert await trace_1.always(
            (trace_1.value > 1.0).filter(trace_1.elapsed_time > 0.05),
            timeout=seconds(1),
        )


async def test_record_approx_once_settled(record: Recorder):
    """
    Test the approx_once_settled usage with an async test function.
    """
    its = 0

    async def decaying_source():
        nonlocal its
        for i in range(100):
            its += 1
            # A rapidly converging value approaching 5
            yield (5 * (1 - math.e**-i))
            await asyncio.sleep(0.001)

    # We'll try using approx_once_settled to see if it reaches near 5 within some tolerance
    with record.from_async_generator(decaying_source()) as rec:
        # Give it a bit of time
        assert await rec.approx_once_settled(
            5, rel_tol=0.1, stability_lookback=seconds(0.05)
        )
