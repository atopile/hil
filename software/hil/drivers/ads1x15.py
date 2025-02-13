import asyncio
from enum import IntEnum
import time

from hil.drivers.aiosmbus2 import AsyncSMBus

# Added global constant for GPIO expander address (fixes "Undefined name GPIO_ADDRESS" error)
GPIO_ADDRESS = 0x20

# ADS1x15 default i2c address
I2C_address = 0x48


class ADS1x15:
    "General ADS1x15 family ADC class"

    # ADS1x15 register address
    CONVERSION_REG = 0x00
    CONFIG_REG = 0x01
    LO_THRESH_REG = 0x02
    HI_THRESH_REG = 0x03

    # Input multiplexer configuration
    class InputConfig(IntEnum):
        DIFF_0_1 = 0
        DIFF_0_3 = 1
        DIFF_1_3 = 2
        DIFF_2_3 = 3
        SINGLE_0 = 4
        SINGLE_1 = 5
        SINGLE_2 = 6
        SINGLE_3 = 7

    # Programmable gain amplifier configuration
    class GainConfig(IntEnum):
        UPTO_6_144V = 0
        UPTO_4_096V = 1
        UPTO_2_048V = 2
        UPTO_1_024V = 4
        UPTO_0_512V = 8
        UPTO_0_256V = 16

    # Device operating mode configuration
    class ModeConfig(IntEnum):
        CONTINUOUS = 0
        SINGLE = 1

    # Data rate configuration
    class DataRateConfig(IntEnum):
        RATE_128 = 0
        RATE_250 = 1
        RATE_490 = 2
        RATE_920 = 3
        RATE_1600 = 4
        RATE_2400 = 5
        RATE_3300 = 6
        RATE_8 = 0
        RATE_16 = 1
        RATE_32 = 2
        RATE_64 = 3
        RATE_128 = 4
        RATE_250 = 5
        RATE_475 = 6
        RATE_860 = 7

    # Comparator configuration
    class ComparatorMode(IntEnum):
        TRADITIONAL = 0
        WINDOW = 1

    class ComparatorPolarity(IntEnum):
        ACTIV_LOW = 0
        ACTIV_HIGH = 1

    class ComparatorLatch(IntEnum):
        LATCH = 0
        NON_LATCH = 1

    class ComparatorQueue(IntEnum):
        QUE_1 = 0
        QUE_2 = 1
        QUE_4 = 2
        QUE_NONE = 3

    # I2C object will be provided via AsyncSMBus
    bus: AsyncSMBus | None = None

    # I2C address
    _address = I2C_address

    # Default config register
    _config = 0x8583

    # Default conversion delay
    _conversionDelay = 8

    # Maximum input port
    _maxPorts = 4

    # Default conversion lengths
    _adcBits = 16

    def __init__(self):
        # Private constructor; use ADS1x15.create() instead.
        self._lock = asyncio.Lock()

    @classmethod
    async def create(cls, bus: AsyncSMBus, address: int = I2C_address):
        """
        Asynchronously create an instance of ADS1x15.
        """
        self = cls.__new__(cls)
        self.bus = bus
        self._address = address
        self._conversionDelay = 8
        self._maxPorts = 4
        self._adcBits = 16
        self._config = await self._read_register(self.CONFIG_REG)
        return self

    async def _write_register(self, address: int, value):
        "Asynchronously write a 16-bit integer to an address pointer register"
        registerValue = [(value >> 8) & 0xFF, value & 0xFF]
        async with self.bus() as handle:
            await handle.write_i2c_block_data(self._address, address, registerValue)

    async def _read_register(self, address: int):
        "Asynchronously read a 16-bit integer value from an address pointer register"
        async with self.bus() as handle:
            registerValue = await handle.read_i2c_block_data(self._address, address, 2)
        return (registerValue[0] << 8) + registerValue[1]

    async def _get_conversion_value(self) -> int:
        "Asynchronously get ADC value"
        value = await self._read_register(self.CONVERSION_REG)
        # Shift value based on ADC bits and adjust for two's complement.
        value = value >> (16 - self._adcBits)
        if value >= (2 ** (self._adcBits - 1)):
            value = value - (2 ** (self._adcBits))
        return value

    async def _set_input(self, input: InputConfig):
        "Set input multiplexer configuration"
        inputRegister = input << 12
        # Masking input argument bits (bit 12-14) to config register
        self._config = (self._config & 0x8FFF) | inputRegister
        await self._write_register(self.CONFIG_REG, self._config)

    def get_input(self):
        "Get input multiplexer configuration"
        return (self._config & 0x7000) >> 12

    async def _set_gain(self, gain: GainConfig):
        "Set programmable gain amplifier configuration"
        if gain == self.GainConfig.UPTO_4_096V:
            gainRegister = 0x0200
        elif gain == self.GainConfig.UPTO_2_048V:
            gainRegister = 0x0400
        elif gain == self.GainConfig.UPTO_1_024V:
            gainRegister = 0x0600
        elif gain == self.GainConfig.UPTO_0_512V:
            gainRegister = 0x0800
        elif gain == self.GainConfig.UPTO_0_256V:
            gainRegister = 0x0A00
        else:
            gainRegister = 0x0000
        self._config = (self._config & 0xF1FF) | gainRegister
        await self._write_register(self.CONFIG_REG, self._config)

    def get_gain(self) -> GainConfig:
        "Get programmable gain amplifier configuration"
        gainRegister = self._config & 0x0E00
        if gainRegister == 0x0200:
            return self.GainConfig.UPTO_4_096V
        elif gainRegister == 0x0400:
            return self.GainConfig.UPTO_2_048V
        elif gainRegister == 0x0600:
            return self.GainConfig.UPTO_1_024V
        elif gainRegister == 0x0800:
            return self.GainConfig.UPTO_0_512V
        elif gainRegister == 0x0A00:
            return self.GainConfig.UPTO_0_256V
        else:
            return self.GainConfig.UPTO_6_144V

    async def _set_mode(self, mode: ModeConfig):
        "Set device operating mode configuration"
        if mode == self.ModeConfig.CONTINUOUS:
            modeRegister = 0x0000
        else:
            modeRegister = 0x0100
        self._config = (self._config & 0xFEFF) | modeRegister
        await self._write_register(self.CONFIG_REG, self._config)

    def get_mode(self) -> ModeConfig:
        "Get device operating mode configuration"
        return self.ModeConfig((self._config & 0x0100) >> 8)

    async def _set_data_rate(self, dataRate: DataRateConfig):
        "Set data rate configuration"
        if dataRate < 0 or dataRate > 7:
            raise ValueError(f"Invalid data rate: {dataRate}")

        dataRateRegister = dataRate << 5
        self._config = (self._config & 0xFF1F) | dataRateRegister
        await self._write_register(self.CONFIG_REG, self._config)

    def get_data_rate(self) -> DataRateConfig:
        "Get data rate configuration"
        return self.DataRateConfig((self._config & 0x00E0) >> 5)

    async def set_comparator_mode(self, comparatorMode: ComparatorMode):
        "Set comparator mode configuration"
        if comparatorMode == self.ComparatorMode.WINDOW:
            comparatorModeRegister = 0x0010
        else:
            comparatorModeRegister = 0x0000
        self._config = (self._config & 0xFFEF) | comparatorModeRegister
        await self._write_register(self.CONFIG_REG, self._config)

    def get_comparator_mode(self) -> ComparatorMode:
        "Get comparator mode configuration"
        return self.ComparatorMode((self._config & 0x0010) >> 4)

    async def set_comparator_polarity(self, comparatorPolarity: ComparatorPolarity):
        "Set comparator polarity configuration"
        if comparatorPolarity == self.ComparatorPolarity.ACTIV_HIGH:
            comparatorPolarityRegister = 0x0008
        else:
            comparatorPolarityRegister = 0x0000
        self._config = (self._config & 0xFFF7) | comparatorPolarityRegister
        await self._write_register(self.CONFIG_REG, self._config)

    def get_comparator_polarity(self) -> ComparatorPolarity:
        "Get comparator polarity configuration"
        return self.ComparatorPolarity((self._config & 0x0008) >> 3)

    async def set_comparator_latch(self, comparatorLatch: ComparatorLatch):
        "Set comparator latch configuration"
        if comparatorLatch == self.ComparatorLatch.LATCH:
            comparatorLatchRegister = 0x0004
        else:
            comparatorLatchRegister = 0x0000
        self._config = (self._config & 0xFFFB) | comparatorLatchRegister
        await self._write_register(self.CONFIG_REG, self._config)

    def get_comparator_latch(self) -> ComparatorLatch:
        "Get comparator latch configuration"
        return self.ComparatorLatch((self._config & 0x0004) >> 2)

    async def set_comparator_queue(self, comparatorQueue: ComparatorQueue):
        "Set comparator queue configuration"
        if comparatorQueue < 0 or comparatorQueue > 3:
            comparatorQueueRegister = 0x0002
        else:
            comparatorQueueRegister = comparatorQueue
        self._config = (self._config & 0xFFFC) | comparatorQueueRegister
        await self._write_register(self.CONFIG_REG, self._config)

    def get_comparator_queue(self) -> ComparatorQueue:
        "Get comparator queue configuration"
        return self.ComparatorQueue(self._config & 0x0003)

    async def set_comparator_threshold_low(self, threshold: float):
        "Set low threshold for voltage comparator"
        await self._write_register(self.LO_THRESH_REG, round(threshold))

    async def get_comparator_threshold_low(self):
        "Get voltage comparator low threshold"
        threshold = await self._read_register(self.LO_THRESH_REG)
        if threshold >= 32768:
            threshold = threshold - 65536
        return threshold

    async def set_comparator_threshold_high(self, threshold: float):
        "Set high threshold for voltage comparator"
        await self._write_register(self.HI_THRESH_REG, round(threshold))

    async def get_comparator_threshold_high(self):
        "Get voltage comparator high threshold"
        threshold = await self._read_register(self.HI_THRESH_REG)
        if threshold >= 32768:
            threshold = threshold - 65536
        return threshold

    async def is_ready(self):
        "Check if device currently not performing conversion"
        value = await self._read_register(self.CONFIG_REG)
        return bool(value & 0x8000)

    async def is_busy(self):
        "Check if device currently performing conversion"
        return not await self.is_ready()

    async def _request_input(self, input: InputConfig):
        "Private method for starting a single-shot conversion"
        await self._set_input(input)
        # Set single-shot conversion start (bit 15)
        if self._config & 0x0100:
            await self._write_register(self.CONFIG_REG, self._config | 0x8000)

    async def _get_adc(self) -> int:
        "Get ADC value with current configuration"
        t = time.time()
        is_continuous = not (self._config & 0x0100)
        # Wait conversion process finish or reach conversion time for continuous mode
        while not await self.is_ready():
            if ((time.time() - t) * 1000) > self._conversionDelay and is_continuous:
                break
        return await self._get_conversion_value()

    async def _set_adc_config(
        self,
        gain: GainConfig | None = None,
        mode: ModeConfig | None = None,
        dataRate: DataRateConfig | None = None,
    ):
        "Set configuration of the ADC"
        if gain is not None and gain != self.get_gain():
            await self._set_gain(gain)
        if mode is not None and mode != self.get_mode():
            await self._set_mode(mode)
        if dataRate is not None and dataRate != self.get_data_rate():
            await self._set_data_rate(dataRate)

    async def set_adc_config(
        self,
        gain: GainConfig | None = None,
        mode: ModeConfig | None = None,
        dataRate: DataRateConfig | None = None,
    ):
        "Set configuration of the ADC"
        async with self._lock:
            await self._set_adc_config(gain, mode, dataRate)

    async def read_pin(
        self,
        pin: int,
        gain: GainConfig | None = None,
        mode: ModeConfig | None = None,
        dataRate: DataRateConfig | None = None,
    ):
        "Asynchronously get ADC value of a pin"
        async with self._lock:
            await self._set_adc_config(gain, mode, dataRate)
            await self._request_input(self.InputConfig(pin + 4))
            return await self._get_adc()

    async def read_adc(
        self,
        input: InputConfig,
        gain: GainConfig | None = None,
        mode: ModeConfig | None = None,
        dataRate: DataRateConfig | None = None,
    ):
        "Asynchronously get ADC value of a pin"
        async with self._lock:
            await self._set_adc_config(gain, mode, dataRate)
            await self._request_input(input)
            return await self._get_adc()

    def get_max_voltage(self) -> float:
        "Get maximum voltage conversion range"
        if self._config & 0x0E00 == 0x0000:
            return 6.144
        elif self._config & 0x0E00 == 0x0200:
            return 4.096
        elif self._config & 0x0E00 == 0x0400:
            return 2.048
        elif self._config & 0x0E00 == 0x0600:
            return 1.024
        elif self._config & 0x0E00 == 0x0800:
            return 0.512
        else:
            return 0.256

    def to_voltage(self, value: int = 1) -> float:
        "Transform an ADC value to nominal voltage"
        volts = self.get_max_voltage() * value
        return volts / ((2 ** (self._adcBits - 1)) - 1)


class ADS1013(ADS1x15):
    "ADS1013 class derived from general ADS1x15 class"

    @classmethod
    async def create(cls, bus: AsyncSMBus, address: int = I2C_address):
        "Initialize ADS1013 with SMBus and I2C address configuration"
        self = cls.__new__(cls)
        self.bus = bus
        self._address = address
        self._conversionDelay = 2
        self._maxPorts = 1
        self._adcBits = 12
        # Store initial config resgister to config property
        self._config = await self._read_register(self.CONFIG_REG)
        return self


class ADS1014(ADS1x15):
    "ADS1014 class derived from general ADS1x15 class"

    @classmethod
    async def create(cls, bus: AsyncSMBus, address: int = I2C_address):
        "Initialize ADS1014 with SMBus and I2C address configuration"
        self = cls.__new__(cls)
        self.bus = bus
        self._address = address
        self._conversionDelay = 2
        self._maxPorts = 1
        self._adcBits = 12
        # Store initial config resgister to config property
        self._config = await self._read_register(self.CONFIG_REG)
        return self


class ADS1015(ADS1x15):
    "ADS1015 class derived from general ADS1x15 class"

    @classmethod
    async def create(cls, bus: AsyncSMBus, address: int = I2C_address):
        "Initialize ADS1015 with SMBus and I2C address configuration"
        self = cls.__new__(cls)
        self.bus = bus
        self._address = address
        self._conversionDelay = 2
        self._maxPorts = 4
        self._adcBits = 12
        # Store initial config resgister to config property
        self._config = await self._read_register(self.CONFIG_REG)
        return self


class ADS1113(ADS1x15):
    "ADS1113 class derived from general ADS1x15 class"

    @classmethod
    async def create(cls, bus: AsyncSMBus, address: int = I2C_address):
        "Initialize ADS1113 with SMBus and I2C address configuration"
        self = cls.__new__(cls)
        self.bus = bus
        self._address = address
        self._conversionDelay = 8
        self._maxPorts = 1
        self._adcBits = 16
        # Store initial config resgister to config property
        self._config = await self._read_register(self.CONFIG_REG)
        return self


class ADS1114(ADS1x15):
    "ADS1114 class derived from general ADS1x15 class"

    @classmethod
    async def create(cls, bus: AsyncSMBus, address: int = I2C_address):
        "Initialize ADS1114 with SMBus and I2C address configuration"
        self = cls.__new__(cls)
        self.bus = bus
        self._address = address
        self._conversionDelay = 8
        self._maxPorts = 1
        self._adcBits = 16
        # Store initial config resgister to config property
        self._config = await self._read_register(self.CONFIG_REG)
        return self


class ADS1115(ADS1x15):
    "ADS1115 class derived from general ADS1x15 class"

    @classmethod
    async def create(cls, bus: AsyncSMBus, address: int = I2C_address):
        "Initialize ADS1115 with SMBus and I2C address configuration"
        self = cls.__new__(cls)
        self.bus = bus
        self._address = address
        self._conversionDelay = 8
        self._maxPorts = 4
        self._adcBits = 16
        # Store initial config resgister to config property
        self._config = await self._read_register(self.CONFIG_REG)
        return self
