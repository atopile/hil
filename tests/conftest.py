import logging
from typing import Sequence, List

from hil.utils.config import ConfigDict
import pytest
from hil.drivers.aiosmbus2 import AsyncSMBus, AsyncSMBusBranch, AsyncSMBusPeripheral
from hil.drivers.cell import Cell
from hil.drivers.tca9548a import TCA9548A
from hil.drivers.blocks.gpio_mux import GpioMux
from software.hil.drivers.examples.cellsim_16ch import CellSim16ChV2

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


@pytest.fixture(scope="session")
async def hil(machine_config: ConfigDict):
    """Provides an initialized HIL driver instance (CellSim16ChV2 from examples)."""
    logger.info("Creating HIL driver instance (CellSim16ChV2 from examples)...")
    # Instantiate the actual driver using its create method
    # The driver now manages its own i2c0/i2c1 lifecycle
    driver_instance = await CellSim16ChV2.create(machine_config)
    try:
        logger.info("HIL driver instance created, yielding to tests.")
        yield driver_instance
    finally:
        logger.info("Tests finished, closing HIL driver instance...")
        # Ensure cleanup using the driver's aclose method
        await driver_instance.aclose()
        logger.info("HIL driver instance closed.")
