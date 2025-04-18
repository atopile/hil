import asyncio
import logging
from enum import IntEnum
from typing import Dict, List
from hil.drivers.aiosmbus2 import AsyncSMBus
from hil.drivers.tca6408 import TCA6408

logger = logging.getLogger(__name__)

class GpioMux:
    bus: AsyncSMBus
    gpio_expander: TCA6408

    class TcaPinout(IntEnum):
        """
        TCA6408 GPIO pin mapping for multiplexer control
        """
        S2 = 1  # Select bit 2 (MSB)
        S1 = 2  # Select bit 1
        S0 = 3  # Select bit 0 (LSB)
        DATA = 4  # Shared data line
        ENABLE = 5  # Active low enable
    
    # Define select pins in order from LSB to MSB
    SELECT_PINS = [TcaPinout.S0, TcaPinout.S1, TcaPinout.S2]
    
    def __init__(self):
        """
        Private constructor. Use create() instead.
        """
        self.bus = None
        self.gpio_expander = None
        self._address = None
    
    @classmethod
    async def create(cls, bus: AsyncSMBus, address: int = 0x20):
        """
        Create and initialize a new GpioMux instance.
        
        Args:
            bus: The I2C bus to use
            address: The I2C address of the TCA6408 GPIO expander
            
        Returns:
            An initialized GpioMux instance
        """
        self = cls()
        self.bus = bus
        self._address = address
        
        # Create the TCA6408 instance
        self.gpio_expander = await TCA6408.create(bus=self.bus, address=self._address)
        
        # Configure all control pins as outputs
        config = {pin: True for pin in self.TcaPinout}
        await self.gpio_expander.configure_io_bulk(config)
        
        # Initialize to a known state (channel 0, disabled)
        await self.set_output(0)
        await self.disable()
        
        logger.info("GPIO MUX initialized")
        return self
    
    async def set_output(self, channel: int):
        """
        Set the MUX output channel using the select bits.
        
        Args:
            channel: The channel to select (0-7)
        """
        if not 0 <= channel <= 7:
            raise ValueError("Channel must be between 0 and 7")
        
        # Create a dictionary mapping each select pin to its state
        select_states = {}
        for i, pin in enumerate(self.SELECT_PINS):
            select_states[pin] = bool(channel & (1 << i))
        
        # Set the select pins
        await self.gpio_expander.set_gpio_bulk(select_states)
        
        # Log the channel and pin states
        pin_states = {pin.name: state for pin, state in select_states.items()}
        logger.info(f"Set MUX output to channel {channel} (Pin states: {pin_states})")
    
    async def enable(self):
        """
        Enable the MUX by setting the enable pin low (active low).
        Also sets the data pin high.
        """
        await self.gpio_expander.set_gpio_bulk({
            self.TcaPinout.ENABLE: False,  # Active low
            self.TcaPinout.DATA: True      # Set data pin high
        })
        logger.info("MUX enabled")
    
    async def disable(self):
        """
        Disable the MUX by setting the enable pin high (active low).
        Also sets the data pin low.
        """
        await self.gpio_expander.set_gpio_bulk({
            self.TcaPinout.ENABLE: True,   # Active low
            self.TcaPinout.DATA: False     # Set data pin low
        })
        logger.info("MUX disabled")
    
    async def aclose(self):
        """
        Close the GPIO expander connection.
        """
        if self.gpio_expander:
            await self.gpio_expander.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.aclose()
    
