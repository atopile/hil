import asyncio

from hil.drivers.aiosmbus2 import AsyncSMBus

_MCP4725_DEFAULT_ADDRESS = 0x62
_MCP4725_WRITE_FAST_MODE = 0b00000000
_MCP4725_WRITE_DAC_EEPROM = 0b01100000


class MCP4725:
    """
    MCP4725 12-bit digital to analog converter.

    :param AsyncSMBus bus: The I2C bus.
    :param int address: The I2C address of the device.
    """

    _bus: AsyncSMBus
    _address: int

    def __init__(self) -> None:
        # Private constructor; use MCP4725.create() instead
        pass

    @classmethod
    async def create(cls, bus: AsyncSMBus, address: int = _MCP4725_DEFAULT_ADDRESS):
        """
        Asynchronously create an instance of MCP4725.
        """
        self = cls.__new__(cls)
        self._bus = bus
        self._address = address
        return self

    async def _write_fast_mode(self, val: int) -> None:
        """Perform a 'fast mode' write to update the DAC value."""
        assert 0 <= val <= 4095
        val &= 0xFFF
        buffer = [_MCP4725_WRITE_FAST_MODE | (val >> 8), val & 0xFF]
        async with self._bus() as handle:
            await handle.write_i2c_block_data(self._address, buffer[0], buffer[1:])

    async def _read(self) -> int:
        """Read the DAC value and return the 12-bit value."""
        async with self._bus() as handle:
            data = await handle.read_i2c_block_data(self._address, 0x00, 3)
        dac_high = data[1]
        dac_low = data[2] >> 4
        return ((dac_high << 4) | dac_low) & 0xFFF

    async def get_value(self) -> int:
        """Get the DAC value as a 16-bit unsigned value."""
        return (await self._read()) << 4

    async def set_value(self, val: int) -> None:
        """Set the DAC value as a 16-bit unsigned value."""
        assert 0 <= val <= 65535
        await self._write_fast_mode(val >> 4)

    async def get_raw_value(self) -> int:
        """Get the DAC value as a 12-bit unsigned value."""
        return await self._read()

    async def set_raw_value(self, val: int) -> None:
        """Set the DAC value as a 12-bit unsigned value."""
        assert 0 <= val <= 4095
        await self._write_fast_mode(val)

    async def get_normalized_value(self) -> float:
        """Get the DAC value as a float between 0.0 and 1.0."""
        return (await self._read()) / 4095.0

    async def set_normalized_value(self, val: float) -> None:
        """Set the DAC value as a float between 0.0 and 1.0."""
        assert 0.0 <= val <= 1.0
        await self._write_fast_mode(int(val * 4095.0))

    async def save_to_eeprom(self) -> None:
        """Store the current DAC value in EEPROM."""
        current_value = await self._read()
        buffer = [
            _MCP4725_WRITE_DAC_EEPROM,
            (current_value >> 4) & 0xFF,
            (current_value << 4) & 0xFF,
        ]
        async with self._bus() as handle:
            await handle.write_i2c_block_data(self._address, buffer[0], buffer[1:])

        # Wait for EEPROM write to complete
        while True:
            await asyncio.sleep(0.05)  # Use asyncio.sleep instead of time.sleep
            async with self._bus() as handle:
                status = await handle.read_byte(self._address)
            if status & 0x80:
                break
