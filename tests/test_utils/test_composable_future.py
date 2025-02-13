from hil.utils.composable_future import Future, composable


class Demo[T](Future[T]):
    @composable
    def operation1(self, a: int, list_: list) -> "Demo[int]":
        list_.append(a)
        return a

    @composable
    def operation2(self, b: str, list_: list) -> "Demo[str]":
        list_.append(b)
        return b


async def test_composable_future():
    # Build up a query using method chaining
    query = Demo()
    list_ = []
    r2 = await query.operation1(1, list_).operation2("2", list_)
    assert list_ == [1, "2"]
    assert r2 == "2"
