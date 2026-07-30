PYemu 🎮
========

A Python-based emulator project aiming to bring classic console emulation to modern machines, starting with the **Nintendo Entertainment System (NES)** and expanding towards the **Super Nintendo Entertainment System (SNES)**.

Written entirely from scratch in Python, PYemu is optimized to run at full speed (60 FPS) when using **PyPy**.

✨ Current Features (NES)
------------------------

*   **Cycle-Accurate 6502 CPU:** Full opcode support(for OFFICIAL instructions), cycle counting, and NMI/IRQ handling.
    
*   **Custom PPU:** Supports background rendering, 64 sprites, 8x16 sprites, horizontal/vertical scrolling, and dynamic CHR bank switching.
    
*   **Frame-Accurate APU:** Emulates Pulse 1, Pulse 2, Triangle, and Noise channels with authentic hardware envelopes and LFSR noise generation.
    
*   **Built-in GUI:** A custom Pygame interface featuring:
    
    *   Live FPS counter and power/reset buttons.
        
    *   A **CHR ROM Viewer** to see pattern tables in real-time.
        
    *   An **APU Oscilloscope** to visualize the live audio waveforms of each channel.
        
*   **Native File Picker:** Automatically prompts you to select a .nes ROM file without needing hardcoded paths.
    

🗺️ Supported NES Mappers
-------------------------

*   **Mapper 0 (NROM):** Fully supported. (e.g., _Super Mario Bros._, _Donkey Kong_)
    
*   **Mapper 1 (MMC1):** Fully supported. (e.g., _Mega Man 2_, _The Legend of Zelda_)
    
*   **Mapper 2 (UxROM):** Almost fully supported with bus conflict emulation. (e.g., _Mega Man_, _Castlevania_)
    
*   **Mapper 3 (CNROM):** Limited support, graphical glitches.
    
*   **Mapper 4 (MMC3):** Almost fully supported. _Super Mario Bros. 3_ is supported fully, while the other titles may experience graphical glitches

*  **Mapper 66** it runs?
    

🚀 SNES Expansion (Roadmap)
---------------------------

PYemu is currently expanding to support 16-bit SNES emulation! The foundational architecture is being built out:

*   **65C816 CPU Core:** Dynamic 8-bit/16-bit register sizing, 24-bit memory banking, and Native/Emulation mode switching are implemented.
    
*   **SNES Bus:** LoROM and HiROM memory mapping layouts are in development.
    

🕹️ Controls
------------

NES ButtonKeyboard KeyUp, Down, Left, RightArrow KeysAZBXStartEnter / ReturnSelectRight ShiftPause EmulatorP

💻 Installation & Usage
-----------------------

### Prerequisites

*   Python 3.8+ (PyPy 3.10+ highly recommended for 60 FPS performance)
    
*   pygame and numpy
    

### Running

1.  git clone https://github.com/LEGASEGA/PYemu.gitcd PYemu
    
2.  bashpip install pygame numpy
    
3.  bashpypy3 main.py_(Or_ _**python main.py**__, though performance will be lower)_A file picker will automatically open prompting you to select your **.nes** ROM.
    

🤝 Contributing
---------------

Contributions, bug reports, and feature requests are welcome! If you want to help implement more NES mappers, improve the NES PPU, or optimize the code, please feel free to open a Pull Request.

📜 License
----------

Copyright (c) 2026 LEGASEGA.

This project is licensed under the **PolyForm Noncommercial License 1.0.0**.You may view, modify, and contribute to this project, but you **may not** use it for any commercial purpose. See the [LICENSE](https://chat.z.ai/c/LICENSE) file for full details.

## Development & Acknowledgments
This project was built to explore and understand NES architecture (6502 CPU execution, PPU rendering, and memory mapping). 
- **Tooling:** Development was assisted by GLM to help generate opcode lookup tables, boilerplate logic, and assist in debugging complex timing/hardware quirks.
- **Architecture & Integration:** Designed, tested, and assembled in Python by LEGASEGA.
