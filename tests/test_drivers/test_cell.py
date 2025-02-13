import asyncio
import pytest
import pytest_asyncio
from hil.drivers.aiosmbus2 import AsyncSMBus, AsyncSMBusBranch, AsyncSMBusPeripheral
from hil.drivers.cell import Cell
from hil.drivers.tca9548a import TCA9548A

# Mark the module as using asyncio
pytestmark = pytest.mark.asyncio


class CellSim:
    """
    Simulates a cell for testing purposes.
    """

    bus: AsyncSMBus
    cells: list[Cell]
    _mux: TCA9548A
    _branch_buses: AsyncSMBusBranch

    @classmethod
    async def create(cls, bus: AsyncSMBus):
        self = cls()
        self._mux = TCA9548A(bus)
        self._branch_buses = AsyncSMBusBranch.from_channels(
            bus, self._mux, list(range(0, 8))
        )
        self.cells = [
            await Cell.create(i, bus) for i, bus in enumerate(self._branch_buses)
        ]
        return self


class Hil:
    """
    Simulates a HIL for testing purposes.
    """

    cellsim: CellSim

    @classmethod
    async def create(cls):
        self = cls()
        physical_bus = AsyncSMBusPeripheral(1)
        self.physical_bus = physical_bus
        self.cellsim = await CellSim.create(physical_bus)
        return self


@pytest.fixture(scope="session")
async def hil():
    hil = await Hil.create()
    async with hil.physical_bus:
        yield hil


async def test_performance(hil: Hil):
    for cell in hil.cellsim.cells:
        await cell.setup()
        await cell.set_voltage(1)

    for _ in range(10):
        for cell in hil.cellsim.cells:
            await cell.enable()
            await cell.turn_on_output_relay()
            await cell.close_load_switch()

        await asyncio.gather(
            *[cell.get_voltage() for cell in hil.cellsim.cells],
            *[cell.get_current() for cell in hil.cellsim.cells],
        )

        for cell in hil.cellsim.cells:
            await cell.open_load_switch()
            await cell.turn_off_output_relay()
            await cell.disable()

@pytest.mark.parametrize("voltage", [v/10 for v in range(5, 44)])  # 0.5V to 4.3V in 0.1V steps
async def test_voltage_accuracy(hil: Hil, voltage: float):
    # Test each cell
    for cell in hil.cellsim.cells:
        await cell.setup()
        await cell.enable()
        await cell.set_voltage(voltage)
        await cell.turn_on_output_relay()
        
        # Allow voltage to settle
        await asyncio.sleep(0.1)
        
        # Measure voltage and check accuracy
        measured_voltage = await cell.get_voltage()
        
        # Assert voltage is within 1% tolerance
        assert abs(measured_voltage - voltage) <= voltage * 0.01, \
            f"Cell {cell} voltage accuracy error: set={voltage}V, measured={measured_voltage}V"
        
        # Cleanup
        await cell.turn_off_output_relay()
        await cell.disable()


