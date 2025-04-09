import smbus2
import time
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
import sys

# Initialize rich console
console = Console()

# --- Configuration ---
I2C_BUS_NO = 1      # !!! UPDATE THIS for your hardware !!!
BQ25756_ADDR = 0x6b # Default BQ25756 address, verify on schematic

# --- BQ25756 Register Addresses (Based on SLUSEN5 Datasheet) ---
# Configuration Registers (Many are 16-bit: LSB Address listed)
REG_CHARGE_VOLTAGE_LIMIT         = 0x00 # R/W, 16-bit
REG_CHARGE_CURRENT_LIMIT         = 0x02 # R/W, 16-bit
REG_INPUT_CURRENT_DPM_LIMIT      = 0x06 # R/W, 16-bit
REG_INPUT_VOLTAGE_DPM_LIMIT      = 0x08 # R/W, 16-bit
REG_REVERSE_MODE_INPUT_CURRENT_LIMIT = 0x0A # R/W, 16-bit
REG_REVERSE_MODE_INPUT_VOLTAGE_LIMIT = 0x0C # R/W, 16-bit
REG_PRECHARGE_CURRENT_LIMIT      = 0x10 # R/W, 16-bit
REG_TERMINATION_CURRENT_LIMIT    = 0x12 # R/W, 16-bit
REG_PRECHARGE_TERM_CTRL          = 0x14 # R/W, 8-bit
REG_TIMER_CTRL                   = 0x15 # R/W, 8-bit
REG_THREE_STAGE_CHARGE_CTRL      = 0x16 # R/W, 8-bit
REG_CHARGER_CTRL                 = 0x17 # R/W, 8-bit
REG_PIN_CTRL                     = 0x18 # R/W, 8-bit
REG_POWER_PATH_REVERSE_MODE_CTRL = 0x19 # R/W, 8-bit
REG_MPPT_CTRL                    = 0x1A # R/W, 8-bit
REG_TS_CHARGE_THRESH_CTRL        = 0x1B # R/W, 8-bit
REG_TS_CHARGE_REGION_BEHAV_CTRL  = 0x1C # R/W, 8-bit
REG_TS_REVERSE_MODE_THRESH_CTRL  = 0x1D # R/W, 8-bit
REG_REVERSE_UNDERVOLTAGE_CTRL    = 0x1E # R/W, 8-bit
REG_ADC_CTRL                     = 0x2B # R/W, 8-bit
REG_ADC_CHANNEL_CTRL             = 0x2C # R/W, 8-bit
REG_GATE_DRIVER_STRENGTH_CTRL    = 0x3B # R/W, 8-bit
REG_GATE_DRIVER_DEAD_TIME_CTRL   = 0x3C # R/W, 8-bit
REG_REVERSE_MODE_BATT_DISCH_CURR = 0x62 # R/W, 8-bit

# Status & Flag Registers (Read Only, mostly 8-bit)
REG_VAC_MAX_POWER_POINT_DETECTED = 0x1F # R, 16-bit
REG_CHARGER_STATUS_1             = 0x21 # R, 8-bit
REG_CHARGER_STATUS_2             = 0x22 # R, 8-bit
REG_CHARGER_STATUS_3             = 0x23 # R, 8-bit
REG_FAULT_STATUS                 = 0x24 # R, 8-bit
REG_CHARGER_FLAG_1               = 0x25 # R/ClearOnRead, 8-bit
REG_CHARGER_FLAG_2               = 0x26 # R/ClearOnRead, 8-bit
REG_FAULT_FLAG                   = 0x27 # R/ClearOnRead, 8-bit

# Mask Registers (R/W, 8-bit)
REG_CHARGER_MASK_1               = 0x28 # R/W, 8-bit
REG_CHARGER_MASK_2               = 0x29 # R/W, 8-bit
REG_FAULT_MASK                   = 0x2A # R/W, 8-bit

# ADC Value Registers (Read Only, 16-bit: LSB Address listed)
REG_IAC_ADC                      = 0x2D # R, 16-bit
REG_IBAT_ADC                     = 0x2F # R, 16-bit
REG_VAC_ADC                      = 0x31 # R, 16-bit
REG_VBAT_ADC                     = 0x33 # R, 16-bit
REG_TS_ADC                       = 0x37 # R, 16-bit
REG_VFB_ADC                      = 0x39 # R, 16-bit

# Part Information Register
REG_PART_INFO                    = 0x3D # R, 8-bit

# --- Constants for ADC Configuration ---
# REG_ADC_CTRL (0x2B) Bits
ADC_CTRL_ADC_EN         = (1 << 7)
ADC_CTRL_ADC_RATE_CONT  = (0 << 6) # Continuous conversion
ADC_CTRL_ADC_RATE_ONESHOT=(1 << 6) # One-shot conversion
ADC_CTRL_ADC_SAMPLE_15BIT=(0 << 4) # 15 bit effective resolution
ADC_CTRL_ADC_SAMPLE_14BIT=(1 << 4) # 14 bit effective resolution
ADC_CTRL_ADC_SAMPLE_13BIT=(2 << 4) # 13 bit effective resolution
ADC_CTRL_ADC_AVG_SINGLE = (0 << 3) # Single value
ADC_CTRL_ADC_AVG_RUNNING= (1 << 3) # Running average
ADC_CTRL_ADC_AVG_INIT_EXIST = (0 << 2) # Start average using existing register value
ADC_CTRL_ADC_AVG_INIT_NEW  = (1 << 2) # Start average using new ADC conversion

# REG_ADC_CHANNEL_CTRL (0x2C) Bits (0=Enable, 1=Disable)
ADC_CHAN_IAC_ADC_DIS   = (1 << 7)
ADC_CHAN_IBAT_ADC_DIS  = (1 << 6)
ADC_CHAN_VAC_ADC_DIS   = (1 << 5)
ADC_CHAN_VBAT_ADC_DIS  = (1 << 4)
# Bit 3 Reserved
ADC_CHAN_TS_ADC_DIS    = (1 << 2)
ADC_CHAN_VFB_ADC_DIS   = (1 << 1) # Disabled by default/recommended when charging
# Bit 0 Reserved

# --- I2C Mux Configuration ---
DEFAULT_MUX_ADDRESS = 0x70
BUCK_BOOST_CHANNEL = 3

# --- I2C Helper Functions ---
def read_byte_with_retry(bus, addr, reg, max_retries=3, delay=0.01):
    """Read I2C byte register with retry logic"""
    last_exception = None
    for attempt in range(max_retries):
        try:
            return bus.read_byte_data(addr, reg)
        except Exception as e:
            last_exception = e
            time.sleep(delay)
    raise IOError(f"Failed to read byte from reg 0x{reg:02X} after {max_retries} attempts: {last_exception}")

def write_byte_with_retry(bus, addr, reg, value, max_retries=3, delay=0.01):
    """Write I2C byte register with retry logic"""
    last_exception = None
    for attempt in range(max_retries):
        try:
            bus.write_byte_data(addr, reg, value)
            # Optional: Verify write
            # read_val = bus.read_byte_data(addr, reg)
            # if read_val == value:
            #     return True
            # else:
            #     last_exception = IOError(f"Write verification failed for reg 0x{reg:02X} (Wrote 0x{value:02X}, Read 0x{read_val:02X})")
            return True # Assume success if no exception
        except Exception as e:
            last_exception = e
            time.sleep(delay)
    raise IOError(f"Failed to write byte 0x{value:02X} to reg 0x{reg:02X} after {max_retries} attempts: {last_exception}")

def read_word_with_retry(bus, addr, reg_lsb, max_retries=3, delay=0.01):
    """Read I2C word (16-bit LSB first) register with retry logic"""
    last_exception = None
    for attempt in range(max_retries):
        try:
            # smbus2 read_word_data reads LSB then MSB
            return bus.read_word_data(addr, reg_lsb)
        except Exception as e:
            last_exception = e
            time.sleep(delay)
    raise IOError(f"Failed to read word from LSB reg 0x{reg_lsb:02X} after {max_retries} attempts: {last_exception}")

def write_word_with_retry(bus, addr, reg_lsb, value, max_retries=3, delay=0.01):
    """Write I2C word (16-bit LSB first) register with retry logic"""
    last_exception = None
    for attempt in range(max_retries):
        try:
            # smbus2 write_word_data writes LSB then MSB
            bus.write_word_data(addr, reg_lsb, value)
            # Optional: Verify write
            # read_val = bus.read_word_data(addr, reg_lsb)
            # if read_val == value:
            #     return True
            # else:
            #     last_exception = IOError(f"Write verification failed for LSB reg 0x{reg_lsb:02X} (Wrote 0x{value:04X}, Read 0x{read_val:04X})")
            return True # Assume success if no exception
        except Exception as e:
            last_exception = e
            time.sleep(delay)
    raise IOError(f"Failed to write word 0x{value:04X} to LSB reg 0x{reg_lsb:02X} after {max_retries} attempts: {last_exception}")

# --- Status Decoding Functions (Based on BQ25756 SLUSEN5 Datasheet) ---

def decode_status_1(status):
    """Decode Charger Status Register 1 (0x21) bits"""
    bits = {
        'ADC_DONE_STAT': (status >> 7) & 0x01, # Bit 7
        'IAC_DPM_STAT':  (status >> 6) & 0x01, # Bit 6
        'VAC_DPM_STAT':  (status >> 5) & 0x01, # Bit 5
        # Bit 4 Reserved
        'WD_STAT':       (status >> 3) & 0x01, # Bit 3
        'CHARGE_STAT':   status & 0x07         # Bits 2:0
    }

    charge_stat_map = {
        0b000: "Not charging",
        0b001: "Trickle Charge (VBAT < VBAT_SHORT)",
        0b010: "Pre-Charge (VBAT < VBAT_LOWV)",
        0b011: "Fast Charge (CC mode)",
        0b100: "Taper Charge (CV mode)",
        0b101: "Reserved",
        0b110: "Top-off Timer Charge",
        0b111: "Charge Termination Done"
    }
    bits['CHARGE_STAT_DESC'] = charge_stat_map.get(bits['CHARGE_STAT'], "Unknown")
    bits['WD_STAT_DESC'] = "Expired" if bits['WD_STAT'] else "Normal"
    bits['VAC_DPM_DESC'] = "In VAC DPM" if bits['VAC_DPM_STAT'] else "Normal"
    bits['IAC_DPM_DESC'] = "In IAC DPM" if bits['IAC_DPM_STAT'] else "Normal"
    bits['ADC_DONE_DESC'] = "Complete (OneShot)" if bits['ADC_DONE_STAT'] else "Not Complete/Continuous"

    return bits

def decode_status_2(status):
    """Decode Charger Status Register 2 (0x22) bits"""
    bits = {
        'PG_STAT':   (status >> 7) & 0x01, # Bit 7
        'TS_STAT':   (status >> 4) & 0x07, # Bits 6:4
        # Bits 3:2 Reserved
        'MPPT_STAT': status & 0x03         # Bits 1:0
    }

    ts_stat_map = {
        0b000: "Normal",
        0b001: "TS Warm",
        0b010: "TS Cool",
        0b011: "TS Cold",
        0b100: "TS Hot",
        # 101, 110, 111 Reserved/Undefined in map
    }
    mppt_stat_map = {
        0b00: "MPPT Disabled",
        0b01: "MPPT Enabled, Not Running",
        0b10: "Full Panel Sweep In Progress",
        0b11: "Max Power Voltage Detected"
    }
    bits['PG_STAT_DESC'] = "Power Good" if bits['PG_STAT'] else "Not Power Good"
    bits['TS_STAT_DESC'] = ts_stat_map.get(bits['TS_STAT'], "TS Reserved")
    bits['MPPT_STAT_DESC'] = mppt_stat_map.get(bits['MPPT_STAT'], "MPPT Reserved")

    return bits

def decode_status_3(status):
    """Decode Charger Status Register 3 (0x23) bits"""
    bits = {
        # Bits 7:6 Reserved
        'FSW_SYNC_STAT': (status >> 4) & 0x03, # Bits 5:4
        'CV_TMR_STAT':   (status >> 3) & 0x01, # Bit 3
        'REVERSE_STAT':  (status >> 2) & 0x01, # Bit 2
        # Bits 1:0 Reserved
    }

    fsw_sync_map = {
        0b00: "Normal, no external clock",
        0b01: "Valid ext. clock detected",
        0b10: "Pin fault (freq out-of-range)",
        # 11 Reserved
    }
    bits['FSW_SYNC_DESC'] = fsw_sync_map.get(bits['FSW_SYNC_STAT'], "FSW Reserved")
    bits['CV_TMR_DESC'] = "CV Timer Expired" if bits['CV_TMR_STAT'] else "Normal"
    bits['REVERSE_STAT_DESC'] = "Reverse Mode On" if bits['REVERSE_STAT'] else "Reverse Mode Off"

    return bits

def decode_fault_status(fault):
    """Decode Fault Status Register (0x24) bits"""
    bits = {
        'VAC_UV_STAT':   (fault >> 7) & 0x01, # Bit 7
        'VAC_OV_STAT':   (fault >> 6) & 0x01, # Bit 6
        'IBAT_OCP_STAT': (fault >> 5) & 0x01, # Bit 5
        'VBAT_OV_STAT':  (fault >> 4) & 0x01, # Bit 4
        'TSHUT_STAT':    (fault >> 3) & 0x01, # Bit 3
        'CHG_TMR_STAT':  (fault >> 2) & 0x01, # Bit 2
        'DRV_OKZ_STAT':  (fault >> 1) & 0x01, # Bit 1
        # Bit 0 Reserved
    }

    active_faults = []
    if bits['VAC_UV_STAT']:   active_faults.append("Input UVP")
    if bits['VAC_OV_STAT']:   active_faults.append("Input OVP")
    if bits['IBAT_OCP_STAT']: active_faults.append("Battery OCP")
    if bits['VBAT_OV_STAT']:  active_faults.append("Battery OVP")
    if bits['TSHUT_STAT']:    active_faults.append("Thermal Shutdown")
    if bits['CHG_TMR_STAT']:  active_faults.append("Charge Safety Timer Expired")
    if bits['DRV_OKZ_STAT']:  active_faults.append("DRV_SUP Fault")

    bits['ACTIVE_FAULTS_DESC'] = ", ".join(active_faults) if active_faults else "No Active Faults"
    return bits

# --- ADC Reading Function ---
def read_adc_values(bus):
    """Read and decode ADC values for all available channels"""
    adc_results = {}
    warnings = []

    # Define ADC channels and their conversion factors/details
    # Format: name: (lsb_reg, factor, valid_range_mV_mA_pct, is_twos_complement, unit)
    channels = {
        'VAC':  (REG_VAC_ADC,  2.0,          (0, 65534), False, 'mV'),
        'VBAT': (REG_VBAT_ADC, 2.0,          (0, 65534), False, 'mV'),
        'IAC':  (REG_IAC_ADC,  0.8,    (-20000, 20000),  True, 'mA'),
        'IBAT': (REG_IBAT_ADC, 2.0,    (-20000, 20000),  True, 'mA'),
        'TS':   (REG_TS_ADC,   0.09765625, (0, 99.9), False, '%'), # % of REGN
        'VFB':  (REG_VFB_ADC,  1.0,          (0, 2047), False, 'mV'),
    }

    for name, (lsb_reg, factor, valid_range, is_twos_complement, unit) in channels.items():
        try:
            raw = read_word_with_retry(bus, BQ25756_ADDR, lsb_reg)

            # Handle 2's complement for current readings
            signed_raw = raw
            if is_twos_complement:
                if raw > 0x7FFF: # Check if negative
                    signed_raw = raw - 0x10000 # Convert to signed

            value = signed_raw * factor

            adc_results[f'{name}_RAW'] = raw
            adc_results[f'{name}_VALUE'] = round(value, 2) # Round for display
            adc_results[f'{name}_UNIT'] = unit

            # Validate ranges
            min_v, max_v = valid_range
            if not (min_v <= value <= max_v):
                 warnings.append(f"Warning: {name} value {value:.2f}{unit} outside expected range {min_v}-{max_v}{unit}")

        except Exception as e:
            warnings.append(f"Error reading {name}: {str(e)}")
            adc_results[f'{name}_RAW'] = 0
            adc_results[f'{name}_VALUE'] = 0
            adc_results[f'{name}_UNIT'] = unit

    adc_results['WARNINGS'] = "; ".join(warnings) if warnings else None
    return adc_results

# --- Configuration Functions ---

def configure_adc(bus, continuous=True, resolution_bits=15, average=False):
    """Configure ADC settings (Enable, Rate, Sample, Average)"""
    console.print("\n[bold]Configuring ADC...[/bold]")

    # --- Configure ADC Control (0x2B) ---
    adc_ctrl_val = ADC_CTRL_ADC_EN # Always enable

    if continuous:
        adc_ctrl_val |= ADC_CTRL_ADC_RATE_CONT
        console.print(" - ADC Rate: Continuous")
    else:
        adc_ctrl_val |= ADC_CTRL_ADC_RATE_ONESHOT
        console.print(" - ADC Rate: One-Shot")

    if resolution_bits == 15:
        adc_ctrl_val |= ADC_CTRL_ADC_SAMPLE_15BIT
        console.print(" - ADC Resolution: 15-bit Effective")
    elif resolution_bits == 14:
        adc_ctrl_val |= ADC_CTRL_ADC_SAMPLE_14BIT
        console.print(" - ADC Resolution: 14-bit Effective")
    elif resolution_bits == 13:
         adc_ctrl_val |= ADC_CTRL_ADC_SAMPLE_13BIT
         console.print(" - ADC Resolution: 13-bit Effective")
    else:
        console.print(f"[yellow]Warning: Invalid resolution {resolution_bits} requested, using 15-bit.[/yellow]")
        adc_ctrl_val |= ADC_CTRL_ADC_SAMPLE_15BIT

    if average:
        adc_ctrl_val |= ADC_CTRL_ADC_AVG_RUNNING
        adc_ctrl_val |= ADC_CTRL_ADC_AVG_INIT_NEW # Start fresh average
        console.print(" - ADC Averaging: Enabled (Running Avg)")
    else:
        adc_ctrl_val |= ADC_CTRL_ADC_AVG_SINGLE
        console.print(" - ADC Averaging: Disabled (Single Value)")

    try:
        write_byte_with_retry(bus, BQ25756_ADDR, REG_ADC_CTRL, adc_ctrl_val)
        verify_ctrl = read_byte_with_retry(bus, BQ25756_ADDR, REG_ADC_CTRL)
        console.print(f" - ADC Control (0x2B) written: 0x{adc_ctrl_val:02X}, Read back: 0x{verify_ctrl:02X}")
        if verify_ctrl != adc_ctrl_val:
             console.print("[red] - ADC Control Write Verification FAILED![/red]")
    except Exception as e:
        console.print(f"[red]Error writing ADC Control (0x2B): {e}[/red]")
        return False

    # --- Configure ADC Channel Control (0x2C) ---
    # Default: Enable VAC, VBAT, IAC, IBAT, TS. Disable VFB.
    adc_channel_ctrl_val = 0x00 # Start with all enabled
    adc_channel_ctrl_val |= ADC_CHAN_VFB_ADC_DIS # Disable VFB``

    try:
        write_byte_with_retry(bus, BQ25756_ADDR, REG_ADC_CHANNEL_CTRL, adc_channel_ctrl_val)
        verify_channel = read_byte_with_retry(bus, BQ25756_ADDR, REG_ADC_CHANNEL_CTRL)
        console.print(f" - ADC Channel Control (0x2C) written: 0x{adc_channel_ctrl_val:02X}, Read back: 0x{verify_channel:02X}")
        if verify_channel != adc_channel_ctrl_val:
            console.print("[red] - ADC Channel Control Write Verification FAILED![/red]")
        console.print(" - ADC Channels Enabled: VAC, VBAT, IAC, IBAT, TS")
        console.print(" - ADC Channels Disabled: VFB")
    except Exception as e:
        console.print(f"[red]Error writing ADC Channel Control (0x2C): {e}[/red]")
        return False

    # Give ADC time to stabilize after configuration
    time.sleep(0.05)
    return True

def set_charge_voltage_limit(bus, voltage_mv):
    """Sets REG0x00/01 Charge Voltage Limit"""
    # VFB_REG (Bits 4:0 of REG0x00/01) - Datasheet Table 8-9
    # Range: 1504mV-1566mV, Step: 2mV, Offset: 1504mV
    min_v, max_v, step, offset = 1504, 1566, 2, 1504
    clamped_v = max(min_v, min(voltage_mv, max_v))
    if clamped_v != voltage_mv:
        console.print(f"[yellow]Charge Voltage Limit clamped from {voltage_mv}mV to {clamped_v}mV (Range: {min_v}-{max_v}mV)[/yellow]")

    vfb_reg_val = round((clamped_v - offset) / step) & 0x1F # Calculate value and mask to 5 bits

    reg_val_16bit = (vfb_reg_val) # Bits 4:0 are the LSB bits of the 16-bit word

    console.print(f"Setting Charge Voltage Limit to {clamped_v}mV (VFB_REG = 0x{vfb_reg_val:02X})")
    try:
        # This register seems odd, only 5 bits are defined. Assuming they are in the LSB byte.
        # Writing full word might affect reserved bits. Write only LSB byte for safety?
        # Datasheet says "I2C REG0x01=[15:8], I2C REG0x00=[7:0]" but defines bits 4:0.
        # Let's write the 16bit word assuming upper bits are 0, respecting the reset value structure [Reset=0x0010]
        # Reset value 0x0010 means VFB_REG=0x10 (16d). (16*2)+1504 = 1536mV.
        # We write only the calculated VFB_REG bits, preserving reserved bits (assuming 0).
        write_word_with_retry(bus, BQ25756_ADDR, REG_CHARGE_VOLTAGE_LIMIT, reg_val_16bit)
        # Readback needs care due to reserved bits, maybe only read LSB?
        read_lsb = read_byte_with_retry(bus, BQ25756_ADDR, REG_CHARGE_VOLTAGE_LIMIT)
        console.print(f" - Charge Voltage Reg (0x00) Read back LSB: 0x{read_lsb:02X}")
        if (read_lsb & 0x1F) != vfb_reg_val:
             console.print("[red] - Charge Voltage Write Verification FAILED![/red]")
    except Exception as e:
        console.print(f"[red]Error setting Charge Voltage Limit: {e}[/red]")

def set_charge_current_limit(bus, current_ma):
    """Sets REG0x02/03 Fast Charge Current Limit"""
    # ICHG_REG (Bits 10:2 of REG0x02/03) - Datasheet Table 8-10
    # Range: 400mA - 20000mA, Step: 50mA, (Assumed Offset=0 based on range/step)
    min_c, max_c, step = 400, 20000, 50
    clamped_c = max(min_c, min(current_ma, max_c))
    if clamped_c != current_ma:
        console.print(f"[yellow]Charge Current Limit clamped from {current_ma}mA to {clamped_c}mA (Range: {min_c}-{max_c}mA)[/yellow]")

    ichg_reg_val = round(clamped_c / step) & 0x1FF # Calculate value and mask to 9 bits (10:2 -> 9 bits)

    # Shift value into correct bit positions (10:2)
    reg_val_16bit = ichg_reg_val << 2

    console.print(f"Setting Charge Current Limit to {clamped_c}mA (ICHG_REG = 0x{ichg_reg_val:03X}) -> Writing 0x{reg_val_16bit:04X}")
    try:
        write_word_with_retry(bus, BQ25756_ADDR, REG_CHARGE_CURRENT_LIMIT, reg_val_16bit)
        read_val = read_word_with_retry(bus, BQ25756_ADDR, REG_CHARGE_CURRENT_LIMIT)
        console.print(f" - Charge Current Regs (0x02/03) Read back: 0x{read_val:04X}")
        if read_val != reg_val_16bit:
            console.print("[red] - Charge Current Write Verification FAILED![/red]")
    except Exception as e:
        console.print(f"[red]Error setting Charge Current Limit: {e}[/red]")

def set_input_current_dpm_limit(bus, current_ma):
    """Sets REG0x06/07 Input Current DPM Limit"""
    # IAC_DPM (Bits 10:2 of REG0x06/07) - Datasheet Table 8-11
    # Range: 400mA - 20000mA, Step: 50mA, (Assumed Offset=0)
    min_c, max_c, step = 400, 20000, 50
    clamped_c = max(min_c, min(current_ma, max_c))
    if clamped_c != current_ma:
         console.print(f"[yellow]Input Current Limit clamped from {current_ma}mA to {clamped_c}mA (Range: {min_c}-{max_c}mA)[/yellow]")

    iac_dpm_val = round(clamped_c / step) & 0x1FF # Calculate value and mask to 9 bits

    # Shift value into correct bit positions (10:2)
    reg_val_16bit = iac_dpm_val << 2

    console.print(f"Setting Input Current Limit to {clamped_c}mA (IAC_DPM = 0x{iac_dpm_val:03X}) -> Writing 0x{reg_val_16bit:04X}")
    try:
        write_word_with_retry(bus, BQ25756_ADDR, REG_INPUT_CURRENT_DPM_LIMIT, reg_val_16bit)
        read_val = read_word_with_retry(bus, BQ25756_ADDR, REG_INPUT_CURRENT_DPM_LIMIT)
        console.print(f" - Input Current Regs (0x06/07) Read back: 0x{read_val:04X}")
        if read_val != reg_val_16bit:
            console.print("[red] - Input Current Write Verification FAILED![/red]")
    except Exception as e:
        console.print(f"[red]Error setting Input Current Limit: {e}[/red]")

def set_input_voltage_dpm_limit(bus, voltage_mv):
    """Sets REG0x08/09 Forward Input Voltage DPM Limit"""
    # VAC_DPM (Bits 13:2 of REG0x08/09) - Datasheet Table 8-12
    # Range: 4200mV - 65000mV, Step: 20mV, (Assumed Offset=0 for calculation relative to 0mV)
    min_v, max_v, step = 4200, 65000, 20
    clamped_v = max(min_v, min(voltage_mv, max_v))
    if clamped_v != voltage_mv:
        console.print(f"[yellow]Input Voltage Limit clamped from {voltage_mv}mV to {clamped_v}mV (Range: {min_v}-{max_v}mV)[/yellow]")

    # Calculate the raw value based on 0mV origin
    vac_dpm_val = round(clamped_v / step) & 0xFFF # Calculate value and mask to 12 bits (13:2 -> 12 bits)

    # Shift value into correct bit positions (13:2)
    reg_val_16bit = vac_dpm_val << 2

    console.print(f"Setting Input Voltage DPM Limit to {clamped_v}mV (VAC_DPM = 0x{vac_dpm_val:03X}) -> Writing 0x{reg_val_16bit:04X}")
    try:
        write_word_with_retry(bus, BQ25756_ADDR, REG_INPUT_VOLTAGE_DPM_LIMIT, reg_val_16bit)
        read_val = read_word_with_retry(bus, BQ25756_ADDR, REG_INPUT_VOLTAGE_DPM_LIMIT)
        console.print(f" - Input Voltage Regs (0x08/09) Read back: 0x{read_val:04X}")
        if read_val != reg_val_16bit:
             console.print("[red] - Input Voltage Write Verification FAILED![/red]")
    except Exception as e:
        console.print(f"[red]Error setting Input Voltage Limit: {e}[/red]")

def enable_charging(bus, enable=True):
    """Sets EN_CHG bit in REG0x17_Charger_Control"""
    reg_addr = REG_CHARGER_CTRL
    bit_mask = (1 << 0) # EN_CHG is bit 0
    action = "Enabling" if enable else "Disabling"
    console.print(f"{action} charging...")
    try:
        current_val = read_byte_with_retry(bus, BQ25756_ADDR, reg_addr)
        if enable:
            new_val = current_val | bit_mask
        else:
            new_val = current_val & ~bit_mask

        if new_val == current_val:
             console.print(f" - Charging already {action.lower().replace('ing','ed')}. Value: 0x{current_val:02X}")
             return

        write_byte_with_retry(bus, BQ25756_ADDR, reg_addr, new_val)
        verify_val = read_byte_with_retry(bus, BQ25756_ADDR, reg_addr)
        console.print(f" - Charger Control (0x17) written: 0x{new_val:02X}, Read back: 0x{verify_val:02X}")
        if verify_val != new_val:
             console.print("[red] - Enable Charging Write Verification FAILED![/red]")

    except Exception as e:
        console.print(f"[red]Error {action.lower()} charging: {e}[/red]")

def set_battery_only_mode(bus):
    """Configures device for battery-only operation (disables charge/reverse)"""
    # This is a basic example, real implementation might need more config.
    console.print("\n[bold]Setting device to battery-only mode (disabling charge & reverse)...[/bold]")
    success = True

    # 1. Disable charging (EN_CHG = 0 in Charger Control 0x17)
    try:
        current_charger_ctrl = read_byte_with_retry(bus, BQ25756_ADDR, REG_CHARGER_CTRL)
        new_charger_ctrl = current_charger_ctrl & ~0x01 # Clear bit 0 (EN_CHG)
        if current_charger_ctrl != new_charger_ctrl:
            write_byte_with_retry(bus, BQ25756_ADDR, REG_CHARGER_CTRL, new_charger_ctrl)
            verify_charger = read_byte_with_retry(bus, BQ25756_ADDR, REG_CHARGER_CTRL)
            console.print(f" - Charger Control (0x17): Wrote 0x{new_charger_ctrl:02X}, Read 0x{verify_charger:02X}")
            if verify_charger != new_charger_ctrl: success = False; console.print("[red]   Verification Failed![/red]")
        else:
             console.print(f" - Charger Control (0x17): Already 0x{current_charger_ctrl:02X} (Charge Disabled)")
    except Exception as e:
        success = False
        console.print(f"[red]Error disabling charge: {e}[/red]")


    # 2. Disable reverse mode (EN_REV = 0 in Power Path Control 0x19)
    #    Also disable VAC Load (EN_IAC_LOAD = 0, bit 6) as good measure
    try:
        current_power_path_ctrl = read_byte_with_retry(bus, BQ25756_ADDR, REG_POWER_PATH_REVERSE_MODE_CTRL)
        new_power_path_ctrl = current_power_path_ctrl & ~((1 << 0) | (1 << 6)) # Clear EN_REV (bit 0), EN_IAC_LOAD (bit 6)
        if current_power_path_ctrl != new_power_path_ctrl:
            write_byte_with_retry(bus, BQ25756_ADDR, REG_POWER_PATH_REVERSE_MODE_CTRL, new_power_path_ctrl)
            verify_power = read_byte_with_retry(bus, BQ25756_ADDR, REG_POWER_PATH_REVERSE_MODE_CTRL)
            console.print(f" - Power Path Control (0x19): Wrote 0x{new_power_path_ctrl:02X}, Read 0x{verify_power:02X}")
            if verify_power != new_power_path_ctrl: success = False; console.print("[red]   Verification Failed![/red]")
        else:
            console.print(f" - Power Path Control (0x19): Already 0x{current_power_path_ctrl:02X} (Reverse/VACLoad Disabled)")
    except Exception as e:
        success = False
        console.print(f"[red]Error disabling reverse mode: {e}[/red]")

    if success:
        console.print("[green]Battery-only mode configuration applied.[/green]")
    else:
        console.print("[red]Failed to fully apply battery-only mode configuration.[/red]")

# --- Monitoring Function ---
def generate_status_table(bus):
    """Creates a Rich Table with current status and ADC readings"""
    table = Table(title="BQ25756 Status", show_header=True, header_style="bold magenta")
    table.add_column("Parameter", style="cyan", min_width=20)
    table.add_column("Value", style="green")
    table.add_column("Raw/Reg", style="dim")

    # --- Read Status Registers ---
    try:
        status1_raw = read_byte_with_retry(bus, BQ25756_ADDR, REG_CHARGER_STATUS_1)
        status1_decoded = decode_status_1(status1_raw)
        table.add_row("Charger Status 1", f"{status1_decoded['CHARGE_STAT_DESC']}", f"0x{status1_raw:02X} @ 0x21")
        if status1_decoded['VAC_DPM_STAT']: table.add_row("Input Voltage DPM", "[yellow]Active[/yellow]", "")
        if status1_decoded['IAC_DPM_STAT']: table.add_row("Input Current DPM", "[yellow]Active[/yellow]", "")
        if status1_decoded['WD_STAT']: table.add_row("Watchdog Status", "[red]Expired[/red]", "")
    except Exception as e:
        table.add_row("Charger Status 1", "[red]Read Error[/red]", f"0x21: {e}")

    try:
        status2_raw = read_byte_with_retry(bus, BQ25756_ADDR, REG_CHARGER_STATUS_2)
        status2_decoded = decode_status_2(status2_raw)
        pg_style = "green" if status2_decoded['PG_STAT'] else "yellow"
        table.add_row("Power Good (PG)", f"[{pg_style}]{status2_decoded['PG_STAT_DESC']}[/]", f"0x{status2_raw:02X} @ 0x22")
        table.add_row("TS Status", f"{status2_decoded['TS_STAT_DESC']}", "")
        table.add_row("MPPT Status", f"{status2_decoded['MPPT_STAT_DESC']}", "")
    except Exception as e:
        table.add_row("Charger Status 2", "[red]Read Error[/red]", f"0x22: {e}")

    try:
        status3_raw = read_byte_with_retry(bus, BQ25756_ADDR, REG_CHARGER_STATUS_3)
        status3_decoded = decode_status_3(status3_raw)
        table.add_row("Reverse Mode", f"{status3_decoded['REVERSE_STAT_DESC']}", f"0x{status3_raw:02X} @ 0x23")
        if status3_decoded['CV_TMR_STAT']: table.add_row("CV Timer", "[yellow]Expired[/yellow]", "")
        table.add_row("FSW Sync", f"{status3_decoded['FSW_SYNC_DESC']}", "")
    except Exception as e:
        table.add_row("Charger Status 3", "[red]Read Error[/red]", f"0x23: {e}")

    try:
        fault_raw = read_byte_with_retry(bus, BQ25756_ADDR, REG_FAULT_STATUS)
        fault_decoded = decode_fault_status(fault_raw)
        fault_style = "red" if fault_decoded['ACTIVE_FAULTS_DESC'] != "No Active Faults" else "green"
        table.add_row("Fault Status", f"[{fault_style}]{fault_decoded['ACTIVE_FAULTS_DESC']}[/]", f"0x{fault_raw:02X} @ 0x24")
    except Exception as e:
        table.add_row("Fault Status", "[red]Read Error[/red]", f"0x24: {e}")

    # --- Read ADC Values ---
    adc = read_adc_values(bus)
    if adc.get('WARNINGS'):
        table.add_row("[yellow]ADC Warnings[/yellow]", adc['WARNINGS'], "")

    table.add_section()
    for name in ['VAC', 'VBAT', 'IAC', 'IBAT', 'TS', 'VFB']:
        val = adc.get(f'{name}_VALUE', 'N/A')
        unit = adc.get(f'{name}_UNIT', '')
        raw = adc.get(f'{name}_RAW', 0)
        lsb_reg = globals().get(f'REG_{name}_ADC') # Get register addr from globals
        reg_str = f"0x{raw:04X} @ 0x{lsb_reg:02X}" if lsb_reg else f"0x{raw:04X}"
        table.add_row(f"ADC {name}", f"{val} {unit}", reg_str)

    return Panel(table, title=f"Status @ {datetime.now().strftime('%H:%M:%S.%f')[:-3]}", border_style="blue")


def monitor_status_live(bus, duration_sec=30, refresh_rate_hz=1):
    """Monitor status registers live using Rich"""
    console.print(f"\n[bold blue]Monitoring BQ25756 Status for {duration_sec} seconds... Press Ctrl+C to stop.[/bold blue]")
    sleep_interval = 1.0 / refresh_rate_hz
    start_time = time.time()

    try:
        with Live(generate_status_table(bus), refresh_per_second=refresh_rate_hz, screen=False) as live:
            while time.time() - start_time < duration_sec:
                live.update(generate_status_table(bus))
                time.sleep(sleep_interval)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Monitoring stopped by user.[/bold yellow]")
    except Exception as e:
        console.print(f"\n[bold red]Error during monitoring: {e}[/bold red]")
        import traceback
        traceback.print_exc()
    finally:
         console.print("[bold blue]Monitoring finished.[/bold blue]")

# Add these functions to your existing script (make sure REG addresses are defined)

def set_reverse_mode_voltage_limit(bus, voltage_mv):
    """Sets REG0x0C/0D Reverse Mode Voltage Limit (Output Voltage Target)"""
    # VAC_REV (Bits 13:2 of REG0x0C/0D) - Datasheet Table 8-14
    # Range: 3300mV - 65000mV, Step: 20mV
    min_v, max_v, step = 3300, 65000, 20
    clamped_v = max(min_v, min(voltage_mv, max_v))
    if clamped_v != voltage_mv:
        console.print(f"[yellow]Reverse Mode Voltage Limit clamped from {voltage_mv}mV to {clamped_v}mV (Range: {min_v}-{max_v}mV)[/yellow]")

    # Calculate the raw value based on 0mV origin
    vac_rev_val = round(clamped_v / step) & 0xFFF # Calculate value and mask to 12 bits

    # Shift value into correct bit positions (13:2)
    reg_val_16bit = vac_rev_val << 2

    console.print(f"Setting Reverse Mode Voltage Limit to {clamped_v}mV (VAC_REV = 0x{vac_rev_val:03X}) -> Writing 0x{reg_val_16bit:04X}")
    try:
        write_word_with_retry(bus, BQ25756_ADDR, REG_REVERSE_MODE_INPUT_VOLTAGE_LIMIT, reg_val_16bit)
        read_val = read_word_with_retry(bus, BQ25756_ADDR, REG_REVERSE_MODE_INPUT_VOLTAGE_LIMIT)
        console.print(f" - Reverse Mode Voltage Regs (0x0C/0D) Read back: 0x{read_val:04X}")
        if read_val != reg_val_16bit:
             console.print("[red] - Reverse Mode Voltage Write Verification FAILED![/red]")
             return False
        return True
    except Exception as e:
        console.print(f"[red]Error setting Reverse Mode Voltage Limit: {e}[/red]")
        return False

def set_reverse_mode_current_limit(bus, current_ma):
    """Sets REG0x0A/0B Reverse Mode Input Current Limit (Output Current Limit)"""
    # IAC_REV (Bits 10:2 of REG0x0A/0B) - Datasheet Table 8-13
    # Range: 400mA - 20000mA, Step: 50mA
    min_c, max_c, step = 400, 20000, 50
    clamped_c = max(min_c, min(current_ma, max_c))
    if clamped_c != current_ma:
         console.print(f"[yellow]Reverse Mode Current Limit clamped from {current_ma}mA to {clamped_c}mA (Range: {min_c}-{max_c}mA)[/yellow]")

    iac_rev_val = round(clamped_c / step) & 0x1FF # Calculate value and mask to 9 bits

    # Shift value into correct bit positions (10:2)
    reg_val_16bit = iac_rev_val << 2

    console.print(f"Setting Reverse Mode Current Limit to {clamped_c}mA (IAC_REV = 0x{iac_rev_val:03X}) -> Writing 0x{reg_val_16bit:04X}")
    try:
        write_word_with_retry(bus, BQ25756_ADDR, REG_REVERSE_MODE_INPUT_CURRENT_LIMIT, reg_val_16bit)
        read_val = read_word_with_retry(bus, BQ25756_ADDR, REG_REVERSE_MODE_INPUT_CURRENT_LIMIT)
        console.print(f" - Reverse Mode Current Regs (0x0A/0B) Read back: 0x{read_val:04X}")
        if read_val != reg_val_16bit:
            console.print("[red] - Reverse Mode Current Write Verification FAILED![/red]")
            return False
        return True
    except Exception as e:
        console.print(f"[red]Error setting Reverse Mode Current Limit: {e}[/red]")
        return False

# --- New function to enable/disable Reverse Mode ---
def set_reverse_mode(bus, enable, target_voltage_mv=5000, target_current_ma=1000):
    """
    Enables or disables Reverse Mode.

    Args:
        bus: The smbus2 object.
        enable (bool): True to enable Reverse Mode, False to disable.
        target_voltage_mv (int): The desired output voltage (on VAC) when enabling.
        target_current_ma (int): The desired output current limit (from VAC) when enabling.
    """
    reg_addr = REG_POWER_PATH_REVERSE_MODE_CTRL # 0x19
    en_rev_bit_mask = (1 << 0) # Bit 0 for EN_REV
    action = "Enabling" if enable else "Disabling"

    console.print(f"\n[bold]{action} Reverse Mode...[/bold]")

    if enable:
        # --- Configure Limits BEFORE Enabling ---
        console.print("Setting Reverse Mode limits...")
        v_ok = set_reverse_mode_voltage_limit(bus, target_voltage_mv)
        c_ok = set_reverse_mode_current_limit(bus, target_current_ma)
        # Add setting for REG0x62 if needed

        if not (v_ok and c_ok):
            console.print("[red]Failed to set Reverse Mode limits. Aborting enable.[/red]")
            return False

        # --- Now Enable the Mode ---
        try:
            current_val = read_byte_with_retry(bus, BQ25756_ADDR, reg_addr)
            new_val = current_val | en_rev_bit_mask # Set EN_REV bit

            if new_val == current_val:
                console.print(" - Reverse Mode already enabled.")
            else:
                write_byte_with_retry(bus, BQ25756_ADDR, reg_addr, new_val)
                verify_val = read_byte_with_retry(bus, BQ25756_ADDR, reg_addr)
                console.print(f" - Power Path Control (0x19) written: 0x{new_val:02X}, Read back: 0x{verify_val:02X}")
                if verify_val != new_val:
                    console.print("[red] - Enable Reverse Mode Write Verification FAILED![/red]")
                    return False
        except Exception as e:
            console.print(f"[red]Error enabling Reverse Mode bit: {e}[/red]")
            return False

    else: # Disable Reverse Mode
        try:
            current_val = read_byte_with_retry(bus, BQ25756_ADDR, reg_addr)
            new_val = current_val & ~en_rev_bit_mask # Clear EN_REV bit

            if new_val == current_val:
                console.print(" - Reverse Mode already disabled.")
            else:
                write_byte_with_retry(bus, BQ25756_ADDR, reg_addr, new_val)
                verify_val = read_byte_with_retry(bus, BQ25756_ADDR, reg_addr)
                console.print(f" - Power Path Control (0x19) written: 0x{new_val:02X}, Read back: 0x{verify_val:02X}")
                if verify_val != new_val:
                    console.print("[red] - Disable Reverse Mode Write Verification FAILED![/red]")
                    return False
        except Exception as e:
            console.print(f"[red]Error disabling Reverse Mode bit: {e}[/red]")
            return False

    # --- Verify Status ---
    time.sleep(0.05) # Allow time for status to update
    try:
        status3_val = read_byte_with_retry(bus, BQ25756_ADDR, REG_CHARGER_STATUS_3)
        reverse_stat = (status3_val >> 2) & 0x01
        expected_stat = 1 if enable else 0
        if reverse_stat == expected_stat:
             console.print(f"[green]Reverse Mode {action} successful. REVERSE_STAT (Reg 0x23, Bit 2) is now {reverse_stat}.[/green]")
             return True
        else:
             console.print(f"[red]Reverse Mode {action} verification failed! REVERSE_STAT (Reg 0x23, Bit 2) is {reverse_stat} (expected {expected_stat}).[/red]")
             return False
    except Exception as e:
        console.print(f"[red]Error verifying Reverse Mode status: {e}[/red]")
        return False

def configure_i2c_mux(bus, mux_address=DEFAULT_MUX_ADDRESS, channel=None):
    """
    Configures an I2C Multiplexer (Example for TCA9548A).

    Args:
        bus: The smbus2 object.
        mux_address (int): The I2C address of the multiplexer chip.
        channel (int or None): The downstream channel number (0-7 for TCA9548A)
                               to enable. If None, disables all channels.

    Returns:
        bool: True if configuration was apparently successful, False otherwise.
    """
    if channel is None:
        control_byte = 0x00
        action_desc = "Disabling all channels on"
    elif 0 <= channel <= 7: # TCA9548A has channels 0-7
        control_byte = 1 << channel # Set the specific bit for the channel
        action_desc = f"Enabling channel {channel} on"
    else:
        console.print(f"[red]Invalid channel {channel} requested for TCA9548A (must be 0-7 or None).[/red]")
        return False

    console.print(f"[bold cyan]{action_desc} I2C Mux @ 0x{mux_address:02X} (Control Byte: 0x{control_byte:02X})...[/bold cyan]")

    try:
        # For TCA9548A, simply write the control byte to the mux address
        bus.write_byte(mux_address, control_byte)

        # Optional: Verify by reading back.
        time.sleep(0.01) # Short delay
        read_back = bus.read_byte(mux_address)
        # For TCA9548A, readback reflects the written value
        if read_back == control_byte:
            console.print(f"[green] - Mux configuration successful (Read back: 0x{read_back:02X}).[/green]")
            return True
        else:
            console.print(f"[red] - Mux config write sent (0x{control_byte:02X}), but read back failed (0x{read_back:02X}). Check mux address and connections.[/red]")
            return False # Treat mismatch as failure for TCA9548A

    except Exception as e:
        console.print(f"[red]Error configuring I2C Mux @ 0x{mux_address:02X}: {e}[/red]")
        return False

# --- Main Execution ---
if __name__ == "__main__":
    console.print(f"[bold]BQ25756 Bring-up Script (Datasheet: SLUSEN5)[/bold]")
    console.print(f"Attempting to use I2C bus {I2C_BUS_NO}, Address 0x{BQ25756_ADDR:02X}")
    console.print(f"Current time: {datetime.now()}")

    bus = None # Initialize bus variable
    try:
        bus = smbus2.SMBus(I2C_BUS_NO)
        console.print(f"[green]Opened I2C bus {I2C_BUS_NO} successfully.[/green]")

        # --- Configure I2C Mux ---
        configure_i2c_mux(bus, mux_address=DEFAULT_MUX_ADDRESS, channel=BUCK_BOOST_CHANNEL)

        # --- Initial Check: Read Part Info ---
        try:
            part_info = read_byte_with_retry(bus, BQ25756_ADDR, REG_PART_INFO)
            part_num = (part_info >> 3) & 0x0F
            dev_rev = part_info & 0x07
            console.print(f"Read Part Info (0x3D): 0x{part_info:02X} -> Part#: {part_num}, Rev: {dev_rev}")
            # According to Table 8-49, Part# 010 (decimal 2) is BQ25756
            if part_num != 0b010:
                 console.print(f"[bold red]WARNING: Detected Part Number ({part_num}) does not match BQ25756 (expected 2)! Check I2C Address and Device.[/bold red]")
                 # sys.exit(1) # Optional: Exit if wrong device detected
        except Exception as e:
            console.print(f"[bold red]FATAL: Failed to read Part Info from 0x{BQ25756_ADDR:02X}. Check I2C bus, address, and device power.[/bold red]")
            console.print(f"Error details: {e}")
            sys.exit(1)

        # --- Configuration Steps ---
        # 1. Configure ADC
        if not configure_adc(bus, continuous=True, resolution_bits=15):
            console.print("[red]ADC Configuration failed. Exiting.[/red]")
            sys.exit(1)

        # 2. Set Operating Limits (Example Values - ADJUST FOR YOUR SYSTEM!)
        console.print("\n[bold]Setting Operating Limits (Examples - Adjust for your system!)...[/bold]")
        set_charge_voltage_limit(bus, 1536)   # Example: Set to reset default 1536mV (VFB) -> Corresponds to actual Batt voltage via divider
        set_charge_current_limit(bus, 2000)   # Example: 2000mA fast charge
        set_input_current_dpm_limit(bus, 3000)# Example: 3000mA input limit
        set_input_voltage_dpm_limit(bus, 4200)# Example: 4200mV input voltage DPM (VINDPM threshold)

        # 3. Enable Charging (if desired for initial test)
        console.print("\n[bold]Enabling Charging...[/bold]")
        enable_charging(bus, enable=True)

        # Optional: Disable watchdog timer if needed during debugging (Reg 0x15, bits 5:4 = 00b)
        try:
           wd_val = read_byte_with_retry(bus, BQ25756_ADDR, REG_TIMER_CTRL)
           new_wd_val = wd_val & ~(0b11 << 4) # Clear bits 5:4
           if wd_val != new_wd_val:
              write_byte_with_retry(bus, BQ25756_ADDR, REG_TIMER_CTRL, new_wd_val)
              console.print(f"Watchdog Disabled (Wrote 0x{new_wd_val:02X} to 0x15)")
        except Exception as e:
           console.print(f"[yellow]Could not disable watchdog: {e}[/yellow]")

        try:
            status2_val = read_byte_with_retry(bus, BQ25756_ADDR, REG_CHARGER_STATUS_2)
            pg_stat = (status2_val >> 7) & 0x01
            if pg_stat == 1:
                console.print("[bold yellow]Warning: Adapter detected (PG_STAT = 1). Chip may prevent entering Reverse Mode.[/bold yellow]")
            else:
                console.print("[bold green]Adapter not detected (PG_STAT = 0). OK to attempt Reverse Mode.[/bold green]")
        except Exception as e:
            console.print(f"[red]Could not read PG_STAT: {e}[/red]")

        # --- Enable Reverse Mode ---
        # --- Example: Enable Reverse Mode with 5V, 1.5A output ---
        TARGET_REV_V = 10000  # mV
        TARGET_REV_I = 1500  # mA
        if set_reverse_mode(bus, enable=True, target_voltage_mv=TARGET_REV_V, target_current_ma=TARGET_REV_I):
            print("Reverse mode enabled, monitoring status...")
            monitor_status_live(bus, duration_sec=30)
        else:
            print("Failed to enable reverse mode.")

        # Example: Disable Reverse Mode
        set_reverse_mode(bus, enable=False)

        # --- Monitoring ---
        monitor_status_live(bus, duration_sec=60, refresh_rate_hz=1) # Monitor for 60 seconds


    except IOError as e:
        console.print(f"\n[bold red]I/O Error: {e}[/bold red]")
        console.print("Please check:")
        console.print(f" - If I2C bus number '{I2C_BUS_NO}' is correct for your system.")
        console.print(f" - If the BQ25756 device is connected and powered at address 0x{BQ25756_ADDR:02X}.")
        console.print(" - If the user running this script has I2C permissions (e.g., part of 'i2c' group).")
    except Exception as e:
        console.print(f"\n[bold red]An unexpected error occurred: {e}[/bold red]")
        import traceback
        traceback.print_exc()

    finally:
        # Close the bus connection if it was opened
        if bus is not None:
            try:
                bus.close()
                console.print("\n[bold]I2C bus closed.[/bold]")
            except Exception as e:
                 console.print(f"[red]Error closing I2C bus: {e}[/red]")