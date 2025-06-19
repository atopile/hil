import logging
from typing import Sequence, List

from hil.utils.config import ConfigDict
import pytest
from hil.drivers.aiosmbus2 import AsyncSMBus, AsyncSMBusBranch
from hil.drivers.cell import Cell
from hil.drivers.tca9548a import TCA9548A
from hil.drivers.blocks.gpio_mux import GpioMux

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class CellSim8Ch:
    """
    Driver for CellSim8Ch ato block
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
        # Ensure config keys are integers for proper indexing
        cell_configs = {int(k): v for k, v in config.items()}
        self.cells = [
            await Cell.create(i, bus, cell_configs.get(str(i), {})) # Pass individual cell config
            for i, bus in enumerate(self._branch_buses)
        ]
        return self

    async def aclose(self):
        logger.info(f"Closing CellSim8Ch on bus {self.bus}...") # Improve logging
        errors = []
        for cell in self.cells:
            try:
                await cell.aclose()
            except Exception as e:
                logger.error(f"Error closing cell {cell.cell_num}: {e}")
                errors.append(e)
        # Close other owned resources like _gpio_mux if added
        # try:
        #     if hasattr(self, '_gpio_mux'): await self._gpio_mux.aclose()
        # except Exception as e:
        #     logger.error(f"Error closing GPIO mux: {e}")
        #     errors.append(e)

        if errors:
            logger.warning("Errors occurred during CellSim8Ch close.")
        else:
             logger.info("CellSim8Ch closed successfully.")