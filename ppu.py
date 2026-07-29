import pygame
import platform
import numpy as np

IS_PYPY = platform.python_implementation() == 'PyPy'

NES_PALETTE = [
    (116,116,116), (36,24,140),   (0,0,168),     (68,0,156),    (112,0,120),   (132,0,64),    (124,0,0),     (92,16,0),
    (56,40,0),     (0,64,0),      (0,80,0),      (0,64,56),     (0,60,116),    (0,0,0),       (0,0,0),       (0,0,0),
    (188,188,188), (0,112,236),   (32,56,236),   (128,0,240),   (180,0,176),   (228,0,88),    (216,40,0),    (160,68,0),
    (124,104,0),   (24,148,0),    (0,168,0),     (0,168,68),    (0,152,180),   (0,0,0),       (0,0,0),       (0,0,0),
    (252,252,252), (60,188,252),   (104,136,252), (152,120,248), (248,120,248), (248,88,152),  (248,120,88),  (252,160,0),
    (228,196,0),   (160,224,0),   (116,228,0),   (76,220,72),   (56,204,108),  (56,180,224),  (60,60,60),    (0,0,0),
    (252,252,252), (164,228,252), (184,204,252), (208,196,252), (248,196,252), (248,184,204), (248,184,184), (252,216,168),
    (248,232,112), (204,240,108), (172,248,120), (156,252,184), (140,252,216), (156,240,236), (0,0,0),       (0,0,0)
]

if not IS_PYPY:
    NES_PALETTE_NP = np.array(NES_PALETTE, dtype=np.uint8)

class PPU:
    def __init__(self, cartridge=None):
        self.cartridge = cartridge
        self.cpu = None

        self.vram = bytearray(2048)
        self.oam = bytearray([0xFF] * 256)
        self.palette_ram = bytearray(32)

        self.ppuctrl = 0x00
        self.ppumask = 0x00
        self.ppustatus = 0x00
        self.oamaddr = 0x00

        self.v = 0x0000
        self.t = 0x0000
        self.x = 0
        self.w = 0

        self.read_buffer = 0x00
        self.scanline = 0
        self.cycle = 0
        self.frame_complete = False

        self.pixel_data = bytearray(256 * 240 * 3)
        self.frame_buffer = pygame.image.frombuffer(self.pixel_data, (256, 240), "RGB")
        self.bg_pixels = bytearray(256)

        self.mapper = cartridge.mapper if cartridge and hasattr(cartridge, 'mapper') else None
        self.mirroring = 0
        if self.mapper:
            self.mirroring = getattr(self.mapper, 'mirroring', 0)
            self.mapper.chr_dirty = True
            
        self.chr_rom = cartridge.chr_rom
        self.chr_rom_len = len(self.chr_rom)
        self.ppu_map_read = cartridge.mapper.ppu_map_read
        self.cart_ppu_write = cartridge.ppu_write

        self.chr_lut = bytearray(8192)
        self.chr_was_dirty = True  # Track for UI viewer updates
        
        if not IS_PYPY:
            # OPTIMIZATION: Pre-allocate Numpy arrays to prevent 240 allocations per frame
            self.tile_indices = np.arange(33, dtype=np.uint16)
            self.bits = np.array([7, 6, 5, 4, 3, 2, 1, 0], dtype=np.uint8)
            self.vram_np = np.frombuffer(self.vram, dtype=np.uint8)
            self.palette_ram_np = np.frombuffer(self.palette_ram, dtype=np.uint8)
            self.pixel_data_np = np.frombuffer(self.pixel_data, dtype=np.uint8)
            self.chr_rom_np = np.frombuffer(self.chr_rom, dtype=np.uint8) if self.chr_rom_len > 0 else np.zeros(8192, dtype=np.uint8)
            
        self.update_chr_lut()

    def update_chr_lut(self):
        chr_rom = self.chr_rom
        if IS_PYPY:
            chr_lut = self.chr_lut
            ppu_map_read = self.ppu_map_read
            for i in range(8192):
                handled, mapped = ppu_map_read(i)
                if handled: chr_lut[i] = chr_rom[mapped]
        else:
            mapper = self.mapper
            # FAST PATH: For MMC3 (Mapper 4), we can rebuild the LUT using Numpy C-level slicing in microseconds!
            if hasattr(mapper, 'chr_banks_map') and self.chr_rom_len >= 8192:
                banks = mapper.chr_banks_map
                lut = np.zeros(8192, dtype=np.uint8)
                chr_rom_np = self.chr_rom_np
                for i in range(8):
                    bank = banks[i]
                    start = i * 1024
                    rom_start = bank * 1024
                    if rom_start + 1024 <= self.chr_rom_len:
                        lut[start : start + 1024] = chr_rom_np[rom_start : rom_start + 1024]
                self.chr_lut_np = lut
                self.chr_lut = lut.tobytes()
            else:
                # Fallback for other mappers
                ppu_map_read = self.ppu_map_read
                new_lut = bytearray(8192)
                for i in range(8192):
                    handled, mapped = ppu_map_read(i)
                    if handled: new_lut[i] = chr_rom[mapped]
                self.chr_lut = new_lut
                self.chr_lut_np = np.array(self.chr_lut, dtype=np.uint8)

    def read_register(self, addr):
        reg = 0x2000 + (addr % 8)
        if reg == 0x2002:
            res = (self.ppustatus & 0xE0) | (self.read_buffer & 0x1F)
            self.ppustatus &= ~0x80
            self.w = 0
            return res
        elif reg == 0x2004:
            return self.oam[self.oamaddr]
        elif reg == 0x2007:
            data = self.vram_read(self.v)
            if (self.v & 0x3FFF) < 0x3F00:
                res = self.read_buffer
                self.read_buffer = data
            else:
                res = data
                self.read_buffer = self.vram_read(self.v - 0x1000)
            self.v = (self.v + (32 if (self.ppuctrl & 0x04) else 1)) & 0x7FFF
            return res
        return 0

    def write_register(self, addr, val):
        reg = 0x2000 + (addr % 8)
        val &= 0xFF
        if reg == 0x2000:
            self.ppuctrl = val
            self.t = (self.t & 0xF3FF) | ((val & 0x03) << 10)
            if (val & 0x80) and (self.ppustatus & 0x80) and self.cpu:
                self.cpu.nmi_pending = True
        elif reg == 0x2001:
            self.ppumask = val
        elif reg == 0x2003:
            self.oamaddr = val
        elif reg == 0x2004:
            self.oam[self.oamaddr] = val
            self.oamaddr = (self.oamaddr + 1) & 0xFF
        elif reg == 0x2005:
            if self.w == 0:
                self.x = val & 0x07
                self.t = (self.t & 0xFFE0) | (val >> 3)
                self.w = 1
            else:
                self.t = (self.t & 0x8FFF) | ((val & 0x07) << 12) | ((val & 0xF8) << 2)
                self.w = 0
        elif reg == 0x2006:
            if self.w == 0:
                self.t = (self.t & 0x00FF) | ((val & 0x3F) << 8)
                self.w = 1
            else:
                self.t = (self.t & 0xFF00) | val
                self.v = self.t
                self.w = 0
        elif reg == 0x2007:
            self.vram_write(self.v, val)
            self.v = (self.v + (32 if (self.ppuctrl & 0x04) else 1)) & 0x7FFF

    def mirror_nametable(self, addr):
        addr = (addr - 0x2000) & 0x0FFF
        if self.mapper:
            self.mirroring = getattr(self.mapper, 'mirroring', self.mirroring)

        if self.mirroring == 0: 
            if addr < 0x0800: return addr % 0x0400
            else: return 0x0400 + (addr % 0x0400)
        elif self.mirroring == 1: 
            return addr % 0x0800
        elif self.mirroring == 2: 
            return addr % 0x0400
        elif self.mirroring == 3: 
            return 0x0400 + (addr % 0x0400)
        return addr % 0x0400

    def vram_read(self, addr):
        addr &= 0x3FFF
        if addr <= 0x1FFF:
            return self.chr_lut[addr]
        elif 0x2000 <= addr <= 0x3EFF:
            return self.vram[self.mirror_nametable(addr)]
        elif 0x3F00 <= addr <= 0x3FFF:
            pal_addr = addr & 0x001F
            if pal_addr in (0x0010, 0x0014, 0x0018, 0x001C): pal_addr &= 0x000F
            return self.palette_ram[pal_addr]
        return 0

    def vram_write(self, addr, val):
        addr &= 0x3FFF
        val &= 0xFF
        if addr <= 0x1FFF:
            if self.cart_ppu_write: self.cart_ppu_write(addr, val)
            self.chr_lut[addr] = val
            if not IS_PYPY: self.chr_lut_np[addr] = val
        elif 0x2000 <= addr <= 0x3EFF:
            self.vram[self.mirror_nametable(addr)] = val
        elif 0x3F00 <= addr <= 0x3FFF:
            pal_addr = addr & 0x001F
            if pal_addr in (0x0010, 0x0014, 0x0018, 0x001C): pal_addr &= 0x000F
            self.palette_ram[pal_addr] = val

    def render_scanline(self):
        # FIX: Only process CHR dirty flag right before rendering a scanline.
        # This prevents the LUT from being rebuilt hundreds of times per frame during VBlank.
        if self.mapper and getattr(self.mapper, 'chr_dirty', False):
            self.update_chr_lut()
            self.mapper.chr_dirty = False
            self.chr_was_dirty = True
            
        if self.mapper:
            self.mirroring = self.mapper.mirroring

        if IS_PYPY:
            self._render_scanline_pypy()
        else:
            self._render_scanline_cpython()

    def _render_scanline_pypy(self):
        scanline = self.scanline
        if not (self.ppumask & 0x18):
            col = NES_PALETTE[self.palette_ram[0] & 0x3F]
            start_idx = scanline * 768
            self.pixel_data[start_idx : start_idx + 3] = col
            self.pixel_data[start_idx + 3 : start_idx + 768] = self.pixel_data[start_idx : start_idx + 765]
            self.bg_pixels[:] = b'\x00' * 256
            return

        if not (self.ppumask & 0x08):
            col = NES_PALETTE[self.palette_ram[0] & 0x3F]
            start_idx = scanline * 768
            self.pixel_data[start_idx : start_idx + 3] = col
            self.pixel_data[start_idx + 3 : start_idx + 768] = self.pixel_data[start_idx : start_idx + 765]
            self.bg_pixels[:] = b'\x00' * 256
        else:
            v = self.v
            fine_y = (v >> 12) & 0x07
            table_base = 0x1000 if (self.ppuctrl & 0x10) else 0x0000
            x_scroll = self.x
            mirroring = self.mirroring
            vram = self.vram
            chr_lut = self.chr_lut
            palette_ram = self.palette_ram
            bg_pixels = self.bg_pixels
            pixel_data = self.pixel_data
            ppumask = self.ppumask

            v_tile_y = (v >> 5) & 0x001F
            cur_tile_x = v & 0x001F
            cur_nt_idx = (v >> 10) & 0x03

            # Initial fetch before the loop
            addr_mirrored = (cur_nt_idx * 0x0400) + (v_tile_y * 32) + cur_tile_x
            if mirroring == 0:
                if addr_mirrored < 0x0800: tile_id = vram[addr_mirrored % 0x0400]
                else: tile_id = vram[0x0400 + (addr_mirrored % 0x0400)]
            elif mirroring == 1: tile_id = vram[addr_mirrored % 0x0800]
            elif mirroring == 2: tile_id = vram[addr_mirrored % 0x0400]
            else: tile_id = vram[0x0400 + (addr_mirrored % 0x0400)]

            attr_mirrored = 0x03C0 + (cur_nt_idx * 0x0400) + ((v_tile_y // 4) * 8) + (cur_tile_x // 4)
            if mirroring == 0:
                if attr_mirrored < 0x0800: attr_byte = vram[attr_mirrored % 0x0400]
                else: attr_byte = vram[0x0400 + (attr_mirrored % 0x0400)]
            elif mirroring == 1: attr_byte = vram[attr_mirrored % 0x0800]
            elif mirroring == 2: attr_byte = vram[attr_mirrored % 0x0400]
            else: attr_byte = vram[0x0400 + (attr_mirrored % 0x0400)]
            
            palette_shift = (((v_tile_y % 4) // 2) * 4) + (((cur_tile_x % 4) // 2) * 2)
            palette_idx = (attr_byte >> palette_shift) & 0x03

            chr_addr = table_base + (tile_id * 16) + fine_y
            chr_low = chr_lut[chr_addr]
            chr_high = chr_lut[(chr_addr + 8) & 0x1FFF]

            for pixel_x in range(256):
                bit_index = (pixel_x + x_scroll) & 7
                
                bit0 = (chr_low >> (7 - bit_index)) & 1
                bit1 = (chr_high >> (7 - bit_index)) & 1
                color_bit = (bit1 << 1) | bit0

                if pixel_x < 8 and not (ppumask & 0x02): color_bit = 0

                bg_pixels[pixel_x] = color_bit
                if color_bit == 0: pal_val = palette_ram[0]
                else:
                    pal_idx = (palette_idx * 4) + color_bit
                    if pal_idx in (0x10, 0x14, 0x18, 0x1C): pal_idx &= 0x0F
                    pal_val = palette_ram[pal_idx]
                
                r, g, b = NES_PALETTE[pal_val & 0x3F]
                idx = (scanline * 256 + pixel_x) * 3
                pixel_data[idx] = r; pixel_data[idx + 1] = g; pixel_data[idx + 2] = b

                if bit_index == 7:
                    if cur_tile_x == 31: cur_tile_x = 0; cur_nt_idx ^= 1
                    else: cur_tile_x += 1
                    
                    # Fetch next tile
                    addr_mirrored = (cur_nt_idx * 0x0400) + (v_tile_y * 32) + cur_tile_x
                    if mirroring == 0:
                        if addr_mirrored < 0x0800: tile_id = vram[addr_mirrored % 0x0400]
                        else: tile_id = vram[0x0400 + (addr_mirrored % 0x0400)]
                    elif mirroring == 1: tile_id = vram[addr_mirrored % 0x0800]
                    elif mirroring == 2: tile_id = vram[addr_mirrored % 0x0400]
                    else: tile_id = vram[0x0400 + (addr_mirrored % 0x0400)]

                    attr_mirrored = 0x03C0 + (cur_nt_idx * 0x0400) + ((v_tile_y // 4) * 8) + (cur_tile_x // 4)
                    if mirroring == 0:
                        if attr_mirrored < 0x0800: attr_byte = vram[attr_mirrored % 0x0400]
                        else: attr_byte = vram[0x0400 + (attr_mirrored % 0x0400)]
                    elif mirroring == 1: attr_byte = vram[attr_mirrored % 0x0800]
                    elif mirroring == 2: attr_byte = vram[attr_mirrored % 0x0400]
                    else: attr_byte = vram[0x0400 + (attr_mirrored % 0x0400)]
                    
                    palette_shift = (((v_tile_y % 4) // 2) * 4) + (((cur_tile_x % 4) // 2) * 2)
                    palette_idx = (attr_byte >> palette_shift) & 0x03

                    chr_addr = table_base + (tile_id * 16) + fine_y
                    chr_low = chr_lut[chr_addr]
                    chr_high = chr_lut[(chr_addr + 8) & 0x1FFF]

        if self.ppumask & 0x18:
            if (self.v & 0x7000) != 0x7000: self.v += 0x1000
            else:
                self.v &= ~0x7000
                y = (self.v & 0x03E0) >> 5
                if y == 29: y = 0; self.v ^= 0x0800
                elif y == 31: y = 0
                else: y += 1
                self.v = (self.v & ~0x03E0) | (y << 5)

    def _render_scanline_cpython(self):
        scanline = self.scanline
        if not (self.ppumask & 0x18):
            col = NES_PALETTE[self.palette_ram[0] & 0x3F]
            start_idx = scanline * 768
            self.pixel_data[start_idx : start_idx + 3] = col
            self.pixel_data[start_idx + 3 : start_idx + 768] = self.pixel_data[start_idx : start_idx + 765]
            self.bg_pixels[:] = b'\x00' * 256
            return

        if not (self.ppumask & 0x08):
            col = NES_PALETTE[self.palette_ram[0] & 0x3F]
            start_idx = scanline * 768
            self.pixel_data[start_idx : start_idx + 3] = col
            self.pixel_data[start_idx + 3 : start_idx + 768] = self.pixel_data[start_idx : start_idx + 765]
            self.bg_pixels[:] = b'\x00' * 256
        else:
            v = self.v
            fine_y = (v >> 12) & 0x07
            table_base = 0x1000 if (self.ppuctrl & 0x10) else 0x0000
            x_scroll = self.x
            mirroring = self.mirroring

            tile_indices = self.tile_indices
            v_tile_x = (v & 0x001F) + tile_indices
            nt_flip_x = v_tile_x > 31
            v_tile_x[nt_flip_x] -= 32
            v_tile_y = (v >> 5) & 0x001F
            nt_base = (v >> 10) & 0x03
            nt_idx = nt_base ^ nt_flip_x.astype(np.uint16)
            
            nt_addrs = 0x2000 + (nt_idx * 0x0400) + (v_tile_y * 32) + v_tile_x
            attr_addrs = 0x23C0 + (nt_idx * 0x0400) + ((v_tile_y // 4) * 8) + (v_tile_x // 4)
            
            nt_offset = nt_addrs - 0x2000
            attr_offset = attr_addrs - 0x2000
            if mirroring == 0:
                mirrored_nt = np.where(nt_offset < 0x0800, nt_offset % 0x0400, 0x0400 + (nt_offset % 0x0400)).astype(np.intp)
                mirrored_attr = np.where(attr_offset < 0x0800, attr_offset % 0x0400, 0x0400 + (attr_offset % 0x0400)).astype(np.intp)
            elif mirroring == 1:
                mirrored_nt = (nt_offset % 0x0800).astype(np.intp)
                mirrored_attr = (attr_offset % 0x0800).astype(np.intp)
            elif mirroring == 2:
                mirrored_nt = (nt_offset % 0x0400).astype(np.intp)
                mirrored_attr = (attr_offset % 0x0400).astype(np.intp)
            elif mirroring == 3:
                mirrored_nt = (0x0400 + (nt_offset % 0x0400)).astype(np.intp)
                mirrored_attr = (0x0400 + (attr_offset % 0x0400)).astype(np.intp)
            else:
                mirrored_nt = (nt_offset % 0x0400).astype(np.intp)
                mirrored_attr = (attr_offset % 0x0400).astype(np.intp)
                
            tile_ids = self.vram_np[mirrored_nt]
            attr_bytes = self.vram_np[mirrored_attr]
            
            palette_shift = (((v_tile_y % 4) // 2) * 4) + (((v_tile_x % 4) // 2) * 2)
            palette_idx = (attr_bytes >> palette_shift) & 0x03
            
            chr_addrs = table_base + (tile_ids.astype(np.int32) * 16) + fine_y
            chr_lows = self.chr_lut_np[chr_addrs]
            chr_highs = np.take(self.chr_lut_np, chr_addrs + 8, mode='wrap')
            
            bits = self.bits
            bit0 = (chr_lows[:, None] >> bits) & 1
            bit1 = (chr_highs[:, None] >> bits) & 1
            color_bits = (bit1 << 1) | bit0
            color_bits = color_bits.flatten()
            
            scanline_colors = color_bits[x_scroll : x_scroll + 256]
            if not (self.ppumask & 0x02): scanline_colors[:8] = 0
                
            self.bg_pixels[:] = scanline_colors.tobytes()
            
            pal_idx_expanded = np.repeat(palette_idx, 8)
            pal_idx_scrolled = pal_idx_expanded[x_scroll : x_scroll + 256]
            pal_addrs = np.where(scanline_colors == 0, 0, (pal_idx_scrolled * 4) + scanline_colors)
            
            pal_vals = self.palette_ram_np[pal_addrs]
            rgb = NES_PALETTE_NP[pal_vals]
            
            start_idx = scanline * 768
            self.pixel_data_np[start_idx : start_idx + 768] = rgb.ravel()

        if self.ppumask & 0x18:
            if (self.v & 0x7000) != 0x7000: self.v += 0x1000
            else:
                self.v &= ~0x7000
                y = (self.v & 0x03E0) >> 5
                if y == 29: y = 0; self.v ^= 0x0800
                elif y == 31: y = 0
                else: y += 1
                self.v = (self.v & ~0x03E0) | (y << 5)

    def render_sprites(self):
        if not (self.ppumask & 0x10): return
        sprite_height = 16 if (self.ppuctrl & 0x20) else 8
        pattern_base = 0x1000 if (self.ppuctrl & 0x08) else 0x0000
        
        chr_lut = self.chr_lut if IS_PYPY else self.chr_lut_np
        palette_ram = self.palette_ram
        bg_pixels = self.bg_pixels
        pixel_data = self.pixel_data
        scanline = self.scanline
        ppumask = self.ppumask
        oam = self.oam

        for i in range(63, -1, -1):
            base = i * 4
            sy = oam[base] + 1
            tile = oam[base + 1]
            attr = oam[base + 2]
            sx = oam[base + 3]

            if not (sy <= scanline < sy + sprite_height): continue
            row = scanline - sy
            if attr & 0x80: row = (sprite_height - 1) - row

            if sprite_height == 16:
                if row >= 8: tile_addr = ((tile & 1) * 0x1000) + ((tile & 0xFE) + 1) * 16 + (row - 8)
                else: tile_addr = ((tile & 1) * 0x1000) + ((tile & 0xFE) * 16) + row
            else:
                tile_addr = pattern_base + (tile * 16) + row

            low = chr_lut[tile_addr]
            high = chr_lut[(tile_addr + 8) & 0x1FFF]
            palette_idx = (attr & 0x03) + 4
            attr_flip = attr & 0x40
            attr_priority = attr & 0x20

            for px in range(8):
                pixel_x = sx + px
                if pixel_x >= 256: continue
                if pixel_x < 8 and not (ppumask & 0x04): continue

                col_bit = (7 - px) if not attr_flip else px
                bit0 = (low >> col_bit) & 1
                bit1 = (high >> col_bit) & 1
                color_bit = (bit1 << 1) | bit0

                if color_bit != 0:
                    if i == 0 and bg_pixels[pixel_x] != 0 and pixel_x < 255:
                        if (ppumask & 0x08) and (ppumask & 0x10): self.ppustatus |= 0x40
                    if attr_priority and bg_pixels[pixel_x] != 0: continue

                    pal_idx = (palette_idx * 4) + color_bit
                    pal_val = palette_ram[pal_idx]
                    r, g, b = NES_PALETTE[pal_val & 0x3F]
                    idx = (scanline * 256 + pixel_x) * 3
                    pixel_data[idx] = r; pixel_data[idx + 1] = g; pixel_data[idx + 2] = b

    def step(self, num_cycles=1):
        # FIX: Removed the update_chr_lut check from here!
        # It was causing the LUT to be rebuilt hundreds of times per frame.
        # It is now safely checked only at the start of render_scanline().
        
        for _ in range(num_cycles):
            self.cycle += 1
            if self.cycle >= 341:
                self.cycle = 0
                self.scanline += 1
                if self.scanline >= 262:
                    self.scanline = 0
                    self.frame_complete = True

            if self.scanline < 240:
                if self.cycle == 260:
                    if (self.ppumask & 0x18) and self.mapper: self.mapper.scanline()
                elif self.cycle == 256:
                    self.render_scanline()
                    self.render_sprites()
                elif self.cycle == 257:
                    if self.ppumask & 0x18: self.v = (self.v & ~0x041F) | (self.t & 0x041F)
            elif self.scanline == 241:
                if self.cycle == 1: self.ppustatus |= 0x80
                elif self.cycle == 3:
                    if self.ppuctrl & 0x80: self.cpu.nmi_pending = True
            elif self.scanline == 261:
                if self.cycle == 1: self.ppustatus &= ~0xC0
                elif self.cycle == 260:
                    if self.ppumask & 0x18 and self.mapper: self.mapper.scanline()
                elif self.cycle == 304:
                    if self.ppumask & 0x18: self.v = self.t

    def blit_to_surface(self):
        self.frame_buffer = pygame.image.frombuffer(self.pixel_data, (256, 240), "RGB")