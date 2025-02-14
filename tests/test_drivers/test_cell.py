import asyncio
from contextlib import ExitStack
from typing import TYPE_CHECKING
from hil.framework import Trace, record, seconds
from hil.utils.exception_table import exception_table


if TYPE_CHECKING:
    from ..conftest import Hil


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


async def test_output_voltage_per_cell(hil: "Hil"):
    # Generate voltage points from 0.5V to 4.3V in 0.1V steps
    VOLTAGES = [v / 10 for v in range(5, 44)]

    async with hil:
        # Set up the cell
        for cell in hil.cellsim.cells:
            await cell.enable()
            await cell.turn_on_output_relay()
            await cell.close_load_switch()

        table = exception_table(
            [f"cell: {cell.cell_num}" for cell in hil.cellsim.cells]
        )
        with ExitStack() as exit_stack:
            traces = [
                exit_stack.enter_context(record(cell.get_voltage))
                for cell in hil.cellsim.cells
            ]

            for voltage, gather_row in zip(VOLTAGES, table):
                await cell.set_voltage(voltage)

                async def _check_voltage(trace: Trace):
                    assert await trace.approx_once_settled(
                        voltage, rel_tol=0.2, timeout=seconds(0.1)
                    )

                await gather_row(
                    *(_check_voltage(t) for t in traces), name=f"{voltage}V"
                )


async def test_buck_voltage_per_cell(hil: "Hil"):
    BUCK_VOLTAGES = [v / 10 for v in range(15, 45)]

    async with hil:
        for cell in hil.cellsim.cells:
            # Set up the cell
            await cell.enable()
            await cell.turn_on_output_relay()
            await cell.close_load_switch()

        table = exception_table(
            [f"cell: {cell.cell_num}" for cell in hil.cellsim.cells]
        )
        with ExitStack() as exit_stack:
            traces = []
            for cell in hil.cellsim.cells:

                async def _get_voltage():
                    return await cell.get_voltage(channel=cell.AdcChannels.BUCK_VOLTAGE)

                traces.append(exit_stack.enter_context(record(_get_voltage)))

            for voltage, gather_row in zip(BUCK_VOLTAGES, table):
                for cell in hil.cellsim.cells:
                    await cell._set_buck_voltage(voltage)

                async def _check_voltage(trace: Trace):
                    assert await trace.approx_once_settled(
                        voltage, rel_tol=0.2, timeout=seconds(0.1)
                    )

                await gather_row(
                    *(_check_voltage(t) for t in traces), name=f"{voltage}V"
                )

    await asyncio.sleep(0)


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
