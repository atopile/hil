from enum import IntEnum
import logging
import numpy as np
from hil.drivers.ads1x15 import ADS1115
from hil.drivers.aiosmbus2 import AsyncSMBus
from hil.drivers.mcp4725 import MCP4725

logger = logging.getLogger(__name__)

# I2C Addresses


class Cell:
    cell_num: int
    mux_channel: int
    bus: AsyncSMBus
    enabled: bool
    adc: ADS1115
    buck_dac: MCP4725
    ldo_dac: MCP4725
    _gpio_state: int

    class Devices(IntEnum):
        LDO = 0x60
        BUCK = 0x61
        ADC = 0x48
        GPIO = 0x20

    class GpioChannels(IntEnum):
        BUCK_ENABLE = 2
        LDO_ENABLE = 3
        LOAD_SWITCH_CONTROL = 4
        OUTPUT_RELAY_CONTROL = 5

    class AdcChannels(IntEnum):
        BUCK_VOLTAGE = 0
        LDO_VOLTAGE = 1
        OUTPUT_CURRENT = 2
        OUTPUT_VOLTAGE = 3

    # Shunt resistor and gain
    SHUNT_RESISTOR_OHMS = 0.11128
    SHUNT_GAIN = 50

    # Voltage limits
    MIN_BUCK_VOLTAGE = 1.5
    MAX_BUCK_VOLTAGE = 4.55
    MIN_LDO_VOLTAGE = 0.35
    MAX_LDO_VOLTAGE = 4.5

    def __init__(self):
        # Private constructor; use create() instead.
        pass

    @classmethod
    async def create(cls, cell_num, bus: AsyncSMBus):
        """
        Initialize the cell.
        If mux_channel is not specified, it will use cell_num % 8.
        Note: Do not call async methods here.
        """
        self = cls.__new__(cls)
        self.cell_num = cell_num
        self.bus = bus
        self.enabled = False
        self.adc = None  # will be created asynchronously in init()
        self.buck_dac = await MCP4725.create(bus, self.Devices.BUCK)
        self.ldo_dac = await MCP4725.create(bus, self.Devices.LDO)
        self.adc = await ADS1115.create(self.bus, self.Devices.ADC)
        self.buck_calibration = [[234, 4.5971], [2625, 1.5041]]
        self.ldo_calibration = [[42, 4.5176], [3760, 0.3334]]
        self._gpio_state = (
            0x00  # 8-bit register representing the current state of GPIO pins.
        )
        await self.reset()

        return self

    async def reset(self):
        """
        Reset the cell.
        - Clears the GPIO state.
        - Resets the ADC gain.
        """
        async with self.bus() as handle:
            await handle.write_byte_data(self.Devices.GPIO, 0x03, 0x00)
            await handle.write_byte_data(self.Devices.GPIO, 0x01, 0x00)

        await self.adc.set_adc_config(gain=ADS1115.GainConfig.UPTO_6_144V)

    def _set_gpio(self, channel: GpioChannels, value: bool):
        if value:
            self._gpio_state |= 1 << channel
        else:
            self._gpio_state &= ~(1 << channel)

    async def _write_gpio_state(self):
        """
        Update the state of the GPIO expander.
        Writes the current GPIO_STATE to the output register.
        """
        async with self.bus() as handle:
            await handle.write_byte_data(self.Devices.GPIO, 0x01, self._gpio_state)
        logger.debug(f"[Cell {self.cell_num}] GPIO state set: {bin(self._gpio_state)}")

    async def enable(self):
        """
        Enable the cell by setting the buck and LDO enable pins high.
        """
        if self.enabled:
            return

        self._set_gpio(self.GpioChannels.BUCK_ENABLE, True)
        self._set_gpio(self.GpioChannels.LDO_ENABLE, True)
        await self._write_gpio_state()
        self.enabled = True
        logger.debug(f"[Cell {self.cell_num}] Enabled")

    async def disable(self):
        """
        Disable the cell by clearing the buck and LDO enable pins.
        """
        if not self.enabled:
            return

        self._set_gpio(self.GpioChannels.BUCK_ENABLE, False)
        self._set_gpio(self.GpioChannels.LDO_ENABLE, False)
        await self._write_gpio_state()
        self.enabled = False
        logger.debug(f"[Cell {self.cell_num}] Disabled")

    async def get_voltage(self, channel=AdcChannels.OUTPUT_VOLTAGE):
        """
        Read the cell output voltage.
        """
        # Read raw ADC count from the specified channel
        raw = await self.adc.read_pin(channel)
        # Convert the raw ADC value to voltage with a 4.096V reference
        volts = raw * (6.144 / 32767.0)
        logger.debug(f"[Cell {self.cell_num}] Voltage read: {volts:.3f} V (raw: {raw})")
        return volts

    async def set_voltage(self, voltage):
        """
        Set the target voltage.
        Computes buck and LDO voltages, clamps them, and sets each output.
        """
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

        logger.debug(
            f"[Cell {self.cell_num}] Setting voltages: buck={buck_voltage:.2f}V, ldo={ldo_voltage:.2f}V"
        )
        await self._set_buck_voltage(buck_voltage)
        await self._set_ldo_voltage(ldo_voltage)

    async def calibrate(self, data_points: int = 8):
        """
        Calibrate the buck and LDO voltages.
        """

        self.buck_calibration = []
        self.ldo_calibration = []
        await self.enable()

        for digital_value in np.linspace(2625, 234, num=data_points, dtype=int):
            await self.buck_dac.set_raw_value(int(digital_value))
            volts_buck = await self.adc.read_pin(self.AdcChannels.BUCK_VOLTAGE) * (
                6.144 / 32767.0
            )
            self.buck_calibration.append([int(digital_value), volts_buck])

        self.buck_dac.set_raw_value(234)
        for digital_value in np.linspace(3760, 42, num=data_points, dtype=int):
            await self.ldo_dac.set_raw_value(int(digital_value))
            volts_ldo = await self.adc.read_pin(self.AdcChannels.LDO_VOLTAGE) * (
                6.144 / 32767.0
            )
            self.ldo_calibration.append([int(digital_value), volts_ldo])

        logger.info(f"[Cell {self.cell_num}] Buck calibration: {self.buck_calibration}")
        logger.info(f"[Cell {self.cell_num}] LDO calibration: {self.ldo_calibration}")

    def _calculate_setpoint(self, voltage: float, calibration: list[tuple[int, float]]):
        """
        Calculate the DAC setpoint using linear regression over all calibration points.
        """
        n = len(calibration)
        total_voltage = 0.0
        total_setpoint = 0.0
        for setp, volt in calibration:
            total_setpoint += setp
            total_voltage += volt
        avg_voltage = total_voltage / n
        avg_setpoint = total_setpoint / n

        numerator = 0.0
        denominator = 0.0
        for setp, volt in calibration:
            numerator += (volt - avg_voltage) * (setp - avg_setpoint)
            denominator += (volt - avg_voltage) ** 2

        if denominator == 0:
            return int(round(avg_setpoint))

        m = numerator / denominator
        b = avg_setpoint - m * avg_voltage

        predicted_setpoint = m * voltage + b
        return int(round(predicted_setpoint))

    async def _set_buck_voltage(self, voltage):
        """
        Set the buck converter voltage.
        """
        setpoint = self._calculate_setpoint(voltage, self.buck_calibration)
        await self.buck_dac.set_raw_value(setpoint)

    async def _set_ldo_voltage(self, voltage):
        """
        Set the LDO voltage.
        """
        setpoint = self._calculate_setpoint(voltage, self.ldo_calibration)
        await self.ldo_dac.set_raw_value(setpoint)

    async def turn_on_output_relay(self):
        """
        Turn on the output relay.
        """
        self._set_gpio(self.GpioChannels.OUTPUT_RELAY_CONTROL, True)
        await self._write_gpio_state()
        logger.debug(f"[Cell {self.cell_num}] Output relay turned ON")

    async def turn_off_output_relay(self):
        """
        Turn off the output relay.
        """
        self._set_gpio(self.GpioChannels.OUTPUT_RELAY_CONTROL, False)
        await self._write_gpio_state()
        logger.debug(f"[Cell {self.cell_num}] Output relay turned OFF")

    async def close_load_switch(self):
        """
        Turn on the load switch.
        """
        self._set_gpio(self.GpioChannels.LOAD_SWITCH_CONTROL, True)
        await self._write_gpio_state()
        logger.debug(f"[Cell {self.cell_num}] Load switch turned ON")

    async def open_load_switch(self):
        """
        Turn off the load switch.
        """
        self._set_gpio(self.GpioChannels.LOAD_SWITCH_CONTROL, False)
        await self._write_gpio_state()
        logger.debug(f"[Cell {self.cell_num}] Load switch turned OFF")

    async def get_current(self):
        """
        Read the cell current.
        """
        raw = await self.adc.read_pin(self.AdcChannels.OUTPUT_CURRENT)
        volts = raw * (6.144 / 32767.0)
        current = volts / (self.SHUNT_RESISTOR_OHMS * self.SHUNT_GAIN)
        logger.debug(f"[Cell {self.cell_num}] Current read: {current:.2f} A")
        return current

    async def read_shunt_current(self):
        """
        Read current using the shunt resistor.
        """
        shunt_voltage = await self.adc.read_pin(self.AdcChannels.OUTPUT_CURRENT)
        current = shunt_voltage / self.SHUNT_RESISTOR_OHMS / self.SHUNT_GAIN
        return current

    async def __str__(self):
        return f"Cell {self.cell_num} | Bus: {self.bus} | Enabled: {self.enabled}"

    async def aclose(self):
        await self.turn_off_output_relay()
        await self.disable()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.aclose()
