from hil.utils.exception_table import ExceptionTable
import pytest


async def test_exception_table():
    async def raise_exception1():
        raise Exception("Test exception 1")

    async def raise_exception2():
        raise Exception("Test exception 2")

    async def totally_fine():
        return "totally fine"

    with pytest.raises(Exception):
        with ExceptionTable(["thing a", "thing b", "totally fine"]) as table:
            for i in range(10):
                await table.gather_row(
                    raise_exception1(),
                    raise_exception2(),
                    totally_fine(),
                    name=f"{i}",
                )


def test_iter_row_successful():
    traces = ["trace1", "trace2"]
    table = ExceptionTable(["Trace 1", "Trace 2"])

    for ctx, t in table.iter_row("success_row", traces):
        with ctx:
            assert isinstance(t, str)
            assert len(t) > 0

    table.finalize()
    assert table.table.row_count == 1


def test_iter_row_with_failure():
    traces = ["trace1", "trace2", "trace3"]
    table = ExceptionTable(["Trace 1", "Trace 2", "Trace 3"])

    for ctx, t in table.iter_row("failure_row", traces):
        with ctx:
            if t == "trace2":
                raise ValueError("Intentional failure for trace2")
            assert isinstance(t, str)

    with pytest.raises(ValueError):
        table.finalize()

    assert table.table.row_count == 1


def test_iter_row_incomplete():
    traces = ["trace1"]
    table = ExceptionTable(["Trace 1", "Trace 2", "Trace 3"])

    for ctx, t in table.iter_row("incomplete_row", traces):
        with ctx:
            assert isinstance(t, str)

    table.finalize()  # Should log a warning about missing columns
    assert table.table.row_count == 1
