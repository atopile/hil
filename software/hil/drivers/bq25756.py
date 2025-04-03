import smbus2
import time
from datetime import datetime

# I2C Bus and Device Addresses
I2C_BUS_NO = 1
MULTIPLEXER_ADDR = 0x70
MULTIPLEXER_CHANNEL_3 = 0x08 # Channel 3 = binary 0000 1000
BQ25756_ADDR = 0x6b

# Register Addresses
REG_CHARGER_STATUS_0 = 0x20
REG_CHARGER_STATUS_1 = 0x21
REG_FAULT_STATUS = 0x24
REG_FAULT_MASK = 0x2A
REG_PART_INFO = 0x3D
REG_REVERSE_MODE = 0x19
REG_REVERSE_VOLTAGE_LIMIT = 0x0C

def decode_status_0(status):
    """Decode Status Register 0 bits"""
    bits = {
        'CHRG_STAT': (status >> 6) & 0x03,  # Bits 7:6
        'CHRG_FAULT': (status >> 4) & 0x03,  # Bits 5:4
        'VSYS_STAT': (status >> 2) & 0x03,   # Bits 3:2
        'VSYS_FAULT': status & 0x03          # Bits 1:0
    }
    return bits

def decode_status_1(status):
    """Decode Status Register 1 bits"""
    bits = {
        'AC_STAT': (status >> 6) & 0x03,     # Bits 7:6
        'AC_FAULT': (status >> 4) & 0x03,    # Bits 5:4
        'BAT_STAT': (status >> 2) & 0x03,    # Bits 3:2
        'BAT_FAULT': status & 0x03           # Bits 1:0
    }
    return bits

def monitor_status(bus, duration=10, sample_rate=0.1):
    """Monitor status registers at specified sample rate for duration seconds"""
    print(f"\nMonitoring status registers for {duration} seconds at {1/sample_rate}Hz...")
    print("Press Ctrl+C to stop early")
    print("\nTime\t\tStatus 0\tStatus 1\tFault")
    print("-" * 80)
    
    start_time = time.time()
    last_status_0 = None
    last_status_1 = None
    
    try:
        while time.time() - start_time < duration:
            current_time = time.time()
            
            # Read status registers
            status_0 = bus.read_byte_data(BQ25756_ADDR, REG_CHARGER_STATUS_0)
            status_1 = bus.read_byte_data(BQ25756_ADDR, REG_CHARGER_STATUS_1)
            fault = bus.read_byte_data(BQ25756_ADDR, REG_FAULT_STATUS)
            
            # Only print if status changed
            if status_0 != last_status_0 or status_1 != last_status_1:
                timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                print(f"{timestamp}\t0x{status_0:02X}\t\t0x{status_1:02X}\t\t0x{fault:02X}")
                
                # Decode and print detailed status
                status_0_bits = decode_status_0(status_0)
                status_1_bits = decode_status_1(status_1)
                print(f"Status 0: CHRG_STAT={status_0_bits['CHRG_STAT']}, CHRG_FAULT={status_0_bits['CHRG_FAULT']}, "
                      f"VSYS_STAT={status_0_bits['VSYS_STAT']}, VSYS_FAULT={status_0_bits['VSYS_FAULT']}")
                print(f"Status 1: AC_STAT={status_1_bits['AC_STAT']}, AC_FAULT={status_1_bits['AC_FAULT']}, "
                      f"BAT_STAT={status_1_bits['BAT_STAT']}, BAT_FAULT={status_1_bits['BAT_FAULT']}")
                print("-" * 80)
                
                last_status_0 = status_0
                last_status_1 = status_1
            
            time.sleep(sample_rate)
            
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user")
    except Exception as e:
        print(f"\nError during monitoring: {e}")

# Initialize SMBus
bus = smbus2.SMBus(I2C_BUS_NO)

print(f"Attempting to communicate on I2C bus {I2C_BUS_NO}")

try:
    # Enable I2C Multiplexer Channel
    print(f"\nEnabling I2C multiplexer (addr 0x{MULTIPLEXER_ADDR:02X}) channel 3")
    bus.write_byte_data(MULTIPLEXER_ADDR, 0, MULTIPLEXER_CHANNEL_3)
    time.sleep(0.1)

    # Monitor status registers
    monitor_status(bus, duration=30, sample_rate=0.1)  # Monitor for 30 seconds at 10Hz

except Exception as e:
    print(f"\nAn error occurred during I2C communication: {e}")
    print("Please check connections, I2C addresses, and multiplexer setup.")

finally:
    # Close the bus connection
    if 'bus' in locals() and bus is not None:
        bus.close()
        print("\nI2C bus closed.") 