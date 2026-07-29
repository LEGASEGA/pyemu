import pygame

class Controller:
    def __init__(self):
        self.strobe = False
        self.button_states = 0  # Bitmask: A, B, Select, Start, Up, Down, Left, Right
        self.shift_reg = 0

    def write_strobe(self, val):
        self.strobe = bool(val & 1)
        if self.strobe:
            self.shift_reg = self.button_states

    def read_state(self):
        if self.strobe:
            self.shift_reg = self.button_states
        val = self.shift_reg & 1
        self.shift_reg >>= 1
        return 0x40 | val

    def update_keys(self):
        keys = pygame.key.get_pressed()
        state = 0
        state |= (1 << 0) if keys[pygame.K_z] else 0        # A (Z key)
        state |= (1 << 1) if keys[pygame.K_x] else 0        # B (X key)
        state |= (1 << 2) if keys[pygame.K_RSHIFT] else 0   # Select (Right Shift)
        state |= (1 << 3) if keys[pygame.K_RETURN] else 0   # Start (Enter)
        state |= (1 << 4) if keys[pygame.K_UP] else 0       # Up
        state |= (1 << 5) if keys[pygame.K_DOWN] else 0     # Down
        state |= (1 << 6) if keys[pygame.K_LEFT] else 0     # Left
        state |= (1 << 7) if keys[pygame.K_RIGHT] else 0    # Right

        self.button_states = state
        if self.strobe:
            self.shift_reg = state


class Zapper:
    def __init__(self, ppu=None):
        self.ppu = ppu
        self.trigger = False
        self.mouse_x = 0
        self.mouse_y = 0

    def update_state(self, x, y, trigger):
        self.mouse_x = x
        self.mouse_y = y
        self.trigger = trigger

    def read(self):
        val = 0
        if self.trigger:
            val |= 0x10  # Bit 4: Trigger pulled
            
        if self.ppu:
            if 0 <= self.mouse_x < 256 and 0 <= self.mouse_y < 240:
                idx = (self.mouse_y * 256 + self.mouse_x) * 3
                r, g, b = self.ppu.pixel_data[idx], self.ppu.pixel_data[idx+1], self.ppu.pixel_data[idx+2]
                # Duck Hunt flashes white targets on a black screen
                if r > 200 and g > 200 and b > 200:
                    val |= 0x08  # Bit 3: Light detected
        return val