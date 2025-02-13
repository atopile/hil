from hil.drivers.aiosmbus2 import AsyncSMBusPeripheral, AsyncSMBusBranch
from hil.drivers.cell import Cell
from hil.drivers.tca9548a import TCA9548A


async def test_performance():
    physical_bus = AsyncSMBusPeripheral(1)
    mux = TCA9548A(physical_bus)
    branch_buses = AsyncSMBusBranch.from_channels(physical_bus, mux, list(range(0, 8)))
    cells: list[Cell] = [await Cell.create(i, bus) for i, bus in enumerate(branch_buses)]

    async with physical_bus:
        for cell in cells:
            await cell.setup()

        for _ in range(10):
            for cell in cells:
                await cell.enable()
                await cell.set_voltage(1)
                await cell.turn_on_output_relay()
                await cell.turn_on_load_switch()

                await cell.get_voltage()
                await cell.get_current()

                await cell.turn_off_load_switch()
                await cell.turn_off_output_relay()
                await cell.disable()
