import sys
import struct

class CPU:
    def __init__(self, bus):
        self.bus = bus
        self.a = 0x00; self.x = 0x00; self.y = 0x00; self.st = 0xFD; self.pc = 0x0000
        self.p = 0x24
        self.C = 1 << 0; self.Z = 1 << 1; self.I = 1 << 2; self.D = 1 << 3
        self.B = 1 << 4; self.U = 1 << 5; self.V = 1 << 6; self.N = 1 << 7
        self.cycles = 0
        self.nmi_pending = False
        self.irq_pending = False
        self.read = bus.read
        self.write = bus.write

    def fetch(self):
        val = self.read(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        return val

    def push(self, value):
        self.write(0x0100 + self.st, value & 0xFF)
        self.st = (self.st - 1) & 0xFF

    def push16(self, value):
        self.push((value >> 8) & 0xFF)
        self.push(value & 0xFF)

    def pop(self):
        self.st = (self.st + 1) & 0xFF
        return self.read(0x0100 + self.st)

    def pop16(self):
        low = self.pop()
        high = self.pop()
        return (high << 8) | low

    def set_flag(self, flag, condition):
        if condition: self.p |= flag
        else: self.p &= ~flag

    def update_zn(self, val):
        if val == 0: self.p |= 0x02
        else: self.p &= ~0x02
        if val & 0x80: self.p |= 0x80
        else: self.p &= ~0x80

    def nmi(self):
        self.push16(self.pc)
        self.push((self.p & ~self.B) | self.U)
        self.p |= self.I
        self.pc = (self.read(0xFFFB) << 8) | self.read(0xFFFA)
        self.cycles += 7

    def trigger_irq(self):
        if not (self.p & self.I): self.irq_pending = True

    def irq(self):
        self.push16(self.pc)
        self.push((self.p & ~self.B) | self.U)
        self.p |= self.I
        self.pc = (self.read(0xFFFF) << 8) | self.read(0xFFFE)
        self.cycles += 7

    def branch(self, condition):
        offset = self.fetch()
        self.cycles += 2
        if offset & 0x80: offset -= 0x100
        if condition:
            self.cycles += 1
            new_pc = (self.pc + offset) & 0xFFFF
            if (self.pc & 0xFF00) != (new_pc & 0xFF00): self.cycles += 1
            self.pc = new_pc

    def step(self):
        start_cycles = self.cycles
        opcode = self.fetch()
        read = self.read
        write = self.write
        pc = self.pc

        # NOP & Illegals
        if opcode == 0xEA or opcode in (0x1A, 0x3A, 0x5A, 0x7A, 0xDA, 0xFA):
            self.cycles += 2
        elif opcode in (0x04, 0x14, 0x34, 0x44, 0x54, 0x64, 0x74, 0x80, 0x82, 0x89, 0xC2, 0xD4, 0xE2, 0xF4):
            self.pc = (self.pc + 1) & 0xFFFF
            if opcode in (0x80, 0x82, 0x89, 0xC2, 0xE2): self.cycles += 2
            elif opcode in (0x04, 0x44, 0x64): self.cycles += 3
            else: self.cycles += 4
        elif opcode in (0x0C, 0x1C, 0x3C, 0x5C, 0x7C, 0xDC, 0xFC):
            if opcode == 0x0C: self.pc = (self.pc + 2) & 0xFFFF; self.cycles += 4
            else:
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF
                addr = (((high << 8) | low) + self.x) & 0xFFFF
                self.cycles += 4
                if (addr & 0xFF00) != ((addr - self.x) & 0xFF00): self.cycles += 1

        # LDA (Inlined Addressing)
        elif opcode in (0xA9, 0xA5, 0xB5, 0xAD, 0xBD, 0xB9, 0xA1, 0xB1):
            if opcode == 0xA9: addr = pc; self.pc = (pc + 1) & 0xFFFF; self.cycles += 2
            elif opcode == 0xA5: addr = read(pc); self.pc = (pc + 1) & 0xFFFF; self.cycles += 3
            elif opcode == 0xB5: addr = (read(pc) + self.x) & 0xFF; self.pc = (pc + 1) & 0xFFFF; self.cycles += 4
            elif opcode == 0xAD: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (high << 8) | low; self.cycles += 4
            elif opcode == 0xBD: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (((high << 8) | low) + self.x) & 0xFFFF; self.cycles += 4
            elif opcode == 0xB9: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (((high << 8) | low) + self.y) & 0xFFFF; self.cycles += 4
            elif opcode == 0xA1: 
                base = (read(pc) + self.x) & 0xFF; self.pc = (pc + 1) & 0xFFFF; addr = (read((base + 1) & 0xFF) << 8) | read(base); self.cycles += 6
            elif opcode == 0xB1: 
                base = read(pc); self.pc = (pc + 1) & 0xFFFF; addr = (((read((base + 1) & 0xFF) << 8) | read(base)) + self.y) & 0xFFFF; self.cycles += 5
            if opcode in (0xBD, 0xB9, 0xB1):
                offset = self.x if opcode == 0xBD else self.y
                if (addr & 0xFF00) != ((addr - offset) & 0xFF00): self.cycles += 1
            self.a = read(addr); self.update_zn(self.a)

        # LDX
        elif opcode in (0xA2, 0xA6, 0xB6, 0xAE, 0xBE):
            if opcode == 0xA2: addr = pc; self.pc = (pc + 1) & 0xFFFF; self.cycles += 2
            elif opcode == 0xA6: addr = read(pc); self.pc = (pc + 1) & 0xFFFF; self.cycles += 3
            elif opcode == 0xB6: addr = (read(pc) + self.y) & 0xFF; self.pc = (pc + 1) & 0xFFFF; self.cycles += 4
            elif opcode == 0xAE: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (high << 8) | low; self.cycles += 4
            elif opcode == 0xBE: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (((high << 8) | low) + self.y) & 0xFFFF; self.cycles += 4
                if (addr & 0xFF00) != ((addr - self.y) & 0xFF00): self.cycles += 1
            self.x = read(addr); self.update_zn(self.x)

        # LDY
        elif opcode in (0xA0, 0xA4, 0xB4, 0xAC, 0xBC):
            if opcode == 0xA0: addr = pc; self.pc = (pc + 1) & 0xFFFF; self.cycles += 2
            elif opcode == 0xA4: addr = read(pc); self.pc = (pc + 1) & 0xFFFF; self.cycles += 3
            elif opcode == 0xB4: addr = (read(pc) + self.x) & 0xFF; self.pc = (pc + 1) & 0xFFFF; self.cycles += 4
            elif opcode == 0xAC: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (high << 8) | low; self.cycles += 4
            elif opcode == 0xBC: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (((high << 8) | low) + self.x) & 0xFFFF; self.cycles += 4
                if (addr & 0xFF00) != ((addr - self.x) & 0xFF00): self.cycles += 1
            self.y = read(addr); self.update_zn(self.y)

        # STA
        elif opcode in (0x85, 0x95, 0x8D, 0x9D, 0x99, 0x81, 0x91):
            if opcode == 0x85: addr = read(pc); self.pc = (pc + 1) & 0xFFFF; self.cycles += 3
            elif opcode == 0x95: addr = (read(pc) + self.x) & 0xFF; self.pc = (pc + 1) & 0xFFFF; self.cycles += 4
            elif opcode == 0x8D: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (high << 8) | low; self.cycles += 4
            elif opcode == 0x9D: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (((high << 8) | low) + self.x) & 0xFFFF; self.cycles += 5
            elif opcode == 0x99: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (((high << 8) | low) + self.y) & 0xFFFF; self.cycles += 5
            elif opcode == 0x81: 
                base = (read(pc) + self.x) & 0xFF; self.pc = (pc + 1) & 0xFFFF; addr = (read((base + 1) & 0xFF) << 8) | read(base); self.cycles += 6
            elif opcode == 0x91: 
                base = read(pc); self.pc = (pc + 1) & 0xFFFF; addr = (((read((base + 1) & 0xFF) << 8) | read(base)) + self.y) & 0xFFFF; self.cycles += 6
            write(addr, self.a)

        # STX
        elif opcode in (0x86, 0x96, 0x8E):
            if opcode == 0x86: addr = read(pc); self.pc = (pc + 1) & 0xFFFF; self.cycles += 3
            elif opcode == 0x96: addr = (read(pc) + self.y) & 0xFF; self.pc = (pc + 1) & 0xFFFF; self.cycles += 4
            elif opcode == 0x8E: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (high << 8) | low; self.cycles += 4
            write(addr, self.x)

        # STY
        elif opcode in (0x84, 0x94, 0x8C):
            if opcode == 0x84: addr = read(pc); self.pc = (pc + 1) & 0xFFFF; self.cycles += 3
            elif opcode == 0x94: addr = (read(pc) + self.x) & 0xFF; self.pc = (pc + 1) & 0xFFFF; self.cycles += 4
            elif opcode == 0x8C: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (high << 8) | low; self.cycles += 4
            write(addr, self.y)

        # Register Transfers
        elif opcode == 0xAA: self.x = self.a; self.update_zn(self.x); self.cycles += 2
        elif opcode == 0xA8: self.y = self.a; self.update_zn(self.y); self.cycles += 2
        elif opcode == 0xBA: self.x = self.st; self.update_zn(self.x); self.cycles += 2
        elif opcode == 0x8A: self.a = self.x; self.update_zn(self.a); self.cycles += 2
        elif opcode == 0x9A: self.st = self.x; self.cycles += 2
        elif opcode == 0x98: self.a = self.y; self.update_zn(self.a); self.cycles += 2

        # INX, INY, DEX, DEY
        elif opcode == 0xE8: self.x = (self.x + 1) & 0xFF; self.update_zn(self.x); self.cycles += 2
        elif opcode == 0xC8: self.y = (self.y + 1) & 0xFF; self.update_zn(self.y); self.cycles += 2
        elif opcode == 0xCA: self.x = (self.x - 1) & 0xFF; self.update_zn(self.x); self.cycles += 2
        elif opcode == 0x88: self.y = (self.y - 1) & 0xFF; self.update_zn(self.y); self.cycles += 2

        # ADC (Inlined Addressing)
        elif opcode in (0x69, 0x65, 0x75, 0x6D, 0x7D, 0x79, 0x61, 0x71):
            if opcode == 0x69: addr = pc; self.pc = (pc + 1) & 0xFFFF; self.cycles += 2
            elif opcode == 0x65: addr = read(pc); self.pc = (pc + 1) & 0xFFFF; self.cycles += 3
            elif opcode == 0x75: addr = (read(pc) + self.x) & 0xFF; self.pc = (pc + 1) & 0xFFFF; self.cycles += 4
            elif opcode == 0x6D: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (high << 8) | low; self.cycles += 4
            elif opcode == 0x7D: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (((high << 8) | low) + self.x) & 0xFFFF; self.cycles += 4
            elif opcode == 0x79: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (((high << 8) | low) + self.y) & 0xFFFF; self.cycles += 4
            elif opcode == 0x61: 
                base = (read(pc) + self.x) & 0xFF; self.pc = (pc + 1) & 0xFFFF; addr = (read((base + 1) & 0xFF) << 8) | read(base); self.cycles += 6
            elif opcode == 0x71: 
                base = read(pc); self.pc = (pc + 1) & 0xFFFF; addr = (((read((base + 1) & 0xFF) << 8) | read(base)) + self.y) & 0xFFFF; self.cycles += 5
            if opcode in (0x7D, 0x79, 0x71):
                offset = self.x if opcode == 0x7D else self.y
                if (addr & 0xFF00) != ((addr - offset) & 0xFF00): self.cycles += 1
            val = read(addr)
            carry = 1 if (self.p & self.C) else 0
            res = self.a + val + carry
            self.set_flag(self.C, res > 0xFF)
            self.set_flag(self.V, bool(~(self.a ^ val) & (self.a ^ res) & 0x80))
            self.a = res & 0xFF; self.update_zn(self.a)

        # SBC
        elif opcode in (0xE9, 0xEB, 0xE5, 0xF5, 0xED, 0xFD, 0xF9, 0xE1, 0xF1):
            if opcode in (0xE9, 0xEB): addr = pc; self.pc = (pc + 1) & 0xFFFF; self.cycles += 2
            elif opcode == 0xE5: addr = read(pc); self.pc = (pc + 1) & 0xFFFF; self.cycles += 3
            elif opcode == 0xF5: addr = (read(pc) + self.x) & 0xFF; self.pc = (pc + 1) & 0xFFFF; self.cycles += 4
            elif opcode == 0xED: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (high << 8) | low; self.cycles += 4
            elif opcode == 0xFD: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (((high << 8) | low) + self.x) & 0xFFFF; self.cycles += 4
            elif opcode == 0xF9: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (((high << 8) | low) + self.y) & 0xFFFF; self.cycles += 4
            elif opcode == 0xE1: 
                base = (read(pc) + self.x) & 0xFF; self.pc = (pc + 1) & 0xFFFF; addr = (read((base + 1) & 0xFF) << 8) | read(base); self.cycles += 6
            elif opcode == 0xF1: 
                base = read(pc); self.pc = (pc + 1) & 0xFFFF; addr = (((read((base + 1) & 0xFF) << 8) | read(base)) + self.y) & 0xFFFF; self.cycles += 5
            if opcode in (0xFD, 0xF9, 0xF1):
                offset = self.x if opcode == 0xFD else self.y
                if (addr & 0xFF00) != ((addr - offset) & 0xFF00): self.cycles += 1
            val = read(addr)
            carry = 1 if (self.p & self.C) else 0
            res = self.a - val - (1 - carry)
            self.set_flag(self.C, res >= 0)
            self.set_flag(self.V, bool((self.a ^ val) & (self.a ^ res) & 0x80))
            self.a = res & 0xFF; self.update_zn(self.a)

        # AND, ORA, EOR
        elif opcode in (0x29, 0x25, 0x35, 0x2D, 0x3D, 0x39, 0x21, 0x31):
            if opcode == 0x29: addr = pc; self.pc = (pc + 1) & 0xFFFF; self.cycles += 2
            elif opcode == 0x25: addr = read(pc); self.pc = (pc + 1) & 0xFFFF; self.cycles += 3
            elif opcode == 0x35: addr = (read(pc) + self.x) & 0xFF; self.pc = (pc + 1) & 0xFFFF; self.cycles += 4
            elif opcode == 0x2D: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (high << 8) | low; self.cycles += 4
            elif opcode == 0x3D: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (((high << 8) | low) + self.x) & 0xFFFF; self.cycles += 4
            elif opcode == 0x39: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (((high << 8) | low) + self.y) & 0xFFFF; self.cycles += 4
            elif opcode == 0x21: 
                base = (read(pc) + self.x) & 0xFF; self.pc = (pc + 1) & 0xFFFF; addr = (read((base + 1) & 0xFF) << 8) | read(base); self.cycles += 6
            elif opcode == 0x31: 
                base = read(pc); self.pc = (pc + 1) & 0xFFFF; addr = (((read((base + 1) & 0xFF) << 8) | read(base)) + self.y) & 0xFFFF; self.cycles += 5
            if opcode in (0x3D, 0x39, 0x31):
                offset = self.x if opcode == 0x3D else self.y
                if (addr & 0xFF00) != ((addr - offset) & 0xFF00): self.cycles += 1
            self.a &= read(addr); self.update_zn(self.a)
        elif opcode in (0x09, 0x05, 0x15, 0x0D, 0x1D, 0x19, 0x01, 0x11):
            if opcode == 0x09: addr = pc; self.pc = (pc + 1) & 0xFFFF; self.cycles += 2
            elif opcode == 0x05: addr = read(pc); self.pc = (pc + 1) & 0xFFFF; self.cycles += 3
            elif opcode == 0x15: addr = (read(pc) + self.x) & 0xFF; self.pc = (pc + 1) & 0xFFFF; self.cycles += 4
            elif opcode == 0x0D: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (high << 8) | low; self.cycles += 4
            elif opcode == 0x1D: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (((high << 8) | low) + self.x) & 0xFFFF; self.cycles += 4
            elif opcode == 0x19: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (((high << 8) | low) + self.y) & 0xFFFF; self.cycles += 4
            elif opcode == 0x01: 
                base = (read(pc) + self.x) & 0xFF; self.pc = (pc + 1) & 0xFFFF; addr = (read((base + 1) & 0xFF) << 8) | read(base); self.cycles += 6
            elif opcode == 0x11: 
                base = read(pc); self.pc = (pc + 1) & 0xFFFF; addr = (((read((base + 1) & 0xFF) << 8) | read(base)) + self.y) & 0xFFFF; self.cycles += 5
            if opcode in (0x1D, 0x19, 0x11):
                offset = self.x if opcode == 0x1D else self.y
                if (addr & 0xFF00) != ((addr - offset) & 0xFF00): self.cycles += 1
            self.a |= read(addr); self.update_zn(self.a)
        elif opcode in (0x49, 0x45, 0x55, 0x4D, 0x5D, 0x59, 0x41, 0x51):
            if opcode == 0x49: addr = pc; self.pc = (pc + 1) & 0xFFFF; self.cycles += 2
            elif opcode == 0x45: addr = read(pc); self.pc = (pc + 1) & 0xFFFF; self.cycles += 3
            elif opcode == 0x55: addr = (read(pc) + self.x) & 0xFF; self.pc = (pc + 1) & 0xFFFF; self.cycles += 4
            elif opcode == 0x4D: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (high << 8) | low; self.cycles += 4
            elif opcode == 0x5D: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (((high << 8) | low) + self.x) & 0xFFFF; self.cycles += 4
            elif opcode == 0x59: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (((high << 8) | low) + self.y) & 0xFFFF; self.cycles += 4
            elif opcode == 0x41: 
                base = (read(pc) + self.x) & 0xFF; self.pc = (pc + 1) & 0xFFFF; addr = (read((base + 1) & 0xFF) << 8) | read(base); self.cycles += 6
            elif opcode == 0x51: 
                base = read(pc); self.pc = (pc + 1) & 0xFFFF; addr = (((read((base + 1) & 0xFF) << 8) | read(base)) + self.y) & 0xFFFF; self.cycles += 5
            if opcode in (0x5D, 0x59, 0x51):
                offset = self.x if opcode == 0x5D else self.y
                if (addr & 0xFF00) != ((addr - offset) & 0xFF00): self.cycles += 1
            self.a ^= read(addr); self.update_zn(self.a)

        # CMP, CPX, CPY
        elif opcode in (0xC9, 0xC5, 0xD5, 0xCD, 0xDD, 0xD9, 0xC1, 0xD1):
            if opcode == 0xC9: addr = pc; self.pc = (pc + 1) & 0xFFFF; self.cycles += 2
            elif opcode == 0xC5: addr = read(pc); self.pc = (pc + 1) & 0xFFFF; self.cycles += 3
            elif opcode == 0xD5: addr = (read(pc) + self.x) & 0xFF; self.pc = (pc + 1) & 0xFFFF; self.cycles += 4
            elif opcode == 0xCD: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (high << 8) | low; self.cycles += 4
            elif opcode == 0xDD: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (((high << 8) | low) + self.x) & 0xFFFF; self.cycles += 4
            elif opcode == 0xD9: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (((high << 8) | low) + self.y) & 0xFFFF; self.cycles += 4
            elif opcode == 0xC1: 
                base = (read(pc) + self.x) & 0xFF; self.pc = (pc + 1) & 0xFFFF; addr = (read((base + 1) & 0xFF) << 8) | read(base); self.cycles += 6
            elif opcode == 0xD1: 
                base = read(pc); self.pc = (pc + 1) & 0xFFFF; addr = (((read((base + 1) & 0xFF) << 8) | read(base)) + self.y) & 0xFFFF; self.cycles += 5
            if opcode in (0xDD, 0xD9, 0xD1):
                offset = self.x if opcode == 0xDD else self.y
                if (addr & 0xFF00) != ((addr - offset) & 0xFF00): self.cycles += 1
            val = read(addr)
            res = self.a - val
            self.set_flag(self.C, self.a >= val)
            self.set_flag(self.Z, (res & 0xFF) == 0)
            self.set_flag(self.N, (res & 0x80) != 0)
        elif opcode in (0xE0, 0xE4, 0xEC):
            if opcode == 0xE0: addr = pc; self.pc = (pc + 1) & 0xFFFF; self.cycles += 2
            elif opcode == 0xE4: addr = read(pc); self.pc = (pc + 1) & 0xFFFF; self.cycles += 3
            elif opcode == 0xEC: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (high << 8) | low; self.cycles += 4
            val = read(addr)
            res = self.x - val
            self.set_flag(self.C, self.x >= val)
            self.set_flag(self.Z, (res & 0xFF) == 0)
            self.set_flag(self.N, (res & 0x80) != 0)
        elif opcode in (0xC0, 0xC4, 0xCC):
            if opcode == 0xC0: addr = pc; self.pc = (pc + 1) & 0xFFFF; self.cycles += 2
            elif opcode == 0xC4: addr = read(pc); self.pc = (pc + 1) & 0xFFFF; self.cycles += 3
            elif opcode == 0xCC: 
                low = read(pc); high = read((pc + 1) & 0xFFFF); self.pc = (pc + 2) & 0xFFFF; addr = (high << 8) | low; self.cycles += 4
            val = read(addr)
            res = self.y - val
            self.set_flag(self.C, self.y >= val)
            self.set_flag(self.Z, (res & 0xFF) == 0)
            self.set_flag(self.N, (res & 0x80) != 0)

        # Remaining Opcodes (Kept compact)
        elif opcode in (0xE6, 0xF6, 0xEE, 0xFE, 0xC6, 0xD6, 0xCE, 0xDE, 0x06, 0x16, 0x0E, 0x1E, 0x46, 0x56, 0x4E, 0x5E, 0x26, 0x36, 0x2E, 0x3E, 0x66, 0x76, 0x6E, 0x7E):
            if opcode in (0xE6, 0xC6, 0x06, 0x46, 0x26, 0x66): addr = self.fetch(); self.cycles += 5
            elif opcode in (0xF6, 0xD6, 0x16, 0x56, 0x36, 0x76): addr = (self.fetch() + self.x) & 0xFF; self.cycles += 6
            elif opcode in (0xEE, 0xCE, 0x0E, 0x4E, 0x2E, 0x6E):
                low = self.fetch(); high = self.fetch(); addr = (high << 8) | low; self.cycles += 6
            elif opcode in (0xFE, 0xDE, 0x1E, 0x5E, 0x3E, 0x7E):
                low = self.fetch(); high = self.fetch(); addr = (((high << 8) | low) + self.x) & 0xFFFF; self.cycles += 7
            val = read(addr)
            if opcode in (0xE6, 0xF6, 0xEE, 0xFE): val = (val + 1) & 0xFF
            elif opcode in (0xC6, 0xD6, 0xCE, 0xDE): val = (val - 1) & 0xFF
            elif opcode in (0x06, 0x16, 0x0E, 0x1E): self.set_flag(self.C, bool(val & 0x80)); val = (val << 1) & 0xFF
            elif opcode in (0x46, 0x56, 0x4E, 0x5E): self.set_flag(self.C, bool(val & 0x01)); val = (val >> 1) & 0xFF
            elif opcode in (0x26, 0x36, 0x2E, 0x3E): old_c = 1 if (self.p & self.C) else 0; self.set_flag(self.C, bool(val & 0x80)); val = ((val << 1) | old_c) & 0xFF
            elif opcode in (0x66, 0x76, 0x6E, 0x7E): old_c = 0x80 if (self.p & self.C) else 0; self.set_flag(self.C, bool(val & 0x01)); val = ((val >> 1) | old_c) & 0xFF
            write(addr, val); self.update_zn(val)
        elif opcode == 0x0A: self.set_flag(self.C, bool(self.a & 0x80)); self.a = (self.a << 1) & 0xFF; self.update_zn(self.a); self.cycles += 2
        elif opcode == 0x4A: self.set_flag(self.C, bool(self.a & 0x01)); self.a = (self.a >> 1) & 0xFF; self.update_zn(self.a); self.cycles += 2
        elif opcode == 0x2A: old_c = 1 if (self.p & self.C) else 0; self.set_flag(self.C, bool(self.a & 0x80)); self.a = ((self.a << 1) | old_c) & 0xFF; self.update_zn(self.a); self.cycles += 2
        elif opcode == 0x6A: old_c = 0x80 if (self.p & self.C) else 0; self.set_flag(self.C, bool(self.a & 0x01)); self.a = ((self.a >> 1) | old_c) & 0xFF; self.update_zn(self.a); self.cycles += 2
        elif opcode in (0x24, 0x2C):
            if opcode == 0x24: addr = self.fetch(); self.cycles += 3
            else: low = self.fetch(); high = self.fetch(); addr = (high << 8) | low; self.cycles += 4
            val = read(addr)
            self.set_flag(self.Z, (self.a & val) == 0)
            self.set_flag(self.N, bool(val & 0x80))
            self.set_flag(self.V, bool(val & 0x40))
        elif opcode == 0x90: self.branch(not (self.p & self.C))
        elif opcode == 0xB0: self.branch(self.p & self.C)
        elif opcode == 0xF0: self.branch(self.p & self.Z)
        elif opcode == 0x30: self.branch(self.p & self.N)
        elif opcode == 0xD0: self.branch(not (self.p & self.Z))
        elif opcode == 0x10: self.branch(not (self.p & self.N))
        elif opcode == 0x50: self.branch(not (self.p & self.V))
        elif opcode == 0x70: self.branch(self.p & self.V)
        elif opcode == 0x4C: self.pc = (self.fetch() | (self.fetch() << 8)); self.cycles += 3
        elif opcode == 0x6C: 
            ptr = self.fetch() | (self.fetch() << 8); low = read(ptr); ptr_high = (ptr & 0xFF00) | ((ptr + 1) & 0x00FF); high = read(ptr_high)
            self.pc = (high << 8) | low; self.cycles += 5
        elif opcode == 0x20: 
            low = self.fetch(); high = self.fetch(); target = (high << 8) | low
            self.push16((self.pc - 1) & 0xFFFF); self.pc = target; self.cycles += 6
        elif opcode == 0x60: self.pc = (self.pop16() + 1) & 0xFFFF; self.cycles += 6
        elif opcode == 0x40: self.p = (self.pop() & ~self.B) | self.U; self.pc = self.pop16(); self.cycles += 6
        elif opcode == 0x48: self.push(self.a); self.cycles += 3
        elif opcode == 0x68: self.a = self.pop(); self.update_zn(self.a); self.cycles += 4
        elif opcode == 0x08: self.push(self.p | self.B | self.U); self.cycles += 3
        elif opcode == 0x28: self.p = (self.pop() & ~self.B) | self.U; self.cycles += 4
        elif opcode == 0x18: self.p &= ~self.C; self.cycles += 2
        elif opcode == 0x38: self.p |= self.C; self.cycles += 2
        elif opcode == 0x58: self.p &= ~self.I; self.cycles += 2
        elif opcode == 0x78: self.p |= self.I; self.cycles += 2
        elif opcode == 0xB8: self.p &= ~self.V; self.cycles += 2
        elif opcode == 0xD8: self.p &= ~self.D; self.cycles += 2
        elif opcode == 0xF8: self.p |= self.D; self.cycles += 2
        elif opcode == 0x00:
            self.pc = (self.pc + 1) & 0xFFFF
            self.push16(self.pc); self.push(self.p | self.B | self.U); self.p |= self.I
            self.pc = (read(0xFFFF) << 8) | read(0xFFFE); self.cycles += 7

        cycles_spent = self.cycles - start_cycles
        return cycles_spent if cycles_spent > 0 else 2