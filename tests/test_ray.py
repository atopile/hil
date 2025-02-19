import pytest
from hil.framework import dist


class Fix:
    def __init__(self, hil):
        self.hil = hil

    async def amethod(self):
        return self.hil

    def __str__(self):
        return f"hil: {self.hil}"


@pytest.fixture
def fix():
    return Fix(1)


@dist
async def test_remote_exec(fix):
    raise TypeError(await fix.amethod())
