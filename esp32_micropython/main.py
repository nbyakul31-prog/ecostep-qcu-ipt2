"""
EcoStep QCU: MicroPython CSV Telemetry Node (ESP32-D0WD-V3 on COM10)
Matches user hardware wiring:
  - GPIO 34 (D34): Supercapacitor Voltage via 100kOhm / 100kOhm divider (2.0x)
  - GPIO 32 (D32): Step Counter from 2 Dummy Piezos (1MOhm bleed + 3.3V Zener)
  - GPIO 0  (BOOT): Built-in test button (always active for bench testing)
  - GPIO 2  (D2): Built-in Blue LED (flashes on every footstep)
  - GPIO 19 (D19): Sign PWM output (100% burst on step -> 20% dim standby)

Streams at 115,200 baud (8-N-1):
  DATA,<step_number>,<adc_raw_10bit>,<v_cap_volts>
  CAP,<adc_raw_10bit>,<v_cap_volts>   (periodic supercap voltage readout)
"""

import os
import select
import sys
import time
from machine import ADC, PWM, Pin

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
HARDWARE_SENSORS = True   # Watches D32 (piezo trigger) & reads D34 (supercap)
DEBOUNCE_MS = 250
STEP_ADC_THRESHOLD = 140  # 10-bit threshold (~0.45V) above bleed noise floor

DIVIDER_CAP_RATIO = 2.00  # (100k + 100k) / 100k = 2.0x for Supercapacitor on D34
ADC_VREF = 3.30
ADC_10BIT_MAX = 1023.0

PWM_FREQ = 5000
PWM_DUTY_DIM = 13107   # ~20% Dim Mode
PWM_DUTY_FULL = 65535  # 100% Full Mode

# ---------------------------------------------------------------------------
# PIN SETUP (30-pin ESP32-WROOM-32 DevKit)
# ---------------------------------------------------------------------------
btn_boot = Pin(0, Pin.IN, Pin.PULL_UP)   # Built-in BOOT button (active LOW)
led_status = Pin(2, Pin.OUT)             # Built-in Blue D2 LED
led_status.value(0)

adc_supercap = ADC(Pin(34))              # D34: Supercapacitor (+) via 100k/100k
adc_supercap.atten(ADC.ATTN_11DB)        # 0 - 3.3V input range (0 - 6.6V cap)

adc_step = ADC(Pin(32))                  # D32: 2 Dummy Piezos (+) + 1M + 3.3V Zener
adc_step.atten(ADC.ATTN_11DB)

pwm_sign = PWM(Pin(19), freq=PWM_FREQ, duty_u16=PWM_DUTY_DIM)

# ---------------------------------------------------------------------------
# RUNTIME STATE
# ---------------------------------------------------------------------------
step_number = 0
last_adc_raw = 0
last_cap_volts = 0.0
sim_cap_volts = 0.0
last_step_ms = 0
last_cap_ms = 0
sign_burst_until = 0
sign_force_full = False
pending_step = False
pending_sim = False


def _rand_unit():
    return int.from_bytes(os.urandom(2), "big") / 65536.0


def _read_adc_10bit(adc_obj, samples=8):
    total = 0
    for _ in range(samples):
        total += adc_obj.read() >> 2  # Scale 12-bit (0-4095) -> 10-bit (0-1023)
        time.sleep_us(50)
    return int(total / samples)


def read_supercap():
    """Returns (adc_raw_10bit, v_cap_volts) from D34 (100k/100k = 2.0x)."""
    raw10 = _read_adc_10bit(adc_supercap, 12)
    volts = round((raw10 / ADC_10BIT_MAX) * ADC_VREF * DIVIDER_CAP_RATIO, 2)
    return raw10, volts


def trigger_step(simulated=False):
    global step_number, last_adc_raw, last_cap_volts, sim_cap_volts, last_step_ms, sign_burst_until

    now = time.ticks_ms()
    if time.ticks_diff(now, last_step_ms) < DEBOUNCE_MS:
        return
    last_step_ms = now

    led_status.value(1)
    pwm_sign.duty_u16(PWM_DUTY_FULL)
    sign_burst_until = time.ticks_add(now, 220)

    if HARDWARE_SENSORS and not simulated:
        raw10, v_cap = read_supercap()
    else:
        # Bench simulation increments simulated supercap charge realistically (0 -> 5.2V)
        sim_cap_volts = min(5.20, sim_cap_volts + 0.08 + (_rand_unit() * 0.07))
        v_cap = round(sim_cap_volts, 2)
        raw10 = int(min(1023, (v_cap / (ADC_VREF * DIVIDER_CAP_RATIO)) * ADC_10BIT_MAX))

    step_number += 1
    last_adc_raw = raw10
    last_cap_volts = v_cap

    print("DATA,{},{},{:.2f}".format(step_number, last_adc_raw, last_cap_volts))
    time.sleep_ms(120)
    led_status.value(0)


def handle_command(cmd):
    global step_number, last_adc_raw, last_cap_volts, sim_cap_volts
    global HARDWARE_SENSORS, sign_force_full, pending_step, pending_sim

    cmd = cmd.strip().upper()
    if not cmd:
        return
    if cmd == "S":
        pending_step = True
        pending_sim = True
    elif cmd == "R":
        step_number = 0
        last_adc_raw = 0
        last_cap_volts = 0.0
        sim_cap_volts = 0.0
        print("RESET,0,0,0.00")
    elif cmd == "M1":
        HARDWARE_SENSORS = True
        print("MODE,TILE")
    elif cmd == "M0":
        HARDWARE_SENSORS = False
        print("MODE,BENCH")
    elif cmd == "L1":
        sign_force_full = True
        pwm_sign.duty_u16(PWM_DUTY_FULL)
        print("SIGN,FULL")
    elif cmd == "L0":
        sign_force_full = False
        pwm_sign.duty_u16(PWM_DUTY_DIM)
        print("SIGN,DIM")
    elif cmd == "?":
        mode_str = "TILE" if HARDWARE_SENSORS else "BENCH"
        print("READY,{},{},{},{:.2f}".format(mode_str, step_number, last_adc_raw, last_cap_volts))


def main():
    global pending_step, pending_sim, last_cap_ms

    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)
    cmd_buf = ""
    prev_btn = 1

    mode_str = "TILE" if HARDWARE_SENSORS else "BENCH"
    print("READY,{},0,0,0.00".format(mode_str))
    last_cap_ms = time.ticks_ms()

    while True:
        now = time.ticks_ms()

        while poll.poll(0):
            ch = sys.stdin.read(1)
            if not ch:
                break
            if ch in ("\n", "\r"):
                if cmd_buf:
                    handle_command(cmd_buf)
                    cmd_buf = ""
            else:
                cmd_buf += ch
                if cmd_buf.upper() in ("S", "R", "?"):
                    handle_command(cmd_buf)
                    cmd_buf = ""
                elif len(cmd_buf) >= 2 and cmd_buf[0].upper() in ("M", "L"):
                    handle_command(cmd_buf)
                    cmd_buf = ""
                elif len(cmd_buf) > 16:
                    cmd_buf = ""

        # Built-in BOOT button always works for quick bench testing
        cur_btn = btn_boot.value()
        if prev_btn == 1 and cur_btn == 0:
            pending_step = True
            pending_sim = not HARDWARE_SENSORS
        prev_btn = cur_btn

        # Real 2-Dummy-Piezo Step Trigger on D32 (GPIO 32)
        if HARDWARE_SENSORS and not pending_step:
            if (adc_step.read() >> 2) > STEP_ADC_THRESHOLD:
                pending_step = True
                pending_sim = False

        if pending_step:
            is_sim = pending_sim
            pending_step = False
            pending_sim = False
            trigger_step(simulated=is_sim)
            last_cap_ms = time.ticks_ms()

        if not sign_force_full and time.ticks_diff(now, sign_burst_until) >= 0:
            pwm_sign.duty_u16(PWM_DUTY_DIM)

        # Periodic 2s Supercapacitor readout in Tile Mode (without incrementing step)
        if HARDWARE_SENSORS and time.ticks_diff(now, last_cap_ms) >= 2000:
            raw10, v_cap = read_supercap()
            print("CAP,{},{:.2f}".format(raw10, v_cap))
            last_cap_ms = now

        time.sleep_ms(20)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pwm_sign.duty_u16(PWM_DUTY_DIM)
        led_status.value(0)
        print("STOPPED")
