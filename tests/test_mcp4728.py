from hil.drivers.aiosmbus2 import AsyncSMBus, AsyncSMBusBranch, AsyncSMBusPeripheral
from hil.drivers.tca9548a import TCA9548A
from hil.drivers.mcp4728 import MCP4728
import pytest


class HilMCP4728:
    """
    Simulates a HIL for testing purposes.
    """

    mcp: "MCP4728"
    physical_bus: AsyncSMBus

    @classmethod
    async def create(cls):
        self = cls()
        self.physical_bus = AsyncSMBusPeripheral(2)
        # Open the bus before creating MCP4728 device
        await self.physical_bus.open()
        async with self.physical_bus:
            bus_mux2 = AsyncSMBusBranch.from_channels(
                upstream=self.physical_bus,
                mux=TCA9548A(self.physical_bus),
                channels=[2],
            )[0]
        self.mcp = await MCP4728.create(bus=bus_mux2)

        return self

    async def aclose(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.aclose()


@pytest.fixture
async def hil_mcp4728():
    # Create HIL instance
    hil_mcp4728 = await HilMCP4728.create()
    # Open bus for the duration of the test session
    async with hil_mcp4728.physical_bus:
        yield hil_mcp4728


@pytest.mark.runs_on(hostname="lively-sloth")
async def test_write_vref_and_read(hil_mcp4728) -> None:
    async with hil_mcp4728:
        mcp: MCP4728 = hil_mcp4728.mcp
        vrefa = MCP4728.ChannelVref.INT_VREF
        vrefb = MCP4728.ChannelVref.INT_VREF
        vrefc = MCP4728.ChannelVref.INT_VREF
        vrefd = MCP4728.ChannelVref.INT_VREF
        vref_list = [vrefa, vrefb, vrefc, vrefd]

        await mcp.set_vref(vref_list)

        await mcp.read()

        for i in range(len(vref_list)):
            assert vref_list[i] == mcp._channels[i].vref


@pytest.mark.runs_on(hostname="lively-sloth")
async def test_write_pd_and_wakeup(hil_mcp4728: MCP4728) -> None:
    async with hil_mcp4728:
        mcp: MCP4728 = hil_mcp4728.mcp
        pda = MCP4728.ChannelPowerDown.PD_1K
        pdb = MCP4728.ChannelPowerDown.PD_100K
        pdc = MCP4728.ChannelPowerDown.PD_500K
        pdd = MCP4728.ChannelPowerDown.NORMAL
        pd_list = [pda, pdb, pdc, pdd]

        await mcp.set_pd(pd_list)
        await mcp.read()

        for i in range(mcp._num_channels):
            assert pd_list[i] == mcp._channels[i].pd

        await mcp.general_call_wakeup()
        await mcp.read()

        for i in range(mcp._num_channels):
            assert MCP4728.ChannelPowerDown.NORMAL == mcp._channels[i].pd


@pytest.mark.runs_on(hostname="lively-sloth")
async def test_write_gain_and_read(hil_mcp4728: MCP4728) -> None:
    async with hil_mcp4728:
        mcp: MCP4728 = hil_mcp4728.mcp
        gxa = MCP4728.ChannelGain.GX_1
        gxb = MCP4728.ChannelGain.GX_1
        gxc = MCP4728.ChannelGain.GX_2
        gxd = MCP4728.ChannelGain.GX_2
        gx_list = [gxa, gxb, gxc, gxd]

        await mcp.set_gain(gx_list)

        await mcp.read()

        for i in range(len(gx_list)):
            assert gx_list[i] == mcp._channels[i].gx


@pytest.mark.runs_on(hostname="lively-sloth")
async def test_write_fast_all(hil_mcp4728: MCP4728) -> None:
    async with hil_mcp4728:
        mcp: MCP4728 = hil_mcp4728.mcp
        pd_list = [MCP4728.ChannelPowerDown.NORMAL] * 4
        dac_list = [1023, 2047, 3071, 4095]
        await mcp.write_fast_mode_all(dac_list, pd_list)

        await mcp.read()

        for i in range(mcp._num_channels):
            assert pd_list[i] == mcp._channels[i].pd
            assert dac_list[i] == mcp._channels[i].dac_val


@pytest.mark.runs_on(hostname="lively-sloth")
async def test_write_channel(hil_mcp4728: MCP4728) -> None:
    async with hil_mcp4728:
        mcp: MCP4728 = hil_mcp4728.mcp
        pd_list = [MCP4728.ChannelPowerDown.NORMAL] * 4
        dac_list = [4095, 3072, 2048, 1024]
        vref_list = [MCP4728.ChannelVref.INT_VREF] * 4
        gx_list = [MCP4728.ChannelGain.GX_1] * 4

        for i in range(mcp._num_channels):
            ch = MCP4728.ChannelId(i)
            await mcp.write_channel(
                ch,
                dac_val=dac_list[i],
                pd=pd_list[i],
                vref=vref_list[i],
                gain=gx_list[i],
            )

        await mcp.read()

        for i in range(mcp._num_channels):
            assert pd_list[i] == mcp._channels[i].pd
            assert dac_list[i] == mcp._channels[i].dac_val
            assert vref_list[i] == mcp._channels[i].vref
            assert gx_list[i] == mcp._channels[i].gx


@pytest.mark.runs_on(hostname="lively-sloth")
async def test_write_eeprom_all(hil_mcp4728: MCP4728) -> None:
    async with hil_mcp4728:
        mcp: MCP4728 = hil_mcp4728.mcp

        # read and current state
        await mcp.read()

        pd_t0: list[MCP4728.ChannelPowerDown] = []
        vref_t0: list[MCP4728.ChannelVref] = []
        gx_t0: list[MCP4728.ChannelGain] = []
        dac_t0: list[int] = []
        for i in range(mcp._num_channels):
            ch: MCP4728.Channel = mcp._channels[i]
            pd_t0.append(ch.pd_eeprom)
            vref_t0.append(ch.vref_eeprom)
            gx_t0.append(ch.gx_eeprom)
            dac_t0.append(ch.dac_val_eeprom)

        # now change the eeprom values
        pd_list = [MCP4728.ChannelPowerDown.NORMAL] * 4
        dac_list = [1111, 2222, 3333, 4011]
        vref_list = [MCP4728.ChannelVref.INT_VREF] * 4
        gx_list = [MCP4728.ChannelGain.GX_2] * 4

        await mcp.write_channel_eeprom_all(
            dac_vals=dac_list, pd=pd_list, vref=vref_list, gain=gx_list
        )

        ready = False
        while not ready:
            ready = await mcp.read_rdy()

        await mcp.read()

        # Confirm that eeprom matches active values
        for i in range(mcp._num_channels):
            assert pd_list[i] == mcp._channels[i].pd_eeprom
            assert vref_list[i] == mcp._channels[i].vref_eeprom
            assert gx_list[i] == mcp._channels[i].gx_eeprom
            assert dac_list[i] == mcp._channels[i].dac_val_eeprom
            assert mcp._channels[i].pd == mcp._channels[i].pd_eeprom
            assert mcp._channels[i].vref == mcp._channels[i].vref_eeprom
            assert mcp._channels[i].gx == mcp._channels[i].gx_eeprom
            assert mcp._channels[i].dac_val == mcp._channels[i].dac_val_eeprom

        # restore eeprom to original state
        await mcp.write_channel_eeprom_all(
            dac_vals=dac_t0, pd=pd_t0, vref=vref_t0, gain=gx_t0
        )
        ready = False
        while not ready:
            ready = await mcp.read_rdy()
        await mcp.read()

        # Confirm that eeprom matches original values
        for i in range(mcp._num_channels):
            assert pd_t0[i] == mcp._channels[i].pd_eeprom
            assert vref_t0[i] == mcp._channels[i].vref_eeprom
            assert gx_t0[i] == mcp._channels[i].gx_eeprom
            assert dac_t0[i] == mcp._channels[i].dac_val_eeprom


@pytest.mark.runs_on(hostname="lively-sloth")
async def test_write_eeprom_single(hil_mcp4728: MCP4728) -> None:
    async with hil_mcp4728:
        mcp: MCP4728 = hil_mcp4728.mcp

        # read and current state
        await mcp.read()

        pd_t0: list[MCP4728.ChannelPowerDown] = []
        vref_t0: list[MCP4728.ChannelVref] = []
        gx_t0: list[MCP4728.ChannelGain] = []
        dac_t0: list[int] = []
        for i in range(mcp._num_channels):
            ch: MCP4728.Channel = mcp._channels[i]
            pd_t0.append(ch.pd_eeprom)
            vref_t0.append(ch.vref_eeprom)
            gx_t0.append(ch.gx_eeprom)
            dac_t0.append(ch.dac_val_eeprom)

        # now change the eeprom values
        pd_list = [MCP4728.ChannelPowerDown.NORMAL] * 4
        dac_list = [0, 0, 0, 0]
        vref_list = [MCP4728.ChannelVref.INT_VREF] * 4
        gx_list = [MCP4728.ChannelGain.GX_1] * 4

        for i in range(mcp._num_channels):
            ch: MCP4728.ChannelId = MCP4728.ChannelId(i)
            await mcp.write_channel_eeprom_single(
                ch=ch,
                dac_val=dac_list[i],
                pd=pd_list[i],
                vref=vref_list[i],
                gain=gx_list[i],
            )

            ready = False
            while not ready:
                ready = await mcp.read_rdy()

        await mcp.read()

        # Confirm that eeprom matches active values
        for i in range(mcp._num_channels):
            assert pd_list[i] == mcp._channels[i].pd_eeprom
            assert vref_list[i] == mcp._channels[i].vref_eeprom
            assert gx_list[i] == mcp._channels[i].gx_eeprom
            assert dac_list[i] == mcp._channels[i].dac_val_eeprom
            assert mcp._channels[i].pd == mcp._channels[i].pd_eeprom
            assert mcp._channels[i].vref == mcp._channels[i].vref_eeprom
            assert mcp._channels[i].gx == mcp._channels[i].gx_eeprom
            assert mcp._channels[i].dac_val == mcp._channels[i].dac_val_eeprom

        # restore eeprom to original state
        for i in range(mcp._num_channels):
            ch: MCP4728.ChannelId = MCP4728.ChannelId(i)
            await mcp.write_channel_eeprom_single(
                ch=ch, dac_val=dac_t0[i], pd=pd_t0[i], vref=vref_t0[i], gain=gx_t0[i]
            )
            ready = False
            while not ready:
                ready = await mcp.read_rdy()
        await mcp.read()

        # Confirm that eeprom matches original values
        for i in range(mcp._num_channels):
            assert pd_t0[i] == mcp._channels[i].pd_eeprom
            assert vref_t0[i] == mcp._channels[i].vref_eeprom
            assert gx_t0[i] == mcp._channels[i].gx_eeprom
            assert dac_t0[i] == mcp._channels[i].dac_val_eeprom


@pytest.mark.runs_on(hostname="lively-sloth")
async def test_general_call_reset(hil_mcp4728: MCP4728) -> None:
    async with hil_mcp4728:
        mcp: MCP4728 = hil_mcp4728.mcp
        pd_list = [MCP4728.ChannelPowerDown.NORMAL] * 4
        dac_list = [234, 455, 754, 1934]
        await mcp.write_fast_mode_all(dac_list, pd_list)
        await mcp.read()
        for i in range(mcp._num_channels):
            assert dac_list[i] == mcp._channels[i].dac_val

        await mcp.general_call_reset()

        await mcp.read()
        for i in range(mcp._num_channels):
            assert mcp._channels[i].dac_val_eeprom == mcp._channels[i].dac_val

    # @pytest.mark.runs_on(hostname='lively-sloth')
    # async def test_general_call_software_update(hil_mcp4728: MCP4728) -> None:
    """
    TODO This test can't be run in software. The UDAC pin is supposed to inhibit
         VOUT updates and general call software should trigger all VOUT updates
         at the same time.
    """


#     async with hil_mcp4728:
#         mcp: MCP4728 = hil_mcp4728.mcp

#         # Initialize dac values
#         dac_list = [4095, 3072, 2048, 1024]

#         for i in range(mcp._num_channels):
#             ch = MCP4728.ChannelId(i)
#             await mcp.write_channel(ch, dac_val=dac_list[i])

#         await mcp.read()

#         for i in range(mcp._num_channels):
#             assert dac_list[i] == mcp._channels[i].dac_val
#         # Set new dac values without update
#         dac_list = [0] * 4
#         for i in range(mcp._num_channels):
#             ch = MCP4728.ChannelId(i)
#             await mcp.write_channel(ch, dac_val=dac_list[i], update=False)
#         # Force update
#         await mcp.general_call_software_update()
#         # Confirm VOUT values match now
