import sys
import struct
from mapper import Mapper0, Mapper1, Mapper2, Mapper3, Mapper4, Mapper7, Mapper66

MAPPER_CLASSES = {
    0: Mapper0,
    1: Mapper1,
    2: Mapper2,
    3: Mapper3,
    4: Mapper4,
    7: Mapper7,
    66: Mapper66,
}

class Cartridge:
    def __init__(self, file_path):
        with open(file_path, "rb") as f:
            file_data = f.read()

        if file_data[:4] != b"NES\x1a":
            raise ValueError("Invalid NES header")

        self.prg_banks = file_data[4]
        self.chr_banks = file_data[5]

        self.mirroring = 0 if (file_data[6] & 0x01) == 0 else 1

        offset = 16
        if file_data[6] & 0x04:
            offset += 512

        prg_size = self.prg_banks * 16384
        self.prg_rom = bytearray(file_data[offset : offset + prg_size])
        offset += prg_size

        chr_size = self.chr_banks * 8192
        if self.chr_banks > 0:
            self.chr_rom = bytearray(file_data[offset : offset + chr_size])
        else:
            self.chr_rom = bytearray(8192)

        self.mapper_id = (file_data[7] & 0xF0) | (file_data[6] >> 4)

        if self.mapper_id in MAPPER_CLASSES:
            self.mapper = MAPPER_CLASSES[self.mapper_id](self.prg_banks, self.chr_banks)
            self.mapper.mirroring = self.mirroring
        else:
            raise NotImplementedError(f"Mapper {self.mapper_id} is not supported yet!")

        # Cache mapper methods for massive CPython speedup
        self.cpu_map_read = self.mapper.cpu_map_read
        self.cpu_map_write = self.mapper.cpu_map_write
        self.ppu_map_read = self.mapper.ppu_map_read
        self.ppu_map_write = self.mapper.ppu_map_write
        
        self.prg_rom_len = len(self.prg_rom)
        self.chr_rom_len = len(self.chr_rom)
        self.has_prg_ram = hasattr(self.mapper, 'prg_ram')

    def cpu_read(self, addr: int) -> int:
        handled, mapped_addr = self.cpu_map_read(addr)
        if handled:
            if mapped_addr == -1 and self.has_prg_ram:
                return self.mapper.prg_ram[addr - 0x6000]
            if mapped_addr < self.prg_rom_len:
                return self.prg_rom[mapped_addr]
        return 0x00

    def cpu_write(self, addr: int, val: int):
        if self.has_prg_ram and 0x6000 <= addr <= 0x7FFF:
            if not getattr(self.mapper, 'prg_ram_protect', False):
                self.mapper.prg_ram[addr - 0x6000] = val
            return
            
        if self.mapper_id == 2 and 0x8000 <= addr <= 0xFFFF:
            handled, mapped_addr = self.cpu_map_read(addr)
            if handled and mapped_addr < self.prg_rom_len:
                val &= self.prg_rom[mapped_addr]

        self.cpu_map_write(addr, val)

    def ppu_read(self, addr: int) -> int:
        handled, mapped_addr = self.ppu_map_read(addr)
        if handled and mapped_addr < self.chr_rom_len:
            return self.chr_rom[mapped_addr]
        return 0x00

    def ppu_write(self, addr: int, val: int):
        handled, mapped_addr = self.ppu_map_write(addr, val)
        if handled and mapped_addr < self.chr_rom_len:
            self.chr_rom[mapped_addr] = val