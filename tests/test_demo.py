import asyncio
from datetime import datetime

from hil.framework import record, during


async def source_1() -> float:
    await asyncio.sleep(0.1)
    return 1.0


async def source_2() -> float:
    await asyncio.sleep(0.2)
    return 2.0


async def test_demo():
    with record(source_1) as t1, record(source_2) as t2:
        async for _ in during(1).any(t1.new_data, t2.new_data):
            print(f"something's ready! {datetime.now()}")
            if t1.duration_s > 0.5 and t1.get_last(0.5) > 1.0 and t2.duration_s > 0.5 and t2.get_last(0.5) > 1.0:
                break
        else:
            raise TimeoutError("Failed to settle in time")

    print(t1)
    print(t2)
