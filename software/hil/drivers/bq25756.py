import smbus2
import time
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel

# Initialize rich console
console = Console()

# I2C Bus and Device Addresses
I2C_BUS_NO = 1
BQ25756_ADDR = 0x6b

# Register Addresses
REG_CHARGER_STATUS_0 = 0x20
REG_CHARGER_STATUS_1 = 0x21
REG_FAULT_STATUS = 0x24
REG_FAULT_MASK = 0x2A
REG_PART_INFO = 0x3D
REG_REVERSE_MODE = 0x19
REG_REVERSE_VOLTAGE_LIMIT = 0x0C
REG_CHARGER_CTRL = 0x17  # Charger Control register
REG_PIN_CTRL = 0x18      # Pin Control register
REG_POWER_PATH_CTRL = 0x19  # Power Path and Reverse Mode Control
REG_ADC_CTRL = 0x2B     # ADC Control register
REG_ADC_CHANNEL_CTRL = 0x2C  # ADC Channel Control register

# ADC Register Addresses (MSB/LSB pairs)
REG_IAC_ADC_MSB = 0x2E
REG_IAC_ADC_LSB = 0x2D
REG_IBAT_ADC_MSB = 0x30
REG_IBAT_ADC_LSB = 0x2F
REG_VAC_ADC_MSB = 0x32
REG_VAC_ADC_LSB = 0x31
REG_VBAT_ADC_MSB = 0x34
REG_VBAT_ADC_LSB = 0x33
REG_TS_ADC_MSB = 0x38
REG_TS_ADC_LSB = 0x37
REG_VFB_ADC_MSB = 0x3A
REG_VFB_ADC_LSB = 0x39

def decode_status_0(status):
    """Decode Status Register 0 bits"""
    bits = {
        'CHRG_STAT': (status >> 6) & 0x03,  # Bits 7:6
        'CHRG_FAULT': (status >> 4) & 0x03,  # Bits 5:4
        'VSYS_STAT': (status >> 2) & 0x03,   # Bits 3:2
        'VSYS_FAULT': status & 0x03          # Bits 1:0
    }
    
    # Decode CHRG_STAT
    chrg_stat = bits['CHRG_STAT']
    if chrg_stat == 0:
        bits['CHRG_STAT_DESC'] = "Not charging"
    elif chrg_stat == 1:
        bits['CHRG_STAT_DESC'] = "Charging"
    elif chrg_stat == 2:
        bits['CHRG_STAT_DESC'] = "Charging complete"
    else:
        bits['CHRG_STAT_DESC'] = "Reserved"
    
    # Decode VSYS_FAULT
    vsys_fault = bits['VSYS_FAULT']
    if vsys_fault == 0:
        bits['VSYS_FAULT_DESC'] = "No fault"
    elif vsys_fault == 1:
        bits['VSYS_FAULT_DESC'] = "System voltage fault (OVP/UVP)"
    elif vsys_fault == 2:
        bits['VSYS_FAULT_DESC'] = "System voltage fault (OVP/UVP)"
    else:
        bits['VSYS_FAULT_DESC'] = "Reserved"
    
    # Decode VSYS_STAT
    vsys_stat = bits['VSYS_STAT']
    if vsys_stat == 0:
        bits['VSYS_STAT_DESC'] = "Normal"
    elif vsys_stat == 1:
        bits['VSYS_STAT_DESC'] = "In transition"
    elif vsys_stat == 2:
        bits['VSYS_STAT_DESC'] = "In transition"
    else:
        bits['VSYS_STAT_DESC'] = "Fault"
    
    return bits

def decode_status_1(status):
    """Decode Status Register 1 bits"""
    bits = {
        'AC_STAT': (status >> 6) & 0x03,     # Bits 7:6
        'AC_FAULT': (status >> 4) & 0x03,    # Bits 5:4
        'BAT_STAT': (status >> 2) & 0x03,    # Bits 3:2
        'BAT_FAULT': status & 0x03           # Bits 1:0
    }
    
    # Decode AC_STAT
    ac_stat = bits['AC_STAT']
    if ac_stat == 0:
        bits['AC_STAT_DESC'] = "No input"
    elif ac_stat == 1:
        bits['AC_STAT_DESC'] = "USB input"
    elif ac_stat == 2:
        bits['AC_STAT_DESC'] = "AC adapter"
    else:
        bits['AC_STAT_DESC'] = "Reserved"
    
    # Decode BAT_STAT
    bat_stat = bits['BAT_STAT']
    if bat_stat == 0:
        bits['BAT_STAT_DESC'] = "No battery"
    elif bat_stat == 1:
        bits['BAT_STAT_DESC'] = "Battery present"
    elif bat_stat == 2:
        bits['BAT_STAT_DESC'] = "Battery charging"
    else:
        bits['BAT_STAT_DESC'] = "Reserved"
    
    # Decode BAT_FAULT
    bat_fault = bits['BAT_FAULT']
    if bat_fault == 0:
        bits['BAT_FAULT_DESC'] = "No fault"
    elif bat_fault == 1:
        bits['BAT_FAULT_DESC'] = "Battery over-voltage"
    elif bat_fault == 2:
        bits['BAT_FAULT_DESC'] = "Battery under-voltage"
    else:
        bits['BAT_FAULT_DESC'] = "Battery fault (reserved)"
    
    # Decode AC_FAULT
    ac_fault = bits['AC_FAULT']
    if ac_fault == 0:
        bits['AC_FAULT_DESC'] = "No fault"
    elif ac_fault == 1:
        bits['AC_FAULT_DESC'] = "Input over-voltage"
    elif ac_fault == 2:
        bits['AC_FAULT_DESC'] = "Input under-voltage"
    else:
        bits['AC_FAULT_DESC'] = "Input fault (reserved)"
    
    return bits

def decode_fault_status(fault):
    """Decode Fault Status Register bits"""
    bits = {
        'VAC_UV_STAT': (fault >> 7) & 0x01,    # Bit 7: Input under-voltage status
        'VAC_OV_STAT': (fault >> 6) & 0x01,    # Bit 6: Input over-voltage status
        'IBAT_OCP_STAT': (fault >> 5) & 0x01,  # Bit 5: Battery over-current status
        'VBAT_OV_STAT': (fault >> 4) & 0x01,   # Bit 4: Battery over-voltage status
        'TSHUT_STAT': (fault >> 3) & 0x01,     # Bit 3: Thermal shutdown status
        'CHG_TMR_STAT': (fault >> 2) & 0x01,   # Bit 2: Charge safety timer status
        'DRV_OKZ_STAT': (fault >> 1) & 0x01,   # Bit 1: DRV_SUP pin voltage status
        'RESERVED': fault & 0x01               # Bit 0: Reserved
    }
    
    # Build description of active faults
    active_faults = []
    for bit_name, value in bits.items():
        if value:
            if bit_name == 'VAC_UV_STAT':
                active_faults.append("Input under-voltage protection")
            elif bit_name == 'VAC_OV_STAT':
                active_faults.append("Input over-voltage protection")
            elif bit_name == 'IBAT_OCP_STAT':
                active_faults.append("Battery over-current detected")
            elif bit_name == 'VBAT_OV_STAT':
                active_faults.append("Battery over-voltage protection")
            elif bit_name == 'TSHUT_STAT':
                active_faults.append("Thermal shutdown protection")
            elif bit_name == 'CHG_TMR_STAT':
                active_faults.append("Charge safety timer expired")
            elif bit_name == 'DRV_OKZ_STAT':
                active_faults.append("DRV_SUP pin voltage out of range")
    
    bits['ACTIVE_FAULTS'] = active_faults
    return bits

def read_with_retry(bus, addr, reg, max_retries=3):
    """Read I2C register with retry logic"""
    for attempt in range(max_retries):
        try:
            return bus.read_byte_data(addr, reg)
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            time.sleep(0.01)  # Short delay before retry

def write_with_retry(bus, addr, reg, value, max_retries=3):
    """Write I2C register with retry logic"""
    for attempt in range(max_retries):
        try:
            bus.write_byte_data(addr, reg, value)
            return True
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            time.sleep(0.01)  # Short delay before retry

def validate_voltage(name, value, expected_range):
    """Validate voltage is within expected range"""
    min_v, max_v = expected_range
    if value < min_v or value > max_v:
        return f"Warning: {name} voltage {value}mV outside expected range {min_v}-{max_v}mV"
    return None

def read_adc_values(bus):
    """Read and decode ADC values for all available channels"""
    try:
        # Read ADC registers (16-bit values)
        # Read MSB first, then LSB for each channel
        adc_values = {}
        warnings = []
        
        # Define ADC channels and their conversion factors
        channels = {
            'VAC': (REG_VAC_ADC_MSB, REG_VAC_ADC_LSB, 2, (0, 65534), False),    # 2mV per LSB, unsigned
            'VBAT': (REG_VBAT_ADC_MSB, REG_VBAT_ADC_LSB, 2, (0, 65534), False),  # 2mV per LSB, unsigned
            'IAC': (REG_IAC_ADC_MSB, REG_IAC_ADC_LSB, 0.8, (-20000, 20000), True),  # 0.8mA per LSB, 2's complement
            'IBAT': (REG_IBAT_ADC_MSB, REG_IBAT_ADC_LSB, 2, (-20000, 20000), True),  # 2mA per LSB, 2's complement
            'TS': (REG_TS_ADC_MSB, REG_TS_ADC_LSB, 0.09765625, (0, 99.90234375), False),  # % of REGN
            'VFB': (REG_VFB_ADC_MSB, REG_VFB_ADC_LSB, 1, (0, 2047), False)     # 1mV per LSB
        }
        
        for name, (msb_reg, lsb_reg, factor, valid_range, is_twos_complement) in channels.items():
            try:
                msb = read_with_retry(bus, BQ25756_ADDR, msb_reg)
                lsb = read_with_retry(bus, BQ25756_ADDR, lsb_reg)
                raw = (msb << 8) | lsb
                
                # Handle 2's complement for current readings
                if is_twos_complement:
                    # Convert to signed 16-bit integer
                    if raw > 0x7FFF:
                        raw = raw - 0x10000
                    value = raw * factor
                else:
                    value = raw * factor
                
                adc_values[f'{name}_MSB'] = msb
                adc_values[f'{name}_LSB'] = lsb
                adc_values[f'{name}_RAW'] = raw
                adc_values[f'{name}_VALUE'] = value
                adc_values[f'{name}_UNIT'] = 'mV' if name.startswith('V') else 'mA' if name in ['IAC', 'IBAT'] else '%' if name == 'TS' else 'mV'
                
                # Validate ranges
                min_v, max_v = valid_range
                if value < min_v or value > max_v:
                    warnings.append(f"Warning: {name} value {value}{adc_values[f'{name}_UNIT']} outside expected range {min_v}-{max_v}{adc_values[f'{name}_UNIT']}")
                
            except Exception as e:
                warnings.append(f"Error reading {name}: {str(e)}")
                adc_values[f'{name}_MSB'] = 0
                adc_values[f'{name}_LSB'] = 0
                adc_values[f'{name}_RAW'] = 0
                adc_values[f'{name}_VALUE'] = 0
                adc_values[f'{name}_UNIT'] = 'mV' if name.startswith('V') else 'mA' if name in ['IAC', 'IBAT'] else '%' if name == 'TS' else 'mV'
        
        adc_values['ERROR'] = None if not warnings else '; '.join(warnings)
        return adc_values
        
    except Exception as e:
        return {
            'ERROR': str(e),
            'VAC_MSB': 0, 'VAC_LSB': 0, 'VAC_RAW': 0, 'VAC_VALUE': 0, 'VAC_UNIT': 'mV',
            'VBAT_MSB': 0, 'VBAT_LSB': 0, 'VBAT_RAW': 0, 'VBAT_VALUE': 0, 'VBAT_UNIT': 'mV',
            'IAC_MSB': 0, 'IAC_LSB': 0, 'IAC_RAW': 0, 'IAC_VALUE': 0, 'IAC_UNIT': 'mA',
            'IBAT_MSB': 0, 'IBAT_LSB': 0, 'IBAT_RAW': 0, 'IBAT_VALUE': 0, 'IBAT_UNIT': 'mA',
            'TS_MSB': 0, 'TS_LSB': 0, 'TS_RAW': 0, 'TS_VALUE': 0, 'TS_UNIT': '%',
            'VFB_MSB': 0, 'VFB_LSB': 0, 'VFB_RAW': 0, 'VFB_VALUE': 0, 'VFB_UNIT': 'mV'
        }

def enable_adc(bus):
    """Enable ADC and configure channels"""
    console.print("\n[bold]Configuring ADC...[/bold]")
    
    # Read current ADC control with retry
    adc_ctrl = read_with_retry(bus, BQ25756_ADDR, REG_ADC_CTRL)
    adc_channel_ctrl = read_with_retry(bus, BQ25756_ADDR, REG_ADC_CHANNEL_CTRL)
    
    console.print(f"Current ADC Control (0x2B): 0x{adc_ctrl:02X}")
    console.print(f"Current ADC Channel Control (0x2C): 0x{adc_channel_ctrl:02X}")
    
    # Configure ADC Control register according to datasheet:
    # Bit 7: ADC_EN = 1 (Enable ADC)
    # Bit 6: ADC_RATE = 0 (Continuous conversion)
    # Bits 5:4: ADC_SAMPLE = 0x3 (16-bit resolution)
    # Bit 3: ADC_AVG = 0 (Single value)
    # Bit 2: ADC_AVG_INIT = 0 (Use existing value)
    # Bits 1:0: Reserved = 0
    new_adc_ctrl = 0x83  # 0b1000 0011
    
    # Configure ADC Channel Control register
    # Bits 7:0 are DISABLE controls (0=Enable, 1=Disable)
    # We want to enable VAC, VBAT, IAC, IBAT, and TS
    # VFB is disabled by default (bit 1 = 1)
    new_channel_ctrl = 0x02  # 0b0000 0010 (only VFB disabled)
    
    # Write new control values with retry
    console.print(f"Writing ADC Control: 0x{new_adc_ctrl:02X}")
    if not write_with_retry(bus, BQ25756_ADDR, REG_ADC_CTRL, new_adc_ctrl):
        console.print("[yellow]Warning: Failed to write ADC Control[/yellow]")
    
    console.print(f"Writing ADC Channel Control: 0x{new_channel_ctrl:02X}")
    if not write_with_retry(bus, BQ25756_ADDR, REG_ADC_CHANNEL_CTRL, new_channel_ctrl):
        console.print("[yellow]Warning: Failed to write ADC Channel Control[/yellow]")
    
    # Read back for information
    verify_adc = read_with_retry(bus, BQ25756_ADDR, REG_ADC_CTRL)
    verify_channel = read_with_retry(bus, BQ25756_ADDR, REG_ADC_CHANNEL_CTRL)
    
    console.print(f"ADC Control after write: 0x{verify_adc:02X}")
    console.print(f"ADC Channel Control after write: 0x{verify_channel:02X}")
    
    console.print("\nADC Configuration:")
    console.print("  - ADC_EN = 1 (Enabled)")
    console.print("  - ADC_RATE = 0 (Continuous conversion)")
    console.print("  - ADC_SAMPLE = 0x3 (16-bit resolution)")
    console.print("  - ADC_AVG = 0 (Single value)")
    console.print("  - ADC_AVG_INIT = 0 (Use existing value)")
    console.print("\nADC Channel Configuration:")
    console.print("  - VAC: Enabled")
    console.print("  - VBAT: Enabled")
    console.print("  - IAC: Enabled")
    console.print("  - IBAT: Enabled")
    console.print("  - TS: Enabled")
    console.print("  - VFB: Disabled (default)")
    
    # Give ADC time to start
    time.sleep(0.1)
    return True  # Continue regardless of verification

def monitor_status(bus, duration=10, sample_rate=0.1):
    """Monitor status registers at specified sample rate for duration seconds"""
    console.print(f"\n[bold]Monitoring status for {duration} seconds at {1/sample_rate}Hz...[/bold]")
    console.print("Press Ctrl+C to stop early")
    
    # Create table
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Time", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("VAC", justify="right")
    table.add_column("VBAT", justify="right")
    table.add_column("IAC", justify="right")
    table.add_column("IBAT", justify="right")
    table.add_column("TS", justify="right")
    
    start_time = time.time()
    last_status_0 = None
    last_status_1 = None
    
    try:
        with Live(table, refresh_per_second=1/sample_rate) as live:
            while time.time() - start_time < duration:
                try:
                    # Read status registers
                    status_0 = bus.read_byte_data(BQ25756_ADDR, REG_CHARGER_STATUS_0)
                    status_1 = bus.read_byte_data(BQ25756_ADDR, REG_CHARGER_STATUS_1)
                    fault = bus.read_byte_data(BQ25756_ADDR, REG_FAULT_STATUS)
                    
                    # Read ADC values
                    adc_values = read_adc_values(bus)
                    
                    # Only update if status changed
                    if status_0 != last_status_0 or status_1 != last_status_1:
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        
                        # Decode status for concise display
                        status_0_bits = decode_status_0(status_0)
                        status_1_bits = decode_status_1(status_1)
                        
                        # Create concise status string
                        status_str = f"{status_0_bits['CHRG_STAT_DESC']}/{status_1_bits['AC_STAT_DESC']}/{status_1_bits['BAT_STAT_DESC']}"
                        
                        # Format values with units
                        vac_str = f"{adc_values['VAC_VALUE']}{adc_values['VAC_UNIT']}"
                        vbat_str = f"{adc_values['VBAT_VALUE']}{adc_values['VBAT_UNIT']}"
                        iac_str = f"{adc_values['IAC_VALUE']}{adc_values['IAC_UNIT']}"
                        ibat_str = f"{adc_values['IBAT_VALUE']}{adc_values['IBAT_UNIT']}"
                        ts_str = f"{adc_values['TS_VALUE']}{adc_values['TS_UNIT']}"
                        
                        # Add row to table
                        table.add_row(
                            timestamp,
                            status_str,
                            vac_str,
                            vbat_str,
                            iac_str,
                            ibat_str,
                            ts_str
                        )
                        
                        # Only show faults if they exist
                        fault_bits = decode_fault_status(fault)
                        if fault_bits['ACTIVE_FAULTS']:
                            console.print(Panel(f"[red]Faults: {', '.join(fault_bits['ACTIVE_FAULTS'])}[/red]"))
                        
                        last_status_0 = status_0
                        last_status_1 = status_1
                    
                    time.sleep(sample_rate)
                    
                except Exception as e:
                    console.print(f"\n[red]Error during monitoring: {e}[/red]")
                    time.sleep(sample_rate)
            
    except KeyboardInterrupt:
        console.print("\n[bold]Monitoring stopped by user[/bold]")
    except Exception as e:
        console.print(f"\n[red]Error during monitoring: {e}[/red]")

def set_battery_only_mode(bus):
    """Set the device to battery-only mode"""
    console.print("\n[bold]Setting device to battery-only mode...[/bold]")
    
    # Read current control registers
    charger_ctrl = bus.read_byte_data(BQ25756_ADDR, REG_CHARGER_CTRL)
    pin_ctrl = bus.read_byte_data(BQ25756_ADDR, REG_PIN_CTRL)
    power_path_ctrl = bus.read_byte_data(BQ25756_ADDR, REG_POWER_PATH_CTRL)
    
    # Create table for control registers
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Register", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Charger Control (0x17)", f"0x{charger_ctrl:02X}")
    table.add_row("Pin Control (0x18)", f"0x{pin_ctrl:02X}")
    table.add_row("Power Path Control (0x19)", f"0x{power_path_ctrl:02X}")
    
    console.print(table)
    
    # Set up battery-only mode:
    # 1. Disable charging (EN_CHG = 0 in Charger Control)
    new_charger_ctrl = charger_ctrl & ~0x01  # Clear bit 0 (EN_CHG)
    
    # 2. Disable input source control (bits 7:6 in Power Path Control)
    new_power_path = power_path_ctrl & ~0xC0  # Clear bits 7:6
    
    # 3. Disable reverse mode (EN_REV = 0 in Power Path Control)
    new_power_path &= ~0x01  # Clear bit 0 (EN_REV)
    
    # Write the new control values
    console.print(f"\n[bold]Writing new control values:[/bold]")
    write_table = Table(show_header=True, header_style="bold magenta")
    write_table.add_column("Register", style="cyan")
    write_table.add_column("New Value", style="green")
    
    write_table.add_row("Charger Control", f"0x{new_charger_ctrl:02X}")
    write_table.add_row("Power Path Control", f"0x{new_power_path:02X}")
    
    console.print(write_table)
    
    bus.write_byte_data(BQ25756_ADDR, REG_CHARGER_CTRL, new_charger_ctrl)
    bus.write_byte_data(BQ25756_ADDR, REG_POWER_PATH_CTRL, new_power_path)
    
    # Verify the writes
    verify_charger = bus.read_byte_data(BQ25756_ADDR, REG_CHARGER_CTRL)
    verify_power = bus.read_byte_data(BQ25756_ADDR, REG_POWER_PATH_CTRL)
    
    if verify_charger == new_charger_ctrl and verify_power == new_power_path:
        console.print("[green]Successfully set battery-only mode[/green]")
    else:
        console.print("[red]Warning: Mode verification failed[/red]")
        verify_table = Table(show_header=True, header_style="bold magenta")
        verify_table.add_column("Register", style="cyan")
        verify_table.add_column("Expected", style="green")
        verify_table.add_column("Got", style="red")
        
        verify_table.add_row("Charger Control", f"0x{new_charger_ctrl:02X}", f"0x{verify_charger:02X}")
        verify_table.add_row("Power Path Control", f"0x{new_power_path:02X}", f"0x{verify_power:02X}")
        
        console.print(verify_table)
    
    # Monitor status for a few seconds to verify mode change
    console.print("\n[bold]Monitoring status after mode change...[/bold]")
    monitor_status(bus, duration=5, sample_rate=0.1)

def set_input_voltage(bus, target_voltage_mv):
    """Set the input voltage target in mV"""
    console.print(f"\n[bold]Setting input voltage target to {target_voltage_mv}mV...[/bold]")
    
    # Input voltage target register (0x0C)
    # Resolution is 100mV per LSB
    target_value = target_voltage_mv // 100
    
    # Read current value
    current = read_with_retry(bus, BQ25756_ADDR, 0x0C)
    console.print(f"Current input voltage target: {current * 100}mV")
    
    # Write new value
    if not write_with_retry(bus, BQ25756_ADDR, 0x0C, target_value):
        console.print("[yellow]Warning: Failed to write input voltage target[/yellow]")
        return True  # Continue anyway
    
    # Read back for information
    verify = read_with_retry(bus, BQ25756_ADDR, 0x0C)
    console.print(f"New input voltage target: {verify * 100}mV")
    return True  # Continue regardless of verification

def scan_i2c_bus(bus):
    """Scan I2C bus for devices"""
    console.print("\n[bold]Scanning I2C bus for devices...[/bold]")
    devices = []
    for addr in range(0x03, 0x78):
        try:
            bus.read_byte(addr)
            devices.append(addr)
            console.print(f"Found device at address: 0x{addr:02X}")
        except:
            pass
    return devices

# Initialize SMBus
bus = smbus2.SMBus(I2C_BUS_NO)

console.print(f"[bold]Attempting to communicate on I2C bus {I2C_BUS_NO}[/bold]")

try:
    # Enable ADC first
    enable_adc(bus)
    
    # Set input voltage target to 30V
    set_input_voltage(bus, 30000)
    
    # First set battery-only mode
    set_battery_only_mode(bus)
    
    # Monitor status registers for a longer period
    console.print("\n[bold]Monitoring status in battery-only mode...[/bold]")
    monitor_status(bus, duration=30, sample_rate=1)

except Exception as e:
    console.print(f"\n[yellow]Warning during I2C communication: {e}[/yellow]")
    console.print("[yellow]Continuing with monitoring...[/yellow]")

finally:
    # Close the bus connection
    if 'bus' in locals() and bus is not None:
        bus.close()
        console.print("\n[bold]I2C bus closed.[/bold]") 