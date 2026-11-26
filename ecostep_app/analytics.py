"""Time-horizon energy math, walking cadence, Battery SoC %, and Device Equivalence Calculator."""

USB_PHONE_WATTS = 2.5    # 5V @ 500 mA per active USB port
LED_12V_WATTS = 3.0      # 12V @ 250 mA campus pathway LED
SIGN_FULL_WATTS = 0.125  # 5V @ 25 mA Full Mode (1.5 kOhm)
SIGN_DIM_WATTS = 0.0175  # 5V @ 3.5 mA Dim Mode (10 kOhm)

PHONE_BATTERY_WH = 15.4  # 4,000 mAh @ 3.85 V smartphone battery
PHONE_TALK_WATTS = 1.2   # Cellular call power draw


def estimate_step_joules(adc_voltage):
    """Estimates harvested Joules from peak rectified voltage per footstep."""
    v = float(adc_voltage)
    if v <= 0:
        return 0.0
    return round(min(1.05, max(0.35, v * 0.062)), 3)


def compute_battery_and_equivalences(total_joules, battery_cap_wh=10.0, usb_loads=0, led_12v_on=False, sign_mode="Dim"):
    cap_wh = max(0.5, float(battery_cap_wh))
    wh_stored = min(cap_wh, max(0.0, float(total_joules) / 3600.0))
    soc_pct = min(100.0, (wh_stored / cap_wh) * 100.0)

    phone_pct = min(100.0, (wh_stored / PHONE_BATTERY_WH) * 100.0)
    phones_full = wh_stored / PHONE_BATTERY_WH
    talk_min = (wh_stored / PHONE_TALK_WATTS) * 60.0
    led_12v_min = (wh_stored / LED_12V_WATTS) * 60.0
    sign_full_min = (wh_stored / SIGN_FULL_WATTS) * 60.0
    sign_dim_min = (wh_stored / SIGN_DIM_WATTS) * 60.0

    sign_w = SIGN_FULL_WATTS if sign_mode == "Full" else SIGN_DIM_WATTS
    total_load_w = (int(usb_loads) * USB_PHONE_WATTS) + (LED_12V_WATTS if led_12v_on else 0.0) + sign_w
    usb_ma = int(usb_loads) * (USB_PHONE_WATTS / 5.0) * 1000.0
    led_ma = (LED_12V_WATTS / 12.0) * 1000.0 if led_12v_on else 0.0
    sign_ma = (sign_w / 5.0) * 1000.0

    return {
        "battery_cap_wh": round(cap_wh, 2),
        "wh_stored": round(wh_stored, 4),
        "soc_pct": round(soc_pct, 2),
        "phone_4000mah_pct": round(phone_pct, 2),
        "phones_full_count": round(phones_full, 3),
        "emergency_talk_min": round(talk_min, 1),
        "led_12v_runtime_min": round(led_12v_min, 1),
        "sign_full_runtime_min": round(sign_full_min, 1),
        "sign_dim_runtime_min": round(sign_dim_min, 1),
        "load_mw": round(total_load_w * 1000.0, 1),
        "load_ma": round(usb_ma + led_ma + sign_ma, 1),
    }
