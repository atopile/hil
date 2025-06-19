import logging
from typing import List

from hil.utils.config import ConfigDict
from hil.drivers.aiosmbus2 import AsyncSMBus, AsyncSMBusPeripheral
from hil.drivers.cell import Cell
from hil.drivers.blocks.cellsim_8ch import CellSim8Ch
from software.hil.drivers.mcp4728 import MCP4728

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class CellSim16ChV2:
    """
    Driver for CellSim16ChV2 hardware.
    Includes two CellSim8Ch boards and two MCP4728 DACs (thermistors).
    Manages the lifecycle of the I2C buses (0, 1, 2, 3) internally.
    """

    # Cell simulator boards
    i2c0: AsyncSMBusPeripheral
    i2c1: AsyncSMBusPeripheral
    cellsim_1_8: CellSim8Ch
    # cellsim_9_16: CellSim8Ch

    # Thermistor DACs
    i2c2: AsyncSMBusPeripheral
    i2c3: AsyncSMBusPeripheral
    thermistors_1_4: MCP4728
    thermistors_5_8: MCP4728

    config: ConfigDict

    @property
    def cells(self) -> List[Cell]:
        """Returns a combined list of cells from both 8-channel boards."""
        if not hasattr(self, 'cellsim_1_8') or not hasattr(self, 'cellsim_9_16'):
            raise AttributeError("CellSim8Ch instances not created yet.")
        return self.cellsim_1_8.cells# + self.cellsim_9_16.cells

    @classmethod
    async def create(cls, config: ConfigDict):
        """
        Creates the CellSim16ChV2 instance, opening I2C buses 0, 1, 2, 3.

        Args:
            config: Configuration dictionary.
        """
        self = cls()
        self.config = config

        # Instantiate peripherals
        self.i2c0 = AsyncSMBusPeripheral(0)
        self.i2c1 = AsyncSMBusPeripheral(1)
        self.i2c2 = AsyncSMBusPeripheral(2)
        self.i2c3 = AsyncSMBusPeripheral(3)

        opened_buses = [] # Keep track of successfully opened buses for cleanup
        try:
            # Open all required buses
            logger.debug("Opening I2C buses...")
            await self.i2c0.open(); opened_buses.append(self.i2c0)
            await self.i2c1.open(); opened_buses.append(self.i2c1)
            await self.i2c2.open(); opened_buses.append(self.i2c2)
            await self.i2c3.open(); opened_buses.append(self.i2c3)
            logger.info("I2C buses 0, 1, 2, 3 opened.")

            # Create CellSim instances
            logger.debug("Creating CellSim8Ch instances...")
            self.cellsim_1_8 = await CellSim8Ch.create(
                self.i2c0, config.get("cellsim_1_8", {})
            )
            # self.cellsim_9_16 = await CellSim8Ch.create(
            #     self.i2c1, config.get("cellsim_9_16", {})
            # )
            logger.info("CellSim8Ch instances created.")

            # Create Thermistor DAC instances
            # Assuming addresses 0x60 on i2c2 and 0x61 on i2c3
            therm_addr_1_4 = int(config.get("thermistor_1_4_addr", "0x60"), 16)
            therm_addr_5_8 = int(config.get("thermistor_5_8_addr", "0x61"), 16)
            logger.debug(f"Creating Thermistor DACs (MCP4728) at {hex(therm_addr_1_4)} on i2c2 and {hex(therm_addr_5_8)} on i2c3...")
            self.thermistors_1_4 = await MCP4728.create(self.i2c2, therm_addr_1_4)
            self.thermistors_5_8 = await MCP4728.create(self.i2c3, therm_addr_5_8)
            logger.info("Thermistor DACs (MCP4728) created.")

        except Exception as e:
            logger.error(f"Failed to create CellSim16ChV2 components: {e}")
            # Attempt cleanup of any buses that were successfully opened
            logger.debug(f"Attempting cleanup after creation failure. Opened buses: {[b._bus_num for b in opened_buses]}")
            for bus in reversed(opened_buses):
                try:
                    await bus.close()
                except Exception as close_e:
                    logger.error(f"Error closing bus {bus._bus_num} during cleanup: {close_e}")
            raise # Re-raise the original exception

        return self

    async def aclose(self):
        """Closes CellSims, Thermistor DACs, and I2C buses."""
        logger.info("Closing CellSim16ChV2...")
        errors = []
        components_to_close = [
            getattr(self, 'cellsim_1_8', None),
            getattr(self, 'cellsim_9_16', None),
            getattr(self, 'thermistors_1_4', None),
            getattr(self, 'thermistors_5_8', None),
        ]
        buses_to_close = [
             getattr(self, 'i2c0', None),
             getattr(self, 'i2c1', None),
             getattr(self, 'i2c2', None),
             getattr(self, 'i2c3', None),
        ]

        # Close components first
        for comp in components_to_close:
            if hasattr(comp, 'aclose'):
                try:
                    await comp.aclose()
                except Exception as e:
                    errors.append(f"Error closing component {type(comp).__name__}: {e}")

        # Close buses
        for bus in buses_to_close:
             if hasattr(bus, 'close'):
                 try:
                     await bus.close()
                 except Exception as e:
                     bus_num = getattr(bus, '_bus_num', '?')
                     errors.append(f"Error closing bus {bus_num}: {e}")

        if errors:
            logger.error("Errors occurred during CellSim16ChV2 close: %s", "\n".join(errors))
        else:
            logger.info("CellSim16ChV2 closed successfully.")
