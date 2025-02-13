from hil.drivers.aiosmbus2 import AsyncSMBus, AsyncSMBusBranch, AsyncSMBusPeripheral
from hil.drivers.tca9548a import TCA9548A


async def test_create():
    async with AsyncSMBusPeripheral(0) as bus:
        async with bus() as handle:
            assert handle is not None


async def test_branch():
    async with AsyncSMBus(0) as bus:
        mux = TCA9548A(bus)
        a, b, c = AsyncSMBusBranch.from_channels(bus, mux, [0, 1, 2])
        async with a() as handle:
            assert handle is not None
