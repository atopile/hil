from hil.utils.exception_table import exception_table
import pytest


async def test_exception_table():
    async def raise_exception1():
        raise Exception("Test exception 1")

    async def raise_exception2():
        raise Exception("Test exception 2")

    async def totally_fine():
        return "totally fine"

    with pytest.raises(ExceptionGroup):
        for i, gather_row in zip(
            range(10), exception_table(["thing a", "thing b", "totally fine"])
        ):
            await gather_row(
                raise_exception1(),
                raise_exception2(),
                totally_fine(),
                name=f"{i}",
            )
