"""Neon-Emerald Glassmorphism (Forest Dark) and Eco-Mat (Light) themes & Pillow visual engine."""

import math
import os
from PIL import Image, ImageDraw, ImageFilter

PALETTE = {
    "sidebar_bg": ("#152B1A", "#08120D"),
    "sidebar_card": ("#102214", "#0E1D15"),
    "sidebar_hover": ("#23462A", "#163022"),
    "sidebar_active": ("#2E7D32", "#16A34A"),
    "green": "#16A34A",
    "green_bright": "#22C55E",
    "emerald_glow": "#34D399",
    "teal": "#38BDF8",
    "blue": "#2563EB",
    "blue_hover": "#1D4ED8",
    "cyan": "#0284C7",
    "cyan_hover": "#0369A1",
    "purple": "#A855F7",
    "amber": "#F59E0B",
    "gold": "#FBBF24",
    "danger": "#EF4444",
    "bg": ("#ECF2E7", "#060D09"),
    "card": ("#FFFFFF", "#0C1811"),
    "card_soft": ("#E5EFE0", "#102319"),
    "border": ("#C8DAC0", "#1E4C32"),
    "input_bg": ("#F8FBF6", "#0A150F"),
    "row_even": ("#FFFFFF", "#0C1811"),
    "row_odd": ("#F4F8F1", "#102118"),
    "text": ("#17261B", "#EBF7EE"),
    "muted": ("#556B58", "#84A98E"),
}


def pick(pair, mode):
    if not isinstance(pair, tuple):
        return pair
    return pair[1] if mode == "Dark" else pair[0]


def hex_to_rgb(hex_col):
    h = hex_col.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def lerp_rgb(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def make_circular_logo(logo_path, size=64):
    """Loads the EcoStep logo and crops it cleanly into a transparent circular crest."""
    img = Image.open(logo_path).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((1, 1, size - 2, size - 2), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    ring = ImageDraw.Draw(out)
    ring.ellipse((1, 1, size - 2, size - 2), outline=(251, 191, 36, 225), width=2)
    return out


def ensure_ico_file(logo_path, assets_dir):
    """Generates a transparent circular .ico for the Windows titlebar & taskbar."""
    ico_path = os.path.join(assets_dir, "ecostep_icon.ico")
    if not os.path.exists(ico_path) and os.path.exists(logo_path):
        circ = make_circular_logo(logo_path, size=128)
        circ.save(ico_path, format="ICO", sizes=[(32, 32), (64, 64), (128, 128)])
    return ico_path if os.path.exists(ico_path) else None


def _draw_watermark(draw, kind, cx, cy, size, rgba):
    """Draws subtle vector watermark icons on KPI cards at (cx, cy)."""
    s = size
    if kind == "foot":
        # Stylized sole + 4 toes
        draw.ellipse((cx - s * 0.28, cy - s * 0.15, cx + s * 0.24, cy + s * 0.50), fill=rgba)
        draw.ellipse((cx - s * 0.22, cy + s * 0.30, cx + s * 0.16, cy + s * 0.65), fill=rgba)
        for i, ox in enumerate((-0.24, -0.07, 0.10, 0.25)):
            r = s * (0.095 if i == 0 else 0.075)
            oy = -0.34 + i * 0.04
            draw.ellipse((cx + s * ox - r, cy + s * oy - r, cx + s * ox + r, cy + s * oy + r), fill=rgba)
    elif kind == "cap":
        # Capacitor schematic symbol
        w_line = max(2, int(s * 0.09))
        draw.line((cx - s * 0.48, cy, cx - s * 0.14, cy), fill=rgba, width=w_line)
        draw.line((cx + s * 0.14, cy, cx + s * 0.48, cy), fill=rgba, width=w_line)
        draw.line((cx - s * 0.14, cy - s * 0.42, cx - s * 0.14, cy + s * 0.42), fill=rgba, width=w_line)
        draw.line((cx + s * 0.14, cy - s * 0.42, cx + s * 0.14, cy + s * 0.42), fill=rgba, width=w_line)
    elif kind == "battery":
        w_line = max(2, int(s * 0.08))
        bx0, by0, bx1, by1 = cx - s * 0.26, cy - s * 0.36, cx + s * 0.26, cy + s * 0.44
        draw.rounded_rectangle((bx0, by0, bx1, by1), radius=int(s * 0.08), outline=rgba, width=w_line)
        draw.rectangle((cx - s * 0.10, by0 - s * 0.10, cx + s * 0.10, by0), fill=rgba)
        draw.rectangle((bx0 + w_line * 1.4, cy, bx1 - w_line * 1.4, by1 - w_line * 1.4), fill=rgba)
    elif kind == "ledger":
        w_line = max(2, int(s * 0.07))
        dx0, dy0, dx1, dy1 = cx - s * 0.30, cy - s * 0.40, cx + s * 0.30, cy + s * 0.40
        draw.rounded_rectangle((dx0, dy0, dx1, dy1), radius=int(s * 0.08), outline=rgba, width=w_line)
        for row_y in (-0.16, 0.02, 0.20):
            draw.line((dx0 + s * 0.12, cy + s * row_y, dx1 - s * 0.12, cy + s * row_y), fill=rgba, width=w_line)


def render_neon_card(width, height, accent_hex, mode, icon_kind=None, radius=14):
    """Generates a frosted-glass neon-rimmed KPI card texture via Pillow."""
    w = max(80, int(width))
    h = max(60, int(height))
    bg_hex = pick(PALETTE["bg"], mode)
    base_rgb = hex_to_rgb(pick(PALETTE["card"], mode))
    outer_rgb = hex_to_rgb(bg_hex)
    acc_rgb = hex_to_rgb(accent_hex)

    canvas = Image.new("RGBA", (w, h), outer_rgb + (255,))

    # Build tinted vertical + top-left radial glow card fill
    card_fill = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fill_draw = ImageDraw.Draw(card_fill)
    top_tint = lerp_rgb(base_rgb, acc_rgb, 0.24 if mode == "Dark" else 0.12)
    bot_tint = lerp_rgb(base_rgb, acc_rgb, 0.05 if mode == "Dark" else 0.03)
    for y in range(h):
        c = lerp_rgb(top_tint, bot_tint, y / max(1, h - 1))
        fill_draw.line((0, y, w, y), fill=c + (255,))

    # Subtle radial glow orb on top-left corner
    orb = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(orb)
    orb_alpha = 72 if mode == "Dark" else 28
    od.ellipse((-w * 0.18, -h * 0.45, w * 0.48, h * 0.65), fill=acc_rgb + (orb_alpha,))
    orb = orb.filter(ImageFilter.GaussianBlur(radius=max(10, int(h * 0.22))))
    card_fill = Image.alpha_composite(card_fill, orb)

    # Watermark icon on right bottom
    if icon_kind:
        wm_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        wm_d = ImageDraw.Draw(wm_layer)
        wm_alpha = 34 if mode == "Dark" else 24
        _draw_watermark(wm_d, icon_kind, w - int(h * 0.42), int(h * 0.62), int(h * 0.54), acc_rgb + (wm_alpha,))
        card_fill = Image.alpha_composite(card_fill, wm_layer)

    # Clip card interior to rounded rectangle
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((2, 2, w - 3, h - 3), radius=radius, fill=255)
    canvas.paste(card_fill, (0, 0), mask)

    # Outer soft glow + crisp neon rim
    glow_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    glow_alpha = 180 if mode == "Dark" else 90
    gd.rounded_rectangle((2, 2, w - 3, h - 3), radius=radius, outline=acc_rgb + (glow_alpha,), width=3)
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=3))
    canvas = Image.alpha_composite(canvas, glow_layer)

    rim = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rim)
    rim_col = lerp_rgb(acc_rgb, (255, 255, 255), 0.15) if mode == "Dark" else acc_rgb
    rim_alpha = 210 if mode == "Dark" else 145
    rd.rounded_rectangle((2, 2, w - 3, h - 3), radius=radius, outline=rim_col + (rim_alpha,), width=2)
    # Brighter top neon edge highlight
    rd.line((radius + 4, 2, w - radius - 4, 2), fill=lerp_rgb(acc_rgb, (255, 255, 255), 0.35) + (235,), width=2)
    canvas = Image.alpha_composite(canvas, rim)
    return canvas


def render_aurora_banner(width, height, mode):
    """Generates the sweeping emerald aurora glass header texture."""
    w = max(200, int(width))
    h = max(48, int(height))
    bg_hex = pick(PALETTE["bg"], mode)
    outer_rgb = hex_to_rgb(bg_hex)
    card_rgb = hex_to_rgb(pick(PALETTE["card"], mode))
    em_dark = hex_to_rgb("#0F3320") if mode == "Dark" else hex_to_rgb("#DFF2DF")
    em_bright = hex_to_rgb("#22C55E")
    teal = hex_to_rgb("#10B981")

    canvas = Image.new("RGBA", (w, h), outer_rgb + (255,))
    fill = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fill)
    for x in range(w):
        # Smooth transition into card_rgb on the right where buttons dock
        t = min(1.0, (x / max(1, w)) * 1.45)
        c = lerp_rgb(em_dark, card_rgb, t)
        fd.line((x, 0, x, h), fill=c + (255,))

    # Swooping aurora ribbons across left/center
    aurora = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ad = ImageDraw.Draw(aurora)
    a1 = 85 if mode == "Dark" else 40
    a2 = 55 if mode == "Dark" else 25
    pts1 = [(-20, h + 15), (int(w * 0.25), int(h * 0.15)), (int(w * 0.58), int(h * 0.85)), (int(w * 0.72), -10), (int(w * 0.45), -10)]
    ad.polygon(pts1, fill=em_bright + (a1,))
    ad.ellipse((int(w * 0.18), -int(h * 0.55), int(w * 0.62), int(h * 0.95)), fill=teal + (a2,))
    aurora = aurora.filter(ImageFilter.GaussianBlur(radius=22))
    fill = Image.alpha_composite(fill, aurora)

    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((1, 1, w - 2, h - 2), radius=14, fill=255)
    canvas.paste(fill, (0, 0), mask)

    rim = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rim_col = hex_to_rgb("#22C55E") if mode == "Dark" else hex_to_rgb(pick(PALETTE["border"], mode))
    ImageDraw.Draw(rim).rounded_rectangle((1, 1, w - 2, h - 2), radius=14, outline=rim_col + (120,), width=1)
    canvas = Image.alpha_composite(canvas, rim)
    return canvas


def render_sidebar_aurora(width, height, mode):
    """Generates subtle emerald wave accent for bottom of navigation sidebar."""
    w = max(120, int(width))
    h = max(80, int(height))
    sb_rgb = hex_to_rgb(pick(PALETTE["sidebar_bg"], mode))
    canvas = Image.new("RGBA", (w, h), sb_rgb + (255,))
    wave = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    wd = ImageDraw.Draw(wave)
    wd.ellipse((-w * 0.25, h * 0.45, w * 0.95, h * 1.55), fill=hex_to_rgb("#16A34A") + (52,))
    wd.ellipse((w * 0.05, h * 0.62, w * 1.15, h * 1.65), fill=hex_to_rgb("#34D399") + (32,))
    wave = wave.filter(ImageFilter.GaussianBlur(radius=18))
    return Image.alpha_composite(canvas, wave)


def make_icon(kind, size=18, color="#E8F5E4"):
    """2x supersampled crisp vector icon for sidebar/buttons/headers (avoids missing Unicode glyphs)."""
    s = size * 2
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rgb = hex_to_rgb(color) + (255,)
    lw = max(3, int(s * 0.10))

    if kind == "leaf":
        d.polygon([(s * 0.18, s * 0.82), (s * 0.25, s * 0.28), (s * 0.85, s * 0.14), (s * 0.72, s * 0.72)], fill=rgb)
        d.line((s * 0.16, s * 0.86, s * 0.70, s * 0.30), fill=hex_to_rgb("#08120D") + (220,), width=lw)
    elif kind == "live":
        pts = [(s * 0.08, s * 0.55), (s * 0.28, s * 0.55), (s * 0.40, s * 0.22), (s * 0.56, s * 0.82), (s * 0.70, s * 0.45), (s * 0.92, s * 0.45)]
        d.line(pts, fill=rgb, width=lw, joint="curve")
    elif kind == "time":
        d.ellipse((s * 0.14, s * 0.14, s * 0.86, s * 0.86), outline=rgb, width=lw)
        d.line((s * 0.50, s * 0.28, s * 0.50, s * 0.52, s * 0.68, s * 0.64), fill=rgb, width=lw)
    elif kind == "runs":
        for i, h_frac in enumerate((0.35, 0.65, 0.50, 0.80)):
            x0 = s * (0.14 + i * 0.20)
            d.rounded_rectangle((x0, s * (0.88 - h_frac), x0 + s * 0.13, s * 0.88), radius=3, fill=rgb)
    elif kind == "bolt":
        d.polygon([(s * 0.58, s * 0.08), (s * 0.22, s * 0.56), (s * 0.48, s * 0.56), (s * 0.38, s * 0.92), (s * 0.78, s * 0.44), (s * 0.52, s * 0.44)], fill=rgb)
    elif kind == "cube":
        d.rounded_rectangle((s * 0.16, s * 0.22, s * 0.84, s * 0.82), radius=5, outline=rgb, width=lw)
        d.line((s * 0.16, s * 0.44, s * 0.84, s * 0.44), fill=rgb, width=lw)
        d.line((s * 0.50, s * 0.44, s * 0.50, s * 0.82), fill=rgb, width=lw)
    elif kind == "db":
        d.ellipse((s * 0.18, s * 0.14, s * 0.82, s * 0.36), outline=rgb, width=lw)
        d.line((s * 0.18, s * 0.25, s * 0.18, s * 0.76), fill=rgb, width=lw)
        d.line((s * 0.82, s * 0.25, s * 0.82, s * 0.76), fill=rgb, width=lw)
        d.arc((s * 0.18, s * 0.38, s * 0.82, s * 0.60), start=0, end=180, fill=rgb, width=lw)
        d.arc((s * 0.18, s * 0.64, s * 0.82, s * 0.86), start=0, end=180, fill=rgb, width=lw)
    elif kind == "usb":
        d.line((s * 0.22, s * 0.50, s * 0.80, s * 0.50), fill=rgb, width=lw)
        d.ellipse((s * 0.10, s * 0.40, s * 0.28, s * 0.60), fill=rgb)
        d.polygon([(s * 0.88, s * 0.50), (s * 0.74, s * 0.40), (s * 0.74, s * 0.60)], fill=rgb)
        d.line((s * 0.38, s * 0.50, s * 0.52, s * 0.28, s * 0.68, s * 0.28), fill=rgb, width=max(2, lw - 1))
        d.line((s * 0.45, s * 0.50, s * 0.58, s * 0.72, s * 0.72, s * 0.72), fill=rgb, width=max(2, lw - 1))
    elif kind == "search":
        d.ellipse((s * 0.16, s * 0.16, s * 0.68, s * 0.68), outline=rgb, width=lw)
        d.line((s * 0.60, s * 0.60, s * 0.86, s * 0.86), fill=rgb, width=lw + 1)
    elif kind == "download":
        d.line((s * 0.50, s * 0.14, s * 0.50, s * 0.66), fill=rgb, width=lw)
        d.polygon([(s * 0.50, s * 0.72), (s * 0.30, s * 0.50), (s * 0.70, s * 0.50)], fill=rgb)
        d.line((s * 0.18, s * 0.68, s * 0.18, s * 0.86, s * 0.82, s * 0.86, s * 0.82, s * 0.68), fill=rgb, width=lw)
    elif kind == "trend":
        d.line([(s * 0.12, s * 0.76), (s * 0.38, s * 0.50), (s * 0.56, s * 0.62), (s * 0.86, s * 0.22)], fill=rgb, width=lw)
        d.polygon([(s * 0.88, s * 0.20), (s * 0.66, s * 0.22), (s * 0.84, s * 0.42)], fill=rgb)

    return img.resize((size, size), Image.Resampling.LANCZOS)


def render_supersampled_arc_gauge(width, height, cx, cy, r, frac, active_hex, track_hex, mode):
    """Renders a 2x anti-aliased glowing semicircular voltmeter arc ring."""
    scale = 2
    W, H = width * scale, height * scale
    CX, CY, R = cx * scale, cy * scale, r * scale
    stroke = 16 * scale

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    track_rgb = hex_to_rgb(track_hex) + (255,)
    d.arc((CX - R, CY - R, CX + R, CY + R), start=180, end=360, fill=track_rgb, width=stroke)

    # Subtle color zone dots along track (0-4V emerald, 4-6V amber)
    if frac > 0.005:
        deg_end = 180 + int(round(180 * max(0.0, min(1.0, frac))))
        acc_rgb = hex_to_rgb(active_hex)
        # Soft glow layer
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        glow_a = 160 if mode == "Dark" else 90
        gd.arc((CX - R, CY - R, CX + R, CY + R), start=180, end=deg_end, fill=acc_rgb + (glow_a,), width=stroke + 8)
        glow = glow.filter(ImageFilter.GaussianBlur(radius=6))
        img = Image.alpha_composite(img, glow)

        # Crisp core arc
        ImageDraw.Draw(img).arc(
            (CX - R, CY - R, CX + R, CY + R),
            start=180,
            end=deg_end,
            fill=lerp_rgb(acc_rgb, (255, 255, 255), 0.18) + (255,),
            width=stroke,
        )

    return img.resize((width, height), Image.Resampling.LANCZOS)


def apply_matplotlib_theme(fig, ax, mode, ax2=None):
    bg = pick(PALETTE["card"], mode)
    plot_bg = "#E8F2E4" if mode == "Light" else "#091D12"
    fg = pick(PALETTE["text"], mode)
    grid_col = "#C8DAC0" if mode == "Light" else "#173D27"

    fig.patch.set_facecolor(bg)
    ax.set_facecolor(plot_bg)
    ax.grid(True, linestyle="-", linewidth=0.65, alpha=0.55, color=grid_col)
    for spine in ax.spines.values():
        spine.set_color(grid_col)
    ax.tick_params(colors=fg, labelsize=8)
    if ax2 is not None:
        for spine in ax2.spines.values():
            spine.set_color(grid_col)
        ax2.tick_params(colors=PALETTE["amber"], labelsize=8)
