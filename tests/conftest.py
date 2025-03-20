import logging
from typing import Sequence

from hil.drivers.mcp4728 import MCP4728
from hil.utils.config import ConfigDict
import pytest
from hil.drivers.aiosmbus2 import AsyncSMBus, AsyncSMBusBranch, AsyncSMBusPeripheral
from hil.drivers.cell import Cell
from hil.drivers.tca9548a import TCA9548A

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class CellSim:
    """
    Simulates a cell for testing purposes.
    """

    bus: AsyncSMBus
    cells: list[Cell]
    _mux: TCA9548A
    _branch_buses: Sequence[AsyncSMBus]

    @classmethod
    async def create(cls, bus: AsyncSMBus, config: ConfigDict):
        self = cls()
        # Open the bus before creating devices
        async with bus:
            self._mux = TCA9548A(bus)
            self._branch_buses = AsyncSMBusBranch.from_channels(
                bus, self._mux, list(range(0, 8))
            )
            self.cells = [
                await Cell.create(i, bus, config[i])
                for i, bus in enumerate(self._branch_buses)
            ]
        return self


class CellsimV1Hil:
    """
    Simulates a HIL for testing purposes.
    """

    cellsim: CellSim
    physical_bus: AsyncSMBus
    config: ConfigDict

    @classmethod
    async def create(cls, config: ConfigDict):
        self = cls()
        self.config = config
        self.physical_bus = AsyncSMBusPeripheral(1)
        # Open the bus before creating CellSim
        async with self.physical_bus:
            self.cellsim = await CellSim.create(
                self.physical_bus, self.config["cellsim"]
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
async def cellsim_v1_hil(machine_config: ConfigDict):
    # Create HIL instance
    hil = await CellsimV1Hil.create(machine_config)
    # Open bus for the duration of the test session
    async with hil.physical_bus:
        yield hil


class SpaceBMSHiLDevV1:
    bus: AsyncSMBus
    config: ConfigDict
    _mux: TCA9548A
    _branch_buses: Sequence[AsyncSMBus]
    analog_out_4ch: MCP4728

    @classmethod
    async def create(cls, config: ConfigDict):
        self = cls()
        self.config = config
        self.bus = AsyncSMBusPeripheral(1)
        async with self.bus:
            self._mux = TCA9548A(self.bus)
            self._branch_buses = AsyncSMBusBranch.from_channels(
                self.bus, self._mux, list(range(0, 8))
            )
            self.analog_out_4ch = MCP4728(self.bus)
        return self


@pytest.fixture(scope="session")
async def spacebms_hil_dev_v1(machine_config: ConfigDict):
    hil = await SpaceBMSHiLDevV1.create(machine_config)
    async with hil.bus:
        yield hil
