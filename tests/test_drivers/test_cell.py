import asyncio
from datetime import datetime
import logging
from contextlib import ExitStack
from typing import TYPE_CHECKING
import numpy as np

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
                await cell.turn_off_output_relay()
                await cell.close_load_switch()

            await asyncio.gather(
                *[cell.get_voltage() for cell in hil.cellsim.cells],
                *[cell.get_current() for cell in hil.cellsim.cells],
            )

            for cell in hil.cellsim.cells:
                await cell.open_load_switch()
                await cell.disable()


@pytest.mark.runs_on(hostname="chunky-otter")
async def test_output_voltage(hil: "Hil", record: Recorder):
    """
    Set output voltage (0.5- 4.3V, 0.1V steps)
        - Set output voltage
        - Measure output voltage
        - Check voltage within 0.02V
    """
    # Generate voltage points from 0.5V to 4.3V in 0.1V steps
    VOLTAGES = [v / 10 for v in range(5, 42)]
    cells = hil.cellsim.cells
    async with hil:
        # Set up the cell
        # for cell in cells:
        await asyncio.gather(*[cell.calibrate(data_points=32) for cell in cells])
        for cell in cells:
            await cell.enable()
            await cell.turn_on_output_relay()
            await cell.close_load_switch()

        table = ExceptionTable([f"cell: {cell.cell_num}" for cell in cells])
        with ExitStack() as exit_stack:
            traces = [
                exit_stack.enter_context(
                    record(cell.get_voltage, name=f"cell {cell.cell_num}")
                )
                for cell in cells
            ]
            target_trace = Trace("Target")
            record.add_trace(target_trace)

            for voltage in VOLTAGES:
                for cell in cells:
                    await cell.set_voltage(voltage)

                # Bracket the voltage with two samples to make it stepped
                target_trace.append(voltage)
                await asyncio.sleep(0.3)  # Collect data for this time
                target_trace.append(voltage)

                ALLOWED_TOLERANCE = 0.02
                now = datetime.now()
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
async def test_buck_voltage(hil: "Hil", record: Recorder):
    """
    Set Buck voltage (1.5 - 4.4V, 0.1V steps)
        - Set Buck voltage
        - Measure buck voltage
        - Check voltage within 0.1V
    """
    BUCK_VOLTAGES = [v / 10 for v in range(15, 45)]
    cells = hil.cellsim.cells

    async with hil:
        for cell in cells:
            await cell.enable()
            await cell.turn_off_output_relay()
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
                ALLOWED_TOLERANCE = 0.1
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


@pytest.mark.runs_on(hostname="chunky-otter")
async def test_cell_calibration(hil: "Hil"):
    """Test the cell calibration functionality"""
    async with hil:
        cell = hil.cellsim.cells[0]  # Test with first cell
        await cell.enable()

        # Store initial calibration values
        initial_ldo_x = cell._ldo_calibration.x.copy()
        initial_ldo_y = cell._ldo_calibration.y.copy()

        # Run calibration
        await cell.calibrate(data_points=8)  # Use fewer points for testing

        # Verify calibration changed the values
        assert cell._ldo_calibration.x != initial_ldo_x, (
            "Calibration did not update LDO x values"
        )
        assert cell._ldo_calibration.y != initial_ldo_y, (
            "Calibration did not update LDO y values"
        )

        # Verify calibration data is sorted and within expected ranges
        assert len(cell._ldo_calibration.x) == 8, (
            "Unexpected number of calibration points"
        )
        assert all(np.diff(cell._ldo_calibration.y) < 0), (
            "Y values not monotonically decreasing"
        )

        # Test voltage output with new calibration
        # Get the actual calibrated voltage range
        # Calculate safe voltage range considering both LDO and buck calibrations
        min_voltage = max(
            min(cell._ldo_calibration.x),  # LDO min calibrated voltage
            cell.MIN_LDO_VOLTAGE,  # LDO minimum voltage
            min(cell._buck_calibration.x),  # Buck min calibrated voltage
        )
        max_voltage = min(
            max(cell._ldo_calibration.x),  # LDO max calibrated voltage
            max(cell._buck_calibration.x),  # Buck max calibrated voltage
            cell.MAX_BUCK_VOLTAGE - 0.5,  # Leave margin for dropout
        )

        # Ensure we have a valid range
        assert max_voltage > min_voltage, "No valid voltage range for testing"

        # Create test points within the calibrated range
        test_voltages = np.linspace(
            min_voltage + 0.1, max_voltage - 0.1, num=5
        ).tolist()

        for voltage in test_voltages:
            voltage = float(voltage)  # Convert to float before using
            await cell.set_voltage(voltage)
            await asyncio.sleep(0.1)  # Allow voltage to settle
            measured = await cell.get_voltage()

            # Check if measured voltage is within 5% of target
            assert abs(measured - voltage) < voltage * 0.05, (
                f"Calibrated voltage out of range: target={voltage}V, measured={measured}V"
            )
