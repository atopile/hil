import logging
from hil.drivers.aiosmbus2 import AsyncSMBus

logger = logging.getLogger(__name__)

DEFAULT_MUX_ADDRESS = 0x70


class TCA9548A:
    def __init__(self, bus: AsyncSMBus, address: int = DEFAULT_MUX_ADDRESS):
        self.bus = bus
        self.address = address
        self._current_channel: int | None = None

    async def set_mux(self, channel: int):
        """
        Select the correct MUX channel.
        Writes 1 << mux_channel to the mux address.
        """
        if self._current_channel == channel:
            return

        value = 1 << channel
        async with self.bus() as handle:
            await handle.write_byte(self.address, value)

        self._current_channel = channel
