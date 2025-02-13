import asyncio
from datetime import datetime, timedelta
import inspect
from typing import Any, AsyncGenerator, Awaitable, Self, cast
from collections.abc import Callable
import numpy as np
import polars as pl


class during:
    def __init__(self, duration: float):
        self.duration = duration
        self.start_time = None

    def start(self) -> Self:
        self.start_time = datetime.now()
        return self

    async def __aiter__(self):
        if not self.started:
            self.start()

        while not self.finished:
            yield
            # yield to other tasks
            await asyncio.sleep(0)

    @property
    def started(self) -> bool:
        return self.start_time is not None

    @property
    def finished(self) -> bool:
        return self.started and self.remaining <= 0

    @property
    def elapsed(self) -> float:
        if self.start_time is None:
            return 0

        return (datetime.now() - self.start_time).total_seconds()

    @property
    def remaining(self) -> float:
        return self.duration - self.elapsed

    async def any(
        self, *others: Callable[[], Awaitable] | AsyncGenerator[Any, None]
    ) -> AsyncGenerator[None, None]:
        def _make_awaitable(
            other: Callable[[], Awaitable] | AsyncGenerator[Any, None],
        ) -> Awaitable[Any]:
            if inspect.iscoroutinefunction(other):
                return other()
            elif inspect.isasyncgenfunction(other):
                return cast(Awaitable[Any], other())
            else:
                raise ValueError(f"Invalid argument: {other}")

        async for _ in self:
            await asyncio.wait(
                [_make_awaitable(other) for other in others],  # type: ignore
                timeout=self.remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            yield


class Trace[T]:
    TIMESTAMP_COLUMN = "timestamp"

    def __init__(self, name: str, data: pl.DataFrame | None = None):
        self._name = name
        self._data: list[T] = []
        self._timestamps: list[datetime] = []
        self._polars: pl.DataFrame | None = data
        self._result_future: asyncio.Future[T] | None = None

    def append(self, timestamp: datetime, data: T) -> None:
        self._timestamps.append(timestamp)
        self._data.append(data)

        if self._result_future is not None:
            self._result_future.set_result(data)
            self._result_future = None

    def to_polars(self) -> pl.DataFrame:
        new_df = pl.DataFrame(
            {self.TIMESTAMP_COLUMN: self._timestamps, self._name: self._data}
        )
        self._timestamps.clear()
        self._data.clear()

        if self._polars is not None:
            self._polars.extend(new_df)
        else:
            self._polars = new_df

        return self._polars

    def derive(self, data: pl.DataFrame) -> Self:
        return self.__class__(self._name, data)

    def get_last(
        self, duration: float | int | timedelta, from_: datetime | None = None
    ) -> Self:
        """Get the last <duration> of data from the trace"""
        if isinstance(duration, (int, float)):
            duration = timedelta(seconds=duration)

        if from_ is None:
            from_ = datetime.now() - duration

        return self.derive(
            self.to_polars()
            .sort(self.TIMESTAMP_COLUMN)
            .filter(pl.col(self.TIMESTAMP_COLUMN) >= from_)
        )

    @property
    def timestamps(self) -> pl.Series:
        return self.to_polars().get_column(self.TIMESTAMP_COLUMN)

    @property
    def data(self) -> pl.Series:
        return self.to_polars().get_column(self._name)

    @property
    def duration(self) -> timedelta:
        max_timestamp = cast(datetime, self.timestamps.max())
        min_timestamp = cast(datetime, self.timestamps.min())
        return max_timestamp - min_timestamp

    @property
    def duration_s(self) -> float:
        return self.duration.total_seconds()

    def new_data(self) -> asyncio.Future[T]:
        if self._result_future is None:
            self._result_future = asyncio.Future()
        return self._result_future

    async def __anext__(self) -> T:
        return await self.new_data()

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, datetime):
            return self.get_last()
        return np.all(self.duration > other)

    def __ge__(self, other: Any) -> bool:
        return self.duration >= other

    def __lt__(self, other: Any) -> bool:
        return self.duration < other


class record[T]:
    def __init__(
        self,
        source: Callable[[], Awaitable[T]] | Callable[[], T],
        *,
        name: str | None = None,
        minimum_interval: float | None = None,
    ):
        self._task: asyncio.Task | None = None

        # Check if the source is a synchronous function
        # or an asynchronous function
        if inspect.iscoroutinefunction(source):
            self._source = source
        else:
            self._source = lambda: asyncio.to_thread(source)

        self._trace = Trace[T](name or source.__name__)
        self._minimum_interval = (
            timedelta(seconds=minimum_interval)
            if minimum_interval is not None
            else None
        )
        self._last_timestamp: datetime | None = None

    def __enter__(self) -> Trace[T]:
        self.start()
        return self.trace

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def start(self) -> None:
        async def _trace() -> None:
            while True:
                if (
                    self._minimum_interval is not None
                    and self._last_timestamp is not None
                ):
                    remaining_time_to_next = (
                        self._last_timestamp + self._minimum_interval - datetime.now()
                    )
                    if remaining_time_to_next > timedelta(0):
                        await asyncio.sleep(remaining_time_to_next.total_seconds())

                data = await self._source()
                data = cast(T, data)
                self._trace.append(datetime.now(), data)

        self._task = asyncio.create_task(_trace())

    def close(self) -> None:
        if self._task is not None:
            self._task.cancel()

    @property
    def trace(self) -> Trace[T]:
        return self._trace

    @property
    def started(self) -> bool:
        return self._task is not None

    @property
    def finished(self) -> bool:
        if self._task is None:
            return False

        return self._task.done()

    @property
    def running(self) -> bool:
        return self.started and not self.finished

    @classmethod
    def from_property(cls, obj: Any, prop: property) -> Self:
        def func() -> T:
            assert prop.fget is not None
            return prop.fget(obj)

        return cls(func)

    async def __anext__(self) -> T:
        if not self.started:
            raise RuntimeError("Recording not started")

        if self.finished:
            raise StopAsyncIteration

        return await self.trace.new_data()
