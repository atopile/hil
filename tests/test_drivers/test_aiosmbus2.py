from hil.drivers.aiosmbus2 import AsyncSMBus, AsyncSMBusBranch
from hil.drivers.tca9548a import TCA9548A


async def test_create():
    async with AsyncSMBus(0) as bus:
        async with bus() as handle:
            assert handle is not None


async def test_branch():
    async with AsyncSMBus(0) as bus:
        mux = TCA9548A(bus)
        branches = AsyncSMBusBranch.from_channels(bus, mux, [0, 1, 2])
        async with branches[0]() as handle:
            assert handle is not None
