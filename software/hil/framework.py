import asyncio
from datetime import datetime
import inspect
from typing import AsyncGenerator, Awaitable, Callable, Self
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
        return (datetime.now() - self.start_time).total_seconds()

    @property
    def remaining(self) -> float:
        return self.duration - self.elapsed

    async def any(self, *others: Callable[[], Awaitable]) -> AsyncGenerator[None, None]:
        async for _ in self:
            await asyncio.wait(
                [other() for other in others],
                timeout=self.remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            yield


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

        self._data: list[T] = []
        self._timestamps: list[datetime] = []
        self._trace: pl.DataFrame | None = None
        self._name = name or source.__name__
        self._result_future: asyncio.Future[T] | None = None
        self._minimum_interval = minimum_interval

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def start(self) -> None:
        async def _trace() -> None:
            while True:
                if self._minimum_interval is not None and self._timestamps:
                    last_timestamp = self._timestamps[-1]
                    remaining_time_to_next = (
                        last_timestamp + self._minimum_interval - datetime.now()
                    )
                    if remaining_time_to_next > 0:
                        await asyncio.sleep(remaining_time_to_next)

                data = await self._source()
                self._data.append(data)
                self._timestamps.append(datetime.now())
                if self._result_future is not None:
                    self._result_future.set_result(data)
                    self._result_future = None

        self._task = asyncio.create_task(_trace())

    def close(self) -> None:
        self._task.cancel()

    @property
    def trace(self) -> pl.DataFrame:
        new_df = pl.DataFrame({"timestamp": self._timestamps, self._name: self._data})
        self._timestamps.clear()
        self._data.clear()
        if self._trace is not None:
            self._trace.extend(new_df)
        else:
            self._trace = new_df
        return self._trace

    @property
    def started(self) -> bool:
        return self._task is not None

    @property
    def finished(self) -> bool:
        return self.started and self._task.done()

    @property
    def running(self) -> bool:
        return self.started and not self.finished

    def new_data(self) -> asyncio.Future[T]:
        if not self.running:
            raise RuntimeError("Recording not running")

        if self._result_future is None:
            self._result_future = asyncio.Future()
        return self._result_future

    async def __anext__(self) -> T:
        if not self.started:
            raise RuntimeError("Recording not started")

        if self.finished:
            raise StopAsyncIteration

        return await self.new_data
