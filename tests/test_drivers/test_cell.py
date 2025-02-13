import asyncio
from hil.drivers.aiosmbus2 import AsyncSMBusBranch, AsyncSMBusPeripheral
from hil.drivers.cell import Cell
from hil.drivers.tca9548a import TCA9548A


async def test_performance():
    physical_bus = AsyncSMBusPeripheral(1)
    mux = TCA9548A(physical_bus)
    branch_buses = AsyncSMBusBranch.from_channels(physical_bus, mux, list(range(0, 8)))
    cells: list[Cell] = [
        await Cell.create(i, bus) for i, bus in enumerate(branch_buses)
    ]

    async with physical_bus:
        for cell in cells:
            await cell.setup()
            await cell.set_voltage(1)

        for _ in range(10):
            for cell in cells:
                await cell.enable()
                await cell.turn_on_output_relay()
                await cell.close_load_switch()

            await asyncio.gather(
                *[cell.get_voltage() for cell in cells],
                *[cell.get_current() for cell in cells],
            )

            for cell in cells:
                await cell.open_load_switch()
                await cell.turn_off_output_relay()
                await cell.disable()
