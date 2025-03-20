from typing import TYPE_CHECKING
from hil.drivers.mcp4728 import MCP4728


if TYPE_CHECKING:
    from ..conftest import SpaceBMSHiLDevV1


async def test_mcp4728(spacebms_hil_dev_v1: SpaceBMSHiLDevV1):
    dac: MCP4728 = spacebms_hil_dev_v1.analog_out_4ch
    await dac.channel_a.set_voltage(1.23)
    await dac.channel_b.set_voltage(2.34)
    await dac.channel_c.set_voltage(3.45)
    await dac.channel_d.set_voltage(4.56)
