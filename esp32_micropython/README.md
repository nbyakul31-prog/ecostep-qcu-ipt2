# ESP32 MicroPython Workspace (COM10)

Board detected: `ESP32-D0WD-V3` (4MB Flash, `USB-SERIAL CH340 (COM10)`).
Firmware flashed: **MicroPython `v1.29.0`** (`ESP32_GENERIC-20260824-v1.29.0.bin`).

## Quick Commands (Antigravity Terminal: `` Ctrl + ` ``)

> **Why `sleep 1.5`?** On Windows, CH340 USB-serial chips briefly reset the ESP32 when `COM10` opens. Waiting `1.5s` lets MicroPython finish booting to `>>>` before `mpremote` sends code.

### 1. Run `main.py` live without saving it to flash (fastest for testing)
```powershell
mpremote connect COM10 sleep 1.5 run esp32_micropython\main.py
```
*(Or press **`Ctrl + Shift + B`** inside Antigravity IDE to run the active Python file on `COM10` via `.vscode/tasks.json`.)*

### 2. Upload `boot.py` & `main.py` so it runs automatically every time the ESP32 boots
```powershell
mpremote connect COM10 sleep 1.5 cp esp32_micropython\boot.py :boot.py + cp esp32_micropython\main.py :main.py + reset
```

### 3. Open interactive MicroPython REPL (`Ctrl + X` to exit)
```powershell
mpremote connect COM10 repl
```

### 4. List or delete files stored on the ESP32
```powershell
mpremote connect COM10 sleep 1.5 ls
mpremote connect COM10 sleep 1.5 rm :main.py
```

> **Tip:** Only one program can hold `COM10` at a time. Exit `mpremote repl` (`Ctrl + X`) before running another `mpremote` command.
