import io
import csv
import time
import contextlib
from smbus2 import SMBus
from cell import Cell

# Helper function to capture printed output from a test step.
def run_test_step(func, *args, **kwargs):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        func(*args, **kwargs)
    output = buffer.getvalue().strip()
    return output

def main():
    # List of test steps (vertical rows) with callable functions.
    # Each tuple has the test name and a function (or lambda) that performs the test.
    # NOTE: For functions requiring parameters, lambdas are used.
    test_steps = [
        ("Initialization", lambda cell_obj: cell_obj.init()),
        ("Enable", lambda cell_obj: cell_obj.enable()),
        ("Set Voltage", lambda cell_obj: cell_obj.set_voltage(3.7)),
        ("Get Voltage", lambda cell_obj: cell_obj.get_voltage()),
        ("Set Buck Voltage", lambda cell_obj: cell_obj.set_buck_voltage(3.7 * 1.05)),
        ("Set LDO Voltage", lambda cell_obj: cell_obj.set_ldo_voltage(3.7)),
        ("Turn On Output Relay", lambda cell_obj: cell_obj.turn_on_output_relay()),
        ("Turn Off Output Relay", lambda cell_obj: cell_obj.turn_off_output_relay()),
        ("Turn On Load Switch", lambda cell_obj: cell_obj.turn_on_load_switch()),
        ("Turn Off Load Switch", lambda cell_obj: cell_obj.turn_off_load_switch()),
        ("Get Current", lambda cell_obj: cell_obj.get_current()),
        ("Read Shunt Current", lambda cell_obj: cell_obj.read_shunt_current()),
        ("Disable", lambda cell_obj: cell_obj.disable())
    ]
    
    # Initialize an empty dictionary to aggregate results.
    # Keys are test step names; values are lists of outputs per cell (Cell 0 ... Cell 7).
    aggregated_results = { test_name: [] for test_name, _ in test_steps }
    
    # Open the real SMBus (bus 1 is typical on Raspberry Pi CM4)
    bus = SMBus(1)
    
    # Loop through all 8 cells (assumed to be connected on mux channels 0-7)
    for cell_num in range(8):
        cell_obj = Cell(cell_num, bus)
        for test_name, test_func in test_steps:
            # Run the test step for this cell; pass the cell_obj into the lambda.
            output = run_test_step(lambda: test_func(cell_obj))
            aggregated_results[test_name].append(output)
            # Short delay between tests
            time.sleep(0.05)
        # Optional: pause between cells.
        time.sleep(0.1)
    
    # Close the bus
    bus.close()
    
    # Write the aggregated summary to CSV.
    csv_filename = "cell_hardware_test_summary.csv"
    with open(csv_filename, "w", newline="") as csvfile:
        header = ["Test Step"] + [f"Cell {cell_num}" for cell_num in range(8)]
        writer = csv.writer(csvfile)
        writer.writerow(header)
        for test_name in aggregated_results:
            row = [test_name] + aggregated_results[test_name]
            writer.writerow(row)
    
    # Print a nicely formatted table to the console.
    print("\nTest Summary for 8 Cells (each row is a test, each column a cell):\n")
    header_row = ["Test Step"] + [f"Cell {cell_num}" for cell_num in range(8)]
    # Calculate the maximum width for each column for neat formatting.
    col_widths = [max(len(str(item)) for item in col) for col in zip(header_row, *[[str(x) for x in aggregated_results[test_name]] for test_name in aggregated_results])]
    
    # Print header
    fmt = "  ".join("{:<" + str(w) + "}" for w in col_widths)
    print(fmt.format(*header_row))
    print("-" * (sum(col_widths) + 2 * len(col_widths)))
    
    # Print each row
    for test_name in aggregated_results:
        row = [test_name] + aggregated_results[test_name]
        print(fmt.format(*row))
    
if __name__ == "__main__":
    main()