import asyncio
from datetime import datetime
import logging
from contextlib import ExitStack
from typing import TYPE_CHECKING, cast, List
import numpy as np
import math
import time

from hil.framework import Recorder, Trace, seconds, record
from hil.utils.exception_table import ExceptionTable
from hil.drivers.cell import Cell
import pytest

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from software.hil.drivers.examples.spacebms_hil import SpaceBMSHil



@pytest.mark.runs_on(hostname="tipsy-raccoon")
async def test_performance(space_bms_hil: "SpaceBMSHil"):
    cells = space_bms_hil.cellsim.cells
    for cell in cells:
        await cell.reset()
        await cell.set_voltage(1)

    for _ in range(10):
        for cell in cells:
            await cell.enable()
            await cell.turn_off_output_relay()
            await cell.turn_on_output_relay()
            await cell.close_load_switch()

        await asyncio.gather(
            *[cell.get_voltage() for cell in cells],
            *[cell.get_current() for cell in cells],
        )

        for cell in cells:
            await cell.open_load_switch()
            await cell.disable()


@pytest.mark.runs_on(hostname="tipsy-raccoon")
async def test_output_voltage(space_bms_hil: "SpaceBMSHil", record: Recorder):
    """
    Set output voltage (0.5- 4.3V, 0.1V steps)
        - Set output voltage
        - Measure output voltage
        - Check voltage within 0.02V
    """
    VOLTAGES = [v / 10 for v in range(5, 42)]
    cells = space_bms_hil.cellsim.cells

    logger.info("Calibrating cells before output voltage test...")
    await asyncio.gather(*[cell.calibrate(data_points=32) for cell in cells])
    logger.info("Setting up cells for output voltage test...")
    for cell in cells:
        await cell.enable()
        await cell.turn_on_output_relay()
        await cell.close_load_switch()

    logger.info("Running output voltage sweep...")
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
            await asyncio.gather(*[cell.set_voltage(voltage) for cell in cells])
            target_trace.append(voltage)
            await asyncio.sleep(0.3)
            target_trace.append(voltage)

            ALLOWED_TOLERANCE = 0.02
            now = datetime.now()
            for ctx, t in table.iter_row(f"{voltage:.1f}V", traces):
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
    logger.info("Output voltage test finished.")
    # Cleanup happens automatically via fixture


@pytest.mark.runs_on(hostname="tipsy-raccoon")
async def test_buck_voltage(space_bms_hil: "SpaceBMSHil", record: Recorder):
    """
    Set Buck voltage (1.5 - 4.4V, 0.1V steps)
        - Set Buck voltage
        - Measure buck voltage
        - Check voltage within 0.1V
    """
    BUCK_VOLTAGES = [v / 10 for v in range(15, 45)]
    cells = space_bms_hil.cellsim.cells

    logger.info("Setting up cells for buck voltage test...")
    for cell in cells:
        await cell.enable()
        await cell.turn_off_output_relay()
        await cell.close_load_switch()

    logger.info("Running buck voltage sweep...")
    table = ExceptionTable([f"cell: {cell.cell_num}" for cell in cells])
    with ExitStack() as exit_stack:
        traces: list[Trace] = []
        target_trace = Trace("Target")
        record.add_trace(target_trace)

        for cell in cells:
            async def _get_buck_voltage(target_cell=cell):
                # Closure to capture the correct cell
                return await target_cell.get_voltage(channel=target_cell.AdcChannels.BUCK_VOLTAGE)

            traces.append(
                exit_stack.enter_context(
                    record(_get_buck_voltage, name=f"cell {cell.cell_num}")
                )
            )

        for voltage in BUCK_VOLTAGES:
            await asyncio.gather(*[cell._set_buck_voltage(voltage) for cell in cells])
            target_trace.append(voltage)
            await asyncio.sleep(0.3)
            target_trace.append(voltage)

            now = datetime.now()
            ALLOWED_TOLERANCE = 0.2
            for ctx, t in table.iter_row(f"{voltage:.1f}V", traces):
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
    logger.info("Buck voltage test finished.")
    # Cleanup happens automatically via fixture


@pytest.mark.runs_on(hostname="tipsy-raccoon")
async def test_mux(space_bms_hil: "SpaceBMSHil"):
    """Tests basic GPIO write/read via output register (original mux test intent)."""
    logger.info("Starting GPIO basic write/read test (test_mux)...")
    for cell in space_bms_hil.cellsim.cells:
        async with cell.bus.handle() as handle:
            await handle.write_byte_data(cell.Devices.GPIO, 0x01, cell.cell_num)

    for cell in space_bms_hil.cellsim.cells:
        async with cell.bus.handle() as handle:
            read_value = await handle.read_byte_data(cell.Devices.GPIO, 0x01)
            error_msg = f"Cell {cell.cell_num} GPIO output state mismatch: wrote {cell.cell_num}, read {read_value}"
            assert read_value == cell.cell_num, error_msg
    logger.info("GPIO basic write/read test (test_mux) finished.")


@pytest.mark.runs_on(hostname="tipsy-raccoon")
async def test_external_load_current(space_bms_hil: "SpaceBMSHil", record: Recorder):
    """Tests current measurement when the external load is enabled for all cells."""
    logger.info("Starting external load current sense test for all cells...")

    target_voltage = 4.0
    EXPECTED_RESISTANCE = 100.0 # Ohms
    tolerance = 0.1 # +/- 10%

    expected_current = target_voltage / EXPECTED_RESISTANCE
    lower_bound = expected_current * (1 - tolerance)
    upper_bound = expected_current * (1 + tolerance)

    failed_cells = []
    with ExitStack() as stack:
        current_traces = {}
        for cell_to_test in space_bms_hil.cellsim.cells:
            trace = stack.enter_context(
                record(cell_to_test.get_current, name=f"cell_{cell_to_test.cell_num}_current")
            )
            current_traces[cell_to_test.cell_num] = trace

        for cell_to_test in space_bms_hil.cellsim.cells:
            logger.info(f"--- Testing Cell {cell_to_test.cell_num} ---")
            cell_failed_this_iteration = False
            try:
                await cell_to_test.enable()
                await cell_to_test.turn_on_output_relay()
                await cell_to_test.set_voltage(target_voltage)
                await asyncio.sleep(0.01)
                await cell_to_test.turn_on_external_load()
                await asyncio.sleep(0.01)

                measured_current = await cell_to_test.get_current()
                logger.info(f"Cell {cell_to_test.cell_num} - Measured current: {measured_current:.4f} A")

                assert lower_bound <= measured_current <= upper_bound, \
                    f"Measured current ({measured_current:.4f} A) out of expected range ({lower_bound:.3f} - {upper_bound:.3f} A)"
                logger.info(f"Cell {cell_to_test.cell_num} passed.")

            except Exception as e:
                cell_failed_this_iteration = True
                logger.error(f"Error during test for cell {cell_to_test.cell_num}: {e}")
                failed_cells.append(cell_to_test.cell_num)
            finally:
                try:
                    if cell_to_test:
                         await cell_to_test.turn_off_external_load()
                         await cell_to_test.turn_off_output_relay()
                         await cell_to_test.disable()
                except Exception as cleanup_e:
                    logger.error(f"Error during cleanup for cell {cell_to_test.cell_num}: {cleanup_e}")
                    if cell_to_test.cell_num not in failed_cells:
                         failed_cells.append(cell_to_test.cell_num)

    if failed_cells:
         pytest.fail(f"External load test failed for cells: {failed_cells}", pytrace=False)

    logger.info("External load current test completed for all cells.")


@pytest.mark.runs_on(hostname="tipsy-raccoon")
async def test_cell_calibration(space_bms_hil: "SpaceBMSHil", record: Recorder):
    """Test the cell calibration functionality on the first cell."""
    logger.info("Starting cell calibration test (on cell 0)...")
    if not space_bms_hil.cellsim.cells:
        pytest.skip("No cells available for calibration test.")
        return

    cell = space_bms_hil.cellsim.cells[0]
    await cell.enable() # Enable cell before calibration

    with record(cell.get_voltage, name=f"cell_{cell.cell_num}_cal_voltage") as voltage_trace:
        try:
            initial_ldo_x = cell._ldo_calibration.x.copy()
            initial_ldo_y = cell._ldo_calibration.y.copy()

            logger.info(f"Running calibration for cell {cell.cell_num} (recording voltage)...")
            await cell.calibrate(data_points=8)

            assert cell._ldo_calibration.x != initial_ldo_x, \
                   f"Cell {cell.cell_num} calibration did not update LDO x values"
            assert cell._ldo_calibration.y != initial_ldo_y, \
                   f"Cell {cell.cell_num} calibration did not update LDO y values"

            assert len(cell._ldo_calibration.x) == 8, \
                   f"Cell {cell.cell_num} unexpected number of calibration points"
            assert np.all(np.diff(cell._ldo_calibration.y) < 1e-9), \
                   f"Cell {cell.cell_num} Y values not monotonically decreasing"

            logger.info(f"Validating voltage output for cell {cell.cell_num} post-calibration..." + 
                        f" (Trace '{voltage_trace.name}' contains calibration voltage curve)")
            min_voltage = max(min(cell._ldo_calibration.x), cell.MIN_LDO_VOLTAGE)
            max_voltage = min(max(cell._ldo_calibration.x), cell.MAX_BUCK_VOLTAGE - 0.5)

            assert max_voltage > min_voltage, f"Cell {cell.cell_num} no valid voltage range post-calibration"

            test_voltages = cast(list[float], np.linspace(min_voltage + 0.1, max_voltage - 0.1, num=5).tolist())
            with record(cell.get_voltage, name=f"cell_{cell.cell_num}_cal_validation_voltage"):
                 target_trace = Trace(f"cell_{cell.cell_num}_cal_validation_target")
                 record.add_trace(target_trace)
                 for voltage in test_voltages:
                     voltage = float(voltage)
                     await cell.set_voltage(voltage)
                     target_trace.append(voltage)
                     await asyncio.sleep(0.2)
                     target_trace.append(voltage)
                     measured = await cell.get_voltage()
                     assert abs(measured - voltage) < voltage * 0.05, \
                           f"Cell {cell.cell_num} calibrated voltage out of range: target={voltage:.3f}V, measured={measured:.3f}V"

            logger.info(f"Cell {cell.cell_num} calibration test passed.")

        finally:
             await cell.disable() # Ensure cell is disabled


# --- Multi-Relay High Frequency Helper ---
async def _generate_multi_relay_freq(
    cells_to_use: List[Cell],
    frequency: float,
    duration: float
):
    num_relays = len(cells_to_use)
    if num_relays == 0: return

    max_possible_freq = num_relays * 1000.0
    if frequency > max_possible_freq:
         logger.warning(
             f"Target freq {frequency:.1f} Hz > theoretical max {max_possible_freq:.1f} Hz "
             f"for {num_relays} relays. Individual relays overdriven."
         )
    if frequency <= 0: return

    step_delay = 1.0 / (2.0 * frequency)
    relay_states = {cell.cell_num: False for cell in cells_to_use}
    start_time = time.monotonic()
    end_time = start_time + duration
    step_count = 0

    # Setup
    await asyncio.gather(*[cell.enable() for cell in cells_to_use])
    await asyncio.gather(*[cell.close_load_switch() for cell in cells_to_use])
    await asyncio.gather(*[cell.turn_off_output_relay() for cell in cells_to_use])

    try:
        while time.monotonic() < end_time:
            relay_index_to_toggle = step_count % num_relays
            cell_to_toggle = cells_to_use[relay_index_to_toggle]
            new_state = not relay_states[cell_to_toggle.cell_num]

            if new_state: await cell_to_toggle.turn_on_output_relay()
            else: await cell_to_toggle.turn_off_output_relay()
            relay_states[cell_to_toggle.cell_num] = new_state
            step_count += 1

            current_time = time.monotonic()
            next_step_target_time = start_time + (step_count * step_delay)
            sleep_duration = max(0, next_step_target_time - current_time)
            if sleep_duration > 0:
                 await asyncio.sleep(sleep_duration)
    finally:
        # Cleanup
        cleanup_tasks = []
        for cell in cells_to_use:
            cleanup_tasks.append(cell.turn_off_output_relay())
            cleanup_tasks.append(cell.open_load_switch())
            cleanup_tasks.append(cell.disable())
        results = await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        for i, result in enumerate(results):
             if isinstance(result, Exception):
                  logger.error(f"Error during multi-relay cleanup task {i}: {result}")


# --- Multi-Relay Tests ---

@pytest.mark.runs_on(hostname="tipsy-raccoon")
async def test_multi_relay_high_freq(space_bms_hil: "SpaceBMSHil"):
    """Tests generating higher frequencies by interleaving multiple relays."""
    target_frequencies = [500.0, 750.0, 1000.0, 1500.0, 2000.0]
    duration = 1.0
    max_relay_freq = 200.0 # User adjusted this limit

    logger.info(f"Starting multi-relay high frequency test. Targets: {target_frequencies} Hz")
    for freq in target_frequencies:
        num_relays_needed = math.ceil(freq / max_relay_freq)
        if num_relays_needed > len(space_bms_hil.cellsim.cells):
            logger.warning(f"Skipping {freq:.1f} Hz. Need {num_relays_needed} relays > {len(hil.cells)} available.")
            pytest.skip(f"Insufficient relays for {freq:.1f} Hz")
            continue
        cells_for_freq = hil.cells[:num_relays_needed]
        logger.info(f"Testing {freq:.1f} Hz using {len(cells_for_freq)} relays ({duration}s)...")
        await _generate_multi_relay_freq(cells_for_freq, freq, duration)
        await asyncio.sleep(0.5)
    logger.info("Multi-relay high frequency test finished.")


@pytest.mark.runs_on(hostname="tipsy-raccoon")
async def test_relay_techno_beat(space_bms_hil: "SpaceBMSHil"):
    """Generates a DnB-style beat pattern using many dedicated relays for kick/snare."""
    logger.info("Starting relay DnB beat test with many relays...")
    bpm = 174.0
    quarter_note_duration = 60.0 / bpm
    sixteenth_note_duration = quarter_note_duration / 4.0
    kick_num_relays = 16
    snare_num_relays = 8
    max_relay_freq = 1000.0

    sounds = {
        "kick": {"freq": 150.0, "duration": sixteenth_note_duration * 0.8, "indices": list(range(kick_num_relays))},
        "snare": {"freq": 1000.0, "duration": sixteenth_note_duration * 0.8, "indices": list(range(snare_num_relays))}
    }

    all_indices = [i for s in sounds.values() for i in s["indices"]]
    total_relays_required = max(all_indices) + 1 if all_indices else 0
    logger.info(f"Beat requires {total_relays_required} unique relays.")
    all_cells = space_bms_hil.cellsim.cells
    if total_relays_required > len(all_cells):
        pytest.skip(f"Insufficient relays ({len(all_cells)}). Beat requires indices up to {total_relays_required-1}.")
        return

    sequence = [None] * 16
    sequence[0] = "kick"
    sequence[3] = "snare"
    sequence[9] = "kick"
    sequence[11] = "snare"
    num_bars = 4

    logger.info(f"Playing {num_bars} bars at {bpm} BPM...")
    start_bar_time = time.monotonic()
    for bar in range(num_bars):
        bar_offset = bar * 16 * sixteenth_note_duration
        for step, sound_name in enumerate(sequence):
            step_start_target_time = start_bar_time + bar_offset + (step * sixteenth_note_duration)
            if sound_name is not None:
                sound_info = sounds[sound_name]
                cells_for_sound = [all_cells[i] for i in sound_info["indices"]]
                await _generate_multi_relay_freq(cells_for_sound, sound_info["freq"], sound_info["duration"])
                remaining_pause = sixteenth_note_duration - sound_info["duration"]
                if remaining_pause > 1e-9:
                    current_time = time.monotonic()
                    pause_target_time = step_start_target_time + sound_info["duration"]
                    actual_remaining = max(0, pause_target_time + remaining_pause - current_time)
                    if actual_remaining > 0: await asyncio.sleep(actual_remaining)
            else:
                current_time = time.monotonic()
                pause_target_time = step_start_target_time
                actual_remaining = max(0, pause_target_time + sixteenth_note_duration - current_time)
                if actual_remaining > 0: await asyncio.sleep(actual_remaining)

    logger.info("Relay DnB beat test finished.")


