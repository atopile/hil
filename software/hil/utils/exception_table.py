import asyncio
import logging
from typing import Any, Sequence

from rich.console import Console
from rich.table import Table
from rich.text import Text

logger = logging.getLogger(__name__)


class ExceptionTable:
    def __init__(
        self, headers: Sequence[str] | None = None, table: Table | None = None
    ):
        # Setup the table if not provided
        if table is None:
            if headers is None:
                raise ValueError("headers must be provided if table is not provided")
            table = Table(*([""] + list(headers)))
        else:
            if headers is not None:
                logger.warning("headers are ignored if table is provided")
        self.table = table
        self.headers = headers

        self.row_names: list[str] = []
        self.rows: list[Sequence[Any]] = []
        self._finalized = False

    @property
    def finalized(self) -> bool:
        return self._finalized

    def _style(self, obj) -> Text:
        # Shorten long strings and assign a style based on the type of object.
        str_val = str(obj)
        if len(str_val) > 10:
            str_val = str_val[:9] + "."
        if isinstance(obj, Exception):
            return Text(str_val, style="red")
        return Text(str_val, style="green")

    async def gather_row(self, *coro_or_future, name: str):
        """
        Awaits the provided coroutines or futures using asyncio.gather.
        Records the results along with the provided name and returns them.
        """
        if self.finalized:
            raise RuntimeError("Cannot call 'gather' on a finalized ExceptionTable.")

        results = await asyncio.gather(*coro_or_future, return_exceptions=True)
        self.rows.append(results)
        self.row_names.append(name)

        return results

    def finalize(self):
        """
        Finalizes the table: adds each recorded row to the table, prints it,
        and raises a grouped exception if any of the recorded results were Exceptions.
        After calling this method, no further gather operations are allowed.
        """
        if self.finalized:
            raise RuntimeError("Cannot call 'finalize' on a finalized ExceptionTable.")
        self._finalized = True

        for name, row in zip(self.row_names, self.rows):
            self.table.add_row(name, *[self._style(cell) for cell in row])

        # FIXME: better color formatting
        Console(color_system="truecolor").print("\n", self.table)
        exs = [ex for row in self.rows for ex in row if isinstance(ex, Exception)]
        if exs:
            raise ExceptionGroup("Various test exceptions", exs)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.finalize()
