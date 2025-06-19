from typing import TYPE_CHECKING
from hil.drivers.aiosmbus2 import AsyncSMBusBranch, AsyncSMBusPeripheral
from hil.drivers.tca9548a import TCA9548A
from hil.drivers.mcp4728 import MCP4728
import pytest

# Import the HIL fixture type for hinting
if TYPE_CHECKING:
    from software.hil.drivers.examples.cellsim_16ch import CellSim16ChV2


# Parametrize tests to run on both MCP4728 instances
@pytest.mark.runs_on(hostname="tipsy-raccoon")
@pytest.mark.parametrize("mcp_instance_name", ["thermistors_1_4", "thermistors_5_8"])
async def test_write_vref_and_read(hil: "CellSim16ChV2", mcp_instance_name: str) -> None:
    mcp: MCP4728 = getattr(hil, mcp_instance_name)
    vrefa = MCP4728.ChannelVref.INT_VREF
    vrefb = MCP4728.ChannelVref.INT_VREF
    vrefc = MCP4728.ChannelVref.INT_VREF
    vrefd = MCP4728.ChannelVref.INT_VREF
    vref_list = [vrefa, vrefb, vrefc, vrefd]

    await mcp.set_vref(vref_list)
    await mcp.read()

    for i in range(len(vref_list)):
        assert vref_list[i] == mcp._channels[i].vref


@pytest.mark.runs_on(hostname="tipsy-raccoon")
@pytest.mark.parametrize("mcp_instance_name", ["thermistors_1_4", "thermistors_5_8"])
async def test_write_pd_and_wakeup(hil: "CellSim16ChV2", mcp_instance_name: str) -> None:
    mcp: MCP4728 = getattr(hil, mcp_instance_name)
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


@pytest.mark.runs_on(hostname="tipsy-raccoon")
@pytest.mark.parametrize("mcp_instance_name", ["thermistors_1_4", "thermistors_5_8"])
async def test_write_gain_and_read(hil: "CellSim16ChV2", mcp_instance_name: str) -> None:
    mcp: MCP4728 = getattr(hil, mcp_instance_name)
    gxa = MCP4728.ChannelGain.GX_1
    gxb = MCP4728.ChannelGain.GX_1
    gxc = MCP4728.ChannelGain.GX_2
    gxd = MCP4728.ChannelGain.GX_2
    gx_list = [gxa, gxb, gxc, gxd]

    await mcp.set_gain(gx_list)
    await mcp.read()

    for i in range(len(gx_list)):
        assert gx_list[i] == mcp._channels[i].gx


@pytest.mark.runs_on(hostname="tipsy-raccoon")
@pytest.mark.parametrize("mcp_instance_name", ["thermistors_1_4", "thermistors_5_8"])
async def test_write_fast_all(hil: "CellSim16ChV2", mcp_instance_name: str) -> None:
    mcp: MCP4728 = getattr(hil, mcp_instance_name)
    pd_list = [MCP4728.ChannelPowerDown.NORMAL] * 4
    dac_list = [1023, 2047, 3071, 4095]
    await mcp.write_fast_mode_all(dac_list, pd_list)
    await mcp.read()

    for i in range(mcp._num_channels):
        assert pd_list[i] == mcp._channels[i].pd
        assert dac_list[i] == mcp._channels[i].dac_val


@pytest.mark.runs_on(hostname="tipsy-raccoon")
@pytest.mark.parametrize("mcp_instance_name", ["thermistors_1_4", "thermistors_5_8"])
async def test_write_channel(hil: "CellSim16ChV2", mcp_instance_name: str) -> None:
    mcp: MCP4728 = getattr(hil, mcp_instance_name)
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


@pytest.mark.runs_on(hostname="tipsy-raccoon")
@pytest.mark.parametrize("mcp_instance_name", ["thermistors_1_4", "thermistors_5_8"])
async def test_write_eeprom_all(hil: "CellSim16ChV2", mcp_instance_name: str) -> None:
    mcp: MCP4728 = getattr(hil, mcp_instance_name)
    await mcp.read()

    # Store initial EEPROM state
    pd_t0 = [ch.pd_eeprom for ch in mcp._channels]
    vref_t0 = [ch.vref_eeprom for ch in mcp._channels]
    gx_t0 = [ch.gx_eeprom for ch in mcp._channels]
    dac_t0 = [ch.dac_val_eeprom for ch in mcp._channels]

    # Write new values
    pd_list = [MCP4728.ChannelPowerDown.NORMAL] * 4
    dac_list = [1111, 2222, 3333, 4011]
    vref_list = [MCP4728.ChannelVref.INT_VREF] * 4
    gx_list = [MCP4728.ChannelGain.GX_2] * 4

    await mcp.write_channel_eeprom_all(
        dac_vals=dac_list, pd=pd_list, vref=vref_list, gain=gx_list
    )
    # Wait for EEPROM write
    while not await mcp.read_rdy(): pass
    await mcp.read()

    # Assert new values
    for i in range(mcp._num_channels):
        assert pd_list[i] == mcp._channels[i].pd_eeprom
        assert vref_list[i] == mcp._channels[i].vref_eeprom
        assert gx_list[i] == mcp._channels[i].gx_eeprom
        assert dac_list[i] == mcp._channels[i].dac_val_eeprom
        # Check if active values also updated
        assert mcp._channels[i].pd == mcp._channels[i].pd_eeprom
        assert mcp._channels[i].vref == mcp._channels[i].vref_eeprom
        assert mcp._channels[i].gx == mcp._channels[i].gx_eeprom
        assert mcp._channels[i].dac_val == mcp._channels[i].dac_val_eeprom

    # Restore original values
    await mcp.write_channel_eeprom_all(
        dac_vals=dac_t0, pd=pd_t0, vref=vref_t0, gain=gx_t0
    )
    while not await mcp.read_rdy(): pass
    await mcp.read()

    # Assert original values restored
    for i in range(mcp._num_channels):
        assert pd_t0[i] == mcp._channels[i].pd_eeprom
        assert vref_t0[i] == mcp._channels[i].vref_eeprom
        assert gx_t0[i] == mcp._channels[i].gx_eeprom
        assert dac_t0[i] == mcp._channels[i].dac_val_eeprom


@pytest.mark.runs_on(hostname="tipsy-raccoon")
@pytest.mark.parametrize("mcp_instance_name", ["thermistors_1_4", "thermistors_5_8"])
async def test_write_eeprom_single(hil: "CellSim16ChV2", mcp_instance_name: str) -> None:
    mcp: MCP4728 = getattr(hil, mcp_instance_name)
    await mcp.read()

    # Store initial EEPROM state
    pd_t0 = [ch.pd_eeprom for ch in mcp._channels]
    vref_t0 = [ch.vref_eeprom for ch in mcp._channels]
    gx_t0 = [ch.gx_eeprom for ch in mcp._channels]
    dac_t0 = [ch.dac_val_eeprom for ch in mcp._channels]

    # Write new values individually
    pd_list = [MCP4728.ChannelPowerDown.NORMAL] * 4
    dac_list = [0, 0, 0, 0]
    vref_list = [MCP4728.ChannelVref.INT_VREF] * 4
    gx_list = [MCP4728.ChannelGain.GX_1] * 4

    for i in range(mcp._num_channels):
        ch_id = MCP4728.ChannelId(i)
        await mcp.write_channel_eeprom_single(
            ch=ch_id,
            dac_val=dac_list[i],
            pd=pd_list[i],
            vref=vref_list[i],
            gain=gx_list[i],
        )
        while not await mcp.read_rdy(): pass
    await mcp.read()

    # Assert new values
    for i in range(mcp._num_channels):
        assert pd_list[i] == mcp._channels[i].pd_eeprom
        assert vref_list[i] == mcp._channels[i].vref_eeprom
        assert gx_list[i] == mcp._channels[i].gx_eeprom
        assert dac_list[i] == mcp._channels[i].dac_val_eeprom
        assert mcp._channels[i].pd == mcp._channels[i].pd_eeprom
        assert mcp._channels[i].vref == mcp._channels[i].vref_eeprom
        assert mcp._channels[i].gx == mcp._channels[i].gx_eeprom
        assert mcp._channels[i].dac_val == mcp._channels[i].dac_val_eeprom

    # Restore original values individually
    for i in range(mcp._num_channels):
        ch_id = MCP4728.ChannelId(i)
        await mcp.write_channel_eeprom_single(
            ch=ch_id, dac_val=dac_t0[i], pd=pd_t0[i], vref=vref_t0[i], gain=gx_t0[i]
        )
        while not await mcp.read_rdy(): pass
    await mcp.read()

    # Assert original values restored
    for i in range(mcp._num_channels):
        assert pd_t0[i] == mcp._channels[i].pd_eeprom
        assert vref_t0[i] == mcp._channels[i].vref_eeprom
        assert gx_t0[i] == mcp._channels[i].gx_eeprom
        assert dac_t0[i] == mcp._channels[i].dac_val_eeprom


@pytest.mark.runs_on(hostname="tipsy-raccoon")
@pytest.mark.parametrize("mcp_instance_name", ["thermistors_1_4", "thermistors_5_8"])
async def test_general_call_reset(hil: "CellSim16ChV2", mcp_instance_name: str) -> None:
    mcp: MCP4728 = getattr(hil, mcp_instance_name)
    pd_list = [MCP4728.ChannelPowerDown.NORMAL] * 4
    dac_list = [234, 455, 754, 1934] # Arbitrary values
    await mcp.write_fast_mode_all(dac_list, pd_list)
    await mcp.read()
    for i in range(mcp._num_channels):
        assert dac_list[i] == mcp._channels[i].dac_val

    await mcp.general_call_reset() # Resets DAC values to EEPROM content
    await mcp.read()
    for i in range(mcp._num_channels):
        assert mcp._channels[i].dac_val_eeprom == mcp._channels[i].dac_val


# Commented out Software Update test remains unchanged
# @pytest.mark.runs_on(hostname='tipsy-raccoon')
# async def test_general_call_software_update(hil: "CellSim16ChV2") -> None:
# ...
