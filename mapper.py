class Mapper:
    """Base class for all NES mappers."""
    def __init__(self, prg_banks: int, chr_banks: int):
        self.prg_banks = prg_banks
        self.chr_banks = chr_banks
        self.irq_state = False
        self.mirroring = 0
        self.chr_dirty = True

    def cpu_map_read(self, addr: int) -> tuple[bool, int]: return False, 0
    def cpu_map_write(self, addr: int, data: int) -> bool: return False
    def ppu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x0000 <= addr <= 0x1FFF: return True, addr
        return False, 0
    def ppu_map_write(self, addr: int, data: int) -> tuple[bool, int]:
        if 0x0000 <= addr <= 0x1FFF and self.chr_banks == 0: return True, addr
        return False, 0
    def scanline(self): pass

class Mapper0(Mapper):
    def cpu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x8000 <= addr <= 0xFFFF:
            mask = 0x3FFF if self.prg_banks == 1 else 0x7FFF
            return True, addr & mask
        return False, 0

class Mapper1(Mapper):
    def __init__(self, prg_banks: int, chr_banks: int):
        super().__init__(prg_banks, chr_banks)
        self.shift_reg = 0x10
        self.control = 0x1C
        self.chr_bank_0 = 0
        self.chr_bank_1 = 0
        self.prg_bank = 0
        self.prg_ram = bytearray(8192)
        self.prg_ram_protect = False
        self.prg_ram_enabled = True

    def cpu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x6000 <= addr <= 0x7FFF:
            if self.prg_ram_enabled:
                return True, -1  
            return False, 0
        if 0x8000 <= addr <= 0xFFFF:
            mode = (self.control >> 2) & 0x03
            if mode in (0, 1):
                bank = ((self.prg_bank & 0x0E) >> 1) % (self.prg_banks // 2) if self.prg_banks >= 2 else 0
                return True, (bank * 0x8000) + (addr & 0x7FFF)
            elif mode == 2:
                if 0x8000 <= addr <= 0xBFFF: return True, addr & 0x3FFF
                else:
                    bank = self.prg_bank % self.prg_banks
                    return True, (bank * 0x4000) + (addr & 0x3FFF)
            elif mode == 3:
                if 0x8000 <= addr <= 0xBFFF:
                    bank = self.prg_bank % self.prg_banks
                    return True, (bank * 0x4000) + (addr & 0x3FFF)
                else:
                    last_bank = self.prg_banks - 1
                    return True, (last_bank * 0x4000) + (addr & 0x3FFF)
        return False, 0

    def cpu_map_write(self, addr: int, data: int) -> bool:
        if 0x6000 <= addr <= 0x7FFF:
            if self.prg_ram_enabled:
                self.prg_ram[addr - 0x6000] = data
            return True
        if 0x8000 <= addr <= 0xFFFF:
            if data & 0x80:
                self.shift_reg = 0x10
                self.control |= 0x0C
                self._update_mirroring()
            else:
                completed = bool(self.shift_reg & 0x01)
                self.shift_reg >>= 1
                self.shift_reg |= (data & 0x01) << 4
                if completed:
                    reg = (addr >> 13) & 0x03
                    val = self.shift_reg & 0x1F
                    if reg == 0:
                        self.control = val
                        self._update_mirroring()
                        self.chr_dirty = True
                    elif reg == 1:
                        self.chr_bank_0 = val
                        self.chr_dirty = True
                    elif reg == 2:
                        self.chr_bank_1 = val
                        self.chr_dirty = True
                    elif reg == 3:
                        self.prg_bank = val & 0x0F
                        self.prg_ram_enabled = not (val & 0x10)
                    self.shift_reg = 0x10
            return True
        return False

    def _update_mirroring(self):
        mirroring_mode = self.control & 0x03
        if mirroring_mode == 2: self.mirroring = 1
        elif mirroring_mode == 3: self.mirroring = 0
        elif mirroring_mode == 0: self.mirroring = 2
        elif mirroring_mode == 1: self.mirroring = 3

    def ppu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x0000 <= addr <= 0x1FFF:
            if self.chr_banks == 0: 
                if self.control & 0x10: 
                    bank_0 = self.chr_bank_0 & 0x01
                    bank_1 = self.chr_bank_1 & 0x01
                    if addr <= 0x0FFF: return True, (bank_0 * 0x1000) + (addr & 0x0FFF)
                    else: return True, (bank_1 * 0x1000) + (addr & 0x0FFF)
                else: return True, addr & 0x1FFF
            else: 
                chr_mask = (self.chr_banks * 2) - 1
                if self.control & 0x10: 
                    if addr <= 0x0FFF: return True, ((self.chr_bank_0 & chr_mask) * 0x1000) + (addr & 0x0FFF)
                    else: return True, ((self.chr_bank_1 & chr_mask) * 0x1000) + (addr & 0x0FFF)
                else: 
                    bank = self.chr_bank_0 & chr_mask
                    return True, (bank * 0x2000) + (addr & 0x1FFF)
        return False, 0

    def ppu_map_write(self, addr: int, data: int) -> tuple[bool, int]:
        if 0x0000 <= addr <= 0x1FFF and self.chr_banks == 0:
            if self.control & 0x10:
                bank_0 = self.chr_bank_0 & 0x01
                bank_1 = self.chr_bank_1 & 0x01
                if addr <= 0x0FFF: return True, (bank_0 * 0x1000) + (addr & 0x0FFF)
                else: return True, (bank_1 * 0x1000) + (addr & 0x0FFF)
            else: return True, addr & 0x1FFF
        return False, 0

class Mapper2(Mapper):
    def __init__(self, prg_banks: int, chr_banks: int):
        super().__init__(prg_banks, chr_banks)
        self.selected_prg = 0
    def cpu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x8000 <= addr <= 0xBFFF: return True, (self.selected_prg * 0x4000) + (addr & 0x3FFF)
        elif 0xC000 <= addr <= 0xFFFF:
            last_bank = self.prg_banks - 1
            return True, (last_bank * 0x4000) + (addr & 0x3FFF)
        return False, 0
    def cpu_map_write(self, addr: int, data: int) -> bool:
        if 0x8000 <= addr <= 0xFFFF:
            self.selected_prg = data & (self.prg_banks - 1)
            return True
        return False

class Mapper3(Mapper):
    def __init__(self, prg_banks: int, chr_banks: int):
        super().__init__(prg_banks, chr_banks)
        self.selected_chr = 0
    def cpu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x8000 <= addr <= 0xFFFF:
            mask = 0x3FFF if self.prg_banks == 1 else 0x7FFF
            return True, addr & mask
        return False, 0
    def cpu_map_write(self, addr: int, data: int) -> bool:
        if 0x8000 <= addr <= 0xFFFF:
            self.selected_chr = data & 0x03
            self.chr_dirty = True
            return True
        return False
    def ppu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x0000 <= addr <= 0x1FFF: return True, (self.selected_chr * 0x2000) + (addr & 0x1FFF)
        return False, 0

class Mapper4(Mapper):
    def __init__(self, prg_banks: int, chr_banks: int):
        super().__init__(prg_banks, chr_banks)
        self.target_reg = 0
        self.prg_mode = 0
        self.chr_mode = 0
        self.registers = [0] * 8
        self.prg_banks_map = [0] * 4
        self.chr_banks_map = [0] * 8
        self.prg_ram = bytearray(8192)
        self.prg_ram_protect = False
        self.prg_ram_enabled = True
        self.irq_enabled = False
        self.irq_counter = 0
        self.irq_reload = 0
        self.irq_update = False
        self.update_banks()

    def update_banks(self):
        num_prg_8k = self.prg_banks * 2
        num_chr_1k = self.chr_banks * 8
        chr_mask = num_chr_1k - 1 if num_chr_1k > 0 else 7

        if self.chr_mode == 0:
            self.chr_banks_map[0] = (self.registers[0] & 0xFE) & chr_mask
            self.chr_banks_map[1] = (self.registers[0] | 0x01) & chr_mask
            self.chr_banks_map[2] = (self.registers[1] & 0xFE) & chr_mask
            self.chr_banks_map[3] = (self.registers[1] | 0x01) & chr_mask
            self.chr_banks_map[4] = self.registers[2] & chr_mask
            self.chr_banks_map[5] = self.registers[3] & chr_mask
            self.chr_banks_map[6] = self.registers[4] & chr_mask
            self.chr_banks_map[7] = self.registers[5] & chr_mask
        else:
            self.chr_banks_map[0] = self.registers[2] & chr_mask
            self.chr_banks_map[1] = self.registers[3] & chr_mask
            self.chr_banks_map[2] = self.registers[4] & chr_mask
            self.chr_banks_map[3] = self.registers[5] & chr_mask
            self.chr_banks_map[4] = (self.registers[0] & 0xFE) & chr_mask
            self.chr_banks_map[5] = (self.registers[0] | 0x01) & chr_mask
            self.chr_banks_map[6] = (self.registers[1] & 0xFE) & chr_mask
            self.chr_banks_map[7] = (self.registers[1] | 0x01) & chr_mask

        if self.prg_mode == 0:
            self.prg_banks_map[0] = self.registers[6] % num_prg_8k if num_prg_8k > 0 else 0
            self.prg_banks_map[1] = self.registers[7] % num_prg_8k if num_prg_8k > 0 else 0
            self.prg_banks_map[2] = num_prg_8k - 2 if num_prg_8k > 0 else 0
            self.prg_banks_map[3] = num_prg_8k - 1 if num_prg_8k > 0 else 0
        else:
            self.prg_banks_map[0] = num_prg_8k - 2 if num_prg_8k > 0 else 0
            self.prg_banks_map[1] = self.registers[7] % num_prg_8k if num_prg_8k > 0 else 0
            self.prg_banks_map[2] = self.registers[6] % num_prg_8k if num_prg_8k > 0 else 0
            self.prg_banks_map[3] = num_prg_8k - 1 if num_prg_8k > 0 else 0
            
        self.chr_dirty = True

    def cpu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x6000 <= addr <= 0x7FFF:
            if self.prg_ram_enabled:
                return True, -1  
            return False, 0
        if 0x8000 <= addr <= 0xFFFF:
            bank_idx = (addr - 0x8000) // 0x2000
            return True, (self.prg_banks_map[bank_idx] * 0x2000) + (addr & 0x1FFF)
        return False, 0

    def cpu_map_write(self, addr: int, data: int) -> bool:
        if 0x6000 <= addr <= 0x7FFF:
            if self.prg_ram_enabled and not self.prg_ram_protect: 
                self.prg_ram[addr - 0x6000] = data
            return True
        if 0x8000 <= addr <= 0x9FFF:
            if not (addr & 0x0001):
                self.target_reg = data & 0x07
                self.prg_mode = (data >> 6) & 0x01
                self.chr_mode = (data >> 7) & 0x01
                self.chr_dirty = True
            else:
                self.registers[self.target_reg] = data
                self.chr_dirty = True
            self.update_banks()
            return True
        elif 0xA000 <= addr <= 0xBFFF:
            if not (addr & 0x0001): self.mirroring = 1 - (data & 0x01)
            else:
                self.prg_ram_enabled = bool(data & 0x80)
                self.prg_ram_protect = not bool(data & 0x40)
            return True
        elif 0xC000 <= addr <= 0xDFFF:
            if not (addr & 0x0001): self.irq_reload = data
            else:
                self.irq_update = True
                self.irq_counter = 0
            return True
        elif 0xE000 <= addr <= 0xFFFF:
            if not (addr & 0x0001):
                self.irq_enabled = False
                self.irq_state = False
            else: self.irq_enabled = True
            return True
        return False

    def scanline(self):
        if self.irq_update:
            self.irq_counter = self.irq_reload
            self.irq_update = False
        elif self.irq_counter == 0:
            self.irq_counter = self.irq_reload
        else:
            self.irq_counter -= 1

        if self.irq_counter == 0 and self.irq_enabled:
            self.irq_state = True

    def ppu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x0000 <= addr <= 0x1FFF:
            bank_idx = addr // 0x0400
            return True, (self.chr_banks_map[bank_idx] * 0x0400) + (addr & 0x03FF)
        return False, 0
    def ppu_map_write(self, addr: int, data: int) -> tuple[bool, int]:
        if 0x0000 <= addr <= 0x1FFF and self.chr_banks == 0:
            bank_idx = addr // 0x0400
            return True, (self.chr_banks_map[bank_idx] * 0x0400) + (addr & 0x03FF)
        return False, 0

class Mapper7(Mapper):
    def __init__(self, prg_banks: int, chr_banks: int):
        super().__init__(prg_banks, chr_banks)
        self.selected_prg = 0
    def cpu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x8000 <= addr <= 0xFFFF: return True, (self.selected_prg * 0x8000) + (addr & 0x7FFF)
        return False, 0
    def cpu_map_write(self, addr: int, data: int) -> bool:
        if 0x8000 <= addr <= 0xFFFF:
            self.selected_prg = data & 0x07
            return True
        return False

class Mapper66(Mapper):
    def __init__(self, prg_banks: int, chr_banks: int):
        super().__init__(prg_banks, chr_banks)
        self.selected_prg = 0
        self.selected_chr = 0
        self.prg_mask = (prg_banks // 2) - 1 if prg_banks >= 2 else 0
        self.chr_mask = chr_banks - 1 if chr_banks > 0 else 0
    def cpu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x8000 <= addr <= 0xFFFF:
            prg = self.selected_prg & self.prg_mask
            if self.prg_banks == 1: return True, (prg * 0x8000) + (addr & 0x3FFF)
            return True, (prg * 0x8000) + (addr & 0x7FFF)
        return False, 0
    def cpu_map_write(self, addr: int, data: int) -> bool:
        if 0x8000 <= addr <= 0xFFFF:
            self.selected_prg = (data >> 4) & 0x03
            self.selected_chr = data & 0x03
            self.chr_dirty = True
            return True
        return False
    def ppu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x0000 <= addr <= 0x1FFF:
            chr_bank = self.selected_chr & self.chr_mask
            return True, (chr_bank * 0x2000) + (addr & 0x1FFF)
        return False, 0