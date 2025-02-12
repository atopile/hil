import asyncio
from multiprocessing import BufferTooShort
import time
import ADS1x15
import logging
from asyncI2C import AsyncSMBus
from mcp4725 import MCP4725
import pyinstrument

# logger = logging.getLogger(__name__)
# logger.info
# logger.warning
# logger.debug

# I2C Addresses

MUX_ADDRESS = 0x70
LDO_ADDRESS = 0x60
BUCK_ADDRESS = 0x61
ADC_ADDRESS = 0x48
GPIO_ADDRESS = 0x20
TCA6408_ADDR = 0x20  # Using same value as GPIO_ADDRESS

class Cell:
    def __init__(self, cell_num, bus: AsyncSMBus, mux_channel=None):
        """
        Initialize the cell.
        If mux_channel is not specified, it will use cell_num % 8.
        Note: Do not call async methods here.
        """
        self.cell_num = cell_num
        self.mux_channel = mux_channel if mux_channel is not None else cell_num % 8
        self.bus = bus
        self.enabled = False
        self.adc = None  # will be created asynchronously in init()
        self.buck_dac = MCP4725(address=0x61)
        self.ldo_dac = MCP4725(address=0x60)

        # Mapping for GPIO expander pins
        self.GPIO = {
            'buck_enable': 2,
            'ldo_enable': 3,
            'load_switch_control': 4,
            'output_relay_control': 5
        }
        # Mapping for ADC channels 
        self.adc_channels = {
            'adc_buck_voltage': 0,
            'adc_ldo_voltage': 1,
            'adc_output_current': 2,
            'adc_output_voltage': 3
        }
        # 8-bit register representing the current state of GPIO pins.
        self.GPIO_STATE = 0x00

        # Shunt resistor and gain
        self.SHUNT_RESISTOR_OHMS = 0.11128
        self.SHUNT_GAIN = 50

        # Voltage limits
        self.MIN_BUCK_VOLTAGE = 1.5
        self.MAX_BUCK_VOLTAGE = 4.55
        self.MIN_LDO_VOLTAGE = 0.35
        self.MAX_LDO_VOLTAGE = 4.5

        # Calibration points: each tuple is (setpoint, voltage)
        self.BUCK_SETPOINTS = [(234, 4.5971), (2625, 1.5041)]
        self.LDO_SETPOINTS = [(42, 4.5176), (3760, 0.3334)]
        # Initialize ADC gain later in async init.
    
    async def set_mux(self, verbose=False):
        """
        Select the correct MUX channel.
        Writes 1 << mux_channel to the mux address.
        """
        value = 1 << self.mux_channel
        await self.bus.write_byte(MUX_ADDRESS, value)
        if verbose:
            print(f"[Cell {self.cell_num}] MUX set: channel {self.mux_channel} (value: {hex(value)})")
    
    async def init(self):
        """
        Initialize the cell.
        - Sets the MUX.
        - Configures the GPIO expander.
        """
        # await self.set_mux()
        await self.bus.write_byte_data(GPIO_ADDRESS, 0x03, 0x00)
        await self.bus.write_byte_data(GPIO_ADDRESS, 0x01, 0x00)
        self.adc = await ADS1x15.ADS1115.create(1)
        await self.adc.setGain(0)
    
    async def set_GPIO_state(self):
        """
        Update the state of the GPIO expander.
        Writes the current GPIO_STATE to the output register.
        """
        # await self.set_mux()
        await self.bus.write_byte_data(TCA6408_ADDR, 0x01, self.GPIO_STATE)
        # logger.debug(f"[Cell {self.cell_num}] GPIO state set: {bin(self.GPIO_STATE)}")
    
    async def enable(self):
        """
        Enable the cell by setting the buck and LDO enable pins high.
        """
        await self.set_mux()
        self.GPIO_STATE |= (1 << self.GPIO['buck_enable'])
        self.GPIO_STATE |= (1 << self.GPIO['ldo_enable'])
        await self.set_GPIO_state()
        self.enabled = True
        # logger.debug(f"[Cell {self.cell_num}] Enabled")
    
    async def disable(self):
        """
        Disable the cell by clearing the buck and LDO enable pins.
        """
        # await self.set_mux()
        self.GPIO_STATE &= ~(1 << self.GPIO['buck_enable'])
        self.GPIO_STATE &= ~(1 << self.GPIO['ldo_enable'])
        await self.set_GPIO_state()
        self.enabled = False
        # logger.debug(f"[Cell {self.cell_num}] Disabled")
    
    async def get_voltage(self, verbose=False):
        """
        Read the cell output voltage.
        """
        # await self.set_mux()
        # Read raw ADC count from the specified channel
        raw = await self.adc.readADC(self.adc_channels['adc_output_voltage'])
        # Convert the raw ADC value to voltage with a 4.096V reference
        volts = raw * (6.144/ 32767.0)
        # logger.debug(f"[Cell {self.cell_num}] Voltage read: {volts:.3f} V (raw: {raw})")
        if verbose:
            raw_ldo = await self.adc.readADC(self.adc_channels['adc_ldo_voltage'])
            raw_buck = await self.adc.readADC(self.adc_channels['adc_buck_voltage'])
            volts_buck = raw_buck * (6.144 / 32767.0)
            volts_ldo = raw_ldo * (6.144/ 32767.0)
            # logger.debug(f"[Cell {self.cell_num}] Voltage buck read: {volts_buck:.3f} V (raw: {raw_buck})")
            # logger.debug(f"[Cell {self.cell_num}] Voltage ldo read: {volts_ldo:.3f} V (raw: {raw_ldo})")
        return volts
    
    async def set_voltage(self, voltage):
        """
        Set the target voltage.
        Computes buck and LDO voltages, clamps them, and sets each output.
        """
        # await self.set_mux()
        buck_voltage = voltage * 1.05
        ldo_voltage = voltage
        
        if buck_voltage < self.MIN_BUCK_VOLTAGE:
            buck_voltage = self.MIN_BUCK_VOLTAGE
        if buck_voltage > self.MAX_BUCK_VOLTAGE:
            buck_voltage = self.MAX_BUCK_VOLTAGE
        if ldo_voltage < self.MIN_LDO_VOLTAGE:
            ldo_voltage = self.MIN_LDO_VOLTAGE
        if ldo_voltage > self.MAX_LDO_VOLTAGE:
            ldo_voltage = self.MAX_LDO_VOLTAGE
        
        # logger.debug(f"[Cell {self.cell_num}] Setting voltage: target {voltage:.2f} V, Buck {buck_voltage:.2f} V, LDO {ldo_voltage:.2f} V")
        await self.set_buck_voltage(buck_voltage)
        await self.set_ldo_voltage(ldo_voltage)

        # FIXME: wait for stabalisation here
    
    async def calculate_setpoint(self, voltage, use_buck_calibration=True):
        """
        Calculate the DAC setpoint with linear calibration.
        """
        calibration = self.BUCK_SETPOINTS if use_buck_calibration else self.LDO_SETPOINTS
        m = (calibration[1][0] - calibration[0][0]) / (calibration[1][1] - calibration[0][1])
        b = calibration[0][0] - m * calibration[0][1]
        setpoint = int(m * voltage + b)
        mode = "Buck" if use_buck_calibration else "LDO"
        # logger.debug(f"[Cell {self.cell_num}] {mode} setpoint calculated: {setpoint} for voltage {voltage:.2f} V")
        return setpoint
    
    async def set_buck_voltage(self, voltage):
        """
        Set the buck converter voltage.
        """
        # await self.set_mux()
        setpoint = await self.calculate_setpoint(voltage, use_buck_calibration=True)
        # logger.debug(f"[Cell {self.cell_num}] Buck DAC set to {setpoint} (voltage: {voltage:.2f} V)")
        self.buck_dac.raw_value = setpoint

    async def set_ldo_voltage(self, voltage):
        """
        Set the LDO voltage.
        """
        # await self.set_mux()
        setpoint = await self.calculate_setpoint(voltage, use_buck_calibration=False)
        # logger.debug(f"[Cell {self.cell_num}] LDO DAC set to {setpoint} (voltage: {voltage} V)")
        self.ldo_dac.raw_value = setpoint

    async def turn_on_output_relay(self):
        """
        Turn on the output relay.
        """
        # await self.set_mux()
        self.GPIO_STATE |= (1 << self.GPIO['output_relay_control'])
        await self.set_GPIO_state()
        # logger.debug(f"[Cell {self.cell_num}] Output relay turned ON")
    
    async def turn_off_output_relay(self):
        """
        Turn off the output relay.
        """
        # await self.set_mux()
        self.GPIO_STATE &= ~(1 << self.GPIO['output_relay_control'])
        await self.set_GPIO_state()
        # logger.debug(f"[Cell {self.cell_num}] Output relay turned OFF")
    
    async def turn_on_load_switch(self):
        """
        Turn on the load switch.
        """
        # await self.set_mux()
        self.GPIO_STATE |= (1 << self.GPIO['load_switch_control'])
        await self.set_GPIO_state()
        # logger.debug(f"[Cell {self.cell_num}] Load switch turned ON")
    
    async def turn_off_load_switch(self):
        """
        Turn off the load switch.
        """
        # await self.set_mux()
        self.GPIO_STATE &= ~(1 << self.GPIO['load_switch_control'])
        await self.set_GPIO_state()
        # logger.debug(f"[Cell {self.cell_num}] Load switch turned OFF")
    
    async def get_current(self):
        """
        Read the cell current.
        """
        # await self.set_mux()
        current = await self.read_shunt_current()
        # logger.debug(f"[Cell {self.cell_num}] Current read: {current:.2f} A")
        return current
    
    async def read_shunt_current(self):
        """
        Read current using the shunt resistor.
        """
        # await self.set_mux()
        shunt_voltage = await self.adc.readADC(self.adc_channels['adc_output_current'])
        current = shunt_voltage / self.SHUNT_RESISTOR_OHMS / self.SHUNT_GAIN
        return current
    
    async def __str__(self):
        return f"Cell {self.cell_num} | Mux Channel: {self.mux_channel} | Enabled: {self.enabled}"

# Example usage:
async def main():
    bus = await AsyncSMBus.create(1)
    test_cell = Cell(0, bus)
    cells: list[Cell] = []
    for x in range (0,8):
        cells.append(Cell(x, bus))

    with pyinstrument.Profiler() as profiler:
        for cell in cells:
            await cell.init()

        for _ in range(10):
            for cell in cells:
                await cell.enable()
                await cell.set_voltage(1)
                await cell.turn_on_output_relay()
                await cell.turn_on_load_switch()

                await cell.get_voltage()
                await cell.get_current()

                await cell.turn_off_load_switch()
                await cell.turn_off_output_relay()
                await cell.disable()

        await bus.close()

    profiler.write_html("trace.html")

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(main())
