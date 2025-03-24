# This file is part of the faebryk project
# SPDX-License-Identifier: MIT

import logging

import faebryk.library._F as F  # noqa: F401
from faebryk.core.module import Module
from faebryk.libs.library import L  # noqa: F401
from faebryk.libs.units import P  # noqa: F401
from faebryk.libs.picker.picker import DescriptiveProperties
# from components.texas_instruments_pc_f8575d_br import Texas_Instruments_PCF8575DBR

logger = logging.getLogger(__name__)


class Texas_Instruments_PCF8575DBR(Module):
    """
    TODO: Docstring describing your module

    SSOP-24-208mil
    I/O Expanders ROHS
    """

    # ----------------------------------------
    #              interfaces
    # ----------------------------------------
    power: F.ElectricPower
    i2c: F.I2C
    address = L.list_field(3, F.ElectricLogic)
    gpio = L.list_field(16, F.ElectricLogic)
    interrupt: F.ElectricLogic

    # ----------------------------------------
    #                traits
    # ----------------------------------------
    designator_prefix = L.f_field(F.has_designator_prefix)(
        F.has_designator_prefix.Prefix.U
    )
    lcsc_id = L.f_field(F.has_descriptive_properties_defined)({"LCSC": "C2863388"})
    descriptive_properties = L.f_field(F.has_descriptive_properties_defined)(
        {
            DescriptiveProperties.manufacturer: "Texas Instruments",
            DescriptiveProperties.partno: "PCF8575DBR",
        }
    )
    datasheet = L.f_field(F.has_datasheet_defined)(
        "https://wmsc.lcsc.com/wmsc/upload/file/pdf/v2/lcsc/2303010800_Texas-Instruments-PCF8575DBR_C2863388.pdf"
    )

    @L.rt_field
    def attach_via_pinmap(self):
        return F.can_attach_to_footprint_via_pinmap(
            {
                "1": self.interrupt.line,
                "2": self.address[1].line,
                "3": self.address[2].line,
                "4": self.gpio[0].line,
                "5": self.gpio[1].line,
                "6": self.gpio[2].line,
                "7": self.gpio[3].line,
                "8": self.gpio[4].line,
                "9": self.gpio[5].line,
                "10": self.gpio[6].line,
                "11": self.gpio[7].line,
                "12": self.power.gnd,
                "13": self.gpio[8].line,
                "14": self.gpio[9].line,
                "15": self.gpio[10].line,
                "16": self.gpio[11].line,
                "17": self.gpio[12].line,
                "18": self.gpio[13].line,
                "19": self.gpio[14].line,
                "20": self.gpio[15].line,
                "21": self.address[0].line,
                "22": self.i2c.scl.line,
                "23": self.i2c.sda.line,
                "24": self.power.vcc,
            }
        )

    def __preinit__(self):
        # ------------------------------------
        #           connections
        # ------------------------------------
        self.power.connect(
            F.ElectricLogic.connect_all_node_references(
                nodes=self.gpio
                + self.address
                + [
                    self.i2c,
                    self.interrupt,
                ]
            )
        )

        # ------------------------------------
        #          parametrization
        # ------------------------------------


class HardwareID(Module):
    """
    Hardware ID block
    Takes in a 16-bit ID and sets the corresponding GPIOs on an I/O expander
    """

    power: F.ElectricPower
    i2c: F.I2C
    gpio_expander: Texas_Instruments_PCF8575DBR
    id = L.p_field(units=P.dimensionless)  # Use direct parameter field

    def _validate_id(self, value):
        """Helper method to validate the ID."""
        if not 0 <= value <= 0xFFFF:
            raise ValueError(f"ID must be a 16-bit number (0-65535), got {value}")
        return value

    def __preinit__(self):
        # Connections
        self.gpio_expander.power.connect(self.power)
        self.gpio_expander.i2c.connect(self.i2c)

        # Default ID address
        self.power.gnd.connect(self.gpio_expander.address[0].line)
        self.power.gnd.connect(self.gpio_expander.address[1].line)
        self.power.gnd.connect(self.gpio_expander.address[2].line)

        # Validate ID value
        id_value = int(self.id)  # Convert from parameter to int
        self._validate_id(id_value)

        # Set ID
        # Connect each GPIO pin to VCC or GND based on the ID bits
        for i in range(16):
            # Use the integer value for bitwise operations
            bit = (id_value >> i) & 1
            if bit:
                self.power.vcc.connect(self.gpio_expander.gpio[i].line)
            else:
                self.power.gnd.connect(self.gpio_expander.gpio[i].line)
