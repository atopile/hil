from smbus2 import SMBus
import time
import asyncio

MUX_ADDRESS = 0x70
GPIO_EXTENDER = { #GPIO extender register definitions
    "address": 0x20,
    "output_register": 0x01,
    "input_register": 0x02,
    "polarity_inversion": 0x03,
    "configuration": 0x04
}

class GPIO_extender:
    def __init__(self):
        address = 0x20
        output_register = 0x01
        input_register = 0x02
        
    def write_register(self, register, value):
        pass

    def read_register(self, register):
        pass
    def __str__(self):
        pass



i2c_bus = SMBus(1) # Unsure if this is the best spot/definition for the bus
class cell:
    def __init__(self, address, mux_channel=None):
        self.address = address
        self.mux_channel = mux_channel
        self.enabled = False
        _gpio_extender = GPIO_EXTENDER()


    def cell_set_mux(self, channel):
        if channel < 0 or channel > 7:
            raise ValueError("Channel must be between 0 and 7")

        control_byte = 1 << channel  # Enable the selected channel
        i2c_bus.write_byte(MUX_ADDRESS, control_byte)
        print(f"Enabled Channel {channel} (Control byte: {control_byte:#04x})")

    def cell_disable(self, ):
        pass

    def cell_enable(self, ):
        pass

    def cell_get_voltage(self, ):
        pass

    def cell_set_voltage(self, ):
        pass

    def cell_output_relay_on(self, ):
        pass

    def cell_output_relay_off(self, ):
        pass

    def cell_load_switch_on(self, ):
        pass

    def cell_load_switch_off(self, ):
        pass

    def cell_get_current(self, ):
        pass

    def cell_get_LDO_voltage(self, ):
        pass

    def cell_set_LDO_voltage(self, ):
        pass

    def cell_get_buck_voltage(self, ):
        pass

    def cell_set_buck_voltage(self, ):
        pass

    def cell_set_GPIO_state(self, ):
        pass

    def cell_get_GPIO_state(self, ):
        pass

    def cell_read_shunt_current(self, ):
        pass
    def __str__(self):
        return f"Cell @ {hex(self.address)} | Mux Channel: {self.mux_channel} | Enabled: {self.enabled}"
    

