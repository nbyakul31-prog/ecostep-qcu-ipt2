"""Refined Eco-Mat (Light) and Forest Night (Dark) palettes & visual helpers for EcoStep QCU."""

import os
from PIL import Image, ImageDraw

PALETTE = {
    "sidebar_bg": ("#152B1A", "#0B160E"),
    "sidebar_card": ("#102214", "#122217"),
    "sidebar_hover": ("#23462A", "#1C3623"),
    "sidebar_active": ("#3F7D2B", "#4B8F34"),
    "green": "#3F7D2B",
    "green_bright": "#559632",
    "teal": "#1E7F6D",
    "amber": "#F5820D",
    "gold": "#F9B218",
    "danger": "#C83E37",
    "bg": ("#ECF2E7", "#09110C"),
    "card": ("#FFFFFF", "#121F16"),
    "card_soft": ("#E5EFE0", "#192B1E"),
    "border": ("#C8DAC0", "#26402D"),
    "input_bg": ("#F8FBF6", "#0D1810"),
    "row_even": ("#FFFFFF", "#121F16"),
    "row_odd": ("#F4F8F1", "#16261B"),
    "text": ("#17261B", "#EDF6EE"),
    "muted": ("#556B58", "#91AB95"),
}


def pick(pair, mode):
    if not isinstance(pair, tuple):
        return pair
    return pair[1] if mode == "Dark" else pair[0]


def make_circular_logo(logo_path, size=64):
    """Loads the EcoStep logo and crops it cleanly into a transparent circular crest."""
    img = Image.open(logo_path).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((1, 1, size - 2, size - 2), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    # Crisp subtle gold-sage ring around perimeter
    ring = ImageDraw.Draw(out)
    ring.ellipse((1, 1, size - 2, size - 2), outline=(249, 178, 24, 210), width=2)
    return out


def ensure_ico_file(logo_path, assets_dir):
    """Generates a transparent circular .ico for the Windows titlebar & taskbar."""
    ico_path = os.path.join(assets_dir, "ecostep_icon.ico")
    if not os.path.exists(ico_path) and os.path.exists(logo_path):
        circ = make_circular_logo(logo_path, size=128)
        circ.save(ico_path, format="ICO", sizes=[(32, 32), (64, 64), (128, 128)])
    return ico_path if os.path.exists(ico_path) else None


def apply_matplotlib_theme(fig, ax, mode, ax2=None):
    bg = pick(PALETTE["card"], mode)
    plot_bg = pick(PALETTE["card_soft"], mode)
    fg = pick(PALETTE["text"], mode)
    grid_col = "#C8DAC0" if mode == "Light" else "#26402D"

    fig.patch.set_facecolor(bg)
    ax.set_facecolor(plot_bg)
    ax.grid(True, linestyle="--", linewidth=0.65, alpha=0.55, color=grid_col)
    for spine in ax.spines.values():
        spine.set_color(grid_col)
    ax.tick_params(colors=fg, labelsize=8)
    if ax2 is not None:
        for spine in ax2.spines.values():
            spine.set_color(grid_col)
        ax2.tick_params(colors=PALETTE["amber"], labelsize=8)
