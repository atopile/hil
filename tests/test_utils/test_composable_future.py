import pytest
from hil.utils.composable_future import Future, composable
import gc  # Import the garbage collector module


class Demo[T](Future[T]):
    @composable
    def operation1(self, a: int, list_: list) -> int:
        list_.append(a)
        return a

    @composable
    def operation2(self, b: str, list_: list) -> str:
        list_.append(b)
        return b

    @composable
    def operation_kw(self, *, c: float, list_: list) -> float:
        list_.append(c)
        return c

    @composable
    def operation_raises(self) -> None:
        raise ValueError("Test exception")


async def test_composable_future_await():
    """Test basic chaining and awaiting."""
    query = Demo()
    list_ = []
    r2 = await query.operation1(1, list_).operation2("2", list_)
    assert list_ == [1, "2"]
    assert r2 == "2"
    assert not query._operations  # Operations should be cleared


async def test_composable_future_execute():
    """Test basic chaining and execute()."""
    query = Demo()
    list_ = []
    r2 = await query.operation1(1, list_).operation2("2", list_).execute()
    assert list_ == [1, "2"]
    assert r2 == "2"
    assert not query._operations  # Operations should be cleared


async def test_execute_returning_all():
    """Test execute_returning_all returns all results."""
    query = Demo()
    list_ = []
    results = (
        await query.operation1(1, list_).operation2("2", list_).execute_returning_all()
    )
    assert list_ == [1, "2"]
    assert results == (1, "2")
    assert not query._operations  # Operations should be cleared


async def test_empty_future_execute():
    """Test executing an empty future raises ValueError."""
    query = Demo()
    with pytest.raises(ValueError, match="Cannot execute a Demo with no operations."):
        await query.execute()


async def test_empty_future_await():
    """Test awaiting an empty future raises ValueError."""
    query = Demo()
    with pytest.raises(ValueError, match="Cannot execute a Demo with no operations."):
        await query


async def test_empty_future_execute_returning_all():
    """Test execute_returning_all on an empty future returns an empty tuple."""
    query = Demo()
    results = await query.execute_returning_all()
    assert results == ()
    assert not query._operations


async def test_operation_raises_exception():
    """Test that exceptions in operations are propagated."""
    query = Demo()
    list_ = []
    query.operation1(1, list_).operation_raises().operation2("2", list_)

    with pytest.raises(ValueError, match="Test exception"):
        await query

    # Check if list_ only contains the element from the first operation
    assert list_ == [1]
    # Operations should be cleared even if an exception occurs during execution
    # (as per the current implementation of _execute)
    assert not query._operations


async def test_operation_raises_exception_returning_all():
    """Test that exceptions in operations are propagated during execute_returning_all."""
    query = Demo()
    list_ = []
    query.operation1(1, list_).operation_raises().operation2("2", list_)

    with pytest.raises(ValueError, match="Test exception"):
        await query.execute_returning_all()

    # Check if list_ only contains the element from the first operation
    assert list_ == [1]
    # Operations should be cleared even if an exception occurs
    assert not query._operations


async def test_keyword_arguments():
    """Test composable methods with keyword arguments."""
    query = Demo()
    list_ = []
    result = await query.operation1(1, list_).operation_kw(c=3.0, list_=list_)
    assert list_ == [1, 3.0]
    assert result == 3.0
    assert not query._operations


def test_future_deleted_with_pending_operations_warns():
    """Test that deleting a future with pending operations issues a warning."""
    query = Demo()
    list_ = []
    query.operation1(1, list_)  # Add an operation but don't execute

    with pytest.warns(
        UserWarning,
        match="Future was deleted with pending operations. This will not execute the operations.",
    ):
        del query
        gc.collect()  # Force garbage collection

    # Ensure the operation didn't run
    assert list_ == []
