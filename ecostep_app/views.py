"""Custom visual widgets and secondary CRUD tab views for EcoStep QCU Desktop App."""

import math
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from . import analytics
from .theme import PALETTE, apply_matplotlib_theme, pick


class VoltageMeterCanvas(tk.Canvas):
    """Instrument-grade semi-circular voltage gauge (0 - 15 V) + 4x4 PZT Eco-Mat pad."""

    def __init__(self, master, mode="Light", **kwargs):
        super().__init__(
            master,
            width=280,
            height=205,
            highlightthickness=0,
            bg=pick(PALETTE["card"], mode),
            **kwargs,
        )
        self.mode = mode
        self.volts = 0.0
        self.pulse_alpha = 0
        self.redraw()

    def set_mode(self, mode):
        self.mode = mode
        self.configure(bg=pick(PALETTE["card"], mode))
        self.redraw()

    def update_reading(self, volts, pulse=False):
        self.volts = max(0.0, min(15.0, float(volts)))
        if pulse:
            self.pulse_alpha = 4
        self.redraw()

    def tick_pulse(self):
        if self.pulse_alpha > 0:
            self.pulse_alpha -= 1
            self.redraw()

    def redraw(self):
        self.delete("all")
        bg_track = "#D5E4CC" if self.mode == "Light" else "#233A29"
        txt_col = pick(PALETTE["text"], self.mode)
        mut_col = pick(PALETTE["muted"], self.mode)
        pad_bg = pick(PALETTE["card_soft"], self.mode)
        pad_border = pick(PALETTE["border"], self.mode)

        cx, cy, r = 140, 118, 84
        # Outer gauge track
        self.create_arc(
            cx - r, cy - r, cx + r, cy + r,
            start=0, extent=180, style="arc", width=15, outline=bg_track
        )
        frac = min(1.0, self.volts / 15.0)
        if frac > 0.01:
            col = PALETTE["amber"] if self.volts >= 9.0 else PALETTE["green_bright"]
            self.create_arc(
                cx - r, cy - r, cx + r, cy + r,
                start=180, extent=-(180 * frac), style="arc", width=15, outline=col
            )

        # Dial tick marks & labels (0, 3, 6, 9, 12, 15 V)
        for v_mark in (0, 3, 6, 9, 12, 15):
            ang = math.radians(180 - (v_mark / 15.0) * 180)
            x1 = cx + (r - 12) * math.cos(ang)
            y1 = cy - (r - 12) * math.sin(ang)
            x2 = cx + (r + 2) * math.cos(ang)
            y2 = cy - (r + 2) * math.sin(ang)
            self.create_line(x1, y1, x2, y2, fill=mut_col, width=1.5)
            lx = cx + (r - 24) * math.cos(ang)
            ly = cy - (r - 24) * math.sin(ang)
            self.create_text(lx, ly, text=str(v_mark), font=("Consolas", 8), fill=mut_col)

        # Gauge needle & hub
        n_ang = math.radians(180 - frac * 180)
        nx = cx + (r - 16) * math.cos(n_ang)
        ny = cy - (r - 16) * math.sin(n_ang)
        needle_col = PALETTE["amber"] if self.pulse_alpha > 0 else PALETTE["green"]
        self.create_line(cx, cy, nx, ny, fill=needle_col, width=3)
        self.create_oval(cx - 6, cy - 6, cx + 6, cy + 6, fill=needle_col, outline=txt_col, width=1)

        self.create_text(cx, cy - 26, text=f"{self.volts:.2f} V", font=("Consolas", 18, "bold"), fill=txt_col)

        # Mini 4x4 PZT Recycled Kinetic Mat indicator strip at bottom
        self.create_rectangle(24, 138, 256, 196, fill=pad_bg, outline=pad_border, width=1.5)
        is_hit = self.pulse_alpha > 0
        disc_fill = PALETTE["gold"] if is_hit else PALETTE["green_bright"]
        for row_i in range(2):
            for col_i in range(8):
                dx = 38 + col_i * 12
                dy = 152 + row_i * 12
                self.create_oval(dx, dy, dx + 7, dy + 7, fill=disc_fill, outline="")

        status_txt = "STEP PULSE!" if is_hit else "4x4 MAT READY"
        status_col = PALETTE["amber"] if is_hit else PALETTE["green"]
        self.create_text(192, 160, text=status_txt, font=("Segoe UI", 9, "bold"), fill=status_col)
        self.create_text(192, 178, text="Upcycled Eco-Tile", font=("Segoe UI", 8), fill=mut_col)


def style_treeview(mode="Light"):
    style = ttk.Style()
    style.theme_use("clam")
    bg = pick(PALETTE["card"], mode)
    fg = pick(PALETTE["text"], mode)
    head_bg = pick(PALETTE["card_soft"], mode)
    border_col = pick(PALETTE["border"], mode)
    sel_bg = PALETTE["green"]

    style.configure(
        "Eco.Treeview",
        background=bg,
        foreground=fg,
        fieldbackground=bg,
        rowheight=29,
        borderwidth=0,
        relief="flat",
        font=("Segoe UI", 10),
    )
    style.configure(
        "Eco.Treeview.Heading",
        background=head_bg,
        foreground=fg,
        bordercolor=border_col,
        relief="flat",
        padding=(6, 6),
        font=("Segoe UI", 9, "bold"),
    )
    style.map("Eco.Treeview", background=[("selected", sel_bg)], foreground=[("selected", "#FFFFFF")])
    style.map("Eco.Treeview.Heading", background=[("active", border_col)])


class MeasurementRunsView(ctk.CTkFrame):
    """CRUD + soft-delete + mWh->Joules analytics view for measurement_runs."""

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.selected_run_id = None
        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Form Card
        form = ctk.CTkFrame(self, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=14)
        form.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        form.grid_columnconfigure((0, 1, 2, 3), weight=1)

        ctk.CTkLabel(
            form, text="100-Step Benchmark Runs (measurement_runs)",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=PALETTE["text"]
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=16, pady=(12, 6))

        self.comp_var = ctk.StringVar(value="")
        self.op_entry = ctk.CTkEntry(form, placeholder_text="Operator Name (e.g. L. Britania)")
        self.steps_entry = ctk.CTkEntry(form, placeholder_text="Steps (100)")
        self.steps_entry.insert(0, "100")
        self.mwh_entry = ctk.CTkEntry(form, placeholder_text="Energy (mWh)")
        self.mwh_entry.insert(0, "0.20")
        self.volts_entry = ctk.CTkEntry(form, placeholder_text="Peak Volts (V)")
        self.volts_entry.insert(0, "0.00")
        self.path_var = ctk.StringVar(value="Path A")
        self.status_var = ctk.StringVar(value="Completed")

        self.comp_menu = ctk.CTkOptionMenu(form, variable=self.comp_var, values=["No Component"], fg_color=PALETTE["green"], button_color=PALETTE["green_bright"])
        self.path_menu = ctk.CTkOptionMenu(form, variable=self.path_var, values=["Path A", "Path B"], fg_color=PALETTE["green"], button_color=PALETTE["green_bright"])
        self.status_menu = ctk.CTkOptionMenu(form, variable=self.status_var, values=["Pending", "Completed", "Invalid"], fg_color=PALETTE["green"], button_color=PALETTE["green_bright"])

        self.comp_menu.grid(row=1, column=0, padx=12, pady=6, sticky="ew")
        self.op_entry.grid(row=1, column=1, padx=12, pady=6, sticky="ew")
        self.steps_entry.grid(row=1, column=2, padx=12, pady=6, sticky="ew")
        self.mwh_entry.grid(row=1, column=3, padx=12, pady=6, sticky="ew")

        self.volts_entry.grid(row=2, column=0, padx=12, pady=6, sticky="ew")
        self.path_menu.grid(row=2, column=1, padx=12, pady=6, sticky="ew")
        self.status_menu.grid(row=2, column=2, padx=12, pady=6, sticky="ew")

        self.preview_lbl = ctk.CTkLabel(
            form, text="Auto-Calc: 0.72 J | 0.0072 J/step",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color=PALETTE["amber"]
        )
        self.preview_lbl.grid(row=2, column=3, padx=12, pady=6, sticky="w")
        self.steps_entry.bind("<KeyRelease>", lambda _e: self._update_preview())
        self.mwh_entry.bind("<KeyRelease>", lambda _e: self._update_preview())

        btns = ctk.CTkFrame(form, fg_color="transparent")
        btns.grid(row=3, column=0, columnspan=4, sticky="ew", padx=12, pady=(4, 12))
        ctk.CTkButton(btns, text="+ Create Run", fg_color=PALETTE["green"], hover_color=PALETTE["green_bright"], command=self._create_run).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="Update Selected", fg_color=PALETTE["amber"], text_color="#FFFFFF", command=self._update_run).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="Set Active for Live Telemetry", fg_color="#284B2F", command=self._set_active).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="Soft Delete", fg_color=PALETTE["danger"], command=lambda: self._toggle_delete(True)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="Restore", fg_color="gray45", command=lambda: self._toggle_delete(False)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="Export CSV", fg_color="transparent", border_width=1, border_color=PALETTE["border"], text_color=PALETTE["text"], command=self._export_csv).pack(side="right")

        # Filter Bar
        fbar = ctk.CTkFrame(self, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=12)
        fbar.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.search_entry = ctk.CTkEntry(fbar, placeholder_text="Search operator or component...", width=260)
        self.search_entry.pack(side="left", padx=12, pady=8)
        self.search_entry.bind("<KeyRelease>", lambda _e: self.refresh())

        self.filter_status = ctk.StringVar(value="ALL")
        ctk.CTkOptionMenu(fbar, variable=self.filter_status, values=["ALL", "Pending", "Completed", "Invalid"], command=lambda _v: self.refresh(), fg_color=PALETTE["green"]).pack(side="left", padx=6, pady=8)

        self.show_deleted = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(fbar, text="Show Soft-Deleted", variable=self.show_deleted, command=self.refresh).pack(side="left", padx=12, pady=8)

        # Table + Yield Chart Split
        split = ctk.CTkFrame(self, fg_color="transparent")
        split.grid(row=2, column=0, sticky="nsew")
        split.grid_columnconfigure(0, weight=3)
        split.grid_columnconfigure(1, weight=2)
        split.grid_rowconfigure(0, weight=1)

        tbl_card = ctk.CTkFrame(split, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=14)
        tbl_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        cols = ("run_id", "component", "operator", "steps", "mwh", "joules", "j_step", "peak_v", "path", "status")
        self.tree = ttk.Treeview(tbl_card, columns=cols, show="headings", style="Eco.Treeview")
        for c, w in zip(cols, (55, 160, 110, 55, 70, 70, 75, 65, 65, 85)):
            self.tree.heading(c, text=c.upper())
            self.tree.column(c, width=w, anchor="center" if c in ("run_id", "steps", "mwh", "joules", "j_step", "peak_v") else "w")
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        chart_card = ctk.CTkFrame(split, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=14)
        chart_card.grid(row=0, column=1, sticky="nsew")
        self.fig = Figure(figsize=(4.2, 3.2), dpi=96)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_card)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)

    def _update_preview(self):
        try:
            j, jps = self.app.db.compute_run_metrics(self.mwh_entry.get(), self.steps_entry.get())
            self.preview_lbl.configure(text=f"Auto-Calc: {j:.2f} J | {jps:.4f} J/step")
        except Exception:
            self.preview_lbl.configure(text="Auto-Calc: invalid input")

    def _get_selected_component_id(self):
        val = self.comp_var.get()
        if ":" in val:
            return int(val.split(":", 1)[0])
        return None

    def _create_run(self):
        if not self.app.db.connected:
            return messagebox.showwarning("PostgreSQL Offline", "Connect to PostgreSQL first.")
        cid = self._get_selected_component_id()
        if cid is None:
            return messagebox.showwarning("Missing Component", "Add a component first.")
        try:
            row = self.app.db.create_run(
                component_id=cid,
                operator_name=self.op_entry.get(),
                steps_count=int(self.steps_entry.get()),
                energy_mwh=float(self.mwh_entry.get()),
                adc_peak_volts=float(self.volts_entry.get() or 0.0),
                charging_path=self.path_var.get(),
                status=self.status_var.get(),
            )
            self.app.active_run_id = row["run_id"]
            self.app.refresh_all()
        except Exception as exc:
            messagebox.showerror("Validation Error", str(exc))

    def _update_run(self):
        if not self.selected_run_id:
            return messagebox.showinfo("Select Run", "Select a row in the table first.")
        cid = self._get_selected_component_id()
        try:
            self.app.db.update_run(
                self.selected_run_id,
                component_id=cid,
                operator_name=self.op_entry.get(),
                steps_count=int(self.steps_entry.get()),
                energy_mwh=float(self.mwh_entry.get()),
                adc_peak_volts=float(self.volts_entry.get() or 0.0),
                charging_path=self.path_var.get(),
                status=self.status_var.get(),
            )
            self.app.refresh_all()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def _toggle_delete(self, flag):
        if not self.selected_run_id:
            return
        self.app.db.soft_delete_run(self.selected_run_id, deleted=flag)
        self.app.refresh_all()

    def _set_active(self):
        if not self.selected_run_id:
            return
        self.app.active_run_id = self.selected_run_id
        self.app.refresh_active_run_label()
        messagebox.showinfo("Active Run Set", f"Live ESP32 telemetry will now log into Run #{self.selected_run_id}.")

    def _export_csv(self):
        if not self.app.db.connected:
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="ecostep_measurement_runs.csv")
        if path:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(self.app.db.export_runs_csv())
            messagebox.showinfo("Exported", f"Saved runs report to:\n{path}")

    def _on_select(self, _evt):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        self.selected_run_id = int(vals[0])
        self.op_entry.delete(0, "end")
        self.op_entry.insert(0, vals[2])
        self.steps_entry.delete(0, "end")
        self.steps_entry.insert(0, vals[3])
        self.mwh_entry.delete(0, "end")
        self.mwh_entry.insert(0, vals[4])
        self.volts_entry.delete(0, "end")
        self.volts_entry.insert(0, vals[7])
        self.path_var.set(vals[8])
        self.status_var.set(vals[9].replace(" [DEL]", ""))
        self._update_preview()

    def refresh(self):
        if not self.app.db.connected:
            return
        comps = self.app.db.list_components()
        comp_opts = [f"{c['component_id']}: {c['component_name'][:28]}" for c in comps]
        if comp_opts:
            self.comp_menu.configure(values=comp_opts)
            if self.comp_var.get() not in comp_opts:
                self.comp_var.set(comp_opts[0])

        rows = self.app.db.list_runs(
            include_deleted=self.show_deleted.get(),
            status=self.filter_status.get(),
            search=self.search_entry.get().strip(),
        )
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            st = f"{r['status']} [DEL]" if r["is_deleted"] else r["status"]
            self.tree.insert(
                "", "end",
                values=(
                    r["run_id"],
                    r["component_name"][:24],
                    r["operator_name"] or "",
                    r["steps_count"],
                    f"{float(r['energy_mwh']):.2f}",
                    f"{float(r['energy_joules']):.2f}",
                    f"{float(r['joules_per_step']):.4f}",
                    f"{float(r['adc_peak_volts']):.2f}",
                    r["charging_path"],
                    st,
                ),
            )

        mode = ctk.get_appearance_mode()
        fg = pick(PALETTE["text"], mode)
        self.ax.clear()
        apply_matplotlib_theme(self.fig, self.ax, mode)
        active = [r for r in rows if not r["is_deleted"]][:8][::-1]
        if active:
            labels = [f"#{r['run_id']}" for r in active]
            vals = [float(r["energy_joules"]) for r in active]
            self.ax.bar(labels, vals, color=PALETTE["green_bright"])
        self.ax.set_title("Harvested Energy per Run (Joules)", color=fg, fontsize=10)
        self.fig.tight_layout()
        self.canvas.draw_idle()


class SignTestsView(ctk.CTkFrame):
    """CRUD view for sign_tests (5V Emergency Evacuation LED Sign Full/Dim verification)."""

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.selected_test_id = None
        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        form = ctk.CTkFrame(self, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=14)
        form.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        form.grid_columnconfigure((0, 1, 2, 3), weight=1)

        ctk.CTkLabel(
            form, text="5V Emergency Sign Load & Runtime Verification (sign_tests)",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=PALETTE["text"]
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=16, pady=(12, 6))

        self.run_var = ctk.StringVar(value="")
        self.mode_var = ctk.StringVar(value="Full")
        self.ma_entry = ctk.CTkEntry(form, placeholder_text="Load Current (mA)")
        self.ma_entry.insert(0, "25.0")
        self.min_entry = ctk.CTkEntry(form, placeholder_text="Runtime (minutes)")
        self.min_entry.insert(0, "3.1")
        self.status_var = ctk.StringVar(value="Completed")
        self.avail_var = ctk.BooleanVar(value=True)

        self.run_menu = ctk.CTkOptionMenu(form, variable=self.run_var, values=["No Runs"], fg_color=PALETTE["green"])
        self.mode_menu = ctk.CTkOptionMenu(form, variable=self.mode_var, values=["Full", "Dim"], command=lambda _v: self._update_preview(), fg_color=PALETTE["green"])
        self.status_menu = ctk.CTkOptionMenu(form, variable=self.status_var, values=["Completed", "Ongoing"], fg_color=PALETTE["green"])

        self.run_menu.grid(row=1, column=0, padx=12, pady=6, sticky="ew")
        self.mode_menu.grid(row=1, column=1, padx=12, pady=6, sticky="ew")
        self.ma_entry.grid(row=1, column=2, padx=12, pady=6, sticky="ew")
        self.min_entry.grid(row=1, column=3, padx=12, pady=6, sticky="ew")

        self.status_menu.grid(row=2, column=0, padx=12, pady=6, sticky="ew")
        ctk.CTkCheckBox(form, text="Sign Mode Active (is_available)", variable=self.avail_var).grid(row=2, column=1, padx=12, pady=6, sticky="w")
        self.preview_lbl = ctk.CTkLabel(
            form, text="Resistor: 1.5 kΩ | P = 5V × 25.0mA = 125.00 mW",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color=PALETTE["amber"]
        )
        self.preview_lbl.grid(row=2, column=2, columnspan=2, padx=12, pady=6, sticky="w")
        self.ma_entry.bind("<KeyRelease>", lambda _e: self._update_preview())

        btns = ctk.CTkFrame(form, fg_color="transparent")
        btns.grid(row=3, column=0, columnspan=4, sticky="ew", padx=12, pady=(4, 12))
        ctk.CTkButton(btns, text="+ Log Sign Test", fg_color=PALETTE["green"], command=self._add_test).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="Update Selected", fg_color=PALETTE["amber"], text_color="#FFFFFF", command=self._update_test).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="Delete Selected", fg_color=PALETTE["danger"], command=self._delete_test).pack(side="left")

        fbar = ctk.CTkFrame(self, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=12)
        fbar.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        ctk.CTkLabel(fbar, text="Filter Mode:", text_color=PALETTE["muted"]).pack(side="left", padx=(12, 6), pady=8)
        self.filter_mode = ctk.StringVar(value="ALL")
        ctk.CTkOptionMenu(fbar, variable=self.filter_mode, values=["ALL", "Full", "Dim"], command=lambda _v: self.refresh(), fg_color=PALETTE["green"]).pack(side="left", padx=6, pady=8)

        tbl_card = ctk.CTkFrame(self, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=14)
        tbl_card.grid(row=2, column=0, sticky="nsew")
        cols = ("test_id", "run_id", "sign_mode", "resistor", "load_ma", "power_mw", "runtime_min", "status", "available")
        self.tree = ttk.Treeview(tbl_card, columns=cols, show="headings", style="Eco.Treeview")
        for c, w in zip(cols, (65, 65, 80, 80, 90, 95, 100, 95, 85)):
            self.tree.heading(c, text=c.upper())
            self.tree.column(c, width=w, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

    def _update_preview(self):
        res = "1.5 kΩ" if self.mode_var.get() == "Full" else "10 kΩ"
        try:
            ma = float(self.ma_entry.get())
            mw = self.app.db.compute_sign_power_mw(ma)
            self.preview_lbl.configure(text=f"Resistor: {res} | P = 5V × {ma:.1f}mA = {mw:.2f} mW")
        except Exception:
            self.preview_lbl.configure(text=f"Resistor: {res} | Invalid current (0-5000 mA)")

    def _add_test(self):
        if not self.app.db.connected:
            return
        val = self.run_var.get()
        if ":" not in val:
            return messagebox.showwarning("Missing Run", "Create a measurement run first.")
        rid = int(val.split(":", 1)[0])
        try:
            self.app.db.add_sign_test(
                run_id=rid,
                sign_mode=self.mode_var.get(),
                load_ma=float(self.ma_entry.get()),
                runtime_minutes=float(self.min_entry.get()),
                status=self.status_var.get(),
                is_available=self.avail_var.get(),
            )
            self.app.refresh_all()
        except Exception as exc:
            messagebox.showerror("Validation Error", str(exc))

    def _update_test(self):
        if not self.selected_test_id:
            return
        try:
            self.app.db.update_sign_test(
                self.selected_test_id,
                sign_mode=self.mode_var.get(),
                load_ma=float(self.ma_entry.get()),
                runtime_minutes=float(self.min_entry.get()),
                status=self.status_var.get(),
                is_available=self.avail_var.get(),
            )
            self.app.refresh_all()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def _delete_test(self):
        if not self.selected_test_id:
            return
        self.app.db.delete_sign_test(self.selected_test_id)
        self.selected_test_id = None
        self.app.refresh_all()

    def _on_select(self, _evt):
        sel = self.tree.selection()
        if not sel:
            return
        v = self.tree.item(sel[0], "values")
        self.selected_test_id = int(v[0])
        self.mode_var.set(v[2])
        self.ma_entry.delete(0, "end")
        self.ma_entry.insert(0, v[4])
        self.min_entry.delete(0, "end")
        self.min_entry.insert(0, v[6])
        self.status_var.set(v[7])
        self.avail_var.set(v[8] == "True")
        self._update_preview()

    def refresh(self):
        if not self.app.db.connected:
            return
        runs = self.app.db.list_runs(include_deleted=False)
        opts = [f"{r['run_id']}: {r['operator_name']} ({r['charging_path']})" for r in runs]
        if opts:
            self.run_menu.configure(values=opts)
            if self.run_var.get() not in opts:
                self.run_var.set(opts[0])

        rows = self.app.db.list_sign_tests(sign_mode=self.filter_mode.get())
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            self.tree.insert(
                "", "end",
                values=(
                    r["test_id"], r["run_id"], r["sign_mode"], r["resistor_value"],
                    f"{float(r['load_ma']):.2f}", f"{float(r['power_mw']):.2f}",
                    f"{float(r['runtime_minutes']):.2f}", r["status"], str(r["is_available"]),
                ),
            )


class ComponentsView(ctk.CTkFrame):
    """CRUD view for components (technical specs & inspection status; no pricing)."""

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.selected_comp_id = None
        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        form = ctk.CTkFrame(self, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=14)
        form.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        form.grid_columnconfigure((0, 1, 2), weight=1)

        ctk.CTkLabel(
            form, text="Project Asset & Component Inventory (components — Functional Specs Only)",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=PALETTE["text"]
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(12, 6))

        self.name_entry = ctk.CTkEntry(form, placeholder_text="Component Name")
        self.cat_var = ctk.StringVar(value="Electronics")
        self.qty_entry = ctk.CTkEntry(form, placeholder_text="Quantity (1)")
        self.qty_entry.insert(0, "1")
        self.spec_entry = ctk.CTkEntry(form, placeholder_text="Technical Specifications / Ratings")
        self.source_entry = ctk.CTkEntry(form, placeholder_text="Source / Configuration Notes")
        self.insp_var = ctk.StringVar(value="Passed")

        self.name_entry.grid(row=1, column=0, padx=12, pady=6, sticky="ew")
        ctk.CTkOptionMenu(form, variable=self.cat_var, values=["Structure", "Drive", "Electronics", "Storage"], fg_color=PALETTE["green"]).grid(row=1, column=1, padx=12, pady=6, sticky="ew")
        self.qty_entry.grid(row=1, column=2, padx=12, pady=6, sticky="ew")

        self.spec_entry.grid(row=2, column=0, padx=12, pady=6, sticky="ew")
        self.source_entry.grid(row=2, column=1, padx=12, pady=6, sticky="ew")
        ctk.CTkOptionMenu(form, variable=self.insp_var, values=["Passed", "Pending", "Replace"], fg_color=PALETTE["green"]).grid(row=2, column=2, padx=12, pady=6, sticky="ew")

        btns = ctk.CTkFrame(form, fg_color="transparent")
        btns.grid(row=3, column=0, columnspan=3, sticky="ew", padx=12, pady=(4, 12))
        ctk.CTkButton(btns, text="+ Add Component", fg_color=PALETTE["green"], command=self._add_comp).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="Update Selected", fg_color=PALETTE["amber"], text_color="#FFFFFF", command=self._update_comp).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="Delete Selected", fg_color=PALETTE["danger"], command=self._del_comp).pack(side="left")

        fbar = ctk.CTkFrame(self, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=12)
        fbar.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.search_entry = ctk.CTkEntry(fbar, placeholder_text="Search components...", width=240)
        self.search_entry.pack(side="left", padx=12, pady=8)
        self.search_entry.bind("<KeyRelease>", lambda _e: self.refresh())

        self.filter_cat = ctk.StringVar(value="ALL")
        self.filter_insp = ctk.StringVar(value="ALL")
        ctk.CTkOptionMenu(fbar, variable=self.filter_cat, values=["ALL", "Structure", "Drive", "Electronics", "Storage"], command=lambda _v: self.refresh(), fg_color=PALETTE["green"]).pack(side="left", padx=6, pady=8)
        ctk.CTkOptionMenu(fbar, variable=self.filter_insp, values=["ALL", "Passed", "Pending", "Replace"], command=lambda _v: self.refresh(), fg_color=PALETTE["green"]).pack(side="left", padx=6, pady=8)

        tbl_card = ctk.CTkFrame(self, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=14)
        tbl_card.grid(row=2, column=0, sticky="nsew")
        cols = ("id", "component_name", "category", "specification", "qty", "source_notes", "inspection")
        self.tree = ttk.Treeview(tbl_card, columns=cols, show="headings", style="Eco.Treeview")
        for c, w in zip(cols, (45, 220, 95, 270, 50, 180, 85)):
            self.tree.heading(c, text=c.upper())
            self.tree.column(c, width=w, anchor="center" if c in ("id", "qty", "inspection") else "w")
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

    def _add_comp(self):
        if not self.app.db.connected:
            return
        try:
            self.app.db.add_component(
                self.name_entry.get(), self.cat_var.get(), self.spec_entry.get(),
                int(self.qty_entry.get()), self.source_entry.get(), self.insp_var.get(),
            )
            self.app.refresh_all()
        except Exception as exc:
            messagebox.showerror("Validation Error", str(exc))

    def _update_comp(self):
        if not self.selected_comp_id:
            return
        try:
            self.app.db.update_component(
                self.selected_comp_id, self.name_entry.get(), self.cat_var.get(),
                self.spec_entry.get(), int(self.qty_entry.get()),
                self.source_entry.get(), self.insp_var.get(),
            )
            self.app.refresh_all()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def _del_comp(self):
        if not self.selected_comp_id:
            return
        try:
            self.app.db.delete_component(self.selected_comp_id)
            self.selected_comp_id = None
            self.app.refresh_all()
        except Exception as exc:
            messagebox.showerror("Cannot Delete", f"Component is referenced by existing runs.\n{exc}")

    def _on_select(self, _evt):
        sel = self.tree.selection()
        if not sel:
            return
        v = self.tree.item(sel[0], "values")
        self.selected_comp_id = int(v[0])
        self.name_entry.delete(0, "end")
        self.name_entry.insert(0, v[1])
        self.cat_var.set(v[2])
        self.spec_entry.delete(0, "end")
        self.spec_entry.insert(0, v[3])
        self.qty_entry.delete(0, "end")
        self.qty_entry.insert(0, v[4])
        self.source_entry.delete(0, "end")
        self.source_entry.insert(0, v[5])
        self.insp_var.set(v[6])

    def refresh(self):
        if not self.app.db.connected:
            return
        rows = self.app.db.list_components(
            category=self.filter_cat.get(),
            status=self.filter_insp.get(),
            search=self.search_entry.get().strip(),
        )
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            self.tree.insert(
                "", "end",
                values=(
                    r["component_id"], r["component_name"], r["category"],
                    r["specification"], r["quantity"], r["source_notes"] or "",
                    r["inspection_status"],
                ),
            )


class TimeAnalyticsView(ctk.CTkFrame):
    """Time-horizon counters (1h/10h/24h/48h/7d), Battery SoC, Load Simulator & Device Equivalences."""

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.current_window = "24h"
        self.usb_loads = 0
        self.led_12v_on = False
        self.sign_mode = "Dim"
        self.battery_cap_wh = 10.0
        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Row 0: 5 Time-Horizon Counter Cards
        cards_row = ctk.CTkFrame(self, fg_color="transparent")
        cards_row.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        cards_row.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        self.period_labels = {}
        specs = [
            ("1h", "LAST 1 HOUR"),
            ("10h", "10H QCU SHIFT"),
            ("24h", "1 DAY (24H)"),
            ("48h", "2 DAYS (48H)"),
            ("7d", "1 WEEK (7D)"),
        ]
        for idx, (key, title) in enumerate(specs):
            c = ctk.CTkFrame(cards_row, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=12)
            c.grid(row=0, column=idx, sticky="nsew", padx=(0 if idx == 0 else 4, 0 if idx == 4 else 4))
            ctk.CTkLabel(c, text=title, font=ctk.CTkFont(size=10, weight="bold"), text_color=PALETTE["muted"]).pack(anchor="w", padx=12, pady=(10, 2))
            val_lbl = ctk.CTkLabel(c, text="0 steps", font=ctk.CTkFont(family="Consolas", size=18, weight="bold"), text_color=PALETTE["green_bright"])
            val_lbl.pack(anchor="w", padx=12)
            sub_lbl = ctk.CTkLabel(c, text="0.00 J • 0.00 mWh", font=ctk.CTkFont(size=11), text_color=PALETTE["muted"])
            sub_lbl.pack(anchor="w", padx=12, pady=(2, 10))
            self.period_labels[key] = (val_lbl, sub_lbl)

        # Row 1: Time-Based Chart (Left) + Battery & Connected Loads (Right)
        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        mid.grid_columnconfigure(0, weight=3)
        mid.grid_columnconfigure(1, weight=2)
        mid.grid_rowconfigure(0, weight=1)

        chart_card = ctk.CTkFrame(mid, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=14)
        chart_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        chart_card.grid_rowconfigure(1, weight=1)
        chart_card.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(chart_card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
        ctk.CTkLabel(head, text="Time-Based Power & Footstep Horizon", font=ctk.CTkFont(size=14, weight="bold"), text_color=PALETTE["text"]).pack(side="left")

        btn_bar = ctk.CTkFrame(head, fg_color="transparent")
        btn_bar.pack(side="right")
        self.win_btns = {}
        for w in ("1h", "10h", "24h", "48h", "7d"):
            b = ctk.CTkButton(
                btn_bar, text=w.upper(), width=44, height=26,
                fg_color=PALETTE["green"] if w == self.current_window else "transparent",
                border_width=1, border_color=PALETTE["border"],
                text_color="#FFFFFF" if w == self.current_window else PALETTE["text"],
                command=lambda win=w: self.set_window(win),
            )
            b.pack(side="left", padx=2)
            self.win_btns[w] = b

        self.fig = Figure(figsize=(5.6, 3.0), dpi=96)
        self.ax = self.fig.add_subplot(111)
        self.ax2 = self.ax.twinx()
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_card)
        self.canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew", padx=10, pady=(2, 6))

        seed_row = ctk.CTkFrame(chart_card, fg_color="transparent")
        seed_row.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 10))
        self.window_sum_lbl = ctk.CTkLabel(seed_row, text="Window total: 0 steps • 0.00 J", font=ctk.CTkFont(size=11), text_color=PALETTE["muted"])
        self.window_sum_lbl.pack(side="left")
        ctk.CTkButton(seed_row, text="Clear Demo", width=85, height=26, fg_color="gray45", command=self._clear_demo).pack(side="right", padx=(6, 0))
        ctk.CTkButton(seed_row, text="Seed 7-Day Demo", width=115, height=26, fg_color=PALETTE["amber"], text_color="#FFFFFF", command=self._seed_demo).pack(side="right")

        # Right: Battery SoC & Connected Loads
        load_card = ctk.CTkFrame(mid, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=14)
        load_card.grid(row=0, column=1, sticky="nsew")

        ctk.CTkLabel(load_card, text="Battery Bank & Connected Loads", font=ctk.CTkFont(size=14, weight="bold"), text_color=PALETTE["text"]).pack(anchor="w", padx=16, pady=(12, 6))

        self.soc_lbl = ctk.CTkLabel(load_card, text="SoC: 0.00%  (0.0000 Wh)", font=ctk.CTkFont(family="Consolas", size=16, weight="bold"), text_color=PALETTE["green_bright"])
        self.soc_lbl.pack(anchor="w", padx=16)
        self.soc_bar = ctk.CTkProgressBar(load_card, progress_color=PALETTE["green_bright"])
        self.soc_bar.pack(fill="x", padx=16, pady=(4, 8))
        self.soc_bar.set(0.0)

        cap_row = ctk.CTkFrame(load_card, fg_color="transparent")
        cap_row.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(cap_row, text="Buffer Cap (Wh):", font=ctk.CTkFont(size=11), text_color=PALETTE["muted"]).pack(side="left")
        self.cap_entry = ctk.CTkEntry(cap_row, width=70, height=26)
        self.cap_entry.insert(0, "10.0")
        self.cap_entry.pack(side="left", padx=6)
        ctk.CTkButton(cap_row, text="Set", width=48, height=26, fg_color=PALETTE["green"], command=self._apply_cap).pack(side="left")

        self.cadence_lbl = ctk.CTkLabel(load_card, text="Walking Cadence: 0.0 steps/min", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["amber"])
        self.cadence_lbl.pack(anchor="w", padx=16, pady=(2, 8))

        # 5V USB Phone Chargers
        usb_box = ctk.CTkFrame(load_card, fg_color=PALETTE["card_soft"], corner_radius=10)
        usb_box.pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(usb_box, text="5V USB Phone Chargers (2.5 W / phone)", font=ctk.CTkFont(size=11, weight="bold"), text_color=PALETTE["text"]).pack(anchor="w", padx=10, pady=(8, 4))
        self.usb_seg = ctk.CTkSegmentedButton(usb_box, values=["0", "1", "2", "3", "4"], command=self._on_usb_change, selected_color=PALETTE["green"])
        self.usb_seg.set("0")
        self.usb_seg.pack(fill="x", padx=10, pady=(0, 8))

        # 12V Pathway LED + 5V Sign Mode
        sw_box = ctk.CTkFrame(load_card, fg_color=PALETTE["card_soft"], corner_radius=10)
        sw_box.pack(fill="x", padx=14, pady=4)
        self.led12_sw = ctk.CTkSwitch(sw_box, text="12V Campus Pathway LED (3.0 W)", command=self._on_loads_update)
        self.led12_sw.pack(anchor="w", padx=10, pady=(8, 4))
        self.sign_seg = ctk.CTkSegmentedButton(sw_box, values=["Dim (10kΩ)", "Full (1.5kΩ)"], command=self._on_sign_change, selected_color=PALETTE["amber"])
        self.sign_seg.set("Dim (10kΩ)")
        self.sign_seg.pack(fill="x", padx=10, pady=(2, 8))

        self.load_draw_lbl = ctk.CTkLabel(load_card, text="Total Output Draw: 17.5 mW (3.5 mA)", font=ctk.CTkFont(family="Consolas", size=12, weight="bold"), text_color=PALETTE["text"])
        self.load_draw_lbl.pack(anchor="w", padx=16, pady=(6, 10))

        # Row 2: Device Equivalence Calculator
        eq_card = ctk.CTkFrame(self, fg_color=PALETTE["card"], border_width=1, border_color=PALETTE["border"], corner_radius=14)
        eq_card.grid(row=2, column=0, sticky="ew")
        eq_card.grid_columnconfigure((0, 1, 2, 3), weight=1)

        ctk.CTkLabel(eq_card, text="Device Equivalence Calculator", font=ctk.CTkFont(size=14, weight="bold"), text_color=PALETTE["text"]).grid(row=0, column=0, columnspan=4, sticky="w", padx=16, pady=(10, 6))

        self.eq_phone = self._make_eq_box(eq_card, 0, "4,000 mAh SMARTPHONE", "0.00%", "0.000 full 15.4 Wh charges")
        self.eq_talk = self._make_eq_box(eq_card, 1, "EMERGENCY TALK-TIME", "0.0 min", "At 1.2 W cellular draw")
        self.eq_sign = self._make_eq_box(eq_card, 2, "5V EVACUATION SIGN", "0.0 min", "Full (1.5kΩ): 0.0 min")
        self.eq_led12 = self._make_eq_box(eq_card, 3, "12V PATHWAY LAMP", "0.0 min", "At 3.0 W campus LED load")

    def _make_eq_box(self, parent, col, title, val, sub):
        box = ctk.CTkFrame(parent, fg_color=PALETTE["card_soft"], corner_radius=10)
        box.grid(row=1, column=col, sticky="ew", padx=(12 if col == 0 else 6, 12 if col == 3 else 6), pady=(0, 12))
        ctk.CTkLabel(box, text=title, font=ctk.CTkFont(size=10, weight="bold"), text_color=PALETTE["muted"]).pack(anchor="w", padx=12, pady=(8, 2))
        v = ctk.CTkLabel(box, text=val, font=ctk.CTkFont(family="Consolas", size=18, weight="bold"), text_color=PALETTE["green"])
        v.pack(anchor="w", padx=12)
        s = ctk.CTkLabel(box, text=sub, font=ctk.CTkFont(size=10), text_color=PALETTE["muted"])
        s.pack(anchor="w", padx=12, pady=(2, 8))
        return v, s

    def set_window(self, win):
        self.current_window = win
        mode = ctk.get_appearance_mode()
        for k, b in self.win_btns.items():
            active = k == win
            b.configure(
                fg_color=PALETTE["green"] if active else "transparent",
                text_color="#FFFFFF" if active else pick(PALETTE["text"], mode),
            )
        self.refresh()

    def _apply_cap(self):
        try:
            self.battery_cap_wh = max(0.5, min(200.0, float(self.cap_entry.get())))
        except ValueError:
            self.battery_cap_wh = 10.0
        self.refresh()

    def _on_usb_change(self, val):
        self.usb_loads = int(val)
        self.refresh()

    def _on_sign_change(self, val):
        self.sign_mode = "Full" if "Full" in val else "Dim"
        if self.app.worker.connected:
            self.app.worker.send_command("L1" if self.sign_mode == "Full" else "L0")
        self.refresh()

    def _on_loads_update(self):
        self.led_12v_on = bool(self.led12_sw.get())
        self.refresh()

    def _seed_demo(self):
        if not self.app.db.connected:
            return messagebox.showwarning("PostgreSQL Offline", "Connect to PostgreSQL first.")
        cnt = self.app.db.seed_demo_7d()
        self.app.refresh_all()
        messagebox.showinfo("7-Day Demo Seeded", f"Inserted {cnt} realistic QCU campus step entries across 7 days.")

    def _clear_demo(self):
        if not self.app.db.connected:
            return
        deleted = self.app.db.clear_demo_data()
        self.app.refresh_all()
        messagebox.showinfo("Demo Cleared", f"Removed {deleted} 'Demo Shift Sim' runs.")

    def refresh(self):
        if not self.app.db.connected:
            return
        periods = self.app.db.get_period_counters()
        for k, (vl, sl) in self.period_labels.items():
            d = periods[k]
            vl.configure(text=f"{d['steps']:,} steps")
            sl.configure(text=f"{d['joules']:.2f} J • {d['mwh']:.2f} mWh")

        summary = self.app.db.get_dashboard_summary()
        cadence = self.app.db.get_cadence_spm(minutes=5)
        eq = analytics.compute_battery_and_equivalences(
            summary["total_joules"],
            battery_cap_wh=self.battery_cap_wh,
            usb_loads=self.usb_loads,
            led_12v_on=self.led_12v_on,
            sign_mode=self.sign_mode,
        )

        self.soc_lbl.configure(text=f"SoC: {eq['soc_pct']:.2f}%  ({eq['wh_stored']:.4f} Wh)")
        self.soc_bar.set(min(1.0, eq["soc_pct"] / 100.0))
        self.cadence_lbl.configure(text=f"Walking Cadence: {cadence:.1f} steps/min")
        self.load_draw_lbl.configure(text=f"Total Output Draw: {eq['load_mw']:.1f} mW ({eq['load_ma']:.1f} mA)")

        self.eq_phone[0].configure(text=f"{eq['phone_4000mah_pct']:.2f}%")
        self.eq_phone[1].configure(text=f"{eq['phones_full_count']:.3f} full 15.4 Wh charges")
        self.eq_talk[0].configure(text=f"{eq['emergency_talk_min']:.1f} min")
        self.eq_sign[0].configure(text=f"{eq['sign_dim_runtime_min']:.1f} min (Dim)")
        self.eq_sign[1].configure(text=f"Full (1.5kΩ): {eq['sign_full_runtime_min']:.1f} min")
        self.eq_led12[0].configure(text=f"{eq['led_12v_runtime_min']:.1f} min")

        ts = self.app.db.get_timeseries(self.current_window)
        self.window_sum_lbl.configure(text=f"Window ({ts['window'].upper()}) total: {ts['total_steps']:,} steps • {ts['total_joules']:.2f} J")

        mode = ctk.get_appearance_mode()
        fg = pick(PALETTE["text"], mode)
        for k, b in self.win_btns.items():
            active = k == self.current_window
            b.configure(
                fg_color=PALETTE["green"] if active else "transparent",
                text_color="#FFFFFF" if active else fg,
            )

        self.ax.clear()
        self.ax2.clear()
        apply_matplotlib_theme(self.fig, self.ax, mode, ax2=self.ax2)

        x = list(range(len(ts["labels"])))
        self.ax.bar(x, ts["joules"], color=PALETTE["green_bright"], alpha=0.78, label="Joules")
        self.ax2.plot(x, ts["steps"], color=PALETTE["amber"], marker="o", markersize=3, linewidth=1.8, label="Steps")

        step_tick = max(1, len(x) // 6)
        self.ax.set_xticks(x[::step_tick])
        self.ax.set_xticklabels(ts["labels"][::step_tick], rotation=0)
        self.ax.set_ylabel("Energy (J)", color=PALETTE["green_bright"], fontsize=9)
        self.ax2.set_ylabel("Footsteps", color=PALETTE["amber"], fontsize=9)
        self.ax.set_title(f"Power & Footstep Generation ({ts['window'].upper()})", color=fg, fontsize=10)
        self.fig.tight_layout()
        self.canvas.draw_idle()
