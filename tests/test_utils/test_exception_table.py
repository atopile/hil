from hil.utils.exception_table import ExceptionTable
import pytest


async def test_exception_table():
    async def raise_exception1():
        raise Exception("Test exception 1")

    async def raise_exception2():
        raise Exception("Test exception 2")

    async def totally_fine():
        return "totally fine"

    with pytest.raises(ExceptionGroup):
        with ExceptionTable(["thing a", "thing b", "totally fine"]) as table:
            for i in range(10):
                await table.gather_row(
                    raise_exception1(),
                    raise_exception2(),
                    totally_fine(),
                    name=f"{i}",
                )
