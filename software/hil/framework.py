import asyncio
from datetime import datetime, timedelta
import inspect
from typing import Any, AsyncGenerator, Awaitable, Self, cast
from collections.abc import Callable
import polars as pl


def milliseconds(n: float) -> timedelta:
    return timedelta(milliseconds=n)


def microseconds(n: float) -> timedelta:
    return timedelta(microseconds=n)


def seconds(n: float) -> timedelta:
    return timedelta(seconds=n)


class during:
    def __init__(self, duration: timedelta):
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
        return self.started and self.remaining <= timedelta(0)

    @property
    def elapsed(self) -> timedelta:
        if self.start_time is None:
            return timedelta(0)

        return datetime.now() - self.start_time

    @property
    def remaining(self) -> timedelta:
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
                timeout=self.remaining.total_seconds(),
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
        self._schema = pl.Schema(
            {
                self.TIMESTAMP_COLUMN: pl.Datetime(time_unit="ms"),
                self._name: pl.Float64,
            }
        )

    def append(self, timestamp: datetime, data: T) -> None:
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

    @inspect.markcoroutinefunction
    def new_data(self) -> asyncio.Future[T]:
        if self._result_future is None:
            self._result_future = asyncio.Future()
        return self._result_future

    async def __anext__(self) -> T:
        return await self.new_data()

    def __gt__(self, other: float) -> "Query":
        return Query(self) > other

    def __lt__(self, other: float) -> "Query":
        return Query(self) < other

    def rolling_minimum(self, duration: timedelta) -> "Query":
        return Query(self).rolling_minimum(duration)

    def rolling_maximum(self, duration: timedelta) -> "Query":
        return Query(self).rolling_maximum(duration)

    async def ever(
        self, expr: pl.Expr, timeout: timedelta = seconds(10)
    ) -> Awaitable[bool]:
        return ever(Query(self, expr), timeout)

    async def always(
        self, expr: pl.Expr, timeout: timedelta = seconds(10)
    ) -> Awaitable[bool]:
        return always(Query(self, expr), timeout)

    async def approx_once_settled(
        self,
        target: float,
        rel_tol: float = 1e-6,
        abs_tol: float = 1e-12,
        stability_lookback: timedelta = seconds(0.5),
        stability_min_samples: int = 10,
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
        ).filter(self.trace.elapsed_time >= duration)

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

        async for _ in during(timeout).any(self.trace.new_data):
            if self._evaluate():
                return True

        return False

    async def always(self, timeout: timedelta = seconds(10)) -> bool:
        """
        Returns False if the query fails at any point
        """
        self._expr = self._expr.all()

        try:
            async for _ in during(timeout).any(self.trace.new_data):
                if not self._evaluate():
                    return False
        except TimeoutError:
            pass

        return True


async def ever(query: Query, timeout: timedelta = seconds(10)) -> bool:
    return await query.ever(timeout=timeout)


async def always(query: Query, timeout: timedelta = seconds(10)) -> bool:
    return await query.always(timeout=timeout)
