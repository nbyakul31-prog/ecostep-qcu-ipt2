# EcoStep — Wire & Hardware Requirements Log

> **Trigger Phrase:** When the user says **"Read the wire requirements"**, read this file in full before modifying hardware wiring notes or `esp32_micropython/main.py`.
>
> **Status:** Hardware verification paused pending hardware specialist classmate. Do **not** touch physical tile wiring or flash V2 pin changes until confirmed.

---

## 1. Current Physical Prototype Inventory (Observed from Photos & User Report)

- **Microcontroller:** 30-pin ESP32-WROOM-32 DevKit (`ESP32-D0WD-V3`, USB-C, hot-glued inside clear `"1/4W 1% Resistor Kit"` organizer box on top of tile).
  - Top-side header holes (`3V3..D23`, `VIN..EN`) are currently open/unpopulated.
  - Yellow wires are soldered to the **underside** pads inside hot glue:
    1. **Yellow wire #1 (`D32`)** — currently **unconnected / open** at the free end.
    2. **Yellow wire #2 (`GND`)** — currently **unconnected / open** at the free end.
    3. **Yellow wire #3 (`D34`)** — connected into the resistor divider cluster + supercapacitor node.
    4. **Yellow wire #4 (`GND`)** — connected to the resistor divider cluster + one side of the supercapacitor.
- **Energy Storage Capacitor Installed:** `KAMCAP 5.5V 1.0F` supercapacitor (glued in upper box compartment).
- **Spare Capacitor On Hand (Not Installed):** `470 µF 50V` electrolytic capacitor.
- **Bridge Rectifier Installed (on white foam):** 4 black diodes labeled **`1N5399 MIC`** (`1.5A / 1000V` standard silicon rectifier diodes, `~1.4V` total drop across two conducting diodes in bridge).
- **Resistors Visible in Glue Cluster (`D34` Divider):** Two blue `1/4W 1%` 5-band metal-film resistors appearing to be `Brown–Black–Black–Orange–Brown` (`100 kΩ` each, forming the `2.0x` voltage divider to `D34` / `GND`). *(Verify exact value on kit strip / multimeter.)*
- **Tile-to-Box Cable (Black outer jacket):** Carries **4 inner wires (`red`, `white`, `green`, `blue`)** exiting from under the wooden tile:
  - `red` and `white` currently enter the glue/bridge/resistor cluster (user notes the piezo wires are not yet fully linked to the supercapacitor).
  - `green` and `blue` are currently **loose/unconnected**, sticking up above the ESP32.
- **Tile Mechanical Construction:** Plywood top and bottom boards; solid square wooden vertical posts hot-glued directly onto the centers of brass/ceramic piezo discs resting flat on the bottom board; `red`/`black` and `white` piezo wires twisted/taped under the tile.

---

## 2. Engineering Audit Findings (`Piezoelectric_Tile_Engineering_Design_Review.pdf`, REV 2.0)

Summary of bottlenecks identified in the groupmate's 4-page design review vs. the current build:

| Area | Current Build Status | REV 2.0 Audit Issue | Recommended Fix (If/When Reworking) |
| :--- | :--- | :--- | :--- |
| **Main Capacitor (A1)** | `KAMCAP 5.5V 1.0F` installed | `0.47F–1.5F` is ~10,000x too large (`+25 µV/step`, ~40,000 steps per `1.0V`, loses to `5–20 µA` self-discharge leakage). | Swap to `100–220 µF` low-ESR (or available **`470 µF 50V`** ~2,127x faster than `1.0F`) **only if paired with a `5.1V` Zener clamp / LED load** so `D34` never sees `> 3.3V` (`Cap > 6.6V`). |
| **Bridge Diodes (A3/A4)** | 1x bridge of `1N5399 MIC` silicon diodes | Silicon drops `~1.4V` (`~2.1V` if a 5th blocking diode is present). | Use Schottky bridge (`1N5819` or `BAT46`, `~0.3V` per diode) and remove any 5th blocking diode. |
| **Tile Array & Flexing (A3 / Sec 7.1)** | Shared splice + solid wood blocks glued flat onto disc centers | All 18 discs in 1 parallel bus dilutes voltage (`20V -> 4.44V`, `78%` loss) & phase-cancels; flat glue pinning reduces `0.5–1.5 mm` flex. | Split into `3 zones x 6 discs` -> `3 Schottky bridges`; support outer brass rim on compliant foam/springs with center striker. |
| **Subsystem B (`GPIO 34`)** | `100 kΩ / 100 kΩ` divider (no visible `100 nF` filter cap) | Works ~90%; missing `C_filt` leaves ADC noise; raw ADC lacks eFuse mV calibration. | Add `100 nF` ceramic cap from `GPIO 34` to `GND`; calibrate via `adc.read_uv()` in MicroPython. |
| **Subsystem C (`GPIO 32`)** | Loose `D32` & `GND` yellow wires (no resistor/Zener yet) | **CRITICAL:** Bare piezo spikes (`+15V..+30V` / `-5V+`) will damage `GPIO 32`; `1N4728A` (1W Zener) leaks `100 µA @ 1.0V`; foot-lift gives `-0.7V` swing (`ESP32` limit `-0.3V`). | **Must add protection before connecting piezos:** `10 kΩ` series resistor (`R4`) to `GPIO 32` + `1 MΩ` bleed (`R3`) + `3.3V` Zener (`BZX55C3V3` 0.5W, stripe toward `D32` side) or `BAT54S` clamp. |
| **Output Load (A2 / GPIO 25)** | No LED fairy lights / MOSFET / boost visible yet | Boost converter brownouts at `~0.8V` (`5–30 mA` startup vs `~0.03 mA` piezo avg). | Drop boost; drive `3V LED Fairy Lights + 47–100 Ω` resistor directly in bursts via `2N7000` MOSFET on `GPIO 25` (`+100 kΩ` pull-down to `GND`). |

---

## 3. Target Wiring Diagrams (For Hardware Specialist Review)

### A. Supercapacitor Voltage Sense (`GPIO 34 / D34`)
```text
Supercap (+) ──[ 100 kΩ ]──┬──┬──▶ ESP32 GPIO 34 (D34 / ADC1)
                           │  │
                      [ 100 kΩ ] [ 100 nF ] (Optional C_filt)
                           │  │
Supercap (-) ──────────────┴──┴──▶ ESP32 GND
```
- **Note:** Divider ratio = `2.0x`. Keep supercap voltage `<= 6.6V` (`D34 <= 3.3V`)—especially critical if swapping `KAMCAP 1.0F` to `470 µF 50V`! Add a `5.1V` Zener across the cap if switching to `470 µF`.

### B. Step Counter — 2 Dummy Piezos (`GPIO 32 / D32`)
```text
2 Dummy Piezos (+) ──[ 10 kΩ ]──┬──┬──▶ ESP32 GPIO 32 (D32 / ADC1)
                                │  │
                           [ 1 MΩ ] [ 3.3V Zener ] (Stripe on top / D32 side)
                                │  │
2 Dummy Piezos (-) ─────────────┴──┴──▶ ESP32 GND
```
- **WARNING:** Never connect the dummy piezo wires directly to the bare `D32` / `GND` yellow wires without at least the `10 kΩ` series + `1 MΩ` bleed (+ `3.3V` Zener).

### C. Bridge Rectifier Polarity Reminder (`1N5399 MIC` Bridge)
- **AC (`~`) corners (2 opposite corners where 1 silver band meets 1 plain black end):** Power piezo array pair.
- **DC (`+`) corner (both silver cathode bands meet):** Capacitor `+` and top of `D34` `100 kΩ` divider.
- **DC (`-`) corner (both plain black ends meet):** Capacitor `-`, bottom of divider, and ESP32 `GND`.

---

## 4. Questions / Confirmations Needed From Hardware Specialist Before Wiring & Flashing

1. **Color Pair Mapping in Black 4-Wire Cable (`red, white, green, blue`):**
   - Which pair is the **main power-generating piezo array**?
   - Which pair is the **2 isolated dummy step-counter piezos**?
2. **Divider & Zener Parts Inside Glue Cluster:**
   - Confirm exact values of the two blue resistors (`100 kΩ`?) and whether a `3.3V` / `5.1V` Zener is available for `D32` / cap protection.
3. **Capacitor Decision:**
   - Stay on `KAMCAP 5.5V 1.0F` (safe, slow mV climb) OR swap to `470 µF 50V` + `5.1V` Zener clamp?
4. **LED / Sign Load:**
   - Will there be an LED load connected (`GPIO 19` PWM or `GPIO 25` `2N7000` burst MOSFET), or is the live demo focusing on `ecostep_app` telemetry (`D32` steps + `D34` capacitor voltage)?

---

## 5. Firmware Alignment Notes (`esp32_micropython/main.py`)

- **Do NOT flash raw Arduino C++ (`Serial.printf`) from the PDF** if continuing to use `ecostep_app`, because `ecostep_app` expects MicroPython CSV lines (`DATA,<step>,<adc_raw>,<v_cap>` and `CAP,<adc_raw>,<v_cap>` at `115200` baud).
- Once hardware wiring is confirmed, update `esp32_micropython/main.py` (while keeping the CSV protocol intact):
  - Replace blocking `time.sleep_ms(20)` / `time.sleep_ms(120)` with a non-blocking `~1 ms` (`1000 Hz`) `time.ticks_ms()` loop.
  - Switch `D34` / `D32` reads to eFuse-calibrated `adc.read_uv()` (millivolts) with `STEP_TRIG_MV = 300` and `STEP_RESET_MV = 120` hysteresis.
  - Add optional `GPIO 25` MOSFET burst control (`BURST_ON_V = 4.20`, `BURST_OFF_V = 2.40`) if a `2N7000` + LED load is added.
