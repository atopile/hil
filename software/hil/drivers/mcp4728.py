"""
x = Don't care bit

From Datasheet: https://ww1.microchip.com/downloads/aemDocuments/documents\
                /OTH/ProductDocuments/DataSheets/22187E.pdf

Not implemented
Note: update address and read address are not implemented since they need LDAC
      pin control
1. General Call Read Address Bits = 0x0C:
    Read the I2C address bits of the device. Max. 400Hz clock.
2. Update address: C2:0=0b011
0 1 1 A2 A1 A0 0 1 A | 0 1 1 N_A2 N_A1 N_A0 1 0 A | 0 1 1 N_A2 N_A1 N_A0 1 1 A P

Bit Name Functions
RDY/BSY This is a status indicator (flag) of EEPROM programming activity:
    1 = EEPROM is not in programming mode
    0 = EEPROM is in programming mode
    Note: RDY/BSY status can also be monitored at the RDY/BSY pin.
(A2, A1, A0) Device I2C address bits.
             See Section 5.3 “MCP4728 Device Addressing” for more details.
    VREF Voltage Reference Selection bit:
    0 = VDD
    1 = Internal voltage reference (2.048V)
    Note: Internal voltage reference circuit is turned off if all channels
          select external reference
    (VREF = VDD).
UDAC DAC latch bit. Upload the selected DAC input register to its output register (VOUT):
    0 = Upload. Output (VOUT) is updated.
    1 = Do not upload.
    Note: UDAC bit affects the selected channel only

Note: When the device is writing EEPROM, the RDY/BSY bit stays “Low” until the
      EEPROM write operation is completed. The state of the RDY/BSY bit flag
      can be monitored by a read command or at the RDY/BSY pin.
      Any new command received during the EEPROM write operation
      (RDY/BSY bit is “Low”) is ignored.
"""

from enum import IntEnum

from hil.drivers.aiosmbus2 import AsyncSMBus

_MCP4728_DEFAULT_ADDRESS = 0x60
_MCP4728_NUM_CHANNELS_ = 4


class MCP4728:
    """
    MCP4728 4ch 12-bit digital to analog converter.

    :param AsyncSMBus bus: The I2C bus.
    :param int address: The I2C address of the device.
    :param int num_channels: Number of channels
    :param dict chan_dict:
    """

    _bus: AsyncSMBus
    _address: int
    _num_channels: int
    _channels: list["MCP4728.Channel"]

    class ChannelId(IntEnum):
        """
        DAC1, DAC0 DAC Channel Selection bits:
            00 = Channel A
            01 = Channel B
            10 = Channel C
            11 = Channel D
        """

        CHA = (0,)
        CHB = (1,)
        CHC = (2,)
        CHD = 3

    class ChannelPowerDown(IntEnum):
        """
        PD1, PD0 Power-Down selection bits:
            00 = Normal Mode
            01 = VOUT is loaded with 1 kΩ resistor to ground.
                 Most of the channel circuits are powered off.
            10 = VOUT is loaded with 100 kΩ resistor to ground.
                 Most of the channel circuits are powered off.
            11 = VOUT is loaded with 500 kΩ resistor to ground.
                 Most of the channel circuits are powered off.
            Note: See Table 4-7 and Figure 4-1 for more details.
        """

        NORMAL = (0,)
        PD_1K = (1,)
        PD_100K = (2,)
        PD_500K = 3

    class ChannelVref(IntEnum):
        """
        Vref
            0 = Vdd
            1 = Vref_internal
        """

        VDD_VREF = (0,)
        INT_VREF = 1

    class ChannelGain(IntEnum):
        """
        GX Gain selection bit:
            0 = x1 (gain of 1)
            1 = x2 (gain of 2)
        Note: Applicable only when internal VREF is selected.
              If VREF = VDD, the device uses a gain of 1 regardless of
              the gain selection bit setting.
        """

        GX_1 = (0,)
        GX_2 = 1

    class Channel:
        """
        Holds the channel configuration and output data
        :param _max_12bit_int Max. DAC output bit value
        :param _vref_volt     Output voltage reference values

        Must call read() first to get valid EEPROM data
        """

        _max_12bit_int: int = 2**12 - 1
        _vref_volt: dict = {
            "MCP4728.ChannelVref.INT_VREF": 2.048,
            "MCP4728.ChannelVref.VDD_VREF": 0,
        }

        def __init__(
            self,
            dac_val: int = 0,
            vref: "MCP4728.ChannelVref" = None,
            gain: "MCP4728.ChannelGain" = None,
            pd: "MCP4728.ChannelPowerDown" = None,
            vdd: float = 0.0,
        ) -> None:
            """
            :param vref    Output voltage reference. See ChannelVref
            :param dac_val DAC output bit value (12-bit)
            :param gain    Output voltage gain. See ChannelGain
            :param pd      Power down mode. See ChannelPowerDown
            :param vdd     External voltage reference setting
            """
            self._vref: MCP4728.ChannelVref = (
                vref if vref else MCP4728.ChannelVref.INT_VREF
            )
            self._vref_eeprom: MCP4728.ChannelVref = MCP4728.ChannelVref.INT_VREF
            self._vref_volt[MCP4728.ChannelVref.VDD_VREF] = vdd
            self._dac_val = dac_val
            self._dac_val_eeprom = 0
            self._gx: MCP4728.ChannelGain = gain if gain else MCP4728.ChannelGain.GX_1
            self._gx_eeprom: MCP4728.ChannelGain = MCP4728.ChannelGain.GX_1
            self._pd: MCP4728.ChannelPowerDown = (
                pd if pd else MCP4728.ChannelPowerDown.NORMAL
            )
            self._pd_eeprom: MCP4728.ChannelPowerDown = MCP4728.ChannelPowerDown.NORMAL

        @property
        def vref(self) -> "MCP4728.ChannelVref":
            return self._vref

        @vref.setter
        def vref(self, val: int) -> None:
            assert val in MCP4728.ChannelVref
            self._vref = MCP4728.ChannelVref(val)

        @property
        def vref_eeprom(self) -> "MCP4728.ChannelVref":
            return self._vref_eeprom

        @vref_eeprom.setter
        def vref_eeprom(self, val: int) -> None:
            assert val in MCP4728.ChannelVref
            self._vref_eeprom = MCP4728.ChannelVref(val)

        @property
        def gx(self) -> "MCP4728.ChannelGain":
            return self._gx

        @gx.setter
        def gx(self, val: int) -> None:
            assert val in MCP4728.ChannelGain
            self._gx = MCP4728.ChannelGain(val)

        @property
        def gx_eeprom(self) -> "MCP4728.ChannelGain":
            return self._gx_eeprom

        @gx_eeprom.setter
        def gx_eeprom(self, val: int) -> None:
            assert val in MCP4728.ChannelGain
            self._gx_eeprom = MCP4728.ChannelGain(val)

        @property
        def pd(self) -> "MCP4728.ChannelPowerDown":
            return self._pd

        @pd.setter
        def pd(self, val: int) -> None:
            assert val in MCP4728.ChannelPowerDown
            self._pd = MCP4728.ChannelPowerDown(val)

        @property
        def pd_eeprom(self) -> "MCP4728.ChannelPowerDown":
            return self._pd_eeprom

        @pd_eeprom.setter
        def pd_eeprom(self, val: int) -> None:
            assert val in MCP4728.ChannelPowerDown
            self._pd_eeprom = MCP4728.ChannelPowerDown(val)

        @property
        def dac_val(self) -> int:
            return self._dac_val

        @dac_val.setter
        def dac_val(self, val: int) -> None:
            assert 0 <= val <= self._max_12bit_int
            self._dac_val = val

        @property
        def dac_val_eeprom(self) -> int:
            return self._dac_val_eeprom

        @dac_val_eeprom.setter
        def dac_val_eeprom(self, val: int) -> None:
            assert 0 <= val <= self._max_12bit_int
            self._dac_val_eeprom = val

        def get_dac_val_from_pct(self, pct_val: float) -> int:
            """
            Helper function to get dac int val from pct output setting
            """
            return int(pct_val * self._max_12bit_int)

        def get_dac_val_from_volt(self, volt: float) -> None:
            """
            Helper function to get dac int val from output voltage setting
            """
            gain = self.gx + 1
            v_scaled = (volt / gain) / self.vref_volt[self.vref]
            return int(v_scaled * self._max_12bit_int)

    def __init__(self) -> None:
        # Private constructor; use MCP4728.create() instead
        pass

    @classmethod
    async def create(cls, bus: AsyncSMBus, address: int = _MCP4728_DEFAULT_ADDRESS):
        """
        Asynchronously create an instance of MCP4728.
        """
        self = cls.__new__(cls)
        self._bus = bus
        self._address = address
        self._num_channels = _MCP4728_NUM_CHANNELS_
        self._channels = self._init_channels()
        return self

    def _init_channels(self) -> list["MCP4728.Channel"]:
        """
        Initialize all channels and add to a list
        """
        chans: list = []
        for i in range(self._num_channels):
            chans.append(MCP4728.Channel())

        return chans

    def _update_channels_with_read_data(self, data: list[int]) -> None:
        """
        Parse and decode received data. Each channel has 6 bytes.
        B1: RDY POR DAC1 DAC0 0 A2 A1 A0 A |
        B2: VREF PD1 PD0 GX D11 D10 D9 D8 A |
        B3: D7 D6 D5 D4 D3 D2 D1 D0 A |
        """
        ch_mask = 0x30
        ch_shift = 4
        vref_mask = 0x80
        vref_shift = 7
        pd_mask = 0x60
        pd_shift = 5
        gx_mask = 0x10
        gx_shift = 4
        dac_high_mask = 0xF

        for i in range(self._num_channels):
            read_ch_shift = 6 * i
            byte1 = data[read_ch_shift]
            byte2 = data[read_ch_shift + 1]
            byte3 = data[read_ch_shift + 2]
            # byte4 = data[read_ch_shift + 3] # unused
            byte5 = data[read_ch_shift + 4]
            byte6 = data[read_ch_shift + 5]

            # active registers
            ch = (byte1 & ch_mask) >> ch_shift
            vref = (byte2 & vref_mask) >> vref_shift
            pd = (byte2 & pd_mask) >> pd_shift
            gx = (byte2 & gx_mask) >> gx_shift
            dac_h = byte2 & dac_high_mask
            dac_l = byte3
            dac = int.from_bytes(bytes([dac_h, dac_l]), "big")

            # eeprom registers
            vref_eeprom = (byte5 & vref_mask) >> vref_shift
            pd_eeprom = (byte5 & pd_mask) >> pd_shift
            gx_eeprom = (byte5 & gx_mask) >> gx_shift
            dac_h = byte5 & dac_high_mask
            dac_l = byte6
            dac_eeprom = int.from_bytes(bytes([dac_h, dac_l]), "big")

            assert ch in self.ChannelId
            dac_ch: MCP4728.Channel = self._channels[ch]
            dac_ch.vref = vref
            dac_ch.gx = gx
            dac_ch.pd = pd
            dac_ch.dac_val = dac
            dac_ch.vref_eeprom = vref_eeprom
            dac_ch.gx_eeprom = gx_eeprom
            dac_ch.pd_eeprom = pd_eeprom
            dac_ch.dac_val_eeprom = dac_eeprom

    """
        Write commands:
        Write: S 1 1 0 0 A2 A1 A0 0 A | ...
    """

    async def write_fast_mode_all(
        self, dac_vals: list[int], pd_vals: list["MCP4728.ChannelPowerDown"]
    ) -> None:
        """
        Fast mode write to all channels.
        @dac_vals list of dac vals [cha, chb, chc, chd] must be 12bit val
        @pd_vals  list of power down vals [pda, pdb, pdc, pdd]
                  See PD options above.
        Format:
        Fast write input registers sequentially: C2=0 C1=0
        Write | 0 0 PD1:0 D11:8 A | D7:0 A |
                   x x PD1:0 D11:8 A | D7:0 A |
                   x x PD1:0 D11:8 A | D7:0 A |
                   x x PD1:0 D11:8 A | D7:0 A P
        """
        assert len(dac_vals) == self._num_channels
        assert len(pd_vals) == self._num_channels

        wfm_bits = 0x00
        data = [0] * 8
        for i, val in enumerate(dac_vals):
            assert 0 <= val <= 4095
            assert pd_vals[i] in MCP4728.ChannelPowerDown
            val = val.to_bytes(2, "big")
            val_h = val[0] & 0xF
            val_l = val[1]
            data[2 * i] = wfm_bits | ((pd_vals[i] & 0x3) << 4) | val_h
            data[2 * i + 1] = val_l

        async with self._bus.handle() as handle:
            await handle.write_i2c_block_data(self._address, data[0], data[1:])

    async def write_channel(
        self,
        ch: "MCP4728.ChannelId",
        dac_val: int,
        pd: "MCP4728.ChannelPowerDown" = None,
        vref: "MCP4728.ChannelVref" = None,
        gain: "MCP4728.ChannelGain" = None,
        update: bool = True,
    ) -> None:
        """
        Single channel write
        @ch         CHA|B|C|D
        @dac_val    12-bit int
        @pd         Power down, see table above
        @vref       Reference voltage source
        @gain       Channel output gain
        @update     Update dac on ACK

        Format:
        Write one DAC input at a time: C2:0=10
        W1:0=0 Input reg only
                0 1 0 0 0 DAC1:0 UDAC A | Vref PD1:0 Gx D11:8 A | D7:0 A |
            (Repeat if needed) x x x x x DAC1:0 UDAC A | Vref PD1:0 Gx D11:8 A | D7:0 A P
        """
        if not pd:
            pd = MCP4728.ChannelPowerDown.NORMAL
        if not vref:
            vref = MCP4728.ChannelVref.INT_VREF
        if not gain:
            gain = MCP4728.ChannelGain.GX_1

        assert ch in MCP4728.ChannelId
        assert 0 <= dac_val <= 4095
        assert pd in MCP4728.ChannelPowerDown
        assert vref in MCP4728.ChannelVref
        assert gain in MCP4728.ChannelGain

        val = dac_val.to_bytes(2, "big")
        val_h = val[0] & 0xF
        val_l = val[1]

        reg = 0x40 | (ch & 0x3) << 1 | update
        data = [(vref << 7 | pd << 5 | gain << 4 | val_h), val_l]

        async with self._bus.handle() as handle:
            await handle.write_i2c_block_data(self._address, reg, data)

    async def write_channel_eeprom_all(
        self,
        dac_vals: list[int],
        pd: list["MCP4728.ChannelPowerDown"] = None,
        vref: list["MCP4728.ChannelVref"] = None,
        gain: list["MCP4728.ChannelGain"] = None,
        update: bool = True,
    ) -> None:
        """
        Multi channel and EEPROM write
        @dac_val 12-bit int
        @pd      Power down, see table above
        @vref    Reference voltage source
        @gain    Channel output gain
        @update  Update dac on ACK
        Format:
            0 1 0 1 0 DAC1:0 UDAC A | Vref PD1:0 Gx D11:8 A | D7:0 A |
                                      Vref PD1:0 Gx D11:8 A | D7:0 A |
                                      Vref PD1:0 Gx D11:8 A | D7:0 A |
                                    Vref PD1:0 Gx D11:8 A | D7:0 A P |
        Note: When the device is writing EEPROM, the RDY/BSY bit
            stays “Low” until the EEPROM write operation is
            completed. The state of the RDY/BSY bit flag can be
            monitored by a read command or at the RDY/BSY pin.
            Any new command received during the EEPROM write
            operation (RDY/BSY bit is “Low”) is ignored.
        """

        reg = 0x50 | update
        if pd is None:
            pd = [MCP4728.ChannelPowerDown.NORMAL] * 4
        if vref is None:
            vref = [MCP4728.ChannelVref.INT_VREF] * 4
        if gain is None:
            gain = [MCP4728.ChannelGain.GX_1] * 4

        data = [0] * 8
        for i in range(self._num_channels):
            assert 0 <= dac_vals[i] <= 4095
            assert pd[i] in MCP4728.ChannelPowerDown
            assert vref[i] in MCP4728.ChannelVref
            assert gain[i] in MCP4728.ChannelGain

            val = dac_vals[i].to_bytes(2, "big")
            val_h = val[0] & 0xF
            val_l = val[1]
            data[2 * i] = (vref[i] << 7) | (pd[i] << 5) | (gain[i] << 4) | val_h
            data[2 * i + 1] = val_l

        async with self._bus.handle() as handle:
            await handle.write_i2c_block_data(self._address, reg, data)

    async def write_channel_eeprom_single(
        self,
        ch: "MCP4728.Channel",
        dac_val: int,
        pd: "MCP4728.ChannelPowerDown" = None,
        vref: "MCP4728.ChannelVref" = None,
        gain: "MCP4728.ChannelGain" = None,
        update: bool = True,
    ) -> None:
        """
        Single channel and EEPROM write
        @dac_val    12-bit int
        @pd         Power down, see table above
        @vref       Reference voltage source
        @gain       Channel output gain
        @update     Update dac on ACK
        Format:
            0 1 0 1 1 DAC1:0 UDAC A | Vref PD1:0 Gx D11:8 A | D7:0 A P
        Note: When the device is writing EEPROM, the RDY/BSY bit
            stays “Low” until the EEPROM write operation is
            completed. The state of the RDY/BSY bit flag can be
            monitored by a read command or at the RDY/BSY pin.
            Any new command received during the EEPROM write
            operation (RDY/BSY bit is “Low”) is ignored.
        """
        if not pd:
            pd = MCP4728.ChannelPowerDown.NORMAL
        if not vref:
            vref = MCP4728.ChannelVref.INT_VREF
        if not gain:
            gain = MCP4728.ChannelGain.GX_1

        assert ch in MCP4728.ChannelId
        assert 0 <= dac_val <= 4095
        assert pd in MCP4728.ChannelPowerDown
        assert vref in MCP4728.ChannelVref
        assert gain in MCP4728.ChannelGain

        reg = 0x58 | ((ch & 0x3) << 1) | update
        val = dac_val.to_bytes(2, "big")
        val_h = val[0] & 0xF
        val_l = val[1]
        data = [(vref << 7) | (pd << 5) | (gain << 4) | val_h, val_l]
        async with self._bus.handle() as handle:
            await handle.write_i2c_block_data(self._address, reg, data)

    """
    Read: S 1 1 0 0 A2 A1 A0 1 A | ...
    """

    async def read_rdy(self) -> bool:
        """
        Read the rdy/not_bsy status bit which is in the 1st byte on read
        RDY POR DAC1 DAC0 0 A2 A1 A0 A

        Returns true when the device is ready (not busy)
        """
        ready = False
        async with self._bus.handle() as handle:
            data = await handle.read_byte(self._address)
            ready = (data & 0x80) > 0

        return ready

    async def read(self) -> None:
        """
        Format: 3 byte reads alternate between DAC input reg and
                EEPROM reg for each channel.
                Can stop after any 3 bytes.
                This function reads all 4 channels
        RDY POR DAC1 DAC0 0 A2 A1 A0 A |
        VREF PD1 PD0 GX D11 D10 D9 D8 A |
        D7 D6 D5 D4 D3 D2 D1 D0 A |
        Continue read to get all channels
        """
        async with self._bus.handle() as handle:
            data = await handle.read_i2c_block_data(self._address, 0, 24)

        self._update_channels_with_read_data(data)

    """
        General Call = 0x00
    """

    async def general_call_reset(self):
        """
        General Call Reset = 0x06:
        At ack, startup timer starts a reset sequence, and EEPROM data is
        loaded into DAC input and output registers immediately
        """
        reg = 0x00
        data = 0x06
        async with self._bus.handle() as handle:
            await handle.write_byte(i2c_addr=reg, value=data)

    async def general_call_wakeup(self):
        """
        General Call Wake-Up = 0x09:
        The device will reset the Power-Down bits for CHA (PD1, PD0 = 0,0)
        """
        reg = 0x00
        data = 0x09
        async with self._bus.handle() as handle:
            await handle.write_byte(i2c_addr=reg, value=data)

    async def general_call_software_update(self):
        """
        General Call Software Update = 0x08:
        The device updates all DAC analog outputs (VOUT) at the same time
        """
        reg = 0x00
        data = 0x08
        async with self._bus.handle() as handle:
            await handle.write_byte(i2c_addr=reg, value=data)

    async def set_vref(self, vref: list["MCP4728.ChannelVref"]) -> None:
        """
        Update the vref for all channels
        C2:0=0b100 Vref [0=Vdd, 1=Vref_internal]
        1 0 0 x VrefA VrefB VrefC VrefD A P
        """
        assert len(vref) == self._num_channels
        for v in vref:
            assert v in MCP4728.ChannelVref

        reg = 0x80 | vref[0] << 3 | vref[1] << 2 | vref[2] << 1 | vref[3]

        async with self._bus.handle() as handle:
            await handle.write_byte(self._address, reg)

    async def set_pd(self, pd: list["MCP4728.ChannelPowerDown"]) -> None:
        """
        Update the power down bits for all channels
        C2:0=0b101 Power down See description above
        1 0 1 x PD1A PD0A PD1B PD0B A | PD1C PD0C PD1D PD0D x x x x A P
        """
        assert len(pd) == self._num_channels
        for v in pd:
            assert v in MCP4728.ChannelPowerDown

        reg = 0xA0 | pd[0] << 2 | pd[1]
        data = pd[2] << 6 | pd[3] << 4

        async with self._bus.handle() as handle:
            await handle.write_byte_data(self._address, reg, data)

    async def set_gain(self, gain: list["MCP4728.ChannelGain"]) -> None:
        """
        Update the gain for all channels
        C2:0=0b110 Gain [0=1x, 1=2x]
        1 1 0 x GxA GxB GxC GxD A P
        """
        assert len(gain) == self._num_channels
        for v in gain:
            assert v in MCP4728.ChannelGain

        reg = 0xC0 | gain[0] & 0x1 << 3 | gain[1] << 2 | gain[2] << 1 | gain[3]

        async with self._bus.handle() as handle:
            await handle.write_byte(self._address, reg)
