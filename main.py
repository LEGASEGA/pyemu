import pygame
import sys
import os
import platform
import subprocess
from cartridge import Cartridge
from bus import Bus
from cpu import CPU
from ppu import PPU
from controller import Controller

# Detect if we are running on PyPy
IS_PYPY = platform.python_implementation() == 'PyPy'

def get_rom_path():
    if len(sys.argv) > 1:
        return sys.argv[1]
        
    os_name = platform.system()
    file_path = ""

    if os_name == 'Darwin':
        try:
            script = '''
            tell application "System Events"
                activate
                set selectedFile to choose file with prompt "Select a NES ROM file" of type {"nes"} default location (path to desktop)
                return POSIX path of selectedFile
            end tell
            '''
            result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                file_path = result.stdout.strip()
        except Exception:
            pass
            
    elif os_name == 'Linux':
        try:
            result = subprocess.run(
                ['zenity', '--file-selection', '--file-filter=NES ROM Files (*.nes) | *.nes', '--title=Select NES ROM'],
                capture_output=True, text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                file_path = result.stdout.strip()
        except Exception:
            pass
            
        if not file_path:
            try:
                result = subprocess.run(
                    ['kdialog', '--getopenfilename', '.', '*.nes|NES ROM Files'],
                    capture_output=True, text=True
                )
                if result.returncode == 0 and result.stdout.strip():
                    file_path = result.stdout.strip()
            except Exception:
                pass

    elif os_name == 'Windows':
        try:
            script = '''
            Add-Type -AssemblyName System.Windows.Forms
            $openFileDialog = New-Object System.Windows.Forms.OpenFileDialog
            $openFileDialog.Filter = "NES ROM Files (*.nes)|*.nes|All Files (*.*)|*.*"
            $openFileDialog.Title = "Select NES ROM"
            if ($openFileDialog.ShowDialog() -eq "OK") {
                $openFileDialog.FileName
            }
            '''
            result = subprocess.run(['powershell', '-NoProfile', '-Command', script], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                file_path = result.stdout.strip()
        except Exception:
            pass

    if not file_path:
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            file_path = filedialog.askopenfilename(
                title="Select NES ROM",
                filetypes=[("NES ROM Files", "*.nes"), ("All Files", "*.*")]
            )
            root.destroy()
        except Exception:
            pass

    if not file_path or not os.path.exists(file_path):
        print("\n--- AUTOMATIC FILE SELECTION FAILED ---")
        print("Please drag and drop a .nes ROM file directly into this terminal window,")
        print("or type the full path to the file, then press Enter:")
        try:
            user_input = input().strip()
            if user_input.startswith("'") and user_input.endswith("'"):
                user_input = user_input[1:-1]
            elif user_input.startswith('"') and user_input.endswith('"'):
                user_input = user_input[1:-1]
                
            if user_input and os.path.exists(user_input):
                file_path = user_input
            else:
                print("Error: File not found. Exiting.")
                sys.exit(1)
        except KeyboardInterrupt:
            print("\nExiting.")
            sys.exit(1)
            
    return file_path


class EmulatorApp:
    def __init__(self):
        # FIX: pre_init MUST be called before pygame.init()
        pygame.mixer.pre_init(44100, -16, 1, 1024)
        pygame.init()
        
        self.screen = pygame.display.set_mode((1024, 640))
        pygame.display.set_caption("PYemu - NES Emulator")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("monospace", 16, bold=True)
        self.small_font = pygame.font.SysFont("monospace", 12, bold=True)

        self.controller = Controller()
        self.rom_file = None
        self.is_powered_on = False
        
        self.cpu = None
        self.ppu = None
        self.bus = None
        self.cart = None
        
        # UI Rectangles
        self.power_rect = pygame.Rect(532, 50, 200, 40)
        self.reset_rect = pygame.Rect(532, 100, 200, 40)
        self.change_rom_rect = pygame.Rect(532, 150, 200, 40)
        self.chr_toggle_rect = pygame.Rect(532, 200, 200, 40)
        
        self.show_chr = True
        self.frame_count = 0
        self.chr_pixels = bytearray(256 * 256 * 3)
        self.chr_surface = None
        
        self.rom_file = get_rom_path()
        self.boot_system()

    def boot_system(self):
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            self.sound_channel = pygame.mixer.Channel(0)
        except pygame.error as e:
            print(f"Warning: Audio could not be initialized. Error: {e}")
            self.sound_channel = None

        self.cart = Cartridge(self.rom_file)
        self.ppu = PPU(cartridge=self.cart)
        self.bus = Bus(cpu=None, ppu=self.ppu, cartridge=self.cart, controller=self.controller)
        self.cpu = CPU(self.bus)
        
        self.bus.cpu = self.cpu
        self.ppu.cpu = self.cpu
        
        low = self.bus.read(0xFFFC)
        high = self.bus.read(0xFFFD)
        self.cpu.pc = (high << 8) | low
        self.is_powered_on = True

    def reset_system(self):
        if not self.cpu: return
        self.cpu.pc = (self.bus.read(0xFFFD) << 8) | self.bus.read(0xFFFC)
        self.cpu.p |= 0x04 
        self.cpu.st = 0xFD
        self.is_powered_on = True

    def run(self):
        running = True
        # OPTIMIZATION: Cache all hot-loop methods to local variables
        cpu = self.cpu
        ppu = self.ppu
        apu = self.bus.apu
        cpu_step = cpu.step
        ppu_step = ppu.step
        cpu_nmi = cpu.nmi
        cpu_irq = cpu.irq
        apu_step = apu.step if IS_PYPY else None
        apu_get_buf = apu.get_frame_buffer if IS_PYPY else apu.generate_samples
        sound_channel = self.sound_channel
        
        while running:
            self.controller.update_keys()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_p:
                        self.is_powered_on = not self.is_powered_on
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self.power_rect.collidepoint(event.pos):
                        self.is_powered_on = not self.is_powered_on
                    elif self.reset_rect.collidepoint(event.pos):
                        self.reset_system()
                    elif self.change_rom_rect.collidepoint(event.pos) and not self.is_powered_on:
                        new_rom = get_rom_path()
                        if new_rom:
                            self.rom_file = new_rom
                            self.boot_system()
                            # Re-cache after boot
                            cpu = self.cpu; ppu = self.ppu; apu = self.bus.apu
                            cpu_step = cpu.step; ppu_step = ppu.step; cpu_nmi = cpu.nmi; cpu_irq = cpu.irq
                            apu_step = apu.step if IS_PYPY else None
                            apu_get_buf = apu.get_frame_buffer if IS_PYPY else apu.generate_samples
                    elif self.chr_toggle_rect.collidepoint(event.pos):
                        self.show_chr = not self.show_chr

            if self.is_powered_on and cpu and ppu:
                ppu.frame_complete = False
                while not ppu.frame_complete:
                    cycles = cpu_step()
                    ppu_step(cycles * 3)

                    # FIX: Step APU dynamically on PyPy for cycle accuracy
                    if apu_step:
                        apu_step(cycles)

                    if cpu.nmi_pending:
                        cpu.nmi_pending = False
                        cpu_nmi()
                        ppu_step(21)

                    mapper = self.cart.mapper if hasattr(self.cart, 'mapper') else None
                    if mapper and getattr(mapper, 'irq_state', False) and not (cpu.p & 0x04):
                        mapper.irq_state = False
                        cpu_irq()
                        ppu_step(21)

                # PLAY AUDIO
                if sound_channel:
                    try:
                        if IS_PYPY:
                            audio_buffer = apu_get_buf()
                            audio_bytes = bytes(audio_buffer) # PyPy array to bytes
                        else:
                            audio_buffer = apu_get_buf()
                            audio_bytes = audio_buffer.tobytes() # Numpy array to bytes
                            
                        sound = pygame.mixer.Sound(buffer=audio_bytes)
                        if not sound_channel.get_busy():
                            sound_channel.play(sound)
                        elif sound_channel.get_queue() is None:
                            sound_channel.queue(sound)
                    except Exception as e:
                        print(f"Audio playback error: {e}")

            self.draw_ui()
            self.clock.tick(60)

        pygame.quit()
        sys.exit()

    def update_chr_viewer(self):
        if not self.cart: return
        ppu_map_read = self.ppu.ppu_map_read
        chr_rom = self.cart.chr_rom
        chr_pixels = self.chr_pixels
        
        for table in range(2):
            for tile_y in range(16):
                for tile_x in range(16):
                    for row in range(8):
                        addr = (table * 0x1000) + (tile_y * 256) + (tile_x * 16) + row
                        handled, mapped = ppu_map_read(addr)
                        if not handled: continue
                        chr_low = chr_rom[mapped]
                        chr_high = chr_rom[mapped + 8]
                        
                        base_x = table * 128 + tile_x * 8
                        base_y = tile_y * 8 + row
                        
                        for col in range(8):
                            bit = 7 - col
                            color_bit = ((chr_low >> bit) & 1) | (((chr_high >> bit) & 1) << 1)
                            c = 50 * color_bit
                            idx = (base_y * 256 + base_x + col) * 3
                            chr_pixels[idx] = c
                            chr_pixels[idx+1] = c
                            chr_pixels[idx+2] = c
                            
        self.chr_surface = pygame.image.frombuffer(bytes(chr_pixels), (256, 256), "RGB")

    def draw_oscilloscope(self, x_offset, y_center, data, color, label):
        pygame.draw.rect(self.screen, (10, 10, 10), (x_offset, 480, 256, 160))
        pygame.draw.rect(self.screen, (50, 50, 50), (x_offset, 480, 256, 160), 1)
        pygame.draw.line(self.screen, (40, 40, 40), (x_offset, y_center), (x_offset+256, y_center), 1)
        
        label_surf = self.small_font.render(label, True, color)
        self.screen.blit(label_surf, (x_offset + 5, 485))
        
        if len(data) > 1:
            points = []
            for i, val in enumerate(data):
                py = y_center - (val // 100)
                points.append((x_offset + i, py))
            if len(points) > 1:
                pygame.draw.aalines(self.screen, color, False, points)

    def draw_ui(self):
        if self.ppu:
            self.ppu.blit_to_surface()
            scaled = pygame.transform.scale(self.ppu.frame_buffer, (512, 480))
            self.screen.blit(scaled, (0, 0))
        else:
            self.screen.fill((0,0,0), (0,0,512,480))

        pygame.draw.rect(self.screen, (30, 30, 30), (512, 0, 256, 480))
        pygame.draw.line(self.screen, (100, 100, 100), (512, 0), (512, 480), 2)
        
        fps_text = self.font.render(f"FPS: {self.clock.get_fps():.1f}", True, (255, 255, 255))
        self.screen.blit(fps_text, (522, 10))
        
        state_color = (0, 255, 0) if self.is_powered_on else (255, 0, 0)
        state_text = self.font.render("State: ON" if self.is_powered_on else "State: OFF", True, state_color)
        self.screen.blit(state_text, (522, 30))

        mouse_pos = pygame.mouse.get_pos()
        
        power_color = (200, 50, 50) if self.is_powered_on else (50, 200, 50)
        if self.power_rect.collidepoint(mouse_pos): power_color = tuple(min(c+30, 255) for c in power_color)
        pygame.draw.rect(self.screen, power_color, self.power_rect, border_radius=5)
        power_text = self.font.render("POWER OFF" if self.is_powered_on else "POWER ON", True, (0,0,0))
        self.screen.blit(power_text, (power_text.get_rect(center=self.power_rect.center)))

        reset_color = (80, 80, 80)
        if self.reset_rect.collidepoint(mouse_pos): reset_color = (110, 110, 110)
        pygame.draw.rect(self.screen, reset_color, self.reset_rect, border_radius=5)
        reset_text = self.font.render("RESET", True, (255, 255, 255))
        self.screen.blit(reset_text, (reset_text.get_rect(center=self.reset_rect.center)))

        rom_color = (80, 80, 80) if not self.is_powered_on else (40, 40, 40)
        if self.change_rom_rect.collidepoint(mouse_pos) and not self.is_powered_on: rom_color = (110, 110, 110)
        pygame.draw.rect(self.screen, rom_color, self.change_rom_rect, border_radius=5)
        rom_text_color = (255, 255, 255) if not self.is_powered_on else (100,100,100)
        rom_text = self.font.render("CHANGE ROM", True, rom_text_color)
        self.screen.blit(rom_text, (rom_text.get_rect(center=self.change_rom_rect.center)))

        chr_color = (50, 100, 150) if self.show_chr else (50, 50, 50)
        if self.chr_toggle_rect.collidepoint(mouse_pos): chr_color = tuple(min(c+30, 255) for c in chr_color)
        pygame.draw.rect(self.screen, chr_color, self.chr_toggle_rect, border_radius=5)
        chr_text = self.font.render("HIDE CHR" if self.show_chr else "SHOW CHR", True, (255, 255, 255))
        self.screen.blit(chr_text, (chr_text.get_rect(center=self.chr_toggle_rect.center)))

        keys_label = self.font.render("Input:", True, (255, 255, 255))
        self.screen.blit(keys_label, (522, 260))
        
        if self.controller:
            btns = []
            if self.controller.button_states & 0x01: btns.append("A")
            if self.controller.button_states & 0x02: btns.append("B")
            if self.controller.button_states & 0x04: btns.append("SELECT")
            if self.controller.button_states & 0x08: btns.append("START")
            if self.controller.button_states & 0x10: btns.append("UP")
            if self.controller.button_states & 0x20: btns.append("DOWN")
            if self.controller.button_states & 0x40: btns.append("LEFT")
            if self.controller.button_states & 0x80: btns.append("RIGHT")
            
            held = ", ".join(btns) if btns else "None"
            held_text = self.small_font.render(held, True, (0, 255, 255))
            self.screen.blit(held_text, (522, 285))

        pygame.draw.rect(self.screen, (0, 0, 0), (768, 0, 256, 480))
        pygame.draw.line(self.screen, (100, 100, 100), (768, 0), (768, 480), 2)
        
        if self.show_chr and self.cart:
            self.frame_count += 1
            if self.frame_count % 5 == 0 or self.chr_surface is None:
                self.update_chr_viewer()
            
            if self.chr_surface:
                self.screen.blit(self.chr_surface, (768, 100))
                
            chr_label = self.small_font.render("Pattern Tables (CHR ROM)", True, (255, 255, 255))
            self.screen.blit(chr_label, (775, 80))

        self.draw_oscilloscope(0, 560, self.bus.apu.osc_p1, (0, 255, 255), "Pulse 1")
        self.draw_oscilloscope(256, 560, self.bus.apu.osc_p2, (255, 0, 255), "Pulse 2")
        self.draw_oscilloscope(512, 560, self.bus.apu.osc_tri, (0, 255, 0), "Triangle")
        self.draw_oscilloscope(768, 560, self.bus.apu.osc_noise, (255, 255, 0), "Noise")

        pygame.display.flip()

if __name__ == "__main__":
    app = EmulatorApp()
    app.run()