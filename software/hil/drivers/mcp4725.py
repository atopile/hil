import time
from smbus2 import SMBus
from typing import Optional  # <-- added for type hinting

# Internal constants:
_MCP4725_DEFAULT_ADDRESS = 0x62
_MCP4725_WRITE_FAST_MODE = 0b00000000
_MCP4725_WRITE_DAC_EEPROM = 0b01100000


class MCP4725:
    """
    MCP4725 12-bit digital to analog converter.

    :param int bus_number: The I2C bus number.
    :param int address: The I2C address of the device.
    """

    # Modified __init__ method to accept an optional 'i2c' parameter.
    def __init__(
        self,
        bus_number: int = 1,
        address: int = _MCP4725_DEFAULT_ADDRESS,
        i2c: Optional[SMBus] = None,
    ) -> None:
        if i2c is not None:
            self._bus = i2c
        else:
            self._bus = SMBus(bus_number)
        self._address = address

    def _write_fast_mode(self, val: int) -> None:
        """Perform a 'fast mode' write to update the DAC value."""
        assert 0 <= val <= 4095
        val &= 0xFFF
        buffer = [_MCP4725_WRITE_FAST_MODE | (val >> 8), val & 0xFF]
        self._bus.write_i2c_block_data(self._address, buffer[0], buffer[1:])

    def _read(self) -> int:
        """Read the DAC value and return the 12-bit value."""
        data = self._bus.read_i2c_block_data(self._address, 0x00, 3)
        dac_high = data[1]
        dac_low = data[2] >> 4
        return ((dac_high << 4) | dac_low) & 0xFFF

    @property
    def value(self) -> int:
        """Get or set the DAC value as a 16-bit unsigned value."""
        return self._read() << 4

    @value.setter
    def value(self, val: int) -> None:
        assert 0 <= val <= 65535
        self._write_fast_mode(val >> 4)

    @property
    def raw_value(self) -> int:
        """Get or set the DAC value as a 12-bit unsigned value."""
        return self._read()

    @raw_value.setter
    def raw_value(self, val: int) -> None:
        assert 0 <= val <= 4095
        self._write_fast_mode(val)

    @property
    def normalized_value(self) -> float:
        """Get or set the DAC value as a float between 0.0 and 1.0."""
        return self._read() / 4095.0

    @normalized_value.setter
    def normalized_value(self, val: float) -> None:
        assert 0.0 <= val <= 1.0
        self._write_fast_mode(int(val * 4095.0))

    def save_to_eeprom(self) -> None:
        """Store the current DAC value in EEPROM."""
        current_value = self._read()
        buffer = [
            _MCP4725_WRITE_DAC_EEPROM,
            (current_value >> 4) & 0xFF,
            (current_value << 4) & 0xFF,
        ]
        self._bus.write_i2c_block_data(self._address, buffer[0], buffer[1:])

        # Wait for EEPROM write to complete
        while True:
            time.sleep(0.05)
            status = self._bus.read_byte(self._address)
            if status & 0x80:
                break
