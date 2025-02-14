import asyncio
from datetime import datetime

from hil.framework import ever, record, during, seconds


async def source_1() -> float:
    await asyncio.sleep(0.1)
    return 1.0


async def source_2() -> float:
    await asyncio.sleep(0.2)
    return 2.0


async def test_demo(record: type[record]):
    with record(source_1) as t1, record(source_2) as t2:
        async for _ in during(seconds(1)).any(t1.new_data, t2.new_data):
            print(f"something's ready! {datetime.now()}")


async def test_demo_assert_ever():
    # condition first
    with record(source_1) as trace_1:
        assert await ever(
            trace_1.rolling_minimum(seconds(0.5)) > 5, timeout=seconds(10)
        )

    # condition last
    with record(source_1) as trace_1:
        assert await (trace_1.rolling_minimum(seconds(0.5)) > 5).ever(seconds(10))

    # direct polars
    with record(source_1) as trace_1:
        # test that the measured value is consistently >=5, for at least 0.5s and 2 samples
        assert await trace_1.ever(
            # minimum over 0.5s is >=5
            (
                trace_1.value.rolling_min_by(
                    trace_1.timestamp,
                    window_size=seconds(0.5),
                    min_samples=2,
                )
                >= 5
            )
            # only when we have 0.5s of data
            .where(trace_1.elapsed_time > 0.5)
            # only need to see it once
            .any(),
            timeout=seconds(10),
        )


async def test_demo_assert_always():
    with record(source_1) as trace_1:
        assert await trace_1.always(
            (trace_1.value > 1.0).where(trace_1.elapsed_time > 0.5), timeout=seconds(10)
        )
