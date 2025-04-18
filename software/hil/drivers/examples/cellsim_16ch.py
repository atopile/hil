import logging
from typing import List

from hil.utils.config import ConfigDict
from hil.drivers.aiosmbus2 import AsyncSMBus, AsyncSMBusPeripheral
from hil.drivers.cell import Cell
from hil.drivers.blocks.cellsim_8ch import CellSim8Ch

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class CellSim16ChV2:
    """
    Driver for CellSim16ChV2 hardware.
    Connects to two separate CellSim8Ch boards on I2C buses 0 and 1.
    Manages the lifecycle of the I2C buses internally.
    """

    i2c0: AsyncSMBusPeripheral
    i2c1: AsyncSMBusPeripheral
    cellsim_1_8: CellSim8Ch
    cellsim_9_16: CellSim8Ch

    @property
    def cells(self) -> List[Cell]:
        """Returns a combined list of cells from both 8-channel boards."""
        if not hasattr(self, 'cellsim_1_8') or not hasattr(self, 'cellsim_9_16'):
            raise AttributeError("CellSim8Ch instances not created yet.")
        return self.cellsim_1_8.cells + self.cellsim_9_16.cells

    @classmethod
    async def create(cls, config: ConfigDict):
        """
        Creates the CellSim16ChV2 instance, opening I2C buses 0 and 1.

        Args:
            config: Configuration dictionary.
        """
        self = cls()

        # Instantiate and open the specific I2C buses using new names
        self.i2c0 = AsyncSMBusPeripheral(0)
        self.i2c1 = AsyncSMBusPeripheral(1)

        # Use try/except to ensure buses are closed if creation fails
        try:
            await self.i2c0.open()
            await self.i2c1.open()

            # Create the two 8-channel CellSim instances using the opened buses
            self.cellsim_1_8 = await CellSim8Ch.create(
                self.i2c0, config.get("cellsim_1_8", {})
            )
            self.cellsim_9_16 = await CellSim8Ch.create(
                self.i2c1, config.get("cellsim_9_16", {})
            )
        except Exception:
            logger.error("Failed to create CellSim16ChV2, closing buses...")
            # Attempt cleanup even if open failed partially
            if hasattr(self.i2c0, '_smbus') and self.i2c0._smbus is not None:
                 await self.i2c0.close()
            if hasattr(self.i2c1, '_smbus') and self.i2c1._smbus is not None:
                 await self.i2c1.close()
            raise # Re-raise the exception

        return self

    async def aclose(self):
        """Closes the underlying CellSim8Ch instances and the I2C buses."""
        logger.info("Closing CellSim16ChV2...")
        errors = []
        # Close cells first
        try:
            if hasattr(self, 'cellsim_1_8'):
                await self.cellsim_1_8.aclose()
        except Exception as e:
            errors.append(f"Error closing cellsim_1_8: {e}")
        try:
            if hasattr(self, 'cellsim_9_16'):
                await self.cellsim_9_16.aclose()
        except Exception as e:
            errors.append(f"Error closing cellsim_9_16: {e}")

        # Close buses using new names
        try:
            if hasattr(self, 'i2c0'): # Check if i2c0 was assigned
                await self.i2c0.close()
        except Exception as e:
            errors.append(f"Error closing bus 0: {e}")
        try:
            if hasattr(self, 'i2c1'): # Check if i2c1 was assigned
                await self.i2c1.close()
        except Exception as e:
            errors.append(f"Error closing bus 1: {e}")

        if errors:
            logger.error("Errors occurred during CellSim16ChV2 close: %s", "\n".join(errors))
        else:
            logger.info("CellSim16ChV2 closed successfully.")