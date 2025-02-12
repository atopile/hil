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
        async for _ in during(3.0).any(t1.new_data, t2.new_data):
            print(f"something's ready! {datetime.now()}")

    print(t1.trace)
    print(t2.trace)
