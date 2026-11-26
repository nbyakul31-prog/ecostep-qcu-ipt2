"""
EcoStep QCU: MicroPython CSV Telemetry Node (ESP32-D0WD-V3 on COM10)
Matches IPT2 Documentation (Section 2.4.3 Table 4 & Figure 5):
Streams comma-separated telemetry at 115,200 baud (8-N-1):
  DATA,<step_number>,<adc_raw_10bit>,<adc_voltage>
"""

import os
import select
import sys
import time
from machine import ADC, PWM, Pin

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
HARDWARE_SENSORS = False  # False = Bare-Board Safe Mode (BOOT button / 'S' cmd)
DEBOUNCE_MS = 250
STEP_ADC_THRESHOLD = 90   # 10-bit threshold (~0.29V)

DIVIDER_GEN_RATIO = 4.30  # (3.3M + 1.0M) / 1.0M
DIVIDER_CAP_RATIO = 2.50  # (1.5M + 1.0M) / 1.0M
ADC_VREF = 3.30
ADC_10BIT_MAX = 1023.0

PWM_FREQ = 5000
PWM_DUTY_DIM = 13107   # ~20% Dim Mode
PWM_DUTY_FULL = 65535  # 100% Full Mode

# ---------------------------------------------------------------------------
# PIN SETUP (30-pin ESP32-WROOM-32 DevKit)
# ---------------------------------------------------------------------------
btn_boot = Pin(0, Pin.IN, Pin.PULL_UP)  # Built-in BOOT button (active LOW)
led_status = Pin(2, Pin.OUT)            # Built-in Blue D2 LED
led_status.value(0)

pin_step_trig = Pin(34, Pin.IN)         # External step trigger (D34)
adc_step = ADC(Pin(34))
adc_step.atten(ADC.ATTN_11DB)

adc_raw_gen = ADC(Pin(35))              # Raw Piezo/Generator ADC (D35)
adc_raw_gen.atten(ADC.ATTN_11DB)

adc_supercap = ADC(Pin(32))             # Storage Capacitor ADC (D32)
adc_supercap.atten(ADC.ATTN_11DB)

pwm_sign = PWM(Pin(19), freq=PWM_FREQ, duty_u16=PWM_DUTY_DIM)

# ---------------------------------------------------------------------------
# RUNTIME STATE
# ---------------------------------------------------------------------------
step_number = 0
last_adc_raw = 0
last_adc_volts = 0.0
last_step_ms = 0
sign_burst_until = 0
sign_force_full = False
pending_step = False


def _rand_unit():
    return int.from_bytes(os.urandom(2), "big") / 65536.0


def _read_adc_10bit(adc_obj, samples=8):
    total = 0
    for _ in range(samples):
        total += adc_obj.read() >> 2  # Scale 12-bit (0-4095) -> 10-bit (0-1023)
        time.sleep_us(50)
    return int(total / samples)


def trigger_step():
    global step_number, last_adc_raw, last_adc_volts, last_step_ms, sign_burst_until

    now = time.ticks_ms()
    if time.ticks_diff(now, last_step_ms) < DEBOUNCE_MS:
        return
    last_step_ms = now

    led_status.value(1)
    pwm_sign.duty_u16(PWM_DUTY_FULL)
    sign_burst_until = time.ticks_add(now, 220)

    if HARDWARE_SENSORS:
        peak_raw = 0
        burst_start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), burst_start) < 120:
            raw10 = _read_adc_10bit(adc_raw_gen, 4)
            if raw10 > peak_raw:
                peak_raw = raw10
            time.sleep_us(200)
        adc_volts = (peak_raw / ADC_10BIT_MAX) * ADC_VREF * DIVIDER_GEN_RATIO
    else:
        # Bench mode realistic 10-bit ADC pulse (600-960 raw -> 8.3V-13.3V scaled)
        peak_raw = int(600 + (_rand_unit() * 360))
        adc_volts = (peak_raw / ADC_10BIT_MAX) * ADC_VREF * DIVIDER_GEN_RATIO

    step_number += 1
    last_adc_raw = peak_raw
    last_adc_volts = round(adc_volts, 2)

    # Exact CSV packet format documented in Figure 5 & Table 4
    print("DATA,{},{},{:.2f}".format(step_number, last_adc_raw, last_adc_volts))
    time.sleep_ms(120)
    led_status.value(0)


def handle_command(cmd):
    global step_number, last_adc_raw, last_adc_volts, HARDWARE_SENSORS, sign_force_full, pending_step

    cmd = cmd.strip().upper()
    if not cmd:
        return
    if cmd == "S":
        pending_step = True
    elif cmd == "R":
        step_number = 0
        last_adc_raw = 0
        last_adc_volts = 0.0
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
        print("READY,{},{},{},{:.2f}".format(mode_str, step_number, last_adc_raw, last_adc_volts))


def main():
    global pending_step

    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)
    cmd_buf = ""
    prev_btn = 1

    print("READY,BENCH,0,0,0.00")

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

        cur_btn = btn_boot.value()
        if prev_btn == 1 and cur_btn == 0:
            pending_step = True
        prev_btn = cur_btn

        if HARDWARE_SENSORS and not pending_step:
            if pin_step_trig.value() == 1 or (adc_step.read() >> 2) > STEP_ADC_THRESHOLD:
                pending_step = True

        if pending_step:
            pending_step = False
            trigger_step()

        if not sign_force_full and time.ticks_diff(now, sign_burst_until) >= 0:
            pwm_sign.duty_u16(PWM_DUTY_DIM)

        time.sleep_ms(20)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pwm_sign.duty_u16(PWM_DUTY_DIM)
        led_status.value(0)
        print("STOPPED")
