from pathlib import Path

# import pyinstrument
import asyncio

from hil.drivers.aiosmbus2 import AsyncSMBusPeripheral, AsyncSMBusBranch
from hil.drivers.cell import Cell
from hil.drivers.tca9548a import TCA9548A


ARTIFACTS_DIR = Path(__file__).parent.parent.parent / "artifacts"


async def test_performance():
    physical_bus = AsyncSMBusPeripheral(1)
    mux = TCA9548A(physical_bus)
    branch_buses = AsyncSMBusBranch.from_channels(physical_bus, mux, list(range(0, 8)))
    cells: list[Cell] = [
        await Cell.create(i, bus) for i, bus in enumerate(branch_buses)
    ]

    # profiler = pyinstrument.Profiler(interval=0.01)

    async with physical_bus:
        for cell in cells:
            await cell.setup()

        # with profiler:
        for _ in range(10):
            for cell in cells:
                await asyncio.gather(
                    cell.enable(),
                    cell.set_voltage(1),
                    cell.turn_on_output_relay(),
                    cell.close_load_switch(),
                )

                voltage, current = await asyncio.gather(
                    cell.get_voltage(),
                    cell.get_current(),
                )

                await asyncio.gather(
                    cell.open_load_switch(),
                    cell.turn_off_output_relay(),
                    cell.disable(),
                )

    # ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    # profiler.write_html(ARTIFACTS_DIR / "cell_performance.html")
