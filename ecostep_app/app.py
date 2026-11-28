"""EcoStep QCU IPT2 Standalone CustomTkinter Desktop Application."""

from collections import deque
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from PIL import ImageTk

from . import analytics, config
from .db import EcoStepDatabase
from .serial_worker import SerialTelemetryWorker, list_serial_ports
from .sia_sync import SiaBridgeSyncService
from .theme import (
    PALETTE,
    apply_matplotlib_theme,
    ensure_ico_file,
    make_circular_logo,
    make_icon,
    pick,
    render_aurora_banner,
    render_sidebar_aurora,
)
from .views import (
    ComponentsView,
    MeasurementRunsView,
    NeonKpiCard,
    SerialDiagnosticsDrawer,
    SignTestsView,
    TimeAnalyticsView,
    VoltageMeterCanvas,
    configure_tree_zebra,
    insert_zebra_row,
    style_treeview,
    styled_entry,
    styled_option,
)


class PostgresSetupDialog(ctk.CTkToplevel):
    """Modal dialog to configure PostgreSQL 16/18 credentials cleanly without hardcoding."""

    def __init__(self, master, db, on_success):
        super().__init__(master)
        self.db = db
        self.on_success = on_success
        self.title("Connect to Local PostgreSQL (ecostep_qcu_db)")
        self.geometry("440x380")
        self.resizable(False, False)
        self.configure(fg_color=PALETTE["card"])
        self.transient(master)
        self.grab_set()

        cfg = db.cfg
        ctk.CTkLabel(self, text="PostgreSQL 16/18 Local Connection", font=ctk.CTkFont(size=16, weight="bold"), text_color=PALETTE["text"]).pack(pady=(18, 4))
        ctk.CTkLabel(self, text="Enter local PostgreSQL credentials to initialize ecostep_qcu_db.", font=ctk.CTkFont(size=12), text_color=PALETTE["muted"]).pack(pady=(0, 12))

        frm = ctk.CTkFrame(self, fg_color="transparent")
        frm.pack(fill="x", padx=28)

        self.host_e = self._field(frm, "Host", cfg["host"])
        self.port_e = self._field(frm, "Port", str(cfg["port"]))
        self.user_e = self._field(frm, "User", cfg["user"])
        self.pass_e = self._field(frm, "Password", cfg["password"], show="*")
        self.db_e = self._field(frm, "Database", cfg["dbname"])

        self.save_env_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self, text="Save credentials locally in .env", variable=self.save_env_var, text_color=PALETTE["text"]).pack(pady=10)

        self.err_lbl = ctk.CTkLabel(self, text="", text_color=PALETTE["danger"], wraplength=380)
        self.err_lbl.pack()

        ctk.CTkButton(self, text="Connect & Initialize Schema", fg_color=PALETTE["green"], hover_color=PALETTE["green_bright"], command=self._submit).pack(pady=(6, 14))

    def _field(self, parent, label, default, show=None):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text=label, width=90, anchor="w", text_color=PALETTE["text"]).pack(side="left")
        ent = styled_entry(row)
        if show:
            ent.configure(show=show)
        ent.insert(0, default)
        ent.pack(side="right", fill="x", expand=True)
        return ent

    def _submit(self):
        host = self.host_e.get().strip() or "127.0.0.1"
        port = int(self.port_e.get().strip() or "5432")
        user = self.user_e.get().strip() or "postgres"
        pwd = self.pass_e.get()
        dbname = self.db_e.get().strip() or "ecostep_qcu_db"

        self.db.update_config(host, port, user, pwd, dbname)
        ok, err = self.db.ensure_initialized()
        if ok:
            if self.save_env_var.get():
                config.save_pg_config(host, port, user, pwd, dbname)
            self.on_success()
            self.destroy()
        else:
            self.err_lbl.configure(text=f"Connection failed: {err}")


class SiaBridgeSetupDialog(ctk.CTkToplevel):
    """Modal dialog to configure SIA101 Web App (Render / localhost) XML bridge settings."""

    def __init__(self, master, sia_sync, on_saved):
        super().__init__(master)
        self.sia_sync = sia_sync
        self.on_saved = on_saved
        self.title("Connect to SIA101 Web Bridge (Render / Flask)")
        self.geometry("480x420")
        self.resizable(False, False)
        self.configure(fg_color=PALETTE["card"])
        self.transient(master)
        self.grab_set()

        cfg = sia_sync.cfg
        ctk.CTkLabel(
            self,
            text="SIA101 Web App XML Bridge Setup",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=PALETTE["text"],
        ).pack(pady=(16, 4))
        ctk.CTkLabel(
            self,
            text="Sync local PostgreSQL telemetry to your live Render web dashboard (zero PII).",
            font=ctk.CTkFont(size=12),
            text_color=PALETTE["muted"],
        ).pack(pady=(0, 12))

        frm = ctk.CTkFrame(self, fg_color="transparent")
        frm.pack(fill="x", padx=26)

        self.url_e = self._field(frm, "Bridge URL", cfg.get("bridge_url", ""), placeholder="https://your-app.onrender.com")
        self.key_e = self._field(frm, "API Key", cfg.get("api_key", ""), placeholder="EQC_API_KEY from Render", show="*")
        self.tile_e = self._field(frm, "Tile ID", cfg.get("tile_id", "TILE-01"), placeholder="TILE-01")
        self.interval_e = self._field(frm, "Sync (sec)", str(cfg.get("sync_interval", 15)), placeholder="15")

        opts = ctk.CTkFrame(self, fg_color="transparent")
        opts.pack(fill="x", padx=26, pady=(6, 4))
        self.show_key_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            opts, text="Show API Key", variable=self.show_key_var,
            text_color=PALETTE["muted"], command=self._toggle_key_vis
        ).pack(side="left")

        self.auto_sync_var = ctk.BooleanVar(value=bool(cfg.get("auto_sync", True)))
        ctk.CTkCheckBox(
            opts, text="Auto-sync in background", variable=self.auto_sync_var,
            text_color=PALETTE["text"]
        ).pack(side="right")

        self.save_env_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            self, text="Save SIA bridge settings locally in .env",
            variable=self.save_env_var, text_color=PALETTE["text"]
        ).pack(pady=(4, 6))

        self.status_lbl = ctk.CTkLabel(
            self, text="", text_color=PALETTE["muted"], wraplength=420, font=ctk.CTkFont(size=11)
        )
        self.status_lbl.pack(pady=(2, 8))

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(pady=(2, 14))
        self.test_btn = ctk.CTkButton(
            btns, text="Test Connection", width=150,
            fg_color=PALETTE["card_soft"], hover_color=PALETTE["sidebar_hover"],
            border_width=1, border_color=PALETTE["border"], text_color=PALETTE["text"],
            font=ctk.CTkFont(weight="bold"), command=self._test_connection
        )
        self.test_btn.pack(side="left", padx=(0, 10))
        ctk.CTkButton(
            btns, text="Save & Sync Now", width=160,
            fg_color=PALETTE["green"], hover_color=PALETTE["green_bright"],
            font=ctk.CTkFont(weight="bold"), command=self._save
        ).pack(side="left")

    def _field(self, parent, label, default, placeholder="", show=None):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text=label, width=90, anchor="w", text_color=PALETTE["text"]).pack(side="left")
        ent = styled_entry(row, placeholder=placeholder)
        if show:
            ent.configure(show=show)
        if default:
            ent.insert(0, default)
        ent.pack(side="right", fill="x", expand=True)
        return ent

    def _toggle_key_vis(self):
        self.key_e.configure(show="" if self.show_key_var.get() else "*")

    def _test_connection(self):
        url = self.url_e.get().strip()
        key = self.key_e.get().strip()
        self.test_btn.configure(state="disabled", text="Testing...")
        self.status_lbl.configure(
            text="Pinging SIA bridge (Render free tier may take ~20-35s on cold start)...",
            text_color=PALETTE["amber"],
        )

        def _worker():
            ok, msg = self.sia_sync.test_connection(bridge_url=url, api_key=key)

            def _finish():
                if not self.winfo_exists():
                    return
                self.test_btn.configure(state="normal", text="Test Connection")
                self.status_lbl.configure(
                    text=msg,
                    text_color=PALETTE["green_bright"] if ok else PALETTE["danger"],
                )

            self.after(0, _finish)

        threading.Thread(target=_worker, daemon=True).start()

    def _save(self):
        url = self.url_e.get().strip().rstrip("/")
        key = self.key_e.get().strip()
        tile = self.tile_e.get().strip() or "TILE-01"
        try:
            interval = max(5, min(300, int(self.interval_e.get().strip() or "15")))
        except ValueError:
            interval = 15
        auto_sync = bool(self.auto_sync_var.get())

        if url and not url.startswith(("http://", "https://")):
            self.status_lbl.configure(
                text="Bridge URL must start with http:// or https://.",
                text_color=PALETTE["danger"],
            )
            return

        self.sia_sync.update_config(url, key, tile_id=tile, auto_sync=auto_sync, sync_interval=interval)
        if self.save_env_var.get():
            config.save_sia_config(url, key, tile_id=tile, auto_sync=auto_sync, sync_interval=interval)
        self.on_saved()
        self.destroy()


class EcoStepApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("green")

        self.title("ECOSTEP QCU — Footstep Energy Telemetry & Monitoring System (IPT2)")
        self.geometry("1340x840")
        self.minsize(1140, 720)
        self.configure(fg_color=PALETTE["bg"])

        ico = ensure_ico_file(config.LOGO_PATH, config.ASSETS_DIR)
        if ico:
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

        self.db = EcoStepDatabase()
        self.serial_q = queue.Queue(maxsize=256)
        self.sia_q = queue.Queue(maxsize=128)
        self.worker = SerialTelemetryWorker(self.serial_q)
        self.sia_sync = SiaBridgeSyncService(
            self.db,
            event_queue=self.sia_q,
            get_sign_mode=self._get_current_sign_mode,
        )
        self.active_run_id = None
        self._sia_sync_debounce_id = None

        self.wave_x = deque(maxlen=40)
        self.wave_v = deque(maxlen=40)
        self.step_counter = 0
        self.demo_volts = 0.0
        self.live_chart_mode = "LIVE"

        self._banner_photo = None
        self._banner_leaf = None
        self._banner_size = (0, 0, None)
        self._sb_wave_photo = None
        self._icons = {}
        self.active_tab = "live"

        self._build_icons()
        self._build_layout()
        self._init_database_on_boot()
        self.sia_sync.start()
        self.after(80, self._poll_serial_queue)
        self.after(180, self._tick_meter_pulse)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _get_current_sign_mode(self):
        time_tab = getattr(self, "tabs", {}).get("time")
        return getattr(time_tab, "sign_mode", "Dim") if time_tab else "Dim"

    def _build_icons(self):
        specs = {
            "live": ("live", 16, "#E8F5E4"),
            "time": ("time", 16, "#E8F5E4"),
            "runs": ("runs", 16, "#E8F5E4"),
            "signs": ("bolt", 16, "#E8F5E4"),
            "components": ("cube", 16, "#E8F5E4"),
            "usb": ("usb", 15, "#07150D"),
            "db": ("db", 15, "#CBE7D2"),
            "bolt_btn": ("bolt", 14, "#FFFFFF"),
            "meter": ("leaf", 15, "#22C55E"),
            "graph": ("runs", 15, "#22C55E"),
            "stream": ("db", 15, "#22C55E"),
        }
        for key, (kind, sz, col) in specs.items():
            pil_ic = make_icon(kind, size=sz, color=col)
            self._icons[key] = ctk.CTkImage(light_image=pil_ic, dark_image=pil_ic, size=(sz, sz))

    def _build_layout(self):
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ---------------- NEON EMERALD SIDEBAR ----------------
        self.sidebar = ctk.CTkFrame(self, width=264, fg_color=PALETTE["sidebar_bg"], corner_radius=0, border_width=1, border_color="#142C1E")
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=16, pady=(14, 6))
        if os.path.exists(config.LOGO_PATH):
            circ_logo = make_circular_logo(config.LOGO_PATH, size=50)
            logo_img = ctk.CTkImage(light_image=circ_logo, dark_image=circ_logo, size=(50, 50))
            ctk.CTkLabel(brand, image=logo_img, text="").pack(side="left", padx=(0, 10))
        tbox = ctk.CTkFrame(brand, fg_color="transparent")
        tbox.pack(side="left", fill="x")
        ctk.CTkLabel(tbox, text="ECOSTEP QCU", font=ctk.CTkFont(size=17, weight="bold"), text_color="#FFFFFF").pack(anchor="w")
        ctk.CTkLabel(tbox, text="Recycled Kinetic Mat", font=ctk.CTkFont(size=11, weight="bold"), text_color=PALETTE["gold"]).pack(anchor="w")
        ctk.CTkLabel(tbox, text="IPT2 + SIA101 Suite", font=ctk.CTkFont(size=10), text_color="#94BD9A").pack(anchor="w")

        ctk.CTkFrame(self.sidebar, height=1, fg_color="#1A3826").pack(fill="x", padx=16, pady=(2, 6))
        ctk.CTkLabel(self.sidebar, text="NAVIGATION", font=ctk.CTkFont(size=10, weight="bold"), text_color="#7AA384").pack(anchor="w", padx=18, pady=(0, 2))

        self.nav_btns = {}
        nav_items = [
            ("live", "Live Telemetry"),
            ("time", "Time & Equivalences"),
            ("runs", "100-Step Runs"),
            ("signs", "5V Sign Tests"),
            ("components", "Asset Inventory"),
        ]
        for key, label in nav_items:
            b = ctk.CTkButton(
                self.sidebar,
                text=f"  {label}",
                image=self._icons[key],
                compound="left",
                anchor="w",
                height=34,
                corner_radius=10,
                border_width=0,
                border_color="#4ADE80",
                fg_color="transparent",
                hover_color=PALETTE["sidebar_hover"],
                text_color="#E8F5E4",
                font=ctk.CTkFont(size=13, weight="bold"),
                command=lambda k=key: self.show_tab(k),
            )
            b.pack(fill="x", padx=14, pady=2)
            self.nav_btns[key] = b

        # USB-C Serial Box
        ser_box = ctk.CTkFrame(self.sidebar, fg_color=PALETTE["sidebar_card"], corner_radius=12, border_width=1, border_color="#1C3A28")
        ser_box.pack(fill="x", padx=14, pady=(8, 4))
        ctk.CTkLabel(ser_box, text="USB-C SERIAL (115,200)", font=ctk.CTkFont(size=10, weight="bold"), text_color="#8CB999").pack(anchor="w", padx=12, pady=(8, 2))

        self.port_var = ctk.StringVar(value=config.DEFAULT_SERIAL_PORT)
        self.port_menu = styled_option(ser_box, self.port_var, list_serial_ports())
        self.port_menu.configure(height=28, fg_color="#12271B", button_color="#1C3D2A", button_hover_color=PALETTE["green"], text_color="#EBF7EE")
        self.port_menu.pack(fill="x", padx=12, pady=3)

        self.connect_btn = ctk.CTkButton(
            ser_box, text="Connect Telemetry", image=self._icons["usb"], compound="left",
            height=29, fg_color=PALETTE["green_bright"], hover_color="#16A34A", text_color="#06140C",
            font=ctk.CTkFont(weight="bold"), command=self._toggle_serial
        )
        self.connect_btn.pack(fill="x", padx=12, pady=(3, 4))

        self.serial_status_lbl = ctk.CTkLabel(ser_box, text="● Disconnected", font=ctk.CTkFont(size=11, weight="bold"), text_color=PALETTE["amber"])
        self.serial_status_lbl.pack(anchor="w", padx=12, pady=(0, 8))

        # PostgreSQL Status Box
        db_box = ctk.CTkFrame(self.sidebar, fg_color=PALETTE["sidebar_card"], corner_radius=12, border_width=1, border_color="#1C3A28")
        db_box.pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(db_box, text="POSTGRESQL DB (3NF)", font=ctk.CTkFont(size=10, weight="bold"), text_color="#8CB999").pack(anchor="w", padx=12, pady=(8, 2))
        self.db_status_lbl = ctk.CTkLabel(db_box, text="● Checking...", font=ctk.CTkFont(size=11, weight="bold"), text_color="#E8F5E4")
        self.db_status_lbl.pack(anchor="w", padx=12, pady=(0, 4))
        ctk.CTkButton(
            db_box, text="DB Connection Setup", image=self._icons["db"], compound="left",
            height=28, fg_color="#152E20", hover_color="#1F422E", border_width=1, border_color="#244E36",
            command=self.open_pg_dialog
        ).pack(fill="x", padx=12, pady=(0, 8))

        # SIA101 Web Bridge Box
        sia_box = ctk.CTkFrame(self.sidebar, fg_color=PALETTE["sidebar_card"], corner_radius=12, border_width=1, border_color="#1C3A28")
        sia_box.pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(sia_box, text="SIA WEB BRIDGE (XML)", font=ctk.CTkFont(size=10, weight="bold"), text_color="#8CB999").pack(anchor="w", padx=12, pady=(8, 2))
        init_sia_txt = "● Ready to Sync" if self.sia_sync.is_configured else "● Not Configured"
        init_sia_col = PALETTE["teal"] if self.sia_sync.is_configured else PALETTE["amber"]
        self.sia_status_lbl = ctk.CTkLabel(sia_box, text=init_sia_txt, font=ctk.CTkFont(size=11, weight="bold"), text_color=init_sia_col)
        self.sia_status_lbl.pack(anchor="w", padx=12, pady=(0, 4))
        sia_btns = ctk.CTkFrame(sia_box, fg_color="transparent")
        sia_btns.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkButton(
            sia_btns, text="Sync Now", height=27,
            fg_color=PALETTE["green"], hover_color=PALETTE["green_bright"], text_color="#FFFFFF",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=lambda: self.trigger_sia_sync(immediate=True),
        ).pack(side="left", expand=True, fill="x", padx=(0, 4))
        ctk.CTkButton(
            sia_btns, text="Setup", height=27, width=72,
            fg_color="#152E20", hover_color="#1F422E", border_width=1, border_color="#244E36",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.open_sia_dialog,
        ).pack(side="right")

        self.active_run_lbl = ctk.CTkLabel(self.sidebar, text="Active Run: None", font=ctk.CTkFont(size=11, weight="bold"), text_color=PALETTE["gold"])
        self.active_run_lbl.pack(anchor="w", padx=18, pady=(4, 2))

        # Subtle aurora wave footer inside sidebar
        self.sb_footer = tk.Canvas(self.sidebar, height=52, highlightthickness=0, bd=0, bg=pick(PALETTE["sidebar_bg"], "Dark"))
        self.sb_footer.pack(side="bottom", fill="x")
        self.sb_footer.bind("<Configure>", self._draw_sidebar_footer)

        self.theme_switch = ctk.CTkSwitch(
            self.sb_footer, text="Dark Eco Mode", text_color="#E8F5E4",
            fg_color="#1D3B2A", progress_color=PALETTE["green_bright"], button_color="#FFFFFF",
            bg_color=pick(PALETTE["sidebar_bg"], "Dark"),
            command=self._toggle_theme
        )
        self.theme_switch.select()
        self.sb_switch_win = self.sb_footer.create_window(18, 26, anchor="w", window=self.theme_switch)

        # ---------------- MAIN WORKSPACE (AURORA TOP BANNER + CONTENT) ----------------
        right_shell = ctk.CTkFrame(self, fg_color="transparent")
        right_shell.grid(row=0, column=1, sticky="nsew", padx=16, pady=12)
        right_shell.grid_columnconfigure(0, weight=1)
        right_shell.grid_rowconfigure(1, weight=1)

        self.topbar_canvas = tk.Canvas(right_shell, height=74, highlightthickness=0, bd=0, bg=pick(PALETTE["bg"], "Dark"))
        self.topbar_canvas.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.topbar_canvas.bind("<Configure>", self._on_topbar_resize)

        self.page_title_str = "Live Telemetry Monitor"
        self.page_sub_str = "Recycled Kinetic Mat • Real-Time USB-C Stream & 4x4 PZT Pulse Gauge"

        # Docked right controls (color-matched seamlessly with right edge of aurora banner)
        top_card_bg = pick(PALETTE["card"], "Dark")
        self.tright = ctk.CTkFrame(self.topbar_canvas, fg_color=top_card_bg, bg_color=top_card_bg, corner_radius=0)
        self.top_hw_pill = ctk.CTkLabel(
            self.tright,
            text="● ESP32 OFFLINE",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=PALETTE["card_soft"],
            bg_color=top_card_bg,
            text_color=PALETTE["green_bright"],
            corner_radius=14,
            padx=12,
            pady=5,
        )
        self.top_hw_pill.pack(side="left", padx=(4, 8), pady=4)

        self.quick_step_btn = ctk.CTkButton(
            self.tright, text="Quick Step", image=self._icons["bolt_btn"], compound="left",
            width=114, height=32, corner_radius=14,
            fg_color=PALETTE["amber"], hover_color="#D97706", bg_color=top_card_bg, text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"), command=self._on_quick_step
        )
        self.quick_step_btn.pack(side="left", padx=(0, 8), pady=4)

        self.top_mode_seg = ctk.CTkSegmentedButton(
            self.tright,
            values=["Eco Light", "Forest Dark"],
            command=self._on_top_theme_seg,
            fg_color=PALETTE["card_soft"],
            selected_color=PALETTE["green"],
            selected_hover_color=PALETTE["green_bright"],
            unselected_color=PALETTE["card_soft"],
            unselected_hover_color=PALETTE["sidebar_hover"],
            bg_color=top_card_bg,
            text_color=PALETTE["text"],
            corner_radius=14,
        )
        self.top_mode_seg.set("Forest Dark")
        self.top_mode_seg.pack(side="left", padx=(0, 2), pady=4)
        self.topbar_controls_win = self.topbar_canvas.create_window(10, 37, anchor="e", window=self.tright)

        self.content = ctk.CTkFrame(right_shell, fg_color="transparent")
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.tabs = {
            "live": self._build_live_tab(),
            "time": TimeAnalyticsView(self.content, self),
            "runs": MeasurementRunsView(self.content, self),
            "signs": SignTestsView(self.content, self),
            "components": ComponentsView(self.content, self),
        }
        style_treeview("Dark")
        self.show_tab("live")

    def _draw_sidebar_footer(self, event=None):
        mode = ctk.get_appearance_mode()
        w = self.sb_footer.winfo_width() or 264
        h = self.sb_footer.winfo_height() or 64
        sb_bg = pick(PALETTE["sidebar_bg"], mode)
        self.sb_footer.configure(bg=sb_bg)
        self.theme_switch.configure(bg_color=sb_bg)
        img = render_sidebar_aurora(w, h, mode)
        self._sb_wave_photo = ImageTk.PhotoImage(img)
        self.sb_footer.delete("sb_art")
        self.sb_footer.create_image(0, 0, anchor="nw", image=self._sb_wave_photo, tags="sb_art")
        self.sb_footer.tag_raise(self.sb_switch_win)

    def _on_topbar_resize(self, event):
        if event.width > 120 and event.height > 30:
            self._redraw_topbar(event.width, event.height)

    def _redraw_topbar(self, w=None, h=None):
        mode = ctk.get_appearance_mode()
        w = w or self.topbar_canvas.winfo_width() or 1020
        h = h or self.topbar_canvas.winfo_height() or 74
        size_key = (w, h, mode)
        if size_key == self._banner_size and self.topbar_canvas.find_withtag("topbar_title"):
            self.topbar_canvas.itemconfigure("topbar_title", text=self.page_title_str)
            self.topbar_canvas.itemconfigure("topbar_sub", text=self.page_sub_str)
            return
        self._banner_size = size_key

        card_col = pick(PALETTE["card"], mode)
        self.topbar_canvas.configure(bg=pick(PALETTE["bg"], mode))
        self.tright.configure(fg_color=card_col, bg_color=card_col)
        self.top_hw_pill.configure(bg_color=card_col)
        self.quick_step_btn.configure(bg_color=card_col)
        self.top_mode_seg.configure(bg_color=card_col)
        self.topbar_canvas.delete("bg_art")

        img = render_aurora_banner(w, h, mode)
        self._banner_photo = ImageTk.PhotoImage(img)
        self.topbar_canvas.create_image(0, 0, anchor="nw", image=self._banner_photo, tags="bg_art")

        leaf = make_icon("leaf", size=28, color="#22C55E" if mode == "Dark" else "#15803D")
        self._banner_leaf = ImageTk.PhotoImage(leaf)
        self.topbar_canvas.create_image(20, h // 2, anchor="w", image=self._banner_leaf, tags="bg_art")

        title_col = "#FFFFFF" if mode == "Dark" else "#122618"
        sub_col = "#A7D7B8" if mode == "Dark" else "#4C6A52"
        self.topbar_canvas.create_text(58, h // 2 - 11, anchor="w", text=self.page_title_str, font=("Segoe UI", 15, "bold"), fill=title_col, tags=("bg_art", "topbar_title"))
        self.topbar_canvas.create_text(58, h // 2 + 12, anchor="w", text=self.page_sub_str, font=("Segoe UI", 9), fill=sub_col, tags=("bg_art", "topbar_sub"))

        self.topbar_canvas.coords(self.topbar_controls_win, w - 12, h // 2)
        self.topbar_canvas.tag_raise(self.topbar_controls_win)

    def _build_live_tab(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        kpis = ctk.CTkFrame(frame, fg_color="transparent")
        kpis.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        kpis.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.kpi_steps = NeonKpiCard(kpis, "FOOTSTEP ENGINE", "D32", "0", "Cadence: 0.0 steps/min", PALETTE["green_bright"], "foot", mode="Dark")
        self.kpi_steps.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.kpi_volts = NeonKpiCard(kpis, "SUPERCAP VOLTAGE", "D34 2X", "0.00 V", "Raw sample: 0 / 1023", PALETTE["amber"], "cap", mode="Dark")
        self.kpi_volts.grid(row=0, column=1, sticky="ew", padx=6)

        self.kpi_joules = NeonKpiCard(kpis, "BATTERY & SoC", "BANK", "0.00 J", "SoC: 0.00% (0.0000 Wh)", PALETTE["teal"], "battery", mode="Dark")
        self.kpi_joules.grid(row=0, column=2, sticky="ew", padx=6)

        self.kpi_db = NeonKpiCard(kpis, "PG18 LEDGER", "3NF", "0 logs", "PostgreSQL ecostep_qcu_db", PALETTE["purple"], "ledger", mode="Dark")
        self.kpi_db.grid(row=0, column=3, sticky="ew", padx=(6, 0))

        self.kpi_cards = (self.kpi_steps, self.kpi_volts, self.kpi_joules, self.kpi_db)

        mid = ctk.CTkFrame(frame, fg_color="transparent")
        mid.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        mid.grid_columnconfigure(0, weight=0)
        mid.grid_columnconfigure(1, weight=1)

        meter_card = ctk.CTkFrame(mid, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=14)
        meter_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        m_head = ctk.CTkFrame(meter_card, fg_color="transparent")
        m_head.pack(fill="x", padx=14, pady=(10, 0))
        ctk.CTkLabel(m_head, text="  Kinetic Eco-Mat & Voltmeter", image=self._icons["meter"], compound="left", font=ctk.CTkFont(size=13, weight="bold"), text_color=PALETTE["text"]).pack(side="left")

        self.meter = VoltageMeterCanvas(meter_card, mode="Dark", on_tile_click=self._on_quick_step)
        self.meter.pack(padx=10, pady=2)

        ctl_row = ctk.CTkFrame(meter_card, fg_color="transparent")
        ctl_row.pack(fill="x", padx=12, pady=(2, 10))
        mode_row = ctk.CTkFrame(ctl_row, fg_color="transparent")
        mode_row.pack(fill="x")
        self.bench_btn = ctk.CTkButton(
            mode_row, text="▶ Bench Mode", width=134, height=30, corner_radius=8,
            fg_color=PALETTE["green"], hover_color=PALETTE["green_bright"],
            border_width=2, border_color="#86EFAC", font=ctk.CTkFont(weight="bold"),
            command=lambda: self._set_hw_mode("M0"),
        )
        self.bench_btn.pack(side="left", expand=True, padx=(0, 4))
        self.tile_btn = ctk.CTkButton(
            mode_row, text="Tile ADC", width=134, height=30, corner_radius=8,
            fg_color=PALETTE["card_soft"], hover_color="#D97706",
            border_width=1, border_color=PALETTE["border"], text_color=PALETTE["amber"],
            font=ctk.CTkFont(weight="bold"), command=lambda: self._set_hw_mode("M1"),
        )
        self.tile_btn.pack(side="right", expand=True, padx=(4, 0))

        wave_card = ctk.CTkFrame(mid, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=14)
        wave_card.grid(row=0, column=1, sticky="nsew")
        w_head = ctk.CTkFrame(wave_card, fg_color="transparent")
        w_head.pack(fill="x", padx=14, pady=(10, 0))
        ctk.CTkLabel(w_head, text="  Telemetry & Time-Horizon Graph", image=self._icons["graph"], compound="left", font=ctk.CTkFont(size=13, weight="bold"), text_color=PALETTE["text"]).pack(side="left")
        self.live_chart_seg = ctk.CTkSegmentedButton(
            w_head,
            values=["LIVE", "1H", "10H", "24H", "48H", "7D"],
            command=self._on_live_chart_mode,
            fg_color=PALETTE["card_soft"],
            selected_color=PALETTE["green"],
            selected_hover_color=PALETTE["green_bright"],
            unselected_color=PALETTE["card_soft"],
            unselected_hover_color=PALETTE["sidebar_hover"],
            text_color=PALETTE["text"],
            corner_radius=10,
        )
        self.live_chart_seg.set("LIVE")
        self.live_chart_seg.pack(side="right")

        self.wave_fig = Figure(figsize=(5.5, 2.7), dpi=96)
        self.wave_ax = self.wave_fig.add_subplot(111)
        self.wave_canvas = FigureCanvasTkAgg(self.wave_fig, master=wave_card)
        self.wave_canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self._redraw_waveform()

        log_card = ctk.CTkFrame(frame, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=14)
        log_card.grid(row=2, column=0, sticky="nsew")
        log_card.grid_rowconfigure(1, weight=1)
        log_card.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(log_card, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=14, pady=(10, 4))
        ctk.CTkLabel(head, text="  Live USB-C Telemetry Stream (telemetry_logs)", image=self._icons["stream"], compound="left", font=ctk.CTkFont(size=14, weight="bold"), text_color=PALETTE["text"]).pack(side="left")
        ctk.CTkButton(head, text="↻ Reset ESP32 Counter (R)", height=28, corner_radius=8, fg_color=PALETTE["card_soft"], hover_color=PALETTE["sidebar_hover"], border_width=1, border_color=PALETTE["border"], text_color=PALETTE["text"], command=self._reset_esp).pack(side="right")

        cols = ("log_id", "run_id", "step_number", "adc_raw", "adc_voltage", "baud_rate", "recorded_at")
        self.live_tree = ttk.Treeview(log_card, columns=cols, show="headings", style="Eco.Treeview")
        for c, w in zip(cols, (70, 70, 100, 110, 110, 95, 190)):
            self.live_tree.heading(c, text=c.upper())
            self.live_tree.column(c, width=w, anchor="center")
        self.live_tree.grid(row=1, column=0, sticky="nsew", padx=(12, 0), pady=(4, 12))
        sb = ctk.CTkScrollbar(log_card, command=self.live_tree.yview)
        sb.grid(row=1, column=1, sticky="ns", padx=(2, 10), pady=(4, 12))
        self.live_tree.configure(yscrollcommand=sb.set)

        self.diag_drawer = SerialDiagnosticsDrawer(frame, on_send=self._send_diag_command, mode="Dark")
        self.diag_drawer.grid(row=3, column=0, sticky="ew", pady=(10, 0))

        return frame

    def show_tab(self, name):
        self.active_tab = name
        titles = {
            "live": ("Live Telemetry Monitor", "Recycled Kinetic Mat • Real-Time USB-C Stream & 4x4 PZT Pulse Gauge"),
            "time": ("Time Horizons & Device Equivalences", "1H / 10H Shift / 24H / 48H / 7D Analytics • Battery SoC % & Connected Loads"),
            "runs": ("100-Step Benchmark Runs", "measurement_runs CRUD • mWh to Joules Analytics & Soft-Delete Ledger"),
            "signs": ("5V Emergency Sign Verification", "sign_tests CRUD • Full (1.5 kΩ) vs Dim (10 kΩ) Power & Runtime Verification"),
            "components": ("Project Asset & Component Inventory", "components CRUD • Hardware Specifications & Inspection Readiness"),
        }
        if name in titles:
            self.page_title_str, self.page_sub_str = titles[name]
            self._redraw_topbar()
        for k, f in self.tabs.items():
            if k == name:
                f.grid(row=0, column=0, sticky="nsew")
                self.nav_btns[k].configure(fg_color=PALETTE["sidebar_active"], border_width=1)
            else:
                f.grid_forget()
                self.nav_btns[k].configure(fg_color="transparent", border_width=0)
        self.refresh_all()

    def _apply_theme_mode(self, mode):
        ctk.set_appearance_mode(mode)
        style_treeview(mode)
        self._redraw_topbar()
        self._draw_sidebar_footer()
        for card in self.kpi_cards:
            card.set_mode(mode)
        self.meter.set_mode(mode)
        self.diag_drawer.set_mode(mode)
        if self.active_tab == "live":
            self._redraw_waveform()
        else:
            self.tabs[self.active_tab].refresh()
        configure_tree_zebra(self.live_tree, mode)
        if mode == "Dark":
            self.theme_switch.select()
            self.top_mode_seg.set("Forest Dark")
        else:
            self.theme_switch.deselect()
            self.top_mode_seg.set("Eco Light")

    def _toggle_theme(self):
        self._apply_theme_mode("Dark" if self.theme_switch.get() else "Light")

    def _on_top_theme_seg(self, val):
        self._apply_theme_mode("Dark" if "Dark" in val else "Light")

    def _on_live_chart_mode(self, val):
        self.live_chart_mode = val
        self._redraw_waveform()

    def _set_hw_mode(self, cmd):
        is_tile = cmd.upper() == "M1"
        if is_tile:
            self.bench_btn.configure(fg_color=PALETTE["card_soft"], border_width=1, border_color=PALETTE["border"], text_color=PALETTE["muted"])
            self.tile_btn.configure(fg_color=PALETTE["amber"], border_width=2, border_color="#FDE68A", text_color="#FFFFFF")
            self.diag_drawer.set_board_mode("TILE")
        else:
            self.bench_btn.configure(fg_color=PALETTE["green"], border_width=2, border_color="#86EFAC", text_color="#FFFFFF")
            self.tile_btn.configure(fg_color=PALETTE["card_soft"], border_width=1, border_color=PALETTE["border"], text_color=PALETTE["amber"])
            self.diag_drawer.set_board_mode("BENCH")
        if not self.worker.send_command(cmd):
            self.diag_drawer.log_event("info", "LOCAL", f"Switched UI mode preview -> {'TILE ADC (M1)' if is_tile else 'BENCH MODE (M0)'} (ESP32 offline)")

    def _send_diag_command(self, cmd):
        if not self.worker.send_command(cmd):
            self.diag_drawer.log_event("err", "WARN", f"Cannot send '{cmd}': ESP32 is offline. Connect USB-C first.")

    def _on_quick_step(self):
        # Send live step trigger to ESP32 if connected; otherwise run bench step & log to DB
        if self.worker.send_command("S"):
            return
        self.step_counter += 1
        self.demo_volts = round(min(5.60, self.demo_volts + 0.34) if self.demo_volts < 5.4 else 0.34, 2)
        adc_raw = int((self.demo_volts / 6.6) * 1023)
        sub_txt = f"⚠ Near 6.6V D34 limit! ({adc_raw}/1023)" if self.demo_volts >= 5.5 else f"Demo preview: {adc_raw} / 1023"
        self.kpi_steps.set_values(val_text=str(self.step_counter))
        self.kpi_volts.set_values(val_text=f"{self.demo_volts:.2f} V", sub_text=sub_txt)
        self.meter.update_reading(self.demo_volts, adc_raw=adc_raw, pulse=True)
        self.wave_x.append(self.step_counter)
        self.wave_v.append(self.demo_volts)
        self._redraw_waveform()
        if self.db.connected and self.active_run_id:
            self.db.insert_telemetry_log(self.active_run_id, self.step_counter, adc_raw, self.demo_volts)
            self.refresh_all()
            self.trigger_sia_sync()
            self.diag_drawer.log_event("raw", "BENCH", f"DATA,{self.step_counter},{adc_raw},{self.demo_volts:.2f} (logged to PG & queued for SIA)", count_rx=True)
        else:
            self.diag_drawer.log_event("raw", "DEMO", f"DATA,{self.step_counter},{adc_raw},{self.demo_volts:.2f} (offline bench preview)", count_rx=True)

    def _init_database_on_boot(self):
        ok, err = self.db.ensure_initialized()
        if ok:
            self._on_db_ready()
        else:
            self.db_status_lbl.configure(text="● Auth Required", text_color="#FCA5A5")
            self.after(300, self.open_pg_dialog)

    def open_pg_dialog(self):
        PostgresSetupDialog(self, self.db, self._on_db_ready)

    def open_sia_dialog(self):
        SiaBridgeSetupDialog(self, self.sia_sync, self._on_sia_saved)

    def _on_sia_saved(self):
        if self.sia_sync.is_configured:
            self.sia_status_lbl.configure(text="● Syncing...", text_color=PALETTE["teal"])
            self.trigger_sia_sync(immediate=True)
        else:
            self.sia_status_lbl.configure(text="● Not Configured", text_color=PALETTE["amber"])

    def trigger_sia_sync(self, immediate=False):
        if not self.sia_sync.is_configured:
            if immediate:
                self.open_sia_dialog()
            return
        if self._sia_sync_debounce_id is not None:
            try:
                self.after_cancel(self._sia_sync_debounce_id)
            except Exception:
                pass
            self._sia_sync_debounce_id = None
        if immediate:
            self.sia_sync.trigger_sync()
        else:
            # Batch rapid footsteps for 1.5s before sending one clean XML run
            self._sia_sync_debounce_id = self.after(1500, self._flush_debounced_sia_sync)

    def _flush_debounced_sia_sync(self):
        self._sia_sync_debounce_id = None
        self.sia_sync.trigger_sync()

    def _on_db_ready(self):
        self.db_status_lbl.configure(text=f"● {self.db.cfg['dbname']}", text_color="#4ADE80")
        runs = self.db.list_runs(include_deleted=False)
        if not runs:
            comps = self.db.list_components()
            if comps:
                row = self.db.create_run(
                    component_id=comps[0]["component_id"],
                    operator_name="QCU Lab Bench",
                    steps_count=100,
                    energy_mwh=0.0,
                    charging_path="Path A",
                    status="Pending",
                )
                self.active_run_id = row["run_id"]
        else:
            self.active_run_id = runs[0]["run_id"]
        self.refresh_active_run_label()
        self.refresh_all()
        if self.sia_sync.is_configured:
            self.trigger_sia_sync(immediate=True)

    def refresh_active_run_label(self):
        txt = f"Active Run: #{self.active_run_id}" if self.active_run_id else "Active Run: None"
        self.active_run_lbl.configure(text=txt)

    def _toggle_serial(self):
        if self.worker.connected:
            self.worker.disconnect()
        else:
            self.port_menu.configure(values=list_serial_ports())
            self.worker.connect(self.port_var.get())

    def _reset_esp(self):
        self.worker.send_command("R")
        self.step_counter = 0
        self.demo_volts = 0.0
        self.wave_x.clear()
        self.wave_v.clear()
        self.kpi_steps.set_values(val_text="0")
        self.kpi_volts.set_values(val_text="0.00 V", sub_text="Raw sample: 0 / 1023")
        self.meter.update_reading(0.0, adc_raw=0, pulse=False)
        self._redraw_waveform()

    def _poll_serial_queue(self):
        updated = False
        while True:
            try:
                evt = self.serial_q.get_nowait()
            except queue.Empty:
                break

            kind = evt.get("kind")
            if kind == "connection":
                if evt["connected"]:
                    self.serial_status_lbl.configure(text=f"● {evt['port']} LIVE", text_color="#4ADE80")
                    self.top_hw_pill.configure(text=f"● {evt['port']} LIVE", text_color=PALETTE["green_bright"])
                    self.connect_btn.configure(text="Disconnect", fg_color=PALETTE["danger"], text_color="#FFFFFF")
                    self.diag_drawer.log_event("status", "CONN", f"Connected to {evt['port']} at 115,200 baud")
                else:
                    self.serial_status_lbl.configure(text="● Disconnected", text_color=PALETTE["amber"])
                    self.top_hw_pill.configure(text="● ESP32 OFFLINE", text_color=PALETTE["green_bright"])
                    self.connect_btn.configure(text="Connect Telemetry", fg_color=PALETTE["green_bright"], text_color="#06140C")
                    self.diag_drawer.log_event("info", "CONN", f"Disconnected from {evt['port']}")
            elif kind == "error":
                self.serial_status_lbl.configure(text="● Port Error", text_color="#FCA5A5")
                self.diag_drawer.log_event("err", "ERR", evt.get("message", "Unknown serial error"))
            elif kind == "tx":
                self.diag_drawer.log_event("tx", "TX", evt.get("command", ""), count_tx=True)
            elif kind == "status":
                bmode = evt.get("mode", "BENCH")
                self.diag_drawer.set_board_mode(bmode)
                self.diag_drawer.log_event("status", "STAT", evt.get("raw_line", bmode), count_rx=True)
                if "TILE" in bmode.upper():
                    self.bench_btn.configure(fg_color=PALETTE["card_soft"], border_width=1, border_color=PALETTE["border"], text_color=PALETTE["muted"])
                    self.tile_btn.configure(fg_color=PALETTE["amber"], border_width=2, border_color="#FDE68A", text_color="#FFFFFF")
                else:
                    self.bench_btn.configure(fg_color=PALETTE["green"], border_width=2, border_color="#86EFAC", text_color="#FFFFFF")
                    self.tile_btn.configure(fg_color=PALETTE["card_soft"], border_width=1, border_color=PALETTE["border"], text_color=PALETTE["amber"])
            elif kind == "raw":
                self.diag_drawer.log_event("raw", "RAW", evt.get("raw_line", ""), count_rx=True)
            elif kind == "cap":
                raw = evt["adc_raw"]
                volts = evt["adc_voltage"]
                sub_txt = f"⚠ Near 6.6V D34 limit! ({raw}/1023)" if volts >= 5.5 else f"Raw sample: {raw} / 1023"
                self.kpi_volts.set_values(val_text=f"{volts:.2f} V", sub_text=sub_txt)
                self.meter.update_reading(volts, adc_raw=raw, pulse=False)
                self.diag_drawer.log_event("rx_cap", "RX", evt.get("raw_line", f"CAP,{raw},{volts:.2f}"), count_rx=True)
            elif kind == "data":
                self.step_counter = evt["step_number"]
                raw = evt["adc_raw"]
                volts = evt["adc_voltage"]
                sub_txt = f"⚠ Near 6.6V D34 limit! ({raw}/1023)" if volts >= 5.5 else f"Raw sample: {raw} / 1023"
                self.kpi_steps.set_values(val_text=str(self.step_counter))
                self.kpi_volts.set_values(val_text=f"{volts:.2f} V", sub_text=sub_txt)
                self.meter.update_reading(volts, adc_raw=raw, pulse=True)
                self.wave_x.append(self.step_counter)
                self.wave_v.append(volts)
                self._redraw_waveform()
                self.diag_drawer.log_event("rx_data", "RX", evt.get("raw_line", f"DATA,{self.step_counter},{raw},{volts:.2f}"), count_rx=True)

                if self.db.connected and self.active_run_id:
                    self.db.insert_telemetry_log(self.active_run_id, self.step_counter, raw, volts)
                    updated = True
                else:
                    insert_zebra_row(self.live_tree, 0, ("RAM", "-", self.step_counter, raw, f"{volts:.2f}", 115200, "LIVE"))

        if updated:
            self.refresh_all()
            self.trigger_sia_sync()

        while True:
            try:
                sevt = self.sia_q.get_nowait()
            except queue.Empty:
                break
            st = sevt.get("status", "unconfigured")
            msg = sevt.get("message", "")
            color_map = {
                "synced": "#4ADE80",
                "syncing": PALETTE["teal"],
                "offline": PALETTE["amber"],
                "unconfigured": PALETTE["amber"],
                "auth_error": "#FCA5A5",
                "error": "#FCA5A5",
            }
            self.sia_status_lbl.configure(text=f"● {msg}", text_color=color_map.get(st, "#E8F5E4"))
            if sevt.get("detail"):
                self.diag_drawer.log_event(sevt.get("log_tag", "info"), "SIA", sevt["detail"])

        self.after(80, self._poll_serial_queue)

    def _tick_meter_pulse(self):
        self.meter.tick_pulse()
        self.diag_drawer.tick_age()
        self.after(180, self._tick_meter_pulse)

    def _redraw_waveform(self):
        mode = ctk.get_appearance_mode()
        fg = pick(PALETTE["text"], mode)
        self.wave_ax.clear()
        apply_matplotlib_theme(self.wave_fig, self.wave_ax, mode)

        if self.live_chart_mode == "LIVE" or not self.db.connected:
            if self.wave_x:
                self.wave_ax.plot(
                    list(self.wave_x), list(self.wave_v),
                    marker="o", markersize=5, markerfacecolor="#FFFFFF", markeredgecolor=PALETTE["emerald_glow"],
                    color=PALETTE["green_bright"], linewidth=2.4
                )
                self.wave_ax.fill_between(list(self.wave_x), list(self.wave_v), color=PALETTE["green_bright"], alpha=0.22)
            self.wave_ax.set_title("Supercapacitor Charge Curve (D34 • USB-C 115,200 Baud)", color=fg, fontsize=10)
            self.wave_ax.set_ylabel("V_cap (V)", color=fg, fontsize=9)
            self.wave_ax.set_ylim(0, 6.2)
        else:
            ts = self.db.get_timeseries(self.live_chart_mode.lower())
            x = list(range(len(ts["labels"])))
            self.wave_ax.bar(x, ts["joules"], color=PALETTE["green_bright"], alpha=0.85)
            step_tick = max(1, len(x) // 6)
            self.wave_ax.set_xticks(x[::step_tick])
            self.wave_ax.set_xticklabels(ts["labels"][::step_tick], rotation=0)
            self.wave_ax.set_title(
                f"Time-Based Harvest ({self.live_chart_mode}: {ts['total_steps']} steps • {ts['total_joules']:.2f} J)",
                color=fg, fontsize=10,
            )
            self.wave_ax.set_ylabel("Joules (J)", color=fg, fontsize=9)

        self.wave_fig.tight_layout()
        self.wave_canvas.draw_idle()

    def refresh_all(self, force_all=False):
        if not self.db.connected:
            return
        active = getattr(self, "active_tab", "live")
        if force_all or active == "live":
            mode = ctk.get_appearance_mode()
            configure_tree_zebra(self.live_tree, mode)
            summary = self.db.get_dashboard_summary()
            cadence = self.db.get_cadence_spm(minutes=5)
            time_tab = self.tabs["time"]
            eq = analytics.compute_battery_and_equivalences(
                summary["total_joules"],
                battery_cap_wh=time_tab.battery_cap_wh,
                usb_loads=time_tab.usb_loads,
                led_12v_on=time_tab.led_12v_on,
                sign_mode=time_tab.sign_mode,
            )
            self.kpi_steps.set_values(sub_text=f"Cadence: {cadence:.1f} steps/min")
            self.kpi_joules.set_values(
                val_text=f"{summary['total_joules']:.2f} J",
                sub_text=f"SoC: {eq['soc_pct']:.2f}% ({eq['wh_stored']:.4f} Wh)",
            )
            self.kpi_db.set_values(
                val_text=f"{summary['telemetry_count']} logs",
                sub_text=f"{summary['active_runs']} runs • {summary['sign_tests_count']} sign tests",
            )

            logs = self.db.list_telemetry_logs(limit=40)
            self.live_tree.delete(*self.live_tree.get_children())
            for idx, r in enumerate(logs):
                insert_zebra_row(
                    self.live_tree, idx,
                    (
                        r["log_id"], r["run_id"], r["step_number"], r["adc_raw"],
                        f"{float(r['adc_voltage']):.2f}", r["baud_rate"], str(r["recorded_at"])[:19],
                    ),
                )
            if self.live_chart_mode != "LIVE":
                self._redraw_waveform()

        if force_all:
            self.tabs["time"].refresh()
            self.tabs["runs"].refresh()
            self.tabs["signs"].refresh()
            self.tabs["components"].refresh()
        elif active in ("time", "runs", "signs", "components"):
            self.tabs[active].refresh()

    def _on_close(self):
        self.sia_sync.stop()
        self.worker.disconnect()
        self.db.close()
        self.destroy()


def main():
    app = EcoStepApp()
    app.mainloop()


if __name__ == "__main__":
    main()
