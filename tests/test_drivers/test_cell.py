from hil.drivers.aiosmbus2 import AsyncSMBus
from hil.drivers.cell import Cell


async def test_performance():
    bus = await AsyncSMBus.create(1)
    cells: list[Cell] = [Cell(x, bus) for x in range(0, 8)]

    for cell in cells:
        await cell.init()

    for _ in range(10):
        for cell in cells:
            await cell.enable()
            await cell.set_voltage(1)
            await cell.turn_on_output_relay()
            await cell.turn_on_load_switch()

            await cell.get_voltage()
            await cell.get_current()

            await cell.turn_off_load_switch()
            await cell.turn_off_output_relay()
            await cell.disable()

    await bus.close()
