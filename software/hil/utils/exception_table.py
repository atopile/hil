import asyncio
from contextlib import contextmanager
import logging
from typing import Any, ContextManager, Generator, Iterable, Sequence

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
        self._finalized = False
        self._exceptions: list[Exception] = []

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

    def add_row(self, name: str, *row: Any):
        self.table.add_row(name, *[self._style(cell) for cell in row])
        self._exceptions.extend([cell for cell in row if isinstance(cell, Exception)])

    async def gather_row(self, *coro_or_future, name: str):
        """
        Awaits the provided coroutines or futures using asyncio.gather.
        Records the results along with the provided name and returns them.
        """
        if self.finalized:
            raise RuntimeError("Cannot call 'gather' on a finalized ExceptionTable.")

        results = await asyncio.gather(*coro_or_future, return_exceptions=True)
        self.add_row(name, *results)

        return results

    def iter_row[T](
        self, name: str, columns: Iterable[T]
    ) -> Generator[tuple[ContextManager, T], None, None]:
        row = []

        @contextmanager
        def _collect():
            try:
                yield
            except Exception as e:
                row.append(e)
            else:
                row.append("Pass")

        try:
            for column in columns:
                yield _collect(), column
        finally:
            missing = len(row) < len(self.table.columns) - 1
            if missing:
                logger.warning("Missing %d column/s for row %s", missing, name)
            self.add_row(name, *row)

    def print_table(self):
        # FIXME: better color formatting
        Console(color_system="256").print("\n", self.table)

    @property
    def exceptions(self) -> list[Exception]:
        return self._exceptions

    def exception_group(self) -> ExceptionGroup | None:
        if self.exceptions:
            return ExceptionGroup("Various test exceptions", self.exceptions)

    def raise_exceptions(self):
        if exg := self.exception_group():
            raise exg

    def finalize(self):
        """
        Finalizes the table: adds each recorded row to the table, prints it,
        and raises a grouped exception if any of the recorded results were Exceptions.
        After calling this method, no further gather operations are allowed.
        """
        if self.finalized:
            raise RuntimeError("Cannot call 'finalize' on a finalized ExceptionTable.")
        self._finalized = True

        self.print_table()

        logger.warning("Raising only the first exception in the table")
        logger.exception(self.exception_group())
        if exs := self.exceptions:
            raise exs[0]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.finalize()
