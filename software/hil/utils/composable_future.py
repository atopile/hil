"""A utility module that implements a composable Future pattern for asynchronous operations.

This module provides a Future class and composable decorator that allow for building
chains of operations that can be executed asynchronously. It's particularly useful
for scenarios where you want to compose multiple operations and execute them together
in a separate thread.
"""

import asyncio
import collections.abc
import functools
from typing import Awaitable, Callable, Concatenate, ParamSpec, Self
import warnings


class Future[T](collections.abc.Awaitable):
    """A composable Future that allows chaining of operations for asynchronous execution.

    The Future class implements a pattern where operations can be composed/chained
    together and then executed asynchronously in a separate thread. This is useful
    for operations that need to run sequentially but should not block the main
    event loop.

    Type parameter T represents the expected return type of the final operation.

    Example:
        ```python
        future = Future()
        future.operation1().operation2().operation3()
        result = await future  # Executes all operations and returns result of operation3
        ```
    """

    def __init__(self):
        """Initialize an empty Future with no operations."""
        self._operations: list[Callable | Awaitable] = []

    async def execute_returning_all(self) -> tuple:
        """Execute all operations and return their results as a tuple.

        Returns:
            tuple: Results from all operations in the order they were added.
        """

        def _execute():
            return tuple(operation() for operation in self._operations)

        return await asyncio.to_thread(_execute)

    async def execute(self) -> T:
        """Execute all operations and return the result of the last operation.

        This method runs all operations sequentially in a separate thread, but only
        returns the result of the final operation.

        Returns:
            T: The result of the last operation in the chain.
        """

        def _execute():
            for operation in self._operations[:-1]:
                operation()

            if last_op := self._operations[-1:]:
                return last_op[0]()

        return await asyncio.to_thread(_execute)

    def __await__(self):
        """Make the Future awaitable.

        This allows the Future to be used with the await keyword, which will
        automatically execute all operations and return the final result.

        Returns:
            Generator: An awaitable that yields the final result.
        """
        return self.execute().__await__()

    def __del__(self):
        """Delete the Future and warn about any pending operations."""
        if self._operations:
            warnings.warn(
                "Future was deleted with pending operations. This will not execute the operations.",
                stacklevel=2,
            )


P = ParamSpec("P")


def composable[T, S: Self](
    func: Callable[Concatenate[S, P], T],
) -> Callable[Concatenate[S, P], S]:
    """Decorator that makes a method composable within a Future chain.

    This decorator allows methods to be chained together on a Future instance.
    When decorated, the method's execution is deferred until the Future is awaited
    or explicitly executed.

    Args:
        func: The method to make composable.

    Returns:
        callable: A wrapped version of the method that can be chained.

    Example:
        ```python
        class MyFuture[T](Future[T]):
            @composable
            def step1(self) -> "MyFuture[str]":
                return "step1"

            @composable
            def step2(self) -> "MyFuture[str]":
                return "step2"

        future = MyFuture()
        result = await future.step1().step2()  # Executes both steps
        ```

    Note:
        The type of the returns must not be "Self", but rather the type of the class
        with the return type of the method.
    """

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        self._operations.append(lambda: func(self, *args, **kwargs))
        return self

    return wrapper
