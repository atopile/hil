import logging
from typing import List

from hil.utils.config import ConfigDict
from hil.drivers.aiosmbus2 import AsyncSMBus, AsyncSMBusPeripheral
from hil.drivers.cell import Cell
from hil.drivers.blocks.cellsim_8ch import CellSim8Ch
from software.hil.drivers.mcp4728 import MCP4728

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class SpaceBMSHil:
    cellsim: CellSim8Ch
    i2c0: AsyncSMBusPeripheral
    config: ConfigDict

    @classmethod
    async def create(cls, config: ConfigDict):
        self = cls()
        self.config = config
        self.i2c0 = AsyncSMBusPeripheral(0)
        # Open the bus before creating CellSim
        async with self.i2c0.open():
            self.cellsim = await CellSim8Ch.create(
                self.i2c0, self.config["cellsim0_7"]
            )
        return self

    async def aclose(self):
        for cell in self.cellsim.cells:
            await cell.aclose()

    async def __aenter__(self):
        await self.i2c0.open()
        return self
    
    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.aclose()
        await self.i2c0.close()
