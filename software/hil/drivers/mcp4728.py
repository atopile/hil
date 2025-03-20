# SPDX-FileCopyrightText: 2019 Bryan Siepert for Adafruit Industries
#
# SPDX-License-Identifier: MIT

"""
MCP4728 I2C 12-bit Quad DAC driver
================================================================================

Helper library for the Microchip MCP4728 I2C 12-bit Quad DAC

Credit for the original implementation goes to Bryan Siepert for Adafruit Industries.

Implementation Notes
--------------------

**Hardware:**
* Microchip MCP4728 I2C 12-bit Quad DAC
"""

import asyncio
import enum
from typing_extensions import Literal
from hil.drivers.aiosmbus2 import AsyncSMBus

MCP4728_DEFAULT_ADDRESS = 0x60
MCP4728A4_DEFAULT_ADDRESS = 0x64

_MCP4728_CH_A_MULTI_EEPROM = 0x50
_MCP4728_GENERAL_CALL_ADDRESS = 0x00
_MCP4728_GENERAL_CALL_RESET_COMMAND = 0x06
_MCP4728_GENERAL_CALL_WAKEUP_COMMAND = 0x09
_MCP4728_GENERAL_CALL_SOFTWARE_UPDATE_COMMAND = 0x08

__version__ = "0.0.0+auto.0"


class Vref(enum.IntEnum):
    """Voltage reference options for the DAC."""

    VDD = 0
    INTERNAL = 1


class PowerState(enum.IntEnum):
    """Power state options for the DAC."""

    NORMAL = 0
    POWER_DOWN_1K = 1
    POWER_DOWN_100K = 2
    POWER_DOWN_500K = 3


class _Channel:
    """An instance of a single channel for a multi-channel DAC.

    :param dac_instance: Instance of the channel object
    :param cache_page: cache page of the channel
    :param index: Index of the channel (0-3)
    """

    def __init__(
        self,
        dac_instance: "MCP4728",
        cache_page: dict[str, int],
        index: int,
    ) -> None:
        self._vref = Vref(cache_page["vref"])
        self._gain = cache_page["gain"]
        self._raw_value = cache_page["value"]
        self._power_state = PowerState(cache_page["power_state"])
        self._dac = dac_instance
        self.channel_index = index

    async def get_voltage(self) -> float:
        """Get the output voltage in volts.

        The voltage range depends on the Vref and gain settings:
        - For Vref.VDD: 0V to VDD
        - For Vref.INTERNAL with gain=1: 0V to 2.048V
        - For Vref.INTERNAL with gain=2: 0V to 4.096V
        """
        vref = await self.get_vref()
        gain = await self.get_gain()
        normalized = await self.get_normalized_value()

        if vref == Vref.VDD:
            vdd = await self._dac.get_vdd()
            return normalized * vdd
        else:  # Vref.INTERNAL
            base_voltage = 2.048  # Internal reference voltage
            return normalized * base_voltage * gain

    async def set_voltage(self, voltage: float) -> None:
        """Set the output voltage in volts.

        The voltage range depends on the Vref and gain settings:
        - For Vref.VDD: 0V to VDD
        - For Vref.INTERNAL with gain=1: 0V to 2.048V
        - For Vref.INTERNAL with gain=2: 0V to 4.096V

        :param voltage: The desired output voltage in volts
        :raises ValueError: If the voltage is outside the valid range
        """
        vref = await self.get_vref()
        gain = await self.get_gain()

        if vref == Vref.VDD:
            vdd = await self._dac.get_vdd()
            if voltage < 0 or voltage > vdd:
                raise ValueError(
                    f"Voltage must be between 0V and {vdd}V for VDD reference"
                )
            normalized = voltage / vdd
        else:  # Vref.INTERNAL
            max_voltage = 2.048 * gain
            if voltage < 0 or voltage > max_voltage:
                raise ValueError(
                    f"Voltage must be between 0V and {max_voltage}V for internal reference with gain={gain}"
                )
            normalized = voltage / max_voltage

        await self.set_normalized_value(normalized)

    async def get_normalized_value(self) -> float:
        """Get the DAC value as a float between 0.0 and 1.0."""
        return await self.get_raw_value() / 4095.0

    async def set_normalized_value(self, value: float) -> None:
        """Set the DAC value as a float between 0.0 and 1.0."""
        if not 0.0 <= value <= 1.0:
            raise ValueError("Value must be between 0.0 and 1.0")
        await self.set_raw_value(int(value * 4095.0))

    async def get_value(self) -> int:
        """Get the DAC value as a 16-bit unsigned value."""
        return (await self.get_raw_value()) << 4

    async def set_value(self, value: int) -> None:
        """Set the DAC value as a 16-bit unsigned value."""
        if not 0 <= value <= 65535:
            raise ValueError("Value must be between 0 and 65535")
        await self.set_raw_value(value >> 4)

    async def get_raw_value(self) -> int:
        """Get the DAC value as a 12-bit unsigned value."""
        return self._raw_value

    async def set_raw_value(self, value: int) -> None:
        """Set the DAC value as a 12-bit unsigned value."""
        if not 0 <= value <= 4095:
            raise ValueError("Value must be between 0 and 4095")
        self._raw_value = value
        await self._dac._set_value(self)

    async def get_gain(self) -> Literal[1, 2]:
        """Get the gain setting (1 or 2). Only affects Vref.INTERNAL mode."""
        return self._gain + 1

    async def set_gain(self, value: Literal[1, 2]) -> None:
        """Set the gain setting (1 or 2). Only affects Vref.INTERNAL mode."""
        if value not in (1, 2):
            raise ValueError("Gain must be 1 or 2")
        self._gain = value - 1
        await self._dac.sync_gains()

    async def get_vref(self) -> Vref:
        """Get the voltage reference setting."""
        return self._vref

    async def set_vref(self, value: Vref) -> None:
        """Set the voltage reference setting."""
        if not isinstance(value, Vref):
            raise ValueError("Value must be a Vref enum")
        self._vref = value
        await self._dac.sync_vrefs()

    async def get_power_state(self) -> PowerState:
        """Get the power state of the channel."""
        return self._power_state

    async def set_power_state(self, value: PowerState) -> None:
        """Set the power state of the channel."""
        if not isinstance(value, PowerState):
            raise ValueError("Value must be a PowerState enum")
        self._power_state = value
        await self._dac.sync_power_states()


class MCP4728:
    """Helper library for the Microchip MCP4728 I2C 12-bit Quad DAC.

    :param AsyncSMBus bus: The I2C bus the MCP4728 is connected to.
    :param int address: The I2C device address. Defaults to :const:`0x60`
    :param float vdd: The VDD voltage in volts. Defaults to 3.3V.

    **Quickstart: Importing and using the MCP4728**

        Here is an example of using the :class:`MCP4728` class.
        First you will need to import the libraries to use the sensor

        .. code-block:: python

            from hil.drivers.aiosmbus2 import AsyncSMBusPeripheral
            from hil.drivers.mcp4728 import MCP4728, Vref, PowerState

        Once this is done you can create your async SMBus object and define your sensor object

        .. code-block:: python

            async def main():
                async with AsyncSMBusPeripheral(1) as bus:  # Use I2C bus 1
                    mcp4728 = await MCP4728.create(bus, vdd=3.3)  # VDD is 3.3V

                    # Set voltages for different channels
                    await mcp4728.channel_a.set_voltage(3.3)  # Maximum voltage (VDD)
                    await mcp4728.channel_b.set_voltage(1.65)  # Half of VDD
                    await mcp4728.channel_c.set_voltage(0.825)  # Quarter of VDD
                    await mcp4728.channel_d.set_voltage(0.0)  # 0V

                    # Or use internal reference with gain
                    await mcp4728.channel_a.set_vref(Vref.INTERNAL)
                    await mcp4728.channel_a.set_gain(2)
                    await mcp4728.channel_a.set_voltage(4.096)  # Maximum voltage with internal ref and gain=2

                    # Set power states
                    await mcp4728.channel_a.set_power_state(PowerState.NORMAL)
                    await mcp478.channel_b.set_power_state(PowerState.POWER_DOWN_1K)

            asyncio.run(main())
    """

    _bus: AsyncSMBus
    _address: int
    _vdd: float
    channel_a: _Channel
    channel_b: _Channel
    channel_c: _Channel
    channel_d: _Channel

    def __init__(self) -> None:
        # Private constructor; use MCP4728.create() instead
        pass

    @classmethod
    async def create(
        cls, bus: AsyncSMBus, address: int = MCP4728_DEFAULT_ADDRESS, vdd: float = 3.3
    ) -> "MCP4728":
        """Asynchronously create an instance of MCP4728."""
        self = cls.__new__(cls)
        self._bus = bus
        self._address = address
        self._vdd = vdd

        raw_registers = await self._read_registers()

        self.channel_a = _Channel(self, self._cache_page(*raw_registers[0]), 0)
        self.channel_b = _Channel(self, self._cache_page(*raw_registers[1]), 1)
        self.channel_c = _Channel(self, self._cache_page(*raw_registers[2]), 2)
        self.channel_d = _Channel(self, self._cache_page(*raw_registers[3]), 3)

        return self

    async def get_vdd(self) -> float:
        """Get the VDD voltage in volts."""
        return self._vdd

    @staticmethod
    def _get_flags(high_byte: int) -> tuple[int, int, int]:
        """Extract Vref, gain, and power state flags from high byte."""
        vref = (high_byte & 1 << 7) > 0
        gain = (high_byte & 1 << 4) > 0
        power_state = (high_byte & 0b011 << 5) >> 5
        return (vref, gain, power_state)

    @staticmethod
    def _cache_page(
        value: int, vref: int, gain: int, power_state: int
    ) -> dict[str, int]:
        """Create a cache page dictionary for a channel."""
        return {"value": value, "vref": vref, "gain": gain, "power_state": power_state}

    async def _read_registers(self) -> list[tuple[int, int, int, int]]:
        """Read all channel registers from the device."""
        async with self._bus() as handle:
            buf = await handle.read_i2c_block_data(self._address, 0x00, 24)

        current_values = []
        for header, high_byte, low_byte, _, _, _ in self._chunk(buf, 6):
            value = (high_byte & 0b00001111) << 8 | low_byte
            vref, gain, power_state = self._get_flags(high_byte)
            current_values.append((value, vref, gain, power_state))

        return current_values

    async def save_settings(self) -> None:
        """Save current settings to EEPROM for all channels."""
        byte_list = []
        for channel in (self.channel_a, self.channel_b, self.channel_c, self.channel_d):
            byte_list.extend(self._generate_bytes_with_flags(channel))
        await self._write_multi_eeprom(byte_list)

    async def _write_multi_eeprom(self, byte_list: list[int]) -> None:
        """Write settings to EEPROM for all channels."""
        buffer_list = [_MCP4728_CH_A_MULTI_EEPROM] + byte_list
        async with self._bus() as handle:
            await handle.write_i2c_block_data(
                self._address, buffer_list[0], buffer_list[1:]
            )
        await asyncio.sleep(0.015)  # EEPROM write time

    async def sync_vrefs(self) -> None:
        """Sync Vref settings for all channels."""
        command = 0b10000000
        for i, channel in enumerate(
            (self.channel_a, self.channel_b, self.channel_c, self.channel_d)
        ):
            command |= await channel.get_vref() << (3 - i)

        async with self._bus() as handle:
            await handle.write_byte(self._address, command)

    async def sync_gains(self) -> None:
        """Sync gain settings for all channels."""
        command = 0b11000000
        for i, channel in enumerate(
            (self.channel_a, self.channel_b, self.channel_c, self.channel_d)
        ):
            command |= await channel.get_gain() << (3 - i)

        async with self._bus() as handle:
            await handle.write_byte(self._address, command)

    async def sync_power_states(self) -> None:
        """Sync power state settings for all channels."""
        command = 0b10100000
        for i, channel in enumerate(
            (self.channel_a, self.channel_b, self.channel_c, self.channel_d)
        ):
            command |= await channel.get_power_state() << (3 - i)

        async with self._bus() as handle:
            await handle.write_byte(self._address, command)

    async def _set_value(self, channel: _Channel) -> None:
        """Set the value for a specific channel."""
        channel_bytes = self._generate_bytes_with_flags(channel)
        write_command = 0b01000000 | (channel.channel_index << 1)
        async with self._bus() as handle:
            await handle.write_i2c_block_data(
                self._address, write_command, channel_bytes
            )

    @staticmethod
    def _chunk(data: bytearray, size: int) -> list[bytearray]:
        """Split data into chunks of specified size."""
        return [data[i : i + size] for i in range(0, len(data), size)]

    async def _general_call(self, command: int) -> None:
        """Send a general call command to all devices."""
        async with self._bus() as handle:
            await handle.write_byte(_MCP4728_GENERAL_CALL_ADDRESS, command)

    async def reset(self) -> None:
        """Reset the device and load EEPROM settings."""
        await self._general_call(_MCP4728_GENERAL_CALL_RESET_COMMAND)

    async def wakeup(self) -> None:
        """Wake up the device from power-down mode."""
        await self._general_call(_MCP4728_GENERAL_CALL_WAKEUP_COMMAND)

    async def soft_update(self) -> None:
        """Update all DAC outputs simultaneously."""
        await self._general_call(_MCP4728_GENERAL_CALL_SOFTWARE_UPDATE_COMMAND)

    @staticmethod
    def _generate_bytes_with_flags(channel: _Channel) -> list[int]:
        """Generate bytes for a channel with its flags."""
        value = channel._raw_value
        high_byte = (value >> 8) & 0xFF
        low_byte = value & 0xFF
        high_byte |= channel._vref << 7
        high_byte |= channel._gain << 4
        high_byte |= channel._power_state << 5
        return [high_byte, low_byte]
