import asyncio
from smbus2 import SMBus


class AsyncSMBus:
    def __init__(self, force=False):
        """
        Synchronous initializer.
        Use the async class method `create(bus, force)` to get an instance with a bus open.
        """
        self.force = force
        self._smbus = None

    @classmethod
    async def create(cls, bus, force=False):
        """
        Asynchronous constructor.
        This creates an instance, opens the bus asynchronously, and returns the instance.
        """
        instance = cls(force=force)
        await instance.open(bus)
        return instance

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def open(self, bus):
        """
        Open the given I2C bus (e.g., an integer 0 or 1 or a device path).
        """
        # Instantiate the synchronous SMBus in a thread.
        self._smbus = await asyncio.to_thread(SMBus, bus, self.force)

    async def close(self):
        """
        Close the I2C connection.
        """
        if self._smbus is not None:
            await asyncio.to_thread(self._smbus.close)
            self._smbus = None

    async def _get_pec(self):
        """
        Get Packet Error Check (PEC) status.
        """
        return await asyncio.to_thread(self._smbus._get_pec)

    async def enable_pec(self, enable=True):
        """
        Enable or disable PEC.
        """
        await asyncio.to_thread(self._smbus.enable_pec, enable)

    async def _set_address(self, address, force=None):
        """
        Set the I2C slave address.
        """
        await asyncio.to_thread(self._smbus._set_address, address, force)

    async def _get_funcs(self):
        """
        Get the functionality mask of the I2C adapter.
        """
        return await asyncio.to_thread(self._smbus._get_funcs)

    async def write_quick(self, i2c_addr, force=None):
        """
        Perform a quick write transaction.
        """
        await asyncio.to_thread(self._smbus.write_quick, i2c_addr, force)

    async def read_byte(self, i2c_addr, force=None):
        """
        Read a single byte from a device.
        """
        return await asyncio.to_thread(self._smbus.read_byte, i2c_addr, force)

    async def write_byte(self, i2c_addr, value, force=None):
        """
        Write a single byte to a device.
        """
        await asyncio.to_thread(self._smbus.write_byte, i2c_addr, value, force)

    async def read_byte_data(self, i2c_addr, register, force=None):
        """
        Read a single byte from a designated register.
        """
        return await asyncio.to_thread(
            self._smbus.read_byte_data, i2c_addr, register, force
        )

    async def write_byte_data(self, i2c_addr, register, value, force=None):
        """
        Write a byte to a given register.
        """
        await asyncio.to_thread(
            self._smbus.write_byte_data, i2c_addr, register, value, force
        )

    async def read_word_data(self, i2c_addr, register, force=None):
        """
        Read a 2-byte word from a given register.
        """
        return await asyncio.to_thread(
            self._smbus.read_word_data, i2c_addr, register, force
        )

    async def write_word_data(self, i2c_addr, register, value, force=None):
        """
        Write a 2-byte word to a given register.
        """
        await asyncio.to_thread(
            self._smbus.write_word_data, i2c_addr, register, value, force
        )

    async def process_call(self, i2c_addr, register, value, force=None):
        """
        Execute a process call (sending a 16-bit value and receiving a 16-bit response).
        """
        return await asyncio.to_thread(
            self._smbus.process_call, i2c_addr, register, value, force
        )

    async def read_block_data(self, i2c_addr, register, force=None):
        """
        Read a block of up to 32 bytes from a given register.
        """
        return await asyncio.to_thread(
            self._smbus.read_block_data, i2c_addr, register, force
        )

    async def write_block_data(self, i2c_addr, register, data, force=None):
        """
        Write a block of byte data to a given register.
        """
        await asyncio.to_thread(
            self._smbus.write_block_data, i2c_addr, register, data, force
        )

    async def block_process_call(self, i2c_addr, register, data, force=None):
        """
        Execute a block process call.
        """
        return await asyncio.to_thread(
            self._smbus.block_process_call, i2c_addr, register, data, force
        )

    async def read_i2c_block_data(self, i2c_addr, register, length, force=None):
        """
        Read a block of byte data from a given register.
        """
        return await asyncio.to_thread(
            self._smbus.read_i2c_block_data, i2c_addr, register, length, force
        )

    async def write_i2c_block_data(self, i2c_addr, register, data, force=None):
        """
        Write a block of byte data to a given register.
        """
        await asyncio.to_thread(
            self._smbus.write_i2c_block_data, i2c_addr, register, data, force
        )

    async def i2c_rdwr(self, *i2c_msgs):
        """
        Perform a combined I2C read/write transaction.
        """
        await asyncio.to_thread(self._smbus.i2c_rdwr, *i2c_msgs)
