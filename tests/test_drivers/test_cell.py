import asyncio
from contextlib import aclosing
import pytest
from hil.drivers.aiosmbus2 import AsyncSMBus, AsyncSMBusBranch, AsyncSMBusPeripheral
from hil.drivers.cell import Cell
from hil.drivers.tca9548a import TCA9548A

# Mark all async test functions in this module
# pytestmark = pytest.mark.asyncio


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
        # Open the bus before creating devices
        async with bus:
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
        self.physical_bus = AsyncSMBusPeripheral(1)
        # Open the bus before creating CellSim
        async with self.physical_bus:
            self.cellsim = await CellSim.create(self.physical_bus)
        return self

    async def aclose(self):
        for cell in self.cellsim.cells:
            await cell.aclose()


@pytest.fixture(scope="session")
async def hil():
    # Create HIL instance
    hil = await Hil.create()
    # Open bus for the duration of the test session
    async with hil.physical_bus:
        yield hil


async def test_performance(hil: Hil):
    async with aclosing(hil):
        for cell in hil.cellsim.cells:
            await cell.reset()
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


# Generate voltage points from 0.5V to 4.3V in 0.1V steps
VOLTAGES = [v / 10 for v in range(5, 44)]


@pytest.mark.parametrize(
    "cell_idx,voltage",
    [
        (cell_idx, voltage)
        for cell_idx in range(8)  # For all 8 cells
        for voltage in VOLTAGES
    ],
)
async def test_output_voltage_per_cell(hil: Hil, cell_idx: int, voltage: float):
    cell = hil.cellsim.cells[cell_idx]
    async with aclosing(cell):
        # Set up the cell
        await cell.enable()
        await cell.set_voltage(voltage)
        await cell.turn_on_output_relay()
        await cell.close_load_switch()

        # Allow voltage to settle
        await asyncio.sleep(0.1)

        # Measure and check accuracy
        measured_voltage = await cell.get_voltage()
        assert measured_voltage == pytest.approx(voltage, rel=0.2)


BUCK_VOLTAGES = [v / 10 for v in range(15, 45)]


@pytest.mark.parametrize(
    "cell_idx,voltage",
    [
        (cell_idx, voltage)
        for cell_idx in range(8)  # For all 8 cells
        for voltage in BUCK_VOLTAGES
    ],
)
async def test_buck_voltage_per_cell(hil: Hil, cell_idx: int, voltage: float):
    cell = hil.cellsim.cells[cell_idx]
    async with aclosing(cell):
        # Set up the cell
        await cell.enable()
        await cell._set_buck_voltage(voltage)
        await cell.turn_on_output_relay()
        await cell.close_load_switch()

        # Allow voltage to settle
        await asyncio.sleep(0.1)

        # Measure and check accuracy
        measured_voltage = await cell.get_voltage(channel=cell.AdcChannels.BUCK_VOLTAGE)
        assert measured_voltage == pytest.approx(voltage, rel=0.2)


async def test_mux(hil: Hil):
    async with aclosing(hil):
        # Write binary to the mux for each cell
        for cell in hil.cellsim.cells:
            async with cell.bus() as handle:
                await handle.write_byte_data(cell.Devices.GPIO, 0x01, cell.cell_num)

        # Verify written values
        for cell in hil.cellsim.cells:
            async with cell.bus() as handle:
                read_value = await handle.read_byte_data(cell.Devices.GPIO, 0x01)
                error_msg = f"Cell {cell.cell_num} GPIO state mismatch: wrote {cell.cell_num}, read {read_value}"
                assert read_value == cell.cell_num, error_msg
