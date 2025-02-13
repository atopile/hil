# import asyncio
# from datetime import datetime

# from hil.framework import record


# async def source_1() -> float:
#     await asyncio.sleep(0.1)
#     return 1.0


# async def source_2() -> float:
#     await asyncio.sleep(0.2)
#     return 2.0


# async def test_record_vanilla():
#     with record(source_1) as t1:
#         async for _ in t1:
#             print(f"something's ready! {datetime.now()}")
