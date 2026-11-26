"""EcoStep QCU IPT2 Standalone CustomTkinter Desktop Application."""

from collections import deque
import os
import queue
import tkinter as tk
from tkinter import messagebox, ttk
import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from PIL import Image

from . import analytics, config
from .db import EcoStepDatabase
from .serial_worker import SerialTelemetryWorker, list_serial_ports
from .theme import PALETTE, apply_matplotlib_theme, pick
from .views import (
    ComponentsView,
    MeasurementRunsView,
    SignTestsView,
    TimeAnalyticsView,
    VoltageMeterCanvas,
    style_treeview,
)


class PostgresSetupDialog(ctk.CTkToplevel):
    """Modal dialog to configure PostgreSQL 16/18 credentials cleanly without hardcoding."""

    def __init__(self, master, db, on_success):
        super().__init__(master)
        self.db = db
        self.on_success = on_success
        self.title("Connect to Local PostgreSQL (ecostep_qcu_db)")
        self.geometry("430x370")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        cfg = db.cfg
        ctk.CTkLabel(self, text="PostgreSQL 16/18 Local Connection", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(16, 4))
        ctk.CTkLabel(self, text="Enter the local PostgreSQL credentials to initialize ecostep_qcu_db.", font=ctk.CTkFont(size=12), text_color=PALETTE["muted"]).pack(pady=(0, 12))

        frm = ctk.CTkFrame(self, fg_color="transparent")
        frm.pack(fill="x", padx=28)

        self.host_e = self._field(frm, "Host", cfg["host"])
        self.port_e = self._field(frm, "Port", str(cfg["port"]))
        self.user_e = self._field(frm, "User", cfg["user"])
        self.pass_e = self._field(frm, "Password", cfg["password"], show="*")
        self.db_e = self._field(frm, "Database", cfg["dbname"])

        self.save_env_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self, text="Save credentials locally in .env", variable=self.save_env_var).pack(pady=10)

        self.err_lbl = ctk.CTkLabel(self, text="", text_color=PALETTE["danger"], wraplength=380)
        self.err_lbl.pack()

        ctk.CTkButton(self, text="Connect & Initialize Schema", fg_color=PALETTE["green"], command=self._submit).pack(pady=(6, 14))

    def _field(self, parent, label, default, show=None):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text=label, width=90, anchor="w").pack(side="left")
        ent = ctk.CTkEntry(row, show=show)
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


class EcoStepApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("Light")
        ctk.set_default_color_theme("green")

        self.title("ECOSTEP QCU — Footstep Energy Telemetry & Monitoring System (IPT2)")
        self.geometry("1280x800")
        self.minsize(1100, 700)
        self.configure(fg_color=PALETTE["bg"])

        self.db = EcoStepDatabase()
        self.serial_q = queue.Queue(maxsize=256)
        self.worker = SerialTelemetryWorker(self.serial_q)
        self.active_run_id = None

        self.wave_x = deque(maxlen=40)
        self.wave_v = deque(maxlen=40)
        self.step_counter = 0
        self.live_chart_mode = "LIVE"

        self._build_layout()
        self._init_database_on_boot()
        self.after(80, self._poll_serial_queue)
        self.after(220, self._tick_meter_pulse)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_layout(self):
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ---------------- FOREST GREEN ECO SIDEBAR ----------------
        self.sidebar = ctk.CTkFrame(self, width=255, fg_color=PALETTE["sidebar_bg"], corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=16, pady=(18, 12))
        if os.path.exists(config.LOGO_PATH):
            logo_img = ctk.CTkImage(Image.open(config.LOGO_PATH), size=(54, 54))
            ctk.CTkLabel(brand, image=logo_img, text="").pack(side="left", padx=(0, 10))
        tbox = ctk.CTkFrame(brand, fg_color="transparent")
        tbox.pack(side="left", fill="x")
        ctk.CTkLabel(tbox, text="ECOSTEP QCU", font=ctk.CTkFont(size=17, weight="bold"), text_color="#FFFFFF").pack(anchor="w")
        ctk.CTkLabel(tbox, text="IPT2 Desktop Monitor", font=ctk.CTkFont(size=11), text_color="#B9D7B2").pack(anchor="w")

        # Navigation Buttons
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
                anchor="w",
                height=38,
                corner_radius=10,
                fg_color="transparent",
                hover_color=PALETTE["sidebar_hover"],
                text_color="#E8F5E4",
                font=ctk.CTkFont(size=13, weight="bold"),
                command=lambda k=key: self.show_tab(k),
            )
            b.pack(fill="x", padx=14, pady=3)
            self.nav_btns[key] = b

        # USB-C Serial Box
        ser_box = ctk.CTkFrame(self.sidebar, fg_color=PALETTE["sidebar_card"], corner_radius=12)
        ser_box.pack(fill="x", padx=14, pady=(18, 10))
        ctk.CTkLabel(ser_box, text="USB-C SERIAL (115,200)", font=ctk.CTkFont(size=10, weight="bold"), text_color="#9EC496").pack(anchor="w", padx=12, pady=(10, 4))

        self.port_var = ctk.StringVar(value=config.DEFAULT_SERIAL_PORT)
        self.port_menu = ctk.CTkOptionMenu(ser_box, variable=self.port_var, values=list_serial_ports(), fg_color=PALETTE["green"])
        self.port_menu.pack(fill="x", padx=12, pady=4)

        self.connect_btn = ctk.CTkButton(ser_box, text="Connect Telemetry", fg_color=PALETTE["amber"], hover_color="#D97008", text_color="#FFFFFF", command=self._toggle_serial)
        self.connect_btn.pack(fill="x", padx=12, pady=(4, 6))

        self.serial_status_lbl = ctk.CTkLabel(ser_box, text="● Disconnected", font=ctk.CTkFont(size=11), text_color="#FCD34D")
        self.serial_status_lbl.pack(anchor="w", padx=12, pady=(0, 10))

        # PostgreSQL Status Box
        db_box = ctk.CTkFrame(self.sidebar, fg_color=PALETTE["sidebar_card"], corner_radius=12)
        db_box.pack(fill="x", padx=14, pady=6)
        ctk.CTkLabel(db_box, text="POSTGRESQL 18", font=ctk.CTkFont(size=10, weight="bold"), text_color="#9EC496").pack(anchor="w", padx=12, pady=(10, 2))
        self.db_status_lbl = ctk.CTkLabel(db_box, text="● Checking...", font=ctk.CTkFont(size=11), text_color="#E8F5E4")
        self.db_status_lbl.pack(anchor="w", padx=12, pady=(0, 6))
        ctk.CTkButton(db_box, text="DB Connection Setup", height=28, fg_color=PALETTE["sidebar_hover"], command=self.open_pg_dialog).pack(fill="x", padx=12, pady=(0, 10))

        self.active_run_lbl = ctk.CTkLabel(self.sidebar, text="Active Run: None", font=ctk.CTkFont(size=11), text_color="#B9D7B2")
        self.active_run_lbl.pack(anchor="w", padx=18, pady=(8, 4))

        # Bottom Theme Indicator
        bottom = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=16, pady=14)
        self.theme_switch = ctk.CTkSwitch(bottom, text="Dark Eco Mode", text_color="#E8F5E4", progress_color=PALETTE["amber"], command=self._toggle_theme)
        self.theme_switch.pack(anchor="w")

        # ---------------- MAIN WORKSPACE (TOP BAR + CONTENT) ----------------
        right_shell = ctk.CTkFrame(self, fg_color="transparent")
        right_shell.grid(row=0, column=1, sticky="nsew", padx=18, pady=14)
        right_shell.grid_columnconfigure(0, weight=1)
        right_shell.grid_rowconfigure(1, weight=1)

        # Sleek Top App Bar
        topbar = ctk.CTkFrame(right_shell, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=14)
        topbar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        tleft = ctk.CTkFrame(topbar, fg_color="transparent")
        tleft.pack(side="left", padx=16, pady=10)
        self.page_title_lbl = ctk.CTkLabel(tleft, text="Live Telemetry Monitor", font=ctk.CTkFont(size=18, weight="bold"), text_color=PALETTE["text"])
        self.page_title_lbl.pack(anchor="w")
        self.page_sub_lbl = ctk.CTkLabel(tleft, text="Recycled Kinetic Mat • Direct USB-C Telemetry & PostgreSQL 3NF Ledger", font=ctk.CTkFont(size=11), text_color=PALETTE["muted"])
        self.page_sub_lbl.pack(anchor="w")

        tright = ctk.CTkFrame(topbar, fg_color="transparent")
        tright.pack(side="right", padx=14, pady=10)
        self.top_mode_seg = ctk.CTkSegmentedButton(
            tright,
            values=["Eco Light", "Forest Dark"],
            command=self._on_top_theme_seg,
            selected_color=PALETTE["green"],
        )
        self.top_mode_seg.set("Eco Light")
        self.top_mode_seg.pack(side="right", padx=(8, 0))
        ctk.CTkButton(tright, text="⚡ Quick Step", width=110, fg_color=PALETTE["amber"], hover_color="#D97008", text_color="#FFFFFF", command=lambda: self.worker.send_command("S")).pack(side="right")

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
        style_treeview("Light")
        self.show_tab("live")

    def _build_live_tab(self):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        # KPI Row
        kpis = ctk.CTkFrame(frame, fg_color="transparent")
        kpis.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        kpis.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.kpi_steps = self._make_kpi(kpis, 0, "FOOTSTEP COUNTER & CADENCE", "0", "Cadence: 0.0 steps/min", PALETTE["green_bright"])
        self.kpi_volts = self._make_kpi(kpis, 1, "INSTANTANEOUS VOLTAGE", "0.00 V", "ADC 10-bit raw: 0 / 1023", PALETTE["amber"])
        self.kpi_joules = self._make_kpi(kpis, 2, "BATTERY STORAGE & SoC", "0.00 J", "SoC: 0.00% (0.0000 Wh)", PALETTE["teal"])
        self.kpi_db = self._make_kpi(kpis, 3, "DATABASE RECORDS", "0 logs", "PostgreSQL ecostep_qcu_db", PALETTE["green"])

        # Middle: Meter + Waveform
        mid = ctk.CTkFrame(frame, fg_color="transparent")
        mid.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        mid.grid_columnconfigure(0, weight=1)
        mid.grid_columnconfigure(1, weight=2)

        meter_card = ctk.CTkFrame(mid, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=14)
        meter_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        ctk.CTkLabel(meter_card, text="Live Kinetic Meter", font=ctk.CTkFont(size=14, weight="bold"), text_color=PALETTE["text"]).pack(pady=(12, 2))
        self.meter = VoltageMeterCanvas(meter_card, mode="Light")
        self.meter.pack(pady=4)

        ctl_row = ctk.CTkFrame(meter_card, fg_color="transparent")
        ctl_row.pack(fill="x", padx=12, pady=(4, 12))
        ctk.CTkButton(ctl_row, text="⚡ Simulate Step (S)", fg_color=PALETTE["green"], command=lambda: self.worker.send_command("S")).pack(fill="x", pady=3)
        mode_row = ctk.CTkFrame(ctl_row, fg_color="transparent")
        mode_row.pack(fill="x", pady=3)
        ctk.CTkButton(mode_row, text="Bench Mode", width=110, fg_color="#284B2F", command=lambda: self.worker.send_command("M0")).pack(side="left", expand=True, padx=(0, 4))
        ctk.CTkButton(mode_row, text="Tile ADC", width=110, fg_color=PALETTE["amber"], text_color="#FFFFFF", command=lambda: self.worker.send_command("M1")).pack(side="right", expand=True, padx=(4, 0))

        wave_card = ctk.CTkFrame(mid, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=14)
        wave_card.grid(row=0, column=1, sticky="nsew")
        w_head = ctk.CTkFrame(wave_card, fg_color="transparent")
        w_head.pack(fill="x", padx=12, pady=(8, 0))
        ctk.CTkLabel(w_head, text="Telemetry & Time-Horizon Graph", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["text"]).pack(side="left")
        self.live_chart_seg = ctk.CTkSegmentedButton(
            w_head,
            values=["LIVE", "1H", "10H", "24H", "48H", "7D"],
            command=self._on_live_chart_mode,
            selected_color=PALETTE["green"],
        )
        self.live_chart_seg.set("LIVE")
        self.live_chart_seg.pack(side="right")

        self.wave_fig = Figure(figsize=(5.5, 2.5), dpi=96)
        self.wave_ax = self.wave_fig.add_subplot(111)
        self.wave_canvas = FigureCanvasTkAgg(self.wave_fig, master=wave_card)
        self.wave_canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self._redraw_waveform()

        # Bottom: Stream Table (telemetry_logs)
        log_card = ctk.CTkFrame(frame, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=14)
        log_card.grid(row=2, column=0, sticky="nsew")
        head = ctk.CTkFrame(log_card, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(10, 4))
        ctk.CTkLabel(head, text="Live USB-C Telemetry Stream (telemetry_logs)", font=ctk.CTkFont(size=14, weight="bold"), text_color=PALETTE["text"]).pack(side="left")
        ctk.CTkButton(head, text="Reset ESP32 Counter (R)", height=26, fg_color="transparent", border_width=1, border_color=PALETTE["border"], text_color=PALETTE["text"], command=self._reset_esp).pack(side="right")

        cols = ("log_id", "run_id", "step_number", "adc_raw", "adc_voltage", "baud_rate", "recorded_at")
        self.live_tree = ttk.Treeview(log_card, columns=cols, show="headings", style="Eco.Treeview")
        for c, w in zip(cols, (70, 70, 100, 110, 110, 95, 190)):
            self.live_tree.heading(c, text=c.upper())
            self.live_tree.column(c, width=w, anchor="center")
        self.live_tree.pack(fill="both", expand=True, padx=12, pady=(4, 12))

        return frame

    def _make_kpi(self, parent, col, title, val, sub, accent=PALETTE["green_bright"]):
        card = ctk.CTkFrame(parent, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=14)
        card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 6, 0 if col == 3 else 6))
        strip = ctk.CTkFrame(card, height=4, fg_color=accent, corner_radius=4)
        strip.pack(fill="x", padx=12, pady=(10, 6))
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=10, weight="bold"), text_color=PALETTE["muted"]).pack(anchor="w", padx=14, pady=(0, 2))
        val_lbl = ctk.CTkLabel(card, text=val, font=ctk.CTkFont(family="Consolas", size=24, weight="bold"), text_color=accent)
        val_lbl.pack(anchor="w", padx=14)
        sub_lbl = ctk.CTkLabel(card, text=sub, font=ctk.CTkFont(size=11), text_color=PALETTE["muted"])
        sub_lbl.pack(anchor="w", padx=14, pady=(2, 12))
        return val_lbl, sub_lbl

    def show_tab(self, name):
        titles = {
            "live": ("Live Telemetry Monitor", "Recycled Kinetic Mat • Real-Time USB-C Stream & 4x4 PZT Pulse Gauge"),
            "time": ("Time Horizons & Device Equivalences", "1H / 10H Shift / 24H / 48H / 7D Analytics • Battery SoC % & Connected Loads"),
            "runs": ("100-Step Benchmark Runs", "measurement_runs CRUD • mWh to Joules Analytics & Soft-Delete Ledger"),
            "signs": ("5V Emergency Sign Verification", "sign_tests CRUD • Full (1.5 kΩ) vs Dim (10 kΩ) Power & Runtime Verification"),
            "components": ("Project Asset & Component Inventory", "components CRUD • Hardware Specifications & Inspection Readiness"),
        }
        if name in titles:
            t, s = titles[name]
            self.page_title_lbl.configure(text=t)
            self.page_sub_lbl.configure(text=s)
        for k, f in self.tabs.items():
            if k == name:
                f.grid(row=0, column=0, sticky="nsew")
                self.nav_btns[k].configure(fg_color=PALETTE["sidebar_active"])
            else:
                f.grid_forget()
                self.nav_btns[k].configure(fg_color="transparent")
        self.refresh_all()

    def _apply_theme_mode(self, mode):
        ctk.set_appearance_mode(mode)
        style_treeview(mode)
        self.meter.set_mode(mode)
        self._redraw_waveform()
        self.tabs["time"].refresh()
        self.tabs["runs"].refresh()
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

    def _init_database_on_boot(self):
        ok, err = self.db.ensure_initialized()
        if ok:
            self._on_db_ready()
        else:
            self.db_status_lbl.configure(text="● Auth Required", text_color="#FCA5A5")
            self.after(300, self.open_pg_dialog)

    def open_pg_dialog(self):
        PostgresSetupDialog(self, self.db, self._on_db_ready)

    def _on_db_ready(self):
        self.db_status_lbl.configure(text=f"● {self.db.cfg['dbname']}", text_color="#86EFAC")
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
        self.wave_x.clear()
        self.wave_v.clear()
        self.kpi_steps[0].configure(text="0")
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
                    self.serial_status_lbl.configure(text=f"● {evt['port']} LIVE", text_color="#86EFAC")
                    self.connect_btn.configure(text="Disconnect", fg_color=PALETTE["danger"])
                else:
                    self.serial_status_lbl.configure(text="● Disconnected", text_color="#FCD34D")
                    self.connect_btn.configure(text="Connect Telemetry", fg_color=PALETTE["amber"])
            elif kind == "error":
                self.serial_status_lbl.configure(text="● Port Error", text_color="#FCA5A5")
            elif kind == "data":
                self.step_counter = evt["step_number"]
                raw = evt["adc_raw"]
                volts = evt["adc_voltage"]
                self.kpi_steps[0].configure(text=str(self.step_counter))
                self.kpi_volts[0].configure(text=f"{volts:.2f} V")
                self.kpi_volts[1].configure(text=f"ADC 10-bit raw: {raw} / 1023")
                self.meter.update_reading(volts, pulse=True)
                self.wave_x.append(self.step_counter)
                self.wave_v.append(volts)
                self._redraw_waveform()

                if self.db.connected and self.active_run_id:
                    self.db.insert_telemetry_log(self.active_run_id, self.step_counter, raw, volts)
                    updated = True
                else:
                    self.live_tree.insert("", 0, values=("RAM", "-", self.step_counter, raw, f"{volts:.2f}", 115200, "LIVE"))

        if updated:
            self.refresh_all()
        self.after(80, self._poll_serial_queue)

    def _tick_meter_pulse(self):
        self.meter.tick_pulse()
        self.after(220, self._tick_meter_pulse)

    def _redraw_waveform(self):
        mode = ctk.get_appearance_mode()
        fg = pick(PALETTE["text"], mode)
        self.wave_ax.clear()
        apply_matplotlib_theme(self.wave_fig, self.wave_ax, mode)

        if self.live_chart_mode == "LIVE" or not self.db.connected:
            if self.wave_x:
                self.wave_ax.plot(list(self.wave_x), list(self.wave_v), marker="o", color=PALETTE["green_bright"], linewidth=2)
                self.wave_ax.fill_between(list(self.wave_x), list(self.wave_v), color=PALETTE["green_bright"], alpha=0.18)
            self.wave_ax.set_title("Real-Time ADC Voltage Waveform (USB-C 115,200 Baud)", color=fg, fontsize=10)
            self.wave_ax.set_ylabel("Volts (V)", color=fg, fontsize=9)
            self.wave_ax.set_ylim(0, 15.5)
        else:
            ts = self.db.get_timeseries(self.live_chart_mode.lower())
            x = list(range(len(ts["labels"])))
            self.wave_ax.bar(x, ts["joules"], color=PALETTE["green_bright"], alpha=0.82)
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

    def refresh_all(self):
        if not self.db.connected:
            return
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
        self.kpi_steps[1].configure(text=f"Cadence: {cadence:.1f} steps/min")
        self.kpi_joules[0].configure(text=f"{summary['total_joules']:.2f} J")
        self.kpi_joules[1].configure(text=f"SoC: {eq['soc_pct']:.2f}% ({eq['wh_stored']:.4f} Wh)")
        self.kpi_db[0].configure(text=f"{summary['telemetry_count']} logs")
        self.kpi_db[1].configure(text=f"{summary['active_runs']} runs • {summary['sign_tests_count']} sign tests")

        logs = self.db.list_telemetry_logs(limit=40)
        self.live_tree.delete(*self.live_tree.get_children())
        for r in logs:
            self.live_tree.insert(
                "", "end",
                values=(
                    r["log_id"], r["run_id"], r["step_number"], r["adc_raw"],
                    f"{float(r['adc_voltage']):.2f}", r["baud_rate"], str(r["recorded_at"])[:19],
                ),
            )
        if self.live_chart_mode != "LIVE":
            self._redraw_waveform()
        time_tab.refresh()
        self.tabs["runs"].refresh()
        self.tabs["signs"].refresh()
        self.tabs["components"].refresh()

    def _on_close(self):
        self.worker.disconnect()
        self.destroy()


def main():
    app = EcoStepApp()
    app.mainloop()


if __name__ == "__main__":
    main()
