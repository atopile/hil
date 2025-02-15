import asyncio
import collections.abc
from datetime import datetime, timedelta
from typing import Any, AsyncGenerator, AsyncIterator, Awaitable, Self, cast
from collections.abc import Callable
import polars as pl


ZERO_TIMEDELTA = timedelta(0)


def milliseconds(n: float) -> timedelta:
    return timedelta(milliseconds=n)


def microseconds(n: float) -> timedelta:
    return timedelta(microseconds=n)


def seconds(n: float) -> timedelta:
    return timedelta(seconds=n)


async def any_ready(
    *iterators: AsyncIterator, timeout: timedelta | None = None
) -> AsyncGenerator[None, None]:
    """
    `any_ready` must take a series of async iterators, and yield when ANY of them yield.
    It should keep yielding from them until ALL of them have been exhausted, unless
    one raises an exception (other than StopAsyncIteration).
    """
    end_time = datetime.now() + timeout if timeout is not None else None
    # Create an initial task for each async iterator's __anext__ call.
    tasks = {asyncio.create_task(it.__anext__()): it for it in iterators}  # type: ignore
    try:
        # Continue until all iterators are exhausted.
        while tasks:
            # Wait until any of the scheduled tasks completes.
            if end_time is None:
                _timeout = None
            else:
                remaining_time = end_time - datetime.now()
                if remaining_time <= ZERO_TIMEDELTA:
                    return
                _timeout = remaining_time.total_seconds()

            done, _ = await asyncio.wait(
                tasks.keys(),
                return_when=asyncio.FIRST_COMPLETED,
                timeout=_timeout,
            )
            for task in done:
                it = tasks.pop(task)
                try:
                    # Get the result (or handle StopAsyncIteration/other exceptions)
                    task.result()
                except StopAsyncIteration:
                    # This iterator is exhausted, no rescheduling.
                    continue
                except Exception:
                    # If an exception occurs, cancel all pending tasks and re-raise.
                    for pending in tasks:
                        pending.cancel()
                    raise
                else:
                    # Yield as soon as any iterator yields a value.
                    yield None
                    # Re-schedule the iterator for its next value.
                    tasks[asyncio.create_task(it.__anext__())] = it  # type: ignore

    finally:
        for task in tasks:
            task.cancel()


class Trace[T](collections.abc.AsyncIterator):
    TIMESTAMP_COLUMN = "timestamp"

    def __init__(self, name: str, data: pl.DataFrame | None = None):
        self._name = name
        self._data: list[T] = []
        self._timestamps: list[datetime] = []
        self._polars: pl.DataFrame | None = data
        self._closed = False
        self._result_future: asyncio.Future[T] | None = None
        self._schema = pl.Schema(
            {
                self.TIMESTAMP_COLUMN: pl.Datetime(time_unit="ms"),
                self._name: pl.Float64,
            }
        )

    def append(self, timestamp: datetime, data: T) -> None:
        if self._closed:
            raise RuntimeError("Trace is closed")

        self._timestamps.append(timestamp)
        self._data.append(data)

        if self._result_future is not None:
            self._result_future.set_result(data)
            self._result_future = None

    def to_polars(self) -> pl.DataFrame:
        new_df = pl.DataFrame(
            {self.TIMESTAMP_COLUMN: self._timestamps, self._name: self._data},
            schema=self._schema,
        )
        self._timestamps.clear()
        self._data.clear()

        if self._polars is not None:
            self._polars = pl.concat([self._polars, new_df])
        else:
            self._polars = new_df

        return self._polars

    @property
    def name(self) -> str:
        return self._name

    @property
    def value(self) -> pl.Expr:
        return pl.col(self._name)

    @property
    def timestamp(self) -> pl.Expr:
        return pl.col(self.TIMESTAMP_COLUMN)

    @property
    def elapsed_time(self) -> pl.Expr:
        return self.timestamp - self.timestamp.min()

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

    async def __anext__(self) -> T:
        if self._closed:
            raise StopAsyncIteration

        if self._result_future is None:
            self._result_future = asyncio.Future()

        try:
            return await self._result_future
        except asyncio.CancelledError:
            raise StopAsyncIteration

    def close(self) -> None:
        self._closed = True
        if self._result_future is not None:
            self._result_future.cancel()

    def __gt__(self, other: float) -> "Query":
        return Query(self) > other

    def __lt__(self, other: float) -> "Query":
        return Query(self) < other

    def rolling_minimum(self, duration: timedelta) -> "Query":
        return Query(self).rolling_minimum(duration)

    def rolling_maximum(self, duration: timedelta) -> "Query":
        return Query(self).rolling_maximum(duration)

    async def ever(self, expr: pl.Expr, timeout: timedelta = seconds(10)) -> bool:
        return await ever(Query(self, expr), timeout)

    async def always(self, expr: pl.Expr, timeout: timedelta = seconds(10)) -> bool:
        return await always(Query(self, expr), timeout)

    async def approx_once_settled(
        self,
        target: float,
        rel_tol: float = 1e-6,
        abs_tol: float = 1e-12,
        stability_lookback: timedelta = seconds(0.5),
        stability_min_samples: int = 3,
        timeout: timedelta = milliseconds(1000),
    ):
        """
        Monitor the trace. If it reaches a stable value within the permitted time, check that value is within the given tolerance.

        Args:
            target: Target value to check against
            rel_tol: Relative tolerance for the target value
            abs_tol: Absolute tolerance for the target value
            stability_lookback: Lookback period during which the trace value must be within bounds
            stability_min_samples: Minimum number of samples in a valid lookback period
            timeout: Timeout for the trace to reach a settled and correct value
        """

        # TODO: early stopping if stable at wrong value

        return await ever(
            Query(self).rolling_within_tolerance(
                target=target,
                rel_tol=rel_tol,
                abs_tol=abs_tol,
                duration=stability_lookback,
                min_samples=stability_min_samples,
            ),
            timeout,
        )


class record[T]:
    def __init__(
        self,
        source: Callable[[], Awaitable[T]],
        *,
        name: str | None = None,
        min_interval: timedelta | None = None,
    ):
        self._task: asyncio.Task | None = None
        self._source = source
        self._trace = Trace[T](name or source.__qualname__)
        self._min_interval = min_interval
        self._last_timestamp: datetime | None = None

    def __enter__(self) -> Trace[T]:
        self.start()
        return self.trace

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def start(self) -> None:
        async def _trace() -> None:
            try:
                while True:
                    if (
                        self._min_interval is not None
                        and self._last_timestamp is not None
                        and (
                            remaining_time_to_next := max(
                                self._last_timestamp
                                + self._min_interval
                                - datetime.now(),
                                ZERO_TIMEDELTA,
                            )
                        )
                    ):
                        await asyncio.sleep(remaining_time_to_next.total_seconds())
                    elif self._last_timestamp is not None:
                        # after out first sample, yield to other tasks
                        # this is critical to prevent tasks that never yield themselves
                        # from starving the event loop
                        await asyncio.sleep(0)

                    data = await self._source()
                    data = cast(T, data)
                    timestamp = datetime.now()
                    self._trace.append(timestamp, data)
                    self._last_timestamp = timestamp

            finally:
                self._trace.close()

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
    def from_property(
        cls,
        obj: Any,
        prop: property,
        *,
        name: str | None = None,
        min_interval: timedelta | None = None,
    ) -> Self:
        async def func() -> T:
            assert prop.fget is not None
            return prop.fget(obj)

        return cls(
            func,
            name=name or prop.__qualname__,
            min_interval=min_interval,
        )

    @classmethod
    def from_sync_to_thread(
        cls,
        func: Callable[[], T],
        *,
        name: str | None = None,
        min_interval: timedelta | None = None,
    ) -> Self:
        async def async_func() -> T:
            return await asyncio.to_thread(func)

        return cls(
            async_func,
            name=name or func.__qualname__,
            min_interval=min_interval,
        )

    @classmethod
    def from_async_generator(
        cls,
        gen: AsyncGenerator[T, None],
        *,
        name: str | None = None,
        min_interval: timedelta | None = None,
    ) -> Self:
        iterable = aiter(gen)
        return cls(
            lambda: anext(iterable),
            name=name or gen.__qualname__,
            min_interval=min_interval,
        )


Recorder = type[record]


class Query:
    """
    Builds a polars query over values from a trace.
    """

    def __init__(self, trace: Trace, expr: pl.Expr | None = None):
        if expr is None:
            expr = pl.col(trace._name)

        self.trace = trace
        self._expr = expr
        self._timestamp = trace.TIMESTAMP_COLUMN

    def _evaluate(self) -> bool:
        results = self.trace.to_polars().select(self._expr)

        if results.shape[1] > 1:
            raise ValueError("Query returned too many columns")

        if results.dtypes[0] != pl.Boolean:
            raise ValueError("Query returned non-boolean value(s)")

        if results.shape[0] != 1:
            return results.get_column(results.columns[0]).any()

        return bool(results.item())

    def __gt__(self, other: float) -> Self:
        self._expr = self._expr > other
        return self

    def __lt__(self, other: float) -> Self:
        self._expr = self._expr < other
        return self

    def __bool__(self) -> bool:
        return self._evaluate()

    def _after(self, duration: timedelta) -> pl.Expr:
        return self._expr.filter(
            (pl.col(self._timestamp).max() - pl.col(self._timestamp).min()) >= duration
        )

    def rolling_minimum(self, duration: timedelta) -> Self:
        self._expr = (
            (self)
            ._after(duration)
            .rolling_min_by(self._timestamp, window_size=duration, min_samples=2)
        )
        return self

    def rolling_maximum(self, duration: timedelta) -> Self:
        self._expr = (
            (self)
            ._after(duration)
            .rolling_max_by(self._timestamp, window_size=duration, min_samples=2)
        )
        return self

    def rolling_within_tolerance(
        self,
        target: float,
        rel_tol: float,
        abs_tol: float,
        duration: timedelta,
        min_samples: int,
    ) -> Self:
        lower_bound = min(target * (1 - rel_tol), target - abs_tol)
        upper_bound = max(target * (1 + rel_tol), target + abs_tol)

        self._expr = (
            (
                self._expr.rolling_min_by(
                    self._timestamp, window_size=duration, min_samples=min_samples
                )
                > lower_bound
            )
            & (
                self._expr.rolling_max_by(
                    self._timestamp, window_size=duration, min_samples=min_samples
                )
                < upper_bound
            )
        ).filter(
            (pl.col(self._timestamp).max() - pl.col(self._timestamp).min()) >= duration
        )

        return self

    def any(self) -> Self:
        self._expr = self._expr.any()
        return self

    def all(self) -> Self:
        self._expr = self._expr.all()
        return self

    async def ever(self, timeout: timedelta = seconds(10)) -> bool:
        """
        Returns True if the query succeeds at any point
        """
        self._expr = self._expr.any()
        async for _ in any_ready(self.trace, timeout=timeout):
            if self._evaluate():
                return True
        return False

    async def always(self, timeout: timedelta = seconds(10)) -> bool:
        """
        Returns False if the query fails at any point
        """
        self._expr = self._expr.all()
        async for _ in any_ready(self.trace, timeout=timeout):
            if not self._evaluate():
                return False
        return True


async def ever(query: Query, timeout: timedelta = seconds(10)) -> bool:
    return await query.ever(timeout=timeout)


async def always(query: Query, timeout: timedelta = seconds(10)) -> bool:
    return await query.always(timeout=timeout)
