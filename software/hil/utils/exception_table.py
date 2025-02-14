import asyncio
from typing import Any, Sequence

from rich.table import Table
from rich.text import Text
from rich.console import Console


def exception_table(
    headers: Sequence[str], table: Table | None = None, max_rows: int = 100
):
    if table is None:
        table = Table(*([""] + headers))

    row_names: list[str] = []
    rows: list[Sequence[Any]] = []

    def _style(obj) -> Text:
        str_ = str(obj)
        if len(str_) > 10:
            str_ = str_[:9] + "."

        if isinstance(obj, Exception):
            return Text(str_, style="red")
        return Text(str_, style="green")

    async def _gather(*coro_or_future, name: str):
        results = await asyncio.gather(*coro_or_future, return_exceptions=True)
        rows.append(results)
        row_names.append(name)
        return results

    try:
        for _ in range(max_rows):
            yield _gather
        else:
            raise Exception(
                "More than max_rows. You might want to increase it,"
                " or maybe you're accidentally looping forever."
            )
    finally:
        for name, row in zip(row_names, rows):
            table.add_row(name, *(_style(cell) for cell in row))

        Console(color_system="truecolor").print("\n", table)

        if exs := [ex for row in rows for ex in row if isinstance(ex, Exception)]:
            raise ExceptionGroup("Various test exceptions", exs)
