import platform
import numpy as np
import array
import collections

IS_PYPY = platform.python_implementation() == 'PyPy'

if IS_PYPY:
    # =====================================================================
    # PURE PYTHON CYCLE-ACCURATE APU (Optimized for PyPy JIT)
    # =====================================================================
    class APU:
        def __init__(self):
            self.sample_rate = 44100
            self.buffer_size = 735
            self.sample_buffer = array.array('h', [0] * self.buffer_size)
            self.buf_idx = 0
            
            self.sample_timer = 40.5844 # CPU cycles per audio sample (1789773 / 44100)
            self.frame_timer = 7457.3875 # CPU cycles per 1/4 APU frame (1789773 / 240)
            
            self.length_table = [
                10,254,20, 2,40, 4,80, 6,160, 8,60,10,14,12,26,14,
                12, 16,24,18,48,20,96,22,192,24,72,26,16,28,32,30,
                80, 32,160,34,64,36,128,38,24,40,48,42,96,44,192,46,
                72, 48,144,50,96,52,240,54,160,56,32,58,64,60,28,62
            ]
            
            self.noise_periods = [4, 8, 16, 32, 64, 96, 128, 160, 202, 254, 380, 508, 762, 1016, 2034, 4068]
            
            self.tri_wave = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
            self.tri_wave = [int(v * 546) for v in self.tri_wave]
            
            self.p1_timer_reg = 0; self.p1_timer = 0; self.p1_length = 0; self.p1_duty = 1
            self.p1_phase = 0; self.p1_timer_counter = 0; self.p1_enabled = False
            self.p1_env_active = False; self.p1_env_counter = 0; self.p1_env_divider = 0; self.p1_env_decay = 0
            self.p1_halt = False; self.p1_volume = 0
            self.p1_sweep_enabled = False; self.p1_sweep_period = 0; self.p1_sweep_negate = False; self.p1_sweep_shift = 0
            self.p1_sweep_counter = 0; self.p1_sweep_reload = False; self.p1_sweep_mute = False
            
            self.p2_timer_reg = 0; self.p2_timer = 0; self.p2_length = 0; self.p2_duty = 1
            self.p2_phase = 0; self.p2_timer_counter = 0; self.p2_enabled = False
            self.p2_env_active = False; self.p2_env_counter = 0; self.p2_env_divider = 0; self.p2_env_decay = 0
            self.p2_halt = False; self.p2_volume = 0
            self.p2_sweep_enabled = False; self.p2_sweep_period = 0; self.p2_sweep_negate = False; self.p2_sweep_shift = 0
            self.p2_sweep_counter = 0; self.p2_sweep_reload = False; self.p2_sweep_mute = False
            
            self.tri_timer = 0; self.tri_length = 0; self.tri_phase = 0; self.tri_timer_counter = 0
            self.tri_enabled = False; self.tri_halt = False; self.tri_linear_counter = 0; self.tri_linear_reload = 0
            self.tri_linear_reload_flag = False
            
            self.noise_timer_reg = 0; self.noise_length = 0; self.noise_lfsr = 1; self.noise_timer_counter = 0
            self.noise_enabled = False; self.noise_env_active = False; self.noise_env_counter = 0
            self.noise_env_divider = 0; self.noise_env_decay = 0; self.noise_halt = False; self.noise_volume = 0
            
            self.frame_step = 0; self.frame_counter_mode = 0; self.frame_irq_inhibit = False
            self.noise_lp = 0
            
            # FIX: Oscilloscope history buffers
            self.osc_p1 = collections.deque([0]*256, maxlen=256)
            self.osc_p2 = collections.deque([0]*256, maxlen=256)
            self.osc_tri = collections.deque([0]*256, maxlen=256)
            self.osc_noise = collections.deque([0]*256, maxlen=256)

        def write_register(self, addr, val):
            val &= 0xFF
            if addr == 0x4000:
                self.p1_duty = (val >> 6) & 0x03; self.p1_halt = bool(val & 0x20)
                self.p1_env_active = not (val & 0x10); self.p1_volume = val & 0x0F; self.p1_env_decay = val & 0x0F
            elif addr == 0x4001:
                self.p1_sweep_enabled = bool(val & 0x80); self.p1_sweep_period = (val >> 4) & 0x07
                self.p1_sweep_negate = bool(val & 0x08); self.p1_sweep_shift = val & 0x07; self.p1_sweep_reload = True
            elif addr == 0x4002: self.p1_timer_reg = (self.p1_timer_reg & 0x0700) | val; self.p1_timer = self.p1_timer_reg
            elif addr == 0x4003:
                self.p1_timer_reg = (self.p1_timer_reg & 0x00FF) | ((val & 0x07) << 8); self.p1_timer = self.p1_timer_reg
                if not self.p1_halt: self.p1_length = self.length_table[(val >> 3) & 0x1F]
                self.p1_env_counter = 15; self.p1_env_divider = self.p1_env_decay
            elif addr == 0x4004:
                self.p2_duty = (val >> 6) & 0x03; self.p2_halt = bool(val & 0x20)
                self.p2_env_active = not (val & 0x10); self.p2_volume = val & 0x0F; self.p2_env_decay = val & 0x0F
            elif addr == 0x4005:
                self.p2_sweep_enabled = bool(val & 0x80); self.p2_sweep_period = (val >> 4) & 0x07
                self.p2_sweep_negate = bool(val & 0x08); self.p2_sweep_shift = val & 0x07; self.p2_sweep_reload = True
            elif addr == 0x4006: self.p2_timer_reg = (self.p2_timer_reg & 0x0700) | val; self.p2_timer = self.p2_timer_reg
            elif addr == 0x4007:
                self.p2_timer_reg = (self.p2_timer_reg & 0x00FF) | ((val & 0x07) << 8); self.p2_timer = self.p2_timer_reg
                if not self.p2_halt: self.p2_length = self.length_table[(val >> 3) & 0x1F]
                self.p2_env_counter = 15; self.p2_env_divider = self.p2_env_decay
            elif addr == 0x4008: self.tri_halt = bool(val & 0x80); self.tri_linear_reload = val & 0x7F
            elif addr == 0x400A: self.tri_timer = (self.tri_timer & 0x0700) | val
            elif addr == 0x400B:
                self.tri_timer = (self.tri_timer & 0x00FF) | ((val & 0x07) << 8)
                if not self.tri_halt: self.tri_length = self.length_table[(val >> 3) & 0x1F]
                self.tri_linear_reload_flag = True
            elif addr == 0x400C:
                self.noise_halt = bool(val & 0x20); self.noise_env_active = not (val & 0x10)
                self.noise_volume = val & 0x0F; self.noise_env_decay = val & 0x0F
            elif addr == 0x400E: self.noise_timer_reg = val & 0x0F
            elif addr == 0x400F:
                if not self.noise_halt: self.noise_length = self.length_table[(val >> 3) & 0x1F]
                self.noise_env_counter = 15; self.noise_env_divider = self.noise_env_decay
            elif addr == 0x4015:
                self.p1_enabled = bool(val & 0x01); self.p2_enabled = bool(val & 0x02)
                self.tri_enabled = bool(val & 0x04); self.noise_enabled = bool(val & 0x08)
                if not self.p1_enabled: self.p1_length = 0
                if not self.p2_enabled: self.p2_length = 0
                if not self.tri_enabled: self.tri_length = 0
                if not self.noise_enabled: self.noise_length = 0
            elif addr == 0x4017:
                self.frame_counter_mode = bool(val & 0x80); self.frame_irq_inhibit = bool(val & 0x40)
                if self.frame_counter_mode:
                    self.clock_quarter_frame(); self.clock_half_frame()
                self.frame_step = 0; self.frame_timer = 7457.3875

        def read_status(self, addr): return 0x0F

        def clock_quarter_frame(self):
            if self.p1_env_active:
                if self.p1_env_divider == 0: self.p1_env_divider = self.p1_env_decay; self.p1_env_counter = (self.p1_env_counter - 1) & 0x0F if self.p1_env_counter > 0 or self.p1_halt else 0
                else: self.p1_env_divider -= 1
            if self.p2_env_active:
                if self.p2_env_divider == 0: self.p2_env_divider = self.p2_env_decay; self.p2_env_counter = (self.p2_env_counter - 1) & 0x0F if self.p2_env_counter > 0 or self.p2_halt else 0
                else: self.p2_env_divider -= 1
            if self.noise_env_active:
                if self.noise_env_divider == 0: self.noise_env_divider = self.noise_env_decay; self.noise_env_counter = (self.noise_env_counter - 1) & 0x0F if self.noise_env_counter > 0 or self.noise_halt else 0
                else: self.noise_env_divider -= 1
            
            if self.tri_linear_reload_flag: self.tri_linear_counter = self.tri_linear_reload
            elif self.tri_linear_counter > 0: self.tri_linear_counter -= 1
            if not self.tri_halt: self.tri_linear_reload_flag = False

        def clock_half_frame(self):
            if not self.p1_halt and self.p1_length > 0: self.p1_length -= 1
            if not self.p2_halt and self.p2_length > 0: self.p2_length -= 1
            if not self.tri_halt and self.tri_length > 0: self.tri_length -= 1
            if not self.noise_halt and self.noise_length > 0: self.noise_length -= 1
            
            self.clock_sweep(1)
            self.clock_sweep(2)

        def clock_sweep(self, ch):
            if ch == 1:
                enabled, period, negate, shift, counter, reload, timer, mute = self.p1_sweep_enabled, self.p1_sweep_period, self.p1_sweep_negate, self.p1_sweep_shift, self.p1_sweep_counter, self.p1_sweep_reload, self.p1_timer, self.p1_sweep_mute
            else:
                enabled, period, negate, shift, counter, reload, timer, mute = self.p2_sweep_enabled, self.p2_sweep_period, self.p2_sweep_negate, self.p2_sweep_shift, self.p2_sweep_counter, self.p2_sweep_reload, self.p2_timer, self.p2_sweep_mute
                
            if reload:
                counter = period; reload = False
            elif counter > 0:
                counter -= 1
                
            if counter == 0:
                counter = period
                if enabled and shift > 0:
                    delta = timer >> shift
                    if negate: delta = -delta - 1 if ch == 1 else -delta
                    target = timer + delta
                    if target < 8 or target > 2047: mute = True
                    else: timer = target; mute = False
                        
            if ch == 1:
                self.p1_sweep_counter = counter; self.p1_sweep_reload = reload; self.p1_timer = timer; self.p1_sweep_mute = mute
            else:
                self.p2_sweep_counter = counter; self.p2_sweep_reload = reload; self.p2_timer = timer; self.p2_sweep_mute = mute

        def clock_timers(self, cpu_cycles):
            period = (self.p1_timer + 1) * 2
            self.p1_timer_counter -= cpu_cycles
            while self.p1_timer_counter <= 0:
                self.p1_timer_counter += period; self.p1_phase = (self.p1_phase + 1) & 7
                
            period = (self.p2_timer + 1) * 2
            self.p2_timer_counter -= cpu_cycles
            while self.p2_timer_counter <= 0:
                self.p2_timer_counter += period; self.p2_phase = (self.p2_phase + 1) & 7
                
            period = self.tri_timer + 1
            self.tri_timer_counter -= cpu_cycles
            while self.tri_timer_counter <= 0:
                self.tri_timer_counter += period; self.tri_phase = (self.tri_phase + 1) & 31
                
            period = self.noise_periods[self.noise_timer_reg & 0x0F]
            self.noise_timer_counter -= cpu_cycles
            while self.noise_timer_counter <= 0:
                self.noise_timer_counter += period
                bit = ((self.noise_lfsr >> 14) ^ (self.noise_lfsr >> 8)) & 1
                self.noise_lfsr = (self.noise_lfsr >> 1) | (bit << 14)

        def step(self, cpu_cycles):
            self.frame_timer -= cpu_cycles
            while self.frame_timer <= 0:
                self.frame_timer += 7457.3875
                self.frame_step += 1
                if self.frame_counter_mode == 0:
                    if self.frame_step == 1: self.clock_quarter_frame()
                    elif self.frame_step == 2: self.clock_quarter_frame(); self.clock_half_frame()
                    elif self.frame_step == 3: self.clock_quarter_frame()
                    elif self.frame_step == 4: self.clock_quarter_frame(); self.clock_half_frame(); self.frame_step = 0
                else:
                    if self.frame_step == 1: self.clock_quarter_frame()
                    elif self.frame_step == 2: self.clock_quarter_frame(); self.clock_half_frame()
                    elif self.frame_step == 3: self.clock_quarter_frame()
                    elif self.frame_step == 4: self.clock_quarter_frame(); self.clock_half_frame()
                    elif self.frame_step == 5: self.frame_step = 0
                
            self.clock_timers(cpu_cycles)
            
            self.sample_timer -= cpu_cycles
            while self.sample_timer <= 0:
                self.sample_timer += 40.5844
                self.generate_one_sample()

        def generate_one_sample(self):
            if self.buf_idx >= self.buffer_size: return
            val_p1 = 0
            if self.p1_enabled and self.p1_length > 0 and not self.p1_sweep_mute and self.p1_timer >= 8:
                if self.p1_phase < [1, 2, 4, 6][self.p1_duty]:
                    vol = self.p1_env_counter if self.p1_env_active else self.p1_volume
                    val_p1 = vol * 546
                    
            val_p2 = 0
            if self.p2_enabled and self.p2_length > 0 and not self.p2_sweep_mute and self.p2_timer >= 8:
                if self.p2_phase < [1, 2, 4, 6][self.p2_duty]:
                    vol = self.p2_env_counter if self.p2_env_active else self.p2_volume
                    val_p2 = vol * 546
                    
            val_tri = 0
            if self.tri_enabled and self.tri_length > 0 and self.tri_linear_counter > 0:
                val_tri = self.tri_wave[self.tri_phase]
                
            val_noise = 0
            if self.noise_enabled and self.noise_length > 0:
                vol = self.noise_env_counter if self.noise_env_active else self.noise_volume
                target = vol * 546 if (self.noise_lfsr & 1) else 0
                self.noise_lp += (target - self.noise_lp) >> 2
                val_noise = self.noise_lp
                    
            sample = val_p1 + val_p2 + val_tri + val_noise
            self.sample_buffer[self.buf_idx] = max(-32767, min(32767, sample))
            self.buf_idx += 1
            
            # Update Oscilloscope history
            self.osc_p1.append(val_p1)
            self.osc_p2.append(val_p2)
            self.osc_tri.append(val_tri)
            self.osc_noise.append(val_noise)

        def get_frame_buffer(self):
            for i in range(self.buf_idx, self.buffer_size): self.sample_buffer[i] = 0
            self.buf_idx = 0
            return self.sample_buffer

else:
    # =====================================================================
    # NUMPY VECTORIZED APU (Optimized for CPython)
    # =====================================================================
    class APU:
        def __init__(self):
            self.sample_rate = 44100
            self.buffer_size = 735 

            self.lfsr = np.zeros(32767, dtype=np.float32)
            reg = 1
            for i in range(32767):
                self.lfsr[i] = (reg & 1) * 2.0 - 1.0
                bit = ((reg >> 14) ^ (reg >> 8)) & 1
                reg = (reg >> 1) | (bit << 14)
            self.noise_lfsr_pos = 0

            self.length_table = [
                10,254,20, 2,40, 4,80, 6,160, 8,60,10,14,12,26,14,
                12, 16,24,18,48,20,96,22,192,24,72,26,16,28,32,30,
                80, 32,160,34,64,36,128,38,24,40,48,42,96,44,192,46,
                72, 48,144,50,96,52,240,54,160,56,32,58,64,60,28,62
            ]
            
            self.noise_periods = [4, 8, 16, 32, 64, 96, 128, 160, 202, 254, 380, 508, 762, 1016, 2034, 4068]

            self.p1_timer = 0; self.p1_length = 0; self.p1_volume = 0; self.p1_duty = 1
            self.p1_env_active = False; self.p1_env_counter = 0; self.p1_env_decay = 0; self.p1_halt = False
            self.p1_phase = 0.0
            
            self.p2_timer = 0; self.p2_length = 0; self.p2_volume = 0; self.p2_duty = 1
            self.p2_env_active = False; self.p2_env_counter = 0; self.p2_env_decay = 0; self.p2_halt = False
            self.p2_phase = 0.0

            self.tri_timer = 0; self.tri_length = 0; self.tri_halt = False; self.tri_phase = 0.0

            self.noise_timer = 0; self.noise_length = 0; self.noise_volume = 0
            self.noise_env_active = False; self.noise_env_counter = 0; self.noise_env_decay = 0; self.noise_halt = False

            self.p1_enabled = False; self.p2_enabled = False; self.tri_enabled = False; self.noise_enabled = False
            
            # FIX: Oscilloscope history buffers
            self.osc_p1 = collections.deque([0]*256, maxlen=256)
            self.osc_p2 = collections.deque([0]*256, maxlen=256)
            self.osc_tri = collections.deque([0]*256, maxlen=256)
            self.osc_noise = collections.deque([0]*256, maxlen=256)

        def write_register(self, addr, val):
            val &= 0xFF
            if addr == 0x4000:
                self.p1_duty = (val >> 6) & 0x03; self.p1_halt = bool(val & 0x20)
                self.p1_env_active = not (val & 0x10); self.p1_volume = val & 0x0F; self.p1_env_decay = val & 0x0F
            elif addr == 0x4002: self.p1_timer = (self.p1_timer & 0x0700) | val
            elif addr == 0x4003:
                self.p1_timer = (self.p1_timer & 0x00FF) | ((val & 0x07) << 8)
                if not self.p1_halt: self.p1_length = self.length_table[(val >> 3) & 0x1F]
                self.p1_env_counter = 15
            elif addr == 0x4004:
                self.p2_duty = (val >> 6) & 0x03; self.p2_halt = bool(val & 0x20)
                self.p2_env_active = not (val & 0x10); self.p2_volume = val & 0x0F; self.p2_env_decay = val & 0x0F
            elif addr == 0x4006: self.p2_timer = (self.p2_timer & 0x0700) | val
            elif addr == 0x4007:
                self.p2_timer = (self.p2_timer & 0x00FF) | ((val & 0x07) << 8)
                if not self.p2_halt: self.p2_length = self.length_table[(val >> 3) & 0x1F]
                self.p2_env_counter = 15
            elif addr == 0x4008: self.tri_halt = bool(val & 0x80)
            elif addr == 0x400A: self.tri_timer = (self.tri_timer & 0x0700) | val
            elif addr == 0x400B:
                self.tri_timer = (self.tri_timer & 0x00FF) | ((val & 0x07) << 8)
                if not self.tri_halt: self.tri_length = self.length_table[(val >> 3) & 0x1F]
            elif addr == 0x400C:
                self.noise_halt = bool(val & 0x20); self.noise_env_active = not (val & 0x10)
                self.noise_volume = val & 0x0F; self.noise_env_decay = val & 0x0F
            elif addr == 0x400E: self.noise_timer = val & 0x0F
            elif addr == 0x400F:
                if not self.noise_halt: self.noise_length = self.length_table[(val >> 3) & 0x1F]
                self.noise_env_counter = 15
            elif addr == 0x4015:
                self.p1_enabled = bool(val & 0x01); self.p2_enabled = bool(val & 0x02)
                self.tri_enabled = bool(val & 0x04); self.noise_enabled = bool(val & 0x08)
                if not self.p1_enabled: self.p1_length = 0
                if not self.p2_enabled: self.p2_length = 0
                if not self.tri_enabled: self.tri_length = 0
                if not self.noise_enabled: self.noise_length = 0

        def read_status(self, addr): return 0x0F

        def clock_quarter_frame(self):
            if self.p1_env_active:
                if self.p1_env_counter > 0: self.p1_env_counter -= 1
                elif self.p1_halt: self.p1_env_counter = 15
            if self.p2_env_active:
                if self.p2_env_counter > 0: self.p2_env_counter -= 1
                elif self.p2_halt: self.p2_env_counter = 15
            if self.noise_env_active:
                if self.noise_env_counter > 0: self.noise_env_counter -= 1
                elif self.noise_halt: self.noise_env_counter = 15

        def clock_half_frame(self):
            if not self.p1_halt and self.p1_length > 0: self.p1_length -= 1
            if not self.p2_halt and self.p2_length > 0: self.p2_length -= 1
            if not self.tri_halt and self.tri_length > 0: self.tri_length -= 1
            if not self.noise_halt and self.noise_length > 0: self.noise_length -= 1

        def generate_samples(self):
            self.clock_quarter_frame(); self.clock_half_frame()
            self.clock_quarter_frame(); self.clock_half_frame()
            self.clock_quarter_frame()
            self.clock_quarter_frame(); self.clock_half_frame()
            
            t = np.arange(self.buffer_size) / self.sample_rate
            
            p1_arr = np.zeros(self.buffer_size, dtype=np.float32)
            p2_arr = np.zeros(self.buffer_size, dtype=np.float32)
            tri_arr = np.zeros(self.buffer_size, dtype=np.float32)
            noise_arr = np.zeros(self.buffer_size, dtype=np.float32)

            if self.p1_enabled and self.p1_timer > 0 and self.p1_length > 0:
                freq = 1789773.0 / (16 * (self.p1_timer + 1))
                if freq > 20:
                    phases = self.p1_phase + (t * freq); self.p1_phase = phases[-1] % 1.0
                    wave = (phases % 1.0) < [0.125, 0.25, 0.5, 0.75][self.p1_duty]
                    vol = (self.p1_env_counter if self.p1_env_active else self.p1_volume) / 15.0
                    p1_arr = wave.astype(np.float32) * vol * 546.0

            if self.p2_enabled and self.p2_timer > 0 and self.p2_length > 0:
                freq = 1789773.0 / (16 * (self.p2_timer + 1))
                if freq > 20:
                    phases = self.p2_phase + (t * freq); self.p2_phase = phases[-1] % 1.0
                    wave = (phases % 1.0) < [0.125, 0.25, 0.5, 0.75][self.p2_duty]
                    vol = (self.p2_env_counter if self.p2_env_active else self.p2_volume) / 15.0
                    p2_arr = wave.astype(np.float32) * vol * 546.0

            if self.tri_enabled and self.tri_timer > 0 and self.tri_length > 0:
                freq = 1789773.0 / (32 * (self.tri_timer + 1))
                if freq > 20:
                    phases = self.tri_phase + (t * freq); self.tri_phase = phases[-1] % 1.0
                    wave = 2 * np.abs(2 * ((phases) % 1.0) - 1) - 1
                    tri_arr = wave.astype(np.float32) * 0.25 * 32767

            if self.noise_enabled and self.noise_timer > 0 and self.noise_length > 0:
                period = self.noise_periods[self.noise_timer & 0x0F]
                freq = 1789773.0 / (8 * period) if period > 0 else 0
                if freq > 20:
                    samples_per_cycle = max(1, int(self.sample_rate / freq))
                    chunk = self.lfsr[self.noise_lfsr_pos : self.noise_lfsr_pos + samples_per_cycle]
                    wave = np.resize(chunk, self.buffer_size)
                    self.noise_lfsr_pos = (self.noise_lfsr_pos + samples_per_cycle) % 32767
                    vol = (self.noise_env_counter if self.noise_env_active else self.noise_volume) / 15.0
                    noise_arr = wave * vol * 546.0

            buffer = p1_arr + p2_arr + tri_arr + noise_arr
            buffer = np.clip(buffer, -32767, 32767)
            
            # Update Oscilloscope history
            self.osc_p1.extend(p1_arr.tolist())
            self.osc_p2.extend(p2_arr.tolist())
            self.osc_tri.extend(tri_arr.tolist())
            self.osc_noise.extend(noise_arr.tolist())
            
            return buffer.astype(np.int16)