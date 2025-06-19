import logging
from typing import Sequence, List

from hil.utils.config import ConfigDict
import pytest
from hil.drivers.aiosmbus2 import AsyncSMBus, AsyncSMBusBranch, AsyncSMBusPeripheral
from hil.drivers.cell import Cell
from hil.drivers.tca9548a import TCA9548A
from hil.drivers.blocks.gpio_mux import GpioMux
from software.hil.drivers.examples.cellsim_16ch import CellSim16ChV2
from software.hil.drivers.examples.spacebms_hil import SpaceBMSHil
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


@pytest.fixture(scope="session")
async def space_bms_hil(machine_config: ConfigDict):
    # Create HIL instance
    hil = await SpaceBMSHil.create(machine_config)
    # Open bus for the duration of the test session
    async with hil:
        yield hil
