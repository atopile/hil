# This file is part of the faebryk project
# SPDX-License-Identifier: MIT
import logging

import faebryk.library._F as F
from faebryk.core.moduleinterface import ModuleInterface
from faebryk.libs.library import L

logger = logging.getLogger(__name__)


class TIAddressor(ModuleInterface):
    address = L.p_field(domain=L.Domains.Numbers.NATURAL())
    offset = L.p_field(domain=L.Domains.Numbers.NATURAL())
    base = L.p_field(domain=L.Domains.Numbers.NATURAL())
    num_addresses = L.p_field(domain=L.Domains.Numbers.NATURAL())
    address_line: F.ElectricLogic
    i2c: F.I2C

    @L.rt_field
    def single_electric_reference(self):
        return F.has_single_electric_reference_defined(
            F.ElectricLogic.connect_all_module_references(self)
        )

    def __preinit__(self) -> None:
        for x in (self.address, self.offset, self.base):
            x.constrain_ge(0)

        self.address.alias_is(self.base + self.offset)

        for i, dest in enumerate(
            [
                self.address_line.reference.gnd,
                self.address_line.reference.vcc,
                self.i2c.sda.line,
                self.i2c.scl.line,
            ]
        ):
            (self.offset.operation_is_subset(i)).if_then_else(
                lambda dest=dest: self.address_line.line.connect(dest)
            )
