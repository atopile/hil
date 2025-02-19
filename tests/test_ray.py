import asyncio
import functools
import inspect
import logging
from typing import Callable, Coroutine

import pytest
import ray

logging.basicConfig(level=logging.DEBUG)

if not ray.is_initialized():
    ray.init()


def dist(func: Callable | Coroutine | None = None):
    # TODO: add support for worker requirements

    def wrapperer(func: Callable | Coroutine):
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                @ray.remote
                def _sync(*args, **kwargs):
                    return asyncio.run(func(*args, **kwargs))

                return await _sync.remote(*args, **kwargs)

            return wrapper
        elif callable(func):

            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                return ray.get(ray.remote(func).remote(*args, **kwargs))

            return wrapper
        else:
            raise TypeError(f"Invalid function: {func}")

    if func is None:
        return wrapperer
    else:
        return wrapperer(func)


class Fix:
    def __init__(self, hil):
        self.hil = hil

    async def amethod(self):
        return self.hil

    def __str__(self):
        return f"hil: {self.hil}"


@pytest.fixture
def fix():
    return Fix(1)


@dist
async def test_remote_exec(fix):
    raise TypeError(await fix.amethod())
