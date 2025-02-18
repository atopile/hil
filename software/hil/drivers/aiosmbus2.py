import asyncio
from contextlib import asynccontextmanager
import os
from typing import AsyncContextManager, Protocol, Self
from abc import ABC, abstractmethod
from hil.utils.composable_future import Future, composable
from smbus2 import SMBus


class SMBusHandle[T](Future[T]):
    def __init__(self, smbus: SMBus):
        super().__init__()
        self._smbus = smbus

    @composable
    def _get_pec(self) -> int:
        """
        Get Packet Error Check (PEC) status.
        """
        return self._smbus._get_pec()

    @composable
    def enable_pec(self, enable=True) -> None:
        """
        Enable or disable PEC.
        """
        self._smbus.enable_pec(enable)

    @composable
    def _set_address(self, address, force=None) -> None:
        """
        Set the I2C slave address.
        """
        self._smbus._set_address(address, force)

    @composable
    def _get_funcs(self) -> int:
        """
        Get the functionality mask of the I2C adapter.
        """
        return self._smbus._get_funcs()

    @composable
    def write_quick(self, i2c_addr, force=None) -> None:
        """
        Perform a quick write transaction.
        """
        self._smbus.write_quick(i2c_addr, force)

    @composable
    def read_byte(self, i2c_addr, force=None) -> int:
        """
        Read a single byte from a device.
        """
        return self._smbus.read_byte(i2c_addr, force)

    @composable
    def write_byte(self, i2c_addr, value, force=None) -> None:
        """
        Write a single byte to a device.
        """
        self._smbus.write_byte(i2c_addr, value, force)

    @composable
    def read_byte_data(self, i2c_addr, register, force=None) -> int:
        """
        Read a single byte from a designated register.
        """
        return self._smbus.read_byte_data(i2c_addr, register, force)

    @composable
    def write_byte_data(self, i2c_addr, register, value, force=None) -> None:
        """
        Write a byte to a given register.
        """
        self._smbus.write_byte_data(i2c_addr, register, value, force)

    @composable
    def read_word_data(self, i2c_addr, register, force=None) -> int:
        """
        Read a 2-byte word from a given register.
        """
        return self._smbus.read_word_data(i2c_addr, register, force)

    @composable
    def write_word_data(self, i2c_addr, register, value, force=None) -> None:
        """
        Write a 2-byte word to a given register.
        """
        self._smbus.write_word_data(i2c_addr, register, value, force)

    @composable
    def process_call(self, i2c_addr, register, value, force=None) -> int:
        """
        Execute a process call (sending a 16-bit value and receiving a 16-bit response).
        """
        return self._smbus.process_call(i2c_addr, register, value, force)

    @composable
    def read_block_data(self, i2c_addr, register, force=None) -> list[int]:
        """
        Read a block of up to 32 bytes from a given register.
        Returns a list of integer byte values.
        """
        return self._smbus.read_block_data(i2c_addr, register, force)

    @composable
    def write_block_data(self, i2c_addr, register, data, force=None) -> None:
        """
        Write a block of byte data to a given register.
        """
        self._smbus.write_block_data(i2c_addr, register, data, force)

    @composable
    def block_process_call(self, i2c_addr, register, data, force=None) -> list[int]:
        """
        Execute a SMBus Block Process Call (variable-length Tx/Rx).
        Returns a list of integer byte values.
        """
        return self._smbus.block_process_call(i2c_addr, register, data, force)

    @composable
    def read_i2c_block_data(self, i2c_addr, register, length, force=None) -> list[int]:
        """
        Read a block of exactly 'length' bytes from the given register.
        Returns a list of integer byte values.
        """
        return self._smbus.read_i2c_block_data(i2c_addr, register, length, force)

    @composable
    def write_i2c_block_data(self, i2c_addr, register, data, force=None) -> None:
        """
        Write a block of byte data to a given register.
        """
        self._smbus.write_i2c_block_data(i2c_addr, register, data, force)

    @composable
    def i2c_rdwr(self, *i2c_msgs) -> None:
        """
        Perform a combined I2C read/write transaction.
        """
        self._smbus.i2c_rdwr(*i2c_msgs)


class AsyncSMBus(ABC):
    """
    Abstract base class for SMBus implementations.
    Defines the common interface that all SMBus implementations must provide.
    """

    @abstractmethod
    def __call__(self) -> AsyncContextManager[SMBusHandle]:
        """
        Get a context manager for accessing the SMBus.
        This is the primary method for interacting with the bus.

        Returns:
            AsyncContextManager[SMBusHandle]: Context manager that yields an SMBusHandle
        """

    @abstractmethod
    async def __aenter__(self) -> Self:
        """Enter the async context manager."""

    @abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit the async context manager."""


class AsyncSMBusPeripheral(AsyncSMBus):
    class BusAlreadyOpen(Exception):
        """
        Exception raised when the bus is already open.
        """

    def __init__(self, bus: int | os.PathLike | None = None, force: bool | None = None):
        """
        Synchronous initializer.
        Use the async class method `create(bus, force)` to get an instance with a bus open.
        """
        super().__init__()
        self._lock = asyncio.Lock()
        self._handle: SMBusHandle | None = None
        self._smbus = None
        self._bus = bus
        self._force = force

    @classmethod
    async def create(
        cls, bus: int | os.PathLike | None = None, force: bool | None = None
    ) -> Self:
        instance = cls(bus, force)
        await instance.open()
        return instance

    async def open(
        self, bus: int | os.PathLike | None = None, force: bool | None = None
    ) -> Self:
        """
        Open the given I2C bus (e.g., an integer 0 or 1 or a device path).
        """
        if bus is None and self._bus is None:
            raise ValueError("bus not provided")
        if bus is not None:
            self._bus = bus
        if not isinstance(self._bus, int):
            self._bus = str(self._bus)

        if force is not None:
            self._force = force
        if self._force is None:
            self._force = False

        async with self._lock:
            if self._smbus is not None:
                raise self.BusAlreadyOpen()

            self._smbus = await asyncio.to_thread(SMBus, self._bus, self._force)
            self._handle = SMBusHandle(self._smbus)
            return self

    async def close(self):
        """
        Close the I2C connection.
        """
        async with self._lock:
            if self._smbus is not None:
                await asyncio.to_thread(self._smbus.close)
                self._smbus = None

    def __call__(self) -> AsyncContextManager[SMBusHandle]:
        @asynccontextmanager
        async def _enter():
            try:
                await self.aquire()
                if self._handle is None:
                    raise RuntimeError("bus not open")
                yield self._handle
            finally:
                self.release()

        return _enter()

    async def aquire(self):
        await self._lock.acquire()

    def release(self):
        self._lock.release()

    async def __aenter__(self) -> Self:
        try:
            await self.open()
        except self.BusAlreadyOpen:
            pass
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


class Mux(Protocol):
    async def set_mux(self, channel: int, handle: SMBusHandle):
        """
        Set the MUX to the given channel.
        """


class AsyncSMBusBranch(AsyncSMBus):
    class _AsyncSMBusMux:
        def __init__(self, upstream: "AsyncSMBus", mux: Mux):
            self.upstream = upstream
            self.mux = mux
            self.lock = asyncio.Lock()

    def __init__(self, mux: _AsyncSMBusMux, channel: int):
        super().__init__()
        self._mux = mux
        self._channel = channel

    def __call__(self) -> AsyncContextManager[SMBusHandle]:
        @asynccontextmanager
        async def _enter():
            async with self._mux.lock, self._mux.upstream() as handle:
                await self._mux.mux.set_mux(self._channel, handle)
                yield handle

        return _enter()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    @classmethod
    def from_channels(
        cls, upstream: "AsyncSMBus", mux: Mux, channels: list[int]
    ) -> list[Self]:
        _mux = cls._AsyncSMBusMux(upstream, mux)
        return [cls(_mux, channel) for channel in channels]
