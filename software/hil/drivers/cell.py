import asyncio
from enum import IntEnum
import logging
from hil.utils.config import ConfigDict
import numpy as np
from hil.drivers.ads1x15 import ADS1115
from hil.drivers.aiosmbus2 import AsyncSMBus
from hil.drivers.mcp4725 import MCP4725
from hil.drivers.tca6408 import TCA6408

from hil.framework import record, Calibration

logger = logging.getLogger(__name__)


class Cell:
    cell_num: int
    mux_channel: int
    bus: AsyncSMBus
    enabled: bool
    adc: ADS1115
    buck_dac: MCP4725
    ldo_dac: MCP4725
    gpio: TCA6408
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
        EXTERNAL_LOAD_CONTROL = 6

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
        logger.debug(f"Creating Cell {cell_num} with config: {config}")
        self.buck_dac = await MCP4725.create(bus, self.Devices.BUCK)
        self.ldo_dac = await MCP4725.create(bus, self.Devices.LDO)
        self.adc = await ADS1115.create(self.bus, self.Devices.ADC)
        self.gpio = await TCA6408.create(bus, self.Devices.GPIO)

        # Use default buck calibration for now
        # TODO: Add buck calibration loading from config if needed
        self._buck_calibration = Calibration(
            [1.5041, 4.5971], [2625, 234], lower_bound=1.45, upper_bound=4.65
        )

        # Safely get LDO calibration config, default to {} if missing
        ldo_cal_config = config.get("ldo_calibration", {})
        if not ldo_cal_config:
             logger.warning(f"[Cell {cell_num}] ldo_calibration missing from config. Using default values.")

        # Pass the obtained (or default empty) dict to from_config
        self._ldo_calibration = Calibration.from_config(
            ldo_cal_config, [0.228, 4.4], [3760, 42]
        )
        await self.reset()

        return self

    async def reset(self):
        """
        Reset the cell.
        - Clears the GPIO state.
        - Resets the ADC gain.
        """
        # Configure all GPIO pins as outputs
        await self.gpio.configure_io_bulk({
            self.GpioChannels.BUCK_ENABLE: True,
            self.GpioChannels.LDO_ENABLE: True,
            self.GpioChannels.LOAD_SWITCH_CONTROL: True,
            self.GpioChannels.OUTPUT_RELAY_CONTROL: True,
            self.GpioChannels.EXTERNAL_LOAD_CONTROL: True
        })
        
        # Set all GPIO pins low
        await self.gpio.set_gpio_bulk({
            self.GpioChannels.BUCK_ENABLE: False,
            self.GpioChannels.LDO_ENABLE: False,
            self.GpioChannels.LOAD_SWITCH_CONTROL: False,
            self.GpioChannels.OUTPUT_RELAY_CONTROL: False,
            self.GpioChannels.EXTERNAL_LOAD_CONTROL: False
        })

        await self.adc.set_adc_config(gain=ADS1115.GainConfig.UPTO_6_144V)

    async def enable(self):
        """
        Enable the cell by setting the buck and LDO enable pins high.
        """
        if self.enabled:
            return

        await self.gpio.set_gpio_bulk({
            self.GpioChannels.BUCK_ENABLE: True,
            self.GpioChannels.LDO_ENABLE: True
        })
        self.enabled = True
        logger.debug(f"[Cell {self.cell_num}] Enabled")

    async def disable(self):
        """
        Disable the cell by clearing the buck and LDO enable pins.
        """
        if not self.enabled:
            return

        await self.gpio.set_gpio_bulk({
            self.GpioChannels.BUCK_ENABLE: False,
            self.GpioChannels.LDO_ENABLE: False
        })
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
        await self.enable()
        await self.turn_off_output_relay()
        await self.close_load_switch()
        await self._set_buck_voltage(
            self.MAX_BUCK_VOLTAGE
        )  # Start with max buck voltage
        await self.ldo_dac.set_raw_value(3760) # Start at high DAC value (low voltage)
        await self.turn_on_output_relay()
        await asyncio.sleep(0.2)

        # Adjust the lower DAC limit (increase from 200 to 250)
        min_dac_value = 250
        for dac_value in np.linspace(
            3760, min_dac_value, num=data_points, dtype=int, endpoint=True
        ):
            await self.ldo_dac.set_raw_value(int(dac_value))
            await asyncio.sleep(0.3)  # Increased settling time
            voltage = await self.get_voltage()
            logger.debug(
                f"[Cell {self.cell_num}] Calibration point: DAC={int(dac_value)}, V={voltage:.4f}"
            )
            ldo_calibration_list.append([voltage, float(dac_value)]) # Store as floats

        # Ensure data is sorted by voltage (x-value) before updating calibration
        calibration_array = np.array(ldo_calibration_list)
        # Handle potential duplicate voltage readings robustly before sorting/updating
        # Option 1: Average DAC values for duplicate voltages (might be okay if close)
        # Option 2: Keep only the first occurrence of a voltage (simpler)
        unique_voltages, indices = np.unique(calibration_array[:, 0], return_index=True)
        if len(unique_voltages) < len(calibration_array):
             logger.warning(f"[Cell {self.cell_num}] Duplicate voltage readings detected during calibration. Keeping first occurrences.")
             calibration_array = calibration_array[indices]

        # Now sort the unique points by voltage
        sorted_indices = np.argsort(calibration_array[:, 0])
        x_sorted = calibration_array[sorted_indices, 0].tolist()
        y_sorted = calibration_array[sorted_indices, 1].tolist()

        # Check again for strictly increasing x after potential filtering/sorting
        if not np.all(np.diff(np.array(x_sorted)) > 1e-9): # Use tolerance for float comparison
             logger.error(f"[Cell {self.cell_num}] LDO calibration failed: x values not strictly increasing after processing. Data: {list(zip(x_sorted, y_sorted))}")
             # Decide how to handle: raise error, use old calibration, use partial data?
             # For now, log error and potentially don't update
             # raise ValueError("LDO Calibration failed: x values not strictly increasing after processing.")
             return # Or maybe just don't update if problematic

        logger.info(f"[Cell {self.cell_num}] Updating LDO calibration with {len(x_sorted)} points.")
        self._ldo_calibration.update(x_sorted, y_sorted)

    async def _set_buck_voltage(self, voltage):
        """
        Set the buck converter voltage.
        """
        setpoint = self._buck_calibration.map_xy(voltage)
        await self.buck_dac.set_raw_value(setpoint)

    async def _set_ldo_voltage(self, voltage):
        """
        Set the LDO voltage.
        """
        setpoint = self._ldo_calibration.map_xy(voltage)
        await self.ldo_dac.set_raw_value(setpoint)

    async def turn_on_output_relay(self):
        """
        Turn on the output relay.
        """
        await self.gpio.set_gpio(self.GpioChannels.OUTPUT_RELAY_CONTROL, True)
        logger.debug(f"[Cell {self.cell_num}] Output relay turned ON")

    async def turn_off_output_relay(self):
        """
        Turn off the output relay.
        """
        await self.gpio.set_gpio(self.GpioChannels.OUTPUT_RELAY_CONTROL, False)
        logger.debug(f"[Cell {self.cell_num}] Output relay turned OFF")

    async def close_load_switch(self):
        """
        Turn on the load switch.
        """
        await self.gpio.set_gpio(self.GpioChannels.LOAD_SWITCH_CONTROL, True)
        logger.debug(f"[Cell {self.cell_num}] Load switch turned ON")

    async def open_load_switch(self):
        """
        Turn off the load switch.
        """
        await self.gpio.set_gpio(self.GpioChannels.LOAD_SWITCH_CONTROL, False)
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
        await self.gpio.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.aclose()

    async def turn_on_external_load(self):
        """
        Turn on the external load switch (connects external load).
        """
        await self.gpio.set_gpio(self.GpioChannels.EXTERNAL_LOAD_CONTROL, True)
        logger.debug(f"[Cell {self.cell_num}] External load turned ON")

    async def turn_off_external_load(self):
        """
        Turn off the external load switch (disconnects external load).
        """
        await self.gpio.set_gpio(self.GpioChannels.EXTERNAL_LOAD_CONTROL, False)
        logger.debug(f"[Cell {self.cell_num}] External load turned OFF")
