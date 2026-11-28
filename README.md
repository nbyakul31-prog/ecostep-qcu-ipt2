# EcoStep QCU — Footstep Energy Telemetry & Monitoring System (IPT2)

A standalone **Python + CustomTkinter** desktop telemetry and energy analytics application paired with an **ESP32 MicroPython** sensor node and a local **PostgreSQL** 3NF relational database, developed for **IPT2 (Integrative Programming and Technologies 2)** at **Quezon City University (QCU – San Bartolome Campus)**.

---

## Architecture Overview

1. **ESP32-WROOM-32 MicroPython Node (`esp32_micropython/`):**
   - Streams comma-separated 10-bit ADC telemetry at `115,200` baud (`8-N-1`) over USB-C:
     `DATA,<step_number>,<adc_raw_0_to_1023>,<adc_voltage>`
   - Supports **Bench Safe Mode** (`BOOT` button / `'S'` serial command) for bare-board testing and **Tile Sensor Mode** (`D34` trigger, `D35` `V_gen`, `D32` `V_cap`, `D19` PWM, `D2` LED).
2. **CustomTkinter Desktop Application (`ecostep_app/`):**
   - **Direct Open-Access Workflow** (no login barriers) with **Eco Light** & **Forest Dark** themes.
   - **Live Telemetry:** Real-time animated `0–15 V` Kinetic Meter, 4×4 PZT Eco-Mat pulse indicator, live waveform, and `1H / 10H / 24H / 48H / 7D` horizon charts.
   - **Time & Equivalences:** Period counters, walking cadence (`steps/min`), Battery `SoC %`, USB/12V load simulation, and Device Equivalence Calculator.
   - **100-Step Benchmark Runs (`measurement_runs`):** Full CRUD + soft-delete (`is_deleted`), `mWh → Joules (× 3.6)` and `J/step` calculations, CSV export.
   - **5V Sign Load Tests (`sign_tests`):** Full (`1.5 kΩ`) vs. Dim (`10 kΩ`) verification (`P = 5V × I_load`).
   - **Asset Inventory (`components`):** Hardware specs & inspection tracking (no volatile pricing).
3. **PostgreSQL 3NF Database (`ecostep_app/schema.sql`):**
   - 4 normalized tables: `components`, `measurement_runs`, `telemetry_logs`, and `sign_tests`.
4. **Hardware Blueprint:**
   - Open [ecostep_complete_wiring.html](ecostep_complete_wiring.html) or [ecostep_complete_circuit.svg](ecostep_complete_circuit.svg) for the full Tile → Breadboard → `"I ❤️ QCU!"` 18-LED Sign → ESP32 → PC wiring schematic.

---

## Setup on a Windows PC / Laptop

### 1. Prerequisites
- **Python 3.12+**
- **PostgreSQL 16 or 18** running locally (`localhost:5432`)
- **CH340 USB-UART driver** (if Windows Device Manager doesn't assign a `COMx` port automatically)

### 2. Install Python Dependencies
```powershell
pip install -r requirements.txt
```

### 3. Flash MicroPython Firmware to the ESP32 (Once per Board)
```powershell
pip install esptool mpremote
esptool --port COM10 erase-flash
esptool --port COM10 --baud 460800 write-flash -z 0x1000 ESP32_GENERIC.bin
mpremote connect COM10 sleep 1.5 cp esp32_micropython\boot.py :boot.py + cp esp32_micropython\main.py :main.py + reset
```

### 4. Launch the Desktop App
```powershell
python -m ecostep_app.app
```
On first launch, enter your local PostgreSQL credentials in the **DB Connection Setup** dialog (it automatically creates `ecostep_qcu_db`, applies `schema.sql`, and seeds default components). Select your ESP32 `COM` port in the sidebar and click **Connect Telemetry**.

### 5. Connect to the SIA101 Web Dashboard (Render / Flask XML Bridge)
1. Click **Setup** inside the sidebar's **SIA WEB BRIDGE (XML)** card (or copy `.env.example` to `.env`).
2. Enter your deployed SIA web app URL (e.g. `https://<your-app>.onrender.com`) and your `EQC_API_KEY`.
3. Click **Test Connection** to verify reachability and API key auth, then click **Save & Sync Now**.
4. All benchmark runs, live ESP32/Quick-Step batches, 5V sign tests, and component inspections save locally in PostgreSQL first and sync automatically in the background as XSD-validated XML (stripping `operator_name` for privacy). If Wi-Fi drops, unsynced rows stay safely queued and retry automatically.
