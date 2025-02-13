import asyncio

import pytest_asyncio
from hil.drivers.aiosmbus2 import AsyncSMBus, AsyncSMBusBranch, AsyncSMBusPeripheral
from hil.drivers.cell import Cell
from hil.drivers.tca9548a import TCA9548A


class CellSim:
    """
    Simulates a cell for testing purposes.
    """

    bus: AsyncSMBus
    cells: list[Cell]
    _mux: TCA9548A
    _branch_buses: AsyncSMBusBranch

    @classmethod
    async def create(cls, bus: AsyncSMBus):
        self = cls()
        self._mux = TCA9548A(bus)
        self._branch_buses = AsyncSMBusBranch.from_channels(
            bus, self._mux, list(range(0, 8))
        )
        self.cells = [
            await Cell.create(i, bus) for i, bus in enumerate(self._branch_buses)
        ]
        return self


class Hil:
    """
    Simulates a HIL for testing purposes.
    """

    cellsim: CellSim

    async def create(cls):
        self = cls()
        physical_bus = AsyncSMBusPeripheral(1)
        self.cellsim = CellSim(physical_bus)
        return self


@pytest_asyncio.fixture(loop_scope="session")
async def hil():
    hil = await Hil.create()
    async with hil.physical_bus:
        yield hil


async def test_performance(hil: Hil):
    for cell in hil.cellsim.cells:
        await cell.setup()
        await cell.set_voltage(1)

    for _ in range(10):
        for cell in hil.cellsim.cells:
            await cell.enable()
            await cell.turn_on_output_relay()
            await cell.close_load_switch()

        await asyncio.gather(
            *[cell.get_voltage() for cell in hil.cellsim.cells],
            *[cell.get_current() for cell in hil.cellsim.cells],
        )

        for cell in hil.cellsim.cells:
            await cell.open_load_switch()
            await cell.turn_off_output_relay()
            await cell.disable()
