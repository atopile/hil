import logging
from typing import Sequence

from hil.utils.config import ConfigDict
import pytest
from hil.drivers.aiosmbus2 import AsyncSMBus, AsyncSMBusBranch, AsyncSMBusPeripheral
from hil.drivers.cell import Cell
from hil.drivers.tca9548a import TCA9548A
from hil.drivers.gpio_mux import GpioMux

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class CellSim:
    """
    Simulates a cell for testing purposes.
    """

    bus: AsyncSMBus
    cells: list[Cell]
    _dmm_mux: GpioMux
    _mux: TCA9548A
    _branch_buses: Sequence[AsyncSMBus]

    @classmethod
    async def create(cls, bus: AsyncSMBus, config: ConfigDict):
        self = cls()
        self._mux = TCA9548A(bus)
        self._branch_buses = AsyncSMBusBranch.from_channels(
            bus, self._mux, list(range(0, 8))
        )
        self.cells = [
            await Cell.create(i, bus, config[i])
            for i, bus in enumerate(self._branch_buses)
        ]
        return self


class CellSim16CHV2:
    """
    Simulates a HIL for testing purposes.
    """

    cellsim_1_8: CellSim
    cellsim_9_16: CellSim
    i2c0: AsyncSMBusPeripheral
    i2c1: AsyncSMBusPeripheral
    i2c2: AsyncSMBusPeripheral
    i2c3: AsyncSMBusPeripheral
    config: ConfigDict

    @classmethod
    async def create(cls, config: ConfigDict):
        self = cls()
        self.config = config
        self.i2c0 = AsyncSMBusPeripheral(0)
        self.i2c1 = AsyncSMBusPeripheral(1)
        self.i2c2 = AsyncSMBusPeripheral(2)
        self.i2c3 = AsyncSMBusPeripheral(3)
        # Open the bus before creating CellSim
        async with self.i2c0.open(), self.i2c1.open(), self.i2c2.open(), self.i2c3.open():
            self.cellsim_1_8 = await CellSim.create(
                self.i2c0, self.config["cellsim_1_8"]
            )
            self.cellsim_9_16 = await CellSim.create(
                self.i2c1, self.config["cellsim_9_16"]
            )
        return self

    async def aclose(self):
        for cell in self.cellsim.cells:
            await cell.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.aclose()


@pytest.fixture(scope="session")
async def hil(machine_config: ConfigDict):
    # Create HIL instance
    hil = await Hil.create(machine_config)
    # Open bus for the duration of the test session
    async with hil.physical_bus.open(), hil:
        yield hil
