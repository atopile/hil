# HIL Tests

This directory contains test scripts for the HIL (Hardware Interface Layer) drivers.

## Available Tests

- `test_tca6408.py`: Tests the TCA6408 GPIO expander driver
- `test_cell_gpio.py`: Tests the Cell class with TCA6408 GPIO integration

## Running Tests

To run a test, execute the script directly with Python:

```bash
# Run TCA6408 test
python -m hil.tests.test_tca6408

# Run Cell GPIO test
python -m hil.tests.test_cell_gpio
```

## Test Requirements

These tests require:
- A Raspberry Pi or similar device with I2C support
- The TCA6408 GPIO expander connected to the I2C bus
- For the Cell test, a complete Cell setup with all required components

## Test Output

The tests will output detailed logs showing the operations being performed and their results. If a test passes, it will display "All tests passed successfully!" at the end. If a test fails, it will display an error message with details about what went wrong. 