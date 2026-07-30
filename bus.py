import sys
import struct
from apu import APU

class Bus:
    def __init__(self, cpu=None, ppu=None, ram=None, cartridge=None, controller=None, zapper=None):
        self.cpu = cpu
        self.ppu = ppu
        self.ram = ram if ram is not None else bytearray(0x0800)
        self.cartridge = cartridge
        self.controller = controller
        self.zapper = zapper
        self.apu = APU()

        self.ppu_read_reg = ppu.read_register if ppu else None
        self.ppu_write_reg = ppu.write_register if ppu else None
        self.cart_cpu_read = cartridge.cpu_read if cartridge else None
        self.cart_cpu_write = cartridge.cpu_write if cartridge else None
        self.ctrl_read = controller.read_state if controller else None
        self.ctrl_write = controller.write_strobe if controller else None
        self.zapper_read = zapper.read if zapper else None

    def read(self, addr: int) -> int:
        addr &= 0xFFFF
        if addr < 0x2000:
            return self.ram[addr & 0x07FF]
        elif addr < 0x4020:
            if addr < 0x4000:
                return self.ppu_read_reg(addr)
            elif addr == 0x4015:
                return self.apu.read_status(addr)
            elif addr == 0x4016:
                return self.ctrl_read()
            elif addr == 0x4017:
                if self.zapper_read:
                    return self.zapper_read()
                return 0x40
            return 0x40
        else:
            return self.cart_cpu_read(addr)

    def write(self, addr: int, val: int):
        addr &= 0xFFFF
        val &= 0xFF
        if addr < 0x2000:
            self.ram[addr & 0x07FF] = val
        elif addr < 0x4020:
            if addr < 0x4000:
                self.ppu_write_reg(addr, val)
            elif addr == 0x4014:
                self.dma_transfer(val)
            elif addr == 0x4016:
                self.ctrl_write(val)
            elif addr <= 0x4017:
                self.apu.write_register(addr, val)
        else:
            self.cart_cpu_write(addr, val)

    def dma_transfer(self, page: int):
        base_addr = (page & 0xFF) << 8
        ram = self.ram
        oam = self.ppu.oam
        oamaddr = self.ppu.oamaddr
        for i in range(256):
            oam[(oamaddr + i) & 0xFF] = ram[(base_addr + i) & 0x07FF]
        if self.cpu:
            self.cpu.cycles += 512