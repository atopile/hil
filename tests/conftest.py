import logging
from typing import Sequence

import pytest
from hil.drivers.aiosmbus2 import AsyncSMBus, AsyncSMBusBranch, AsyncSMBusPeripheral
from hil.drivers.cell import Cell
from hil.drivers.tca9548a import TCA9548A

logger = logging.getLogger(__name__)


class CellSim:
    """
    Simulates a cell for testing purposes.
    """

    bus: AsyncSMBus
    cells: list[Cell]
    _mux: TCA9548A
    _branch_buses: Sequence[AsyncSMBus]

    @classmethod
    async def create(cls, bus: AsyncSMBus):
        self = cls()
        # Open the bus before creating devices
        async with bus:
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
    physical_bus: AsyncSMBus

    @classmethod
    async def create(cls):
        self = cls()
        self.physical_bus = AsyncSMBusPeripheral(1)
        # Open the bus before creating CellSim
        async with self.physical_bus:
            self.cellsim = await CellSim.create(self.physical_bus)
        return self

    async def aclose(self):
        for cell in self.cellsim.cells:
            await cell.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.aclose()


@pytest.fixture(scope="session")
async def hil():
    # Create HIL instance
    hil = await Hil.create()
    # Open bus for the duration of the test session
    async with hil.physical_bus:
        yield hil
