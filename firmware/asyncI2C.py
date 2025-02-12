
from typing import Callable, TypeVar


T = TypeVar("T")  # Input type
U = TypeVar("U")  # Output type

async def _async_wrap(func: Callable[[T], U], *args) -> U:
    pass


class AsyncSMBus:
    async def __init__(self, bus=None, force=False):
        raise NotImplementedError

    async def __enter__(self):
        raise NotImplementedError

    async def __exit__(self, exc_type, exc_val, exc_tb):
        raise NotImplementedError

    async def open(self, bus):
        raise NotImplementedError

    async def close(self):
        raise NotImplementedError

    async def _get_pec(self):
        raise NotImplementedError

    async def enable_pec(self, enable=True):
        raise NotImplementedError

    async def _set_address(self, address, force=None):
        raise NotImplementedError

    async def _get_funcs(self):
        raise NotImplementedError

    async def write_quick(self, i2c_addr, force=None):
        raise NotImplementedError

    async def read_byte(self, i2c_addr, force=None):
        raise NotImplementedError

    async def write_byte(self, i2c_addr, value, force=None):
        raise NotImplementedError

    async def read_byte_data(self, i2c_addr, register, force=None):
        raise NotImplementedError

    async def write_byte_data(self, i2c_addr, register, value, force=None):
        raise NotImplementedError

    async def read_word_data(self, i2c_addr, register, force=None):
        raise NotImplementedError

    async def write_word_data(self, i2c_addr, register, value, force=None):
        raise NotImplementedError

    async def process_call(self, i2c_addr, register, value, force=None):
        raise NotImplementedError

    async def read_block_data(self, i2c_addr, register, force=None):
        raise NotImplementedError

    async def write_block_data(self, i2c_addr, register, data, force=None):
        raise NotImplementedError

    async def block_process_call(self, i2c_addr, register, data, force=None):
        raise NotImplementedError

    async def read_i2c_block_data(self, i2c_addr, register, length, force=None):
        raise NotImplementedError

    async def write_i2c_block_data(self, i2c_addr, register, data, force=None):
        raise NotImplementedError

    async def i2c_rdwr(self, *i2c_msgs):
        raise NotImplementedError

