import asyncio
import logging

from hil.drivers.aiosmbus2 import AsyncSMBus

_TCA6408_DEFAULT_ADDRESS = 0x20
_TCA6408_INPUT_REGISTER = 0x00
_TCA6408_OUTPUT_REGISTER = 0x01
_TCA6408_POLARITY_REGISTER = 0x02
_TCA6408_CONFIG_REGISTER = 0x03

logger = logging.getLogger(__name__)


class TCA6408:
    """
    TCA6408 8-bit I/O expander.

    :param AsyncSMBus bus: The I2C bus.
    :param int address: The I2C address of the device.
    """

    _bus: AsyncSMBus
    _address: int
    _gpio_state: int  # Internal state of GPIO pins
    _io_config: int   # Internal state of IO configuration (0=output, 1=input)

    def __init__(self) -> None:
        # Private constructor; use TCA6408.create() instead
        pass

    @classmethod
    async def create(cls, bus: AsyncSMBus, address: int = _TCA6408_DEFAULT_ADDRESS):
        """
        Asynchronously create an instance of TCA6408.
        """
        self = cls.__new__(cls)
        self._bus = bus
        self._address = address
        self._gpio_state = 0
        self._io_config = 0xFF  # Default all pins as inputs
        
        # Initialize by reading current state from device
        async with self._bus.handle() as handle:
            # Read Input Port register for initial GPIO state
            self._gpio_state = (await handle.read_i2c_block_data(self._address, _TCA6408_INPUT_REGISTER, 1))[0]
            # Read Configuration register for initial IO config
            self._io_config = (await handle.read_i2c_block_data(self._address, _TCA6408_CONFIG_REGISTER, 1))[0]
        
        return self
    
    def _set_gpio(self, channel: int, value: bool) -> None:
        """
        Update the internal GPIO state.
        
        :param channel: GPIO channel number (0-7)
        :param value: True to set high, False to set low
        """
        if value:
            self._gpio_state |= 1 << channel
        else:
            self._gpio_state &= ~(1 << channel)
    
    async def _write_gpio_state(self) -> None:
        """
        Write the current GPIO state to the device's Output Port register.
        """
        async with self._bus.handle() as handle:
            # Write to Output Port register
            await handle.write_i2c_block_data(self._address, _TCA6408_OUTPUT_REGISTER, [self._gpio_state])
        logger.debug(f"TCA6408 GPIO state set: {bin(self._gpio_state)}")
    
    def _set_io_config(self, channel: int, is_output: bool) -> None:
        """
        Update the internal IO configuration.
        
        :param channel: GPIO channel number (0-7)
        :param is_output: True to configure as output, False for input
        """
        if is_output:
            # Set bit to 0 for output
            self._io_config &= ~(1 << channel)
        else:
            # Set bit to 1 for input
            self._io_config |= (1 << channel)
    
    async def _write_io_config(self) -> None:
        """
        Write the current IO configuration to the device.
        """
        async with self._bus.handle() as handle:
            await handle.write_i2c_block_data(self._address, _TCA6408_CONFIG_REGISTER, [self._io_config])
        logger.debug(f"TCA6408 IO config set: {bin(self._io_config)}")
    
    async def read_gpio(self, channel: int) -> bool:
        """
        Read the state of a GPIO channel.
        
        :param channel: GPIO channel number (0-7)
        :return: True if high, False if low
        """
        # Update internal state from device's Input Port register
        async with self._bus.handle() as handle:
            # Read from Input Port register
            self._gpio_state = (await handle.read_i2c_block_data(self._address, _TCA6408_INPUT_REGISTER, 1))[0]
        return bool(self._gpio_state & (1 << channel))

    async def set_gpio(self, channel: int, value: bool) -> None:
        """
        Set the state of a GPIO channel.
        
        :param channel: GPIO channel number (0-7)
        :param value: True to set high, False to set low
        """
        self._set_gpio(channel, value)
        await self._write_gpio_state()
    
    async def set_gpio_bulk(self, values: dict[int, bool]) -> None:
        """
        Set multiple GPIO channels at once.
        
        :param values: Dictionary mapping channel numbers to boolean values
        """
        for channel, value in values.items():
            self._set_gpio(channel, value)
        await self._write_gpio_state()
    
    async def configure_io(self, channel: int, is_output: bool) -> None:
        """
        Configure a GPIO channel as input or output.
        
        :param channel: GPIO channel number (0-7)
        :param is_output: True to configure as output, False for input
        """
        self._set_io_config(channel, is_output)
        await self._write_io_config()
    
    async def configure_io_bulk(self, configs: dict[int, bool]) -> None:
        """
        Configure multiple GPIO channels at once.
        
        :param configs: Dictionary mapping channel numbers to boolean values
                       (True for output, False for input)
        """
        for channel, is_output in configs.items():
            self._set_io_config(channel, is_output)
        await self._write_io_config()
    
    async def get_all_gpio_states(self) -> dict[int, bool]:
        """
        Get the state of all GPIO channels.
        
        :return: Dictionary mapping channel numbers to boolean values
        """
        # Update internal state from device's Input Port register
        async with self._bus.handle() as handle:
            # Read from Input Port register
            self._gpio_state = (await handle.read_i2c_block_data(self._address, _TCA6408_INPUT_REGISTER, 1))[0]
        
        return {i: bool(self._gpio_state & (1 << i)) for i in range(8)}
    
    async def get_all_io_configs(self) -> dict[int, bool]:
        """
        Get the configuration of all GPIO channels.
        
        :return: Dictionary mapping channel numbers to boolean values
                (True for output, False for input)
        """
        # Update internal state from device's Input Port register
        async with self._bus.handle() as handle:
            # Read from Input Port register
            self._gpio_state = (await handle.read_i2c_block_data(self._address, _TCA6408_INPUT_REGISTER, 1))[0]
        
        return {i: not bool(self._io_config & (1 << i)) for i in range(8)}

    async def aclose(self):
        """
        Close the device connection.
        """
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.aclose()
