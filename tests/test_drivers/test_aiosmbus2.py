from hil.drivers.aiosmbus2 import _Opener
import pytest

# async def test_create():
#     async with AsyncSMBusPeripheral(0) as bus:
#         async with bus() as handle:
#             assert handle is not None


# async def test_branch():
#     async with AsyncSMBus(0) as bus:
#         mux = TCA9548A(bus)
#         a, b, c = AsyncSMBusBranch.from_channels(bus, mux, [0, 1, 2])
#         async with a() as handle:
#             assert handle is not None


class Openable:
    def __init__(self):
        self.opened = False

    async def do_open(self):
        self.opened = True
        return self

    async def close(self):
        self.opened = False


@pytest.fixture
def openable():
    return Openable()


async def test_openable_context(openable: Openable):
    assert not openable.opened
    assert not openable.opened

    async with _Opener(openable, openable.do_open) as openable_returned:
        assert openable_returned is openable
        assert openable.opened

    assert not openable.opened


async def test_openable_await(openable: Openable):
    assert not openable.opened
    await openable.do_open()
    assert openable.opened
    await openable.close()
    assert not openable.opened


class FileLikeOpen(Openable):
    def open(self):
        return _Opener(self, self.do_open)


@pytest.fixture
def filelike_openable():
    return FileLikeOpen()


async def test_openable_filelike(filelike_openable: FileLikeOpen):
    assert not filelike_openable.opened

    async with filelike_openable.open() as filelike_openable_returned:
        assert filelike_openable_returned is filelike_openable
        assert filelike_openable.opened

    assert not filelike_openable.opened


async def test_openable_filelike_await(filelike_openable: FileLikeOpen):
    assert not filelike_openable.opened

    await filelike_openable.open()
    assert filelike_openable.opened

    await filelike_openable.close()
    assert not filelike_openable.opened
