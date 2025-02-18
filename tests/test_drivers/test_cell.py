import asyncio
from datetime import datetime
import logging
from contextlib import ExitStack
from typing import TYPE_CHECKING

from hil.framework import Recorder, Trace, seconds
from hil.utils.exception_table import ExceptionTable
import pytest

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..conftest import Hil


@pytest.mark.runs_on(hostname="chunky-otter")
async def test_performance(hil: "Hil"):
    async with hil:
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


@pytest.mark.runs_on(hostname="chunky-otter")
async def test_output_voltage_per_cell(hil: "Hil", record: Recorder):
    # Generate voltage points from 0.5V to 4.3V in 0.1V steps
    VOLTAGES = [v / 10 for v in range(5, 44)]

    async with hil:
        # Set up the cell
        for cell in hil.cellsim.cells:
            await cell.enable()
            await cell.turn_on_output_relay()
            await cell.close_load_switch()

        table = ExceptionTable([f"cell: {cell.cell_num}" for cell in hil.cellsim.cells])
        with ExitStack() as exit_stack, table:
            traces = [
                exit_stack.enter_context(
                    record(cell.get_voltage, name=f"cell {cell.cell_num}")
                )
                for cell in hil.cellsim.cells
            ]

            for voltage in VOLTAGES:
                for cell in hil.cellsim.cells:
                    await cell.set_voltage(voltage)

                async def _check_voltage(trace: Trace):
                    await asyncio.sleep(0.5)
                    measured = await trace.get_value()
                    assert abs(measured - voltage) <= voltage * 0.2, (
                        f"Expected {voltage}V (±20%), got {measured}V"
                    )

                await table.gather_row(
                    *(_check_voltage(t) for t in traces), name=f"{voltage}V"
                )


@pytest.mark.runs_on(hostname="chunky-otter")
async def test_buck_voltage_per_cell(hil: "Hil", record: Recorder):
    """
    Test the buck voltage per cell.
        - Set Buck voltage (1.5- 4.4V, 0.1V steps)
            - Set Buck voltage
            - Measure buck voltage
            - Check voltage within 0.02V
    """
    BUCK_VOLTAGES = [v / 10 for v in range(15, 45)][::5]
    cells = hil.cellsim.cells

    async with hil:
        for cell in cells:
            await cell.enable()
            await cell.turn_on_output_relay()
            await cell.close_load_switch()

        table = ExceptionTable([f"cell: {cell.cell_num}" for cell in cells])
        with ExitStack() as exit_stack:
            traces: list[Trace] = []
            target_trace = Trace("Target")
            record.add_trace(target_trace)

            for cell in cells:

                async def _get_voltage():
                    return await cell.get_voltage(channel=cell.AdcChannels.BUCK_VOLTAGE)

                traces.append(
                    exit_stack.enter_context(
                        record(_get_voltage, name=f"cell {cell.cell_num}")
                    )
                )

            for voltage in BUCK_VOLTAGES:
                for cell in cells:
                    await cell._set_buck_voltage(voltage)
                target_trace.append(voltage)

                # Record for 0.3s to ensure all traces are recorded
                await asyncio.sleep(0.3)
                target_trace.append(voltage)  # Do this both sides to make it stepped

                now = datetime.now()
                ALLOWED_TOLERANCE = 0.02
                for ctx, t in table.iter_row(f"{voltage}V", traces):
                    with ctx:
                        assert (
                            t.to_polars()
                            .select(
                                (
                                    (voltage - ALLOWED_TOLERANCE < t.value)
                                    & (t.value < voltage + ALLOWED_TOLERANCE)
                                )
                                .filter((t.timestamp > now - seconds(0.2)))
                                .all()
                            )
                            .item(0, t._name)
                        )

        table.finalize()


@pytest.mark.runs_on(hostname="chunky-otter")
async def test_mux(hil: "Hil"):
    async with hil:
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
