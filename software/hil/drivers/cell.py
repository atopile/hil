import asyncio
import polars as pl
from datetime import datetime
from enum import IntEnum
import logging
from hil.utils.config import ConfigDict
import numpy as np
from hil.drivers.ads1x15 import ADS1115
from hil.drivers.aiosmbus2 import AsyncSMBus
from hil.drivers.mcp4725 import MCP4725

from hil.framework import record, Recorder, Trace, Calibration

logger = logging.getLogger(__name__)


class Cell:
    cell_num: int
    mux_channel: int
    bus: AsyncSMBus
    enabled: bool
    adc: ADS1115
    buck_dac: MCP4725
    ldo_dac: MCP4725
    _gpio_state: int
    _buck_calibration: Calibration
    _ldo_calibration: Calibration

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

    MIN_BUCK_VOLTAGE = 1.5
    MAX_BUCK_VOLTAGE = 4.55
    MIN_LDO_VOLTAGE = 0.35

    def __init__(self):
        # Private constructor; use create() instead.
        pass

    @classmethod
    async def create(cls, cell_num, bus: AsyncSMBus, config: ConfigDict):
        """
        Initialize the cell.
        If mux_channel is not specified, it will use cell_num % 8.
        Note: Do not call async methods here.
        """
        self = cls.__new__(cls)
        self.cell_num = cell_num
        self.bus = bus
        self.enabled = False
        self.buck_dac = await MCP4725.create(bus, self.Devices.BUCK)
        self.ldo_dac = await MCP4725.create(bus, self.Devices.LDO)
        self.adc = await ADS1115.create(self.bus, self.Devices.ADC)
        self._buck_calibration = Calibration.from_config(config["buck_calibration"], [1.5041, 4.5971], [2625, 234])
        self._ldo_calibration = Calibration.from_config(config["ldo_calibration"], [0.228, 4.4], [3760, 42])
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

    @staticmethod
    def _dropout_voltage(vout: float):
        """
        .                     | typ   | max
        0.65 V ≤ Vout < 0.8 V | 896mV | 1050mV
        0.8 V ≤ Vout < 0.9 V  | 765mV | 920mV
        0.9 V ≤ Vout < 1.0 V  | 700mV | 850mV
        1.0 V ≤ Vout < 1.2 V  | 600mV | 750mV
        1.2 V ≤ Vout < 1.5 V  | 464mV | 585mV
        1.5 V ≤ Vout < 1.8 V  | 332mV | 440mV
        1.8 V ≤ Vout < 2.5 V  | 264mV | 360mV
        2.5 V ≤ Vout < 3.3 V  | 193mV | 270mV
        3.3 V ≤ Vout ≤ 5.5 V  | 161mV | 225mV
        """
        if vout < 0.65:
            return 1.05
        elif vout < 0.8:
            return 0.92
        elif vout < 0.9:
            return 0.85
        elif vout < 1.0:
            return 0.75
        elif vout < 1.2:
            return 0.7
        elif vout < 1.5:
            return 0.585
        elif vout < 1.8:
            return 0.332
        elif vout < 2.5:
            return 0.360
        elif vout < 3.3:
            return 0.270
        else:
            return 0.225

    async def set_voltage(self, voltage: float):
        """
        Set the target voltage.
        Computes buck and LDO voltages, clamps them, and sets each output.
        """
        if voltage < self.MIN_LDO_VOLTAGE:
            raise ValueError(
                f"Voltage {voltage} is below the minimum LDO voltage of {self.MIN_LDO_VOLTAGE}"
            )

        buck_voltage = max(
            voltage + self._dropout_voltage(voltage), self.MIN_BUCK_VOLTAGE
        )
        if buck_voltage > self.MAX_BUCK_VOLTAGE:
            raise ValueError(
                f"The required buck voltage for {voltage}V is {buck_voltage}V, which is above the maximum buck voltage of {self.MAX_BUCK_VOLTAGE}"
            )
        await self._set_buck_voltage(self.MAX_BUCK_VOLTAGE)
        await self._set_ldo_voltage(voltage)

    async def calibrate(self, data_points: int = 16, recorder: record | None = None):
        """
        Calibrate the LDO voltages.
        """
        ldo_calibration_list = []
        await asyncio.gather(
            self.enable(),
            self.turn_off_output_relay(),
            self.close_load_switch(),
            self._set_buck_voltage(self.MAX_BUCK_VOLTAGE),  # Start with max buck voltage
            self.ldo_dac.set_raw_value(3760)
        )
        await asyncio.sleep(1)

        await self.turn_on_output_relay() # 3760, 42
        for dac_value in np.linspace(3760, 200, num=data_points, dtype=int, endpoint=True):
            await self.ldo_dac.set_raw_value(int(dac_value))
            await asyncio.sleep(0.3)  # Increased settling time
            voltage = await self.get_voltage()
            logger.debug(f"[Cell {self.cell_num}] Voltage read: {voltage:.3f} V (raw: {dac_value})")
            ldo_calibration_list.append([voltage, dac_value])
        calibration_array = np.array(ldo_calibration_list)
        sorted_indices = np.argsort(calibration_array[:, 0])
        x_sorted = calibration_array[sorted_indices, 0].tolist()
        y_sorted = calibration_array[sorted_indices, 1].tolist()
        self._ldo_calibration.update(x_sorted, y_sorted)

    def _calculate_setpoint(
        self, voltage: float, calibration: Calibration
    ) -> int:

        return calibration.map_xy(voltage)

    async def _set_buck_voltage(self, voltage):
        """
        Set the buck converter voltage.
        """
        setpoint = self._calculate_setpoint(voltage, self._buck_calibration)
        await self.buck_dac.set_raw_value(setpoint)

    async def _set_ldo_voltage(self, voltage):
        """
        Set the LDO voltage.
        """
        setpoint = self._calculate_setpoint(voltage, self._ldo_calibration)
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

    async def aclose(self):
        await self.turn_off_output_relay()
        await self.disable()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.aclose()
