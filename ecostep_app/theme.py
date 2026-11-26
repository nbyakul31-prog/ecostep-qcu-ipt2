"""Refined Eco-Mat (Light) and Forest Night (Dark) palettes for EcoStep QCU."""

PALETTE = {
    "sidebar_bg": ("#172E1C", "#0D1910"),
    "sidebar_card": ("#112416", "#132418"),
    "sidebar_hover": ("#24472B", "#1E3824"),
    "sidebar_active": ("#3F7D2B", "#4B8F34"),
    "green": "#3F7D2B",
    "green_bright": "#559632",
    "teal": "#1E7F6D",
    "amber": "#F5820D",
    "gold": "#F9B218",
    "danger": "#C83E37",
    "bg": ("#EEF3EA", "#0B130E"),
    "card": ("#FFFFFF", "#132117"),
    "card_soft": ("#E6EFE0", "#1A2C1F"),
    "border": ("#CDDDC4", "#26402D"),
    "input_bg": ("#F8FBF6", "#0F1B13"),
    "text": ("#19281D", "#ECF5ED"),
    "muted": ("#566B59", "#94AD98"),
}


def pick(pair, mode):
    if not isinstance(pair, tuple):
        return pair
    return pair[1] if mode == "Dark" else pair[0]


def apply_matplotlib_theme(fig, ax, mode, ax2=None):
    bg = pick(PALETTE["card"], mode)
    plot_bg = pick(PALETTE["card_soft"], mode)
    fg = pick(PALETTE["text"], mode)
    grid_col = "#CBDAC2" if mode == "Light" else "#28422F"

    fig.patch.set_facecolor(bg)
    ax.set_facecolor(plot_bg)
    ax.grid(True, linestyle="--", linewidth=0.6, alpha=0.55, color=grid_col)
    for spine in ax.spines.values():
        spine.set_color(grid_col)
    ax.tick_params(colors=fg, labelsize=8)
    if ax2 is not None:
        for spine in ax2.spines.values():
            spine.set_color(grid_col)
        ax2.tick_params(colors=PALETTE["amber"], labelsize=8)
