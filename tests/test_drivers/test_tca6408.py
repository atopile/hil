import asyncio
import logging
import pytest
from typing import Dict

from hil.drivers.aiosmbus2 import AsyncSMBusPeripheral, AsyncSMBusBranch
from hil.drivers.tca6408 import TCA6408
from hil.drivers.tca9548a import TCA9548A

logger = logging.getLogger(__name__)


class HilTCA6408:
    """
    Simulates a HIL for testing TCA6408 purposes, including MUX control.
    Assumes GPIO 0-2 are MUX select lines (S0-S2) and GPIO 3 is MUX enable (active high).
    """
    # Define MUX control pins (adjust if your hardware is different)
    MUX_S0_PIN = 0
    MUX_S1_PIN = 1
    MUX_S2_PIN = 2
    MUX_ENABLE_PIN = 3
    
    SELECT_PINS = [MUX_S0_PIN, MUX_S1_PIN, MUX_S2_PIN]
    CONTROL_PINS = SELECT_PINS + [MUX_ENABLE_PIN]

    tca: "TCA6408"
    physical_bus: AsyncSMBusPeripheral

    @classmethod
    async def create(cls):
        self = cls()
        # Create the physical bus but don't open it yet
        self.physical_bus = AsyncSMBusPeripheral(0)
        
        # Open the bus explicitly
        await self.physical_bus.open()
        
        # Create the TCA6408 device directly on the physical bus
        # Using address 0x20 as a common default, adjust if needed
        self.tca = await TCA6408.create(bus=self.physical_bus, address=0x20) 
        
        # Configure MUX control pins as outputs
        config = {pin: True for pin in cls.CONTROL_PINS}
        await self.tca.configure_io_bulk(config)
        
        # Initialize MUX to channel 0 and disabled
        await self.set_output(0)
        await self.disable()
        
        return self
        
    async def set_output(self, channel: int):
        """Sets the MUX output channel using the select pins."""
        if not 0 <= channel <= 7:
            raise ValueError("Channel must be between 0 and 7 for a 3-bit select.")
            
        select_states = {
            self.MUX_S0_PIN: bool(channel & 1),
            self.MUX_S1_PIN: bool(channel & 2),
            self.MUX_S2_PIN: bool(channel & 4),
        }
        logger.info(f"Setting MUX channel to {channel} (States: {select_states})")
        await self.tca.set_gpio_bulk(select_states)
        
    async def enable(self):
        """Enables the MUX output by setting the enable pin high."""
        logger.info("Enabling MUX")
        await self.tca.set_gpio(self.MUX_ENABLE_PIN, True)

    async def disable(self):
        """Disables the MUX output by setting the enable pin low."""
        logger.info("Disabling MUX")
        await self.tca.set_gpio(self.MUX_ENABLE_PIN, False)
    
    async def aclose(self):
        """Close all resources."""
        if hasattr(self, 'tca') and self.tca:
            await self.tca.aclose()
        if hasattr(self, 'physical_bus') and self.physical_bus:
            await self.physical_bus.close()


@pytest.fixture
async def hil_tca6408():
    # Create HIL instance
    hil_tca6408 = await HilTCA6408.create()
    try:
        yield hil_tca6408
    finally:
        # Ensure resources are cleaned up
        await hil_tca6408.aclose()


@pytest.mark.runs_on(hostname="tipsy-raccoon")
async def test_initialization(hil_tca6408):
    """Test that the TCA6408 initializes correctly."""
    # The fixture already creates the device, so if we get here, initialization worked
    assert hil_tca6408.tca is not None
    logger.info("TCA6408 initialized successfully")
    
    # Read the initial state of all pins
    initial_states = await hil_tca6408.tca.get_all_gpio_states()
    logger.info(f"Initial GPIO states: {initial_states}")
    
    # Read the initial configuration of all pins
    initial_configs = await hil_tca6408.tca.get_all_io_configs()
    logger.info(f"Initial IO configurations: {initial_configs}")


@pytest.mark.runs_on(hostname="tipsy-raccoon")
async def test_individual_pin_operations(hil_tca6408):
    """Test individual pin operations (set and read)."""
    # Configure all pins as outputs
    await hil_tca6408.tca.configure_io_bulk({i: True for i in range(8)})
    logger.info("All pins configured as outputs")
    
    # Wait for configuration to take effect
    await asyncio.sleep(0.1)
    
    # Read back the configuration to verify
    configs = await hil_tca6408.tca.get_all_io_configs()
    logger.info(f"IO configurations after setting as outputs: {configs}")
    
    # Test each pin individually
    for pin in range(8):
        # Set pin high
        await hil_tca6408.tca.set_gpio(pin, True)
        logger.info(f"Set pin {pin} high")
        
        # Read back the state
        state = await hil_tca6408.tca.read_gpio(pin)
        logger.info(f"Read pin {pin}: {state}")
        
        # Verify the state
        assert state is True, f"Pin {pin} should be high, but read as {state}"
        
        # Set pin low
        await hil_tca6408.tca.set_gpio(pin, False)
        logger.info(f"Set pin {pin} low")
        
        # Read back the state
        state = await hil_tca6408.tca.read_gpio(pin)
        logger.info(f"Read pin {pin}: {state}")
        
        # Verify the state
        assert state is False, f"Pin {pin} should be low, but read as {state}"


@pytest.mark.runs_on(hostname="tipsy-raccoon")
async def test_bulk_operations(hil_tca6408):
    """Test bulk operations for setting and reading GPIO states."""
    # Configure all pins as outputs
    await hil_tca6408.tca.configure_io_bulk({i: True for i in range(8)})
    logger.info("All pins configured as outputs")
    
    # Read back the configuration to verify
    configs = await hil_tca6408.tca.get_all_io_configs()
    logger.info(f"IO configurations after setting as outputs: {configs}")
    
    # Create a pattern of alternating high/low states
    pattern: Dict[int, bool] = {i: (i % 2 == 0) for i in range(8)}
    logger.info(f"Setting pattern: {pattern}")
    
    # Write the pattern
    await hil_tca6408.tca.set_gpio_bulk(pattern)
    
    # Read back all states
    states = await hil_tca6408.tca.get_all_gpio_states()
    logger.info(f"Read states: {states}")
    
    # Verify the states match the pattern
    for pin, expected in pattern.items():
        assert states[pin] == expected, f"Pin {pin} should be {expected}, but read as {states[pin]}"


@pytest.mark.runs_on(hostname="tipsy-raccoon")
async def test_io_configuration(hil_tca6408):
    """Test configuring pins as inputs and outputs."""
    # Configure pins as inputs
    await hil_tca6408.tca.configure_io_bulk({i: False for i in range(8)})
    logger.info("All pins configured as inputs")
    
    # Wait for configuration to take effect
    await asyncio.sleep(0.1)
    
    # Read back the configuration
    configs = await hil_tca6408.tca.get_all_io_configs()
    logger.info(f"IO configurations: {configs}")
    
    # Verify all pins are configured as inputs
    for pin, is_output in configs.items():
        assert is_output is False, f"Pin {pin} should be configured as input, but read as output"
    
    # Configure pins as outputs
    await hil_tca6408.tca.configure_io_bulk({i: True for i in range(8)})
    logger.info("All pins configured as outputs")
    
    # Wait for configuration to take effect
    await asyncio.sleep(0.1)
    
    # Read back the configuration
    configs = await hil_tca6408.tca.get_all_io_configs()
    logger.info(f"IO configurations: {configs}")
    
    # Verify all pins are configured as outputs
    for pin, is_output in configs.items():
        assert is_output is True, f"Pin {pin} should be configured as output, but read as input"


@pytest.mark.runs_on(hostname="tipsy-raccoon")
async def test_mixed_io_configuration(hil_tca6408):
    """Test configuring some pins as inputs and others as outputs."""
    # Configure even pins as outputs and odd pins as inputs
    config = {i: (i % 2 == 0) for i in range(8)}
    await hil_tca6408.tca.configure_io_bulk(config)
    logger.info(f"Configured pins: {config}")
    
    # Wait for configuration to take effect
    await asyncio.sleep(0.1)
    
    # Read back the configuration
    configs = await hil_tca6408.tca.get_all_io_configs()
    logger.info(f"IO configurations: {configs}")
    
    # Verify the configuration
    for pin, is_output in configs.items():
        expected = pin % 2 == 0
        assert is_output == expected, f"Pin {pin} should be configured as {'output' if expected else 'input'}, but read as {'output' if is_output else 'input'}"


@pytest.mark.runs_on(hostname="tipsy-raccoon")
async def test_direct_register_access(hil_tca6408):
    """Test direct register access to verify the device is working correctly."""
    # Configure all pins as outputs
    await hil_tca6408.tca.configure_io_bulk({i: True for i in range(8)})
    logger.info("All pins configured as outputs")
    
    # Wait for configuration to take effect
    await asyncio.sleep(0.1)
    
    # Read the current state of all pins
    initial_states = await hil_tca6408.tca.get_all_gpio_states()
    logger.info(f"Initial GPIO states: {initial_states}")
    
    # Set all pins high
    await hil_tca6408.tca.set_gpio_bulk({i: True for i in range(8)})
    logger.info("Set all pins high")
    
    # Wait for the pins to settle
    await asyncio.sleep(0.1)
    
    # Read back all states
    states = await hil_tca6408.tca.get_all_gpio_states()
    logger.info(f"Read states after setting all high: {states}")
    
    # Verify all pins are high
    for pin, state in states.items():
        assert state is True, f"Pin {pin} should be high, but read as {state}"
    
    # Set all pins low
    await hil_tca6408.tca.set_gpio_bulk({i: False for i in range(8)})
    logger.info("Set all pins low")
    
    # Wait for the pins to settle
    await asyncio.sleep(0.1)
    
    # Read back all states
    states = await hil_tca6408.tca.get_all_gpio_states()
    logger.info(f"Read states after setting all low: {states}")
    
    # Verify all pins are low
    for pin, state in states.items():
        assert state is False, f"Pin {pin} should be low, but read as {state}"
