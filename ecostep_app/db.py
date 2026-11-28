"""PostgreSQL 16/18 database layer implementing EcoStep QCU's 4-table 3NF schema."""

import csv
import io
import os
import random
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from . import analytics, config


DEFAULT_COMPONENTS = [
    (
        "PZT-5A 35mm Piezoelectric Matrix (16 pcs)",
        "Drive",
        "35mm brass-backed ceramic transducers, 4x4 parallel-series array",
        16,
        "Local electronics supply / QCU Lab Bench",
        "Passed",
    ),
    (
        "Recycled Tread & Marine Plywood Platform",
        "Structure",
        "300mm x 300mm x 18mm load-bearing platform with M8 stop bolts (300+ kg)",
        1,
        "Upcycled Eco-Mat tread + salvaged lumber",
        "Passed",
    ),
    (
        "ESP32-WROOM-32 DevKit (ESP32-D0WD-V3)",
        "Electronics",
        "USB-C CH340, 115200 baud UART, MicroPython v1.29.0",
        1,
        "Main telemetry microcontroller (COM10)",
        "Passed",
    ),
    (
        "Schottky Bridge + 5.1V Zener + Storage Bank",
        "Storage",
        "4x 1N5819 Schottky, 1N4733A Zener clamp, 6600uF / 5.5V supercap",
        1,
        "Salvaged power supply & conditioning board",
        "Passed",
    ),
    (
        "5V Emergency Evacuation LED Sign Circuit",
        "Electronics",
        "Full Mode (1.5 kOhm) & Dim Mode (10 kOhm) salvaged micro-LEDs",
        1,
        "Recycled holiday LEDs + 1.5k / 10k branch resistors",
        "Pending",
    ),
]


class EcoStepDatabase:
    def __init__(self, pg_cfg=None):
        self.cfg = pg_cfg or config.load_pg_config()
        self._lock = threading.RLock()
        self._conn = None
        self.connected = False
        self.last_error = None

    def _close_cached_conn(self):
        conn = self._conn
        self._conn = None
        if conn is not None:
            try:
                if conn.closed == 0:
                    conn.close()
            except Exception:
                pass

    def close(self):
        with self._lock:
            self._close_cached_conn()

    def update_config(self, host, port, user, password, dbname="ecostep_qcu_db"):
        with self._lock:
            self._close_cached_conn()
            self.cfg = {
                "host": host,
                "port": int(port),
                "user": user,
                "password": password,
                "dbname": dbname,
            }

    def _open_new_connection(self, dbname=None):
        return psycopg2.connect(
            host=self.cfg["host"],
            port=self.cfg["port"],
            user=self.cfg["user"],
            password=self.cfg["password"],
            dbname=dbname or self.cfg["dbname"],
            connect_timeout=4,
            cursor_factory=RealDictCursor,
        )

    def _connect(self, dbname=None):
        # One-off connection for admin database tasks (e.g. dbname="postgres")
        if dbname is not None:
            return self._open_new_connection(dbname=dbname)
        # Reuse persistent connection for all app queries (eliminates per-click TCP handshakes)
        conn = self._conn
        if conn is not None and conn.closed == 0:
            try:
                if conn.status != psycopg2.extensions.STATUS_READY:
                    conn.rollback()
                return conn
            except Exception:
                self._close_cached_conn()
        self._conn = self._open_new_connection()
        return self._conn

    @staticmethod
    def _find_pg_ctl():
        candidates = [
            r"C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe",
            r"C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe",
            r"C:\Program Files\PostgreSQL\16\bin\pg_ctl.exe",
            os.path.join(config.APP_DIR, "pgsql", "bin", "pg_ctl.exe"),
        ]
        for path in candidates:
            if os.path.isfile(path):
                return path
        return None

    def _maybe_start_local_cluster(self):
        """Starts the workspace-local PostgreSQL cluster on port 5433 if stopped."""
        if self.cfg["host"] not in ("127.0.0.1", "localhost") or int(self.cfg["port"]) != 5433:
            return
        data_dir = os.path.join(config.APP_DIR, "pgdata")
        log_file = os.path.join(config.APP_DIR, "postgres.log")
        pg_ctl = self._find_pg_ctl()
        if not (os.path.isdir(data_dir) and pg_ctl):
            return
        # Remove stale log inside pgdata if present from earlier setup
        old_log = os.path.join(data_dir, "postgres.log")
        if os.path.exists(old_log):
            try:
                os.remove(old_log)
            except OSError:
                pass
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.run(
                [pg_ctl, "-D", data_dir, "-l", log_file, "-o", "-p 5433", "-w", "start"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
                timeout=20,
                check=False,
            )
        except Exception:
            pass

    def stop_local_cluster(self):
        """Cleanly shuts down the workspace-local PostgreSQL cluster if running."""
        if self.cfg["host"] not in ("127.0.0.1", "localhost") or int(self.cfg["port"]) != 5433:
            return
        data_dir = os.path.join(config.APP_DIR, "pgdata")
        pg_ctl = self._find_pg_ctl()
        if not (os.path.isdir(data_dir) and pg_ctl):
            return
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.run(
                [pg_ctl, "-D", data_dir, "-m", "fast", "-w", "stop"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
                timeout=15,
                check=False,
            )
        except Exception:
            pass

    def ensure_initialized(self):
        """Creates ecostep_qcu_db if missing, applies 3NF schema.sql, and seeds defaults."""
        with self._lock:
            try:
                admin_conn = None
                for attempt in range(6):
                    try:
                        admin_conn = self._connect(dbname="postgres")
                        break
                    except psycopg2.OperationalError as exc:
                        msg = str(exc)
                        if attempt == 0:
                            self._maybe_start_local_cluster()
                        if "starting up" in msg or attempt == 0:
                            time.sleep(0.5)
                            continue
                        raise
                if admin_conn is None:
                    admin_conn = self._connect(dbname="postgres")
                admin_conn.autocommit = True
                try:
                    with admin_conn.cursor() as cur:
                        cur.execute(
                            "SELECT 1 FROM pg_database WHERE datname = %s;",
                            (self.cfg["dbname"],),
                        )
                        if not cur.fetchone():
                            cur.execute(
                                sql.SQL("CREATE DATABASE {} ENCODING 'UTF8';").format(
                                    sql.Identifier(self.cfg["dbname"])
                                )
                            )
                finally:
                    admin_conn.close()

                with open(config.SCHEMA_PATH, "r", encoding="utf-8") as f:
                    ddl = f.read()

                conn = self._connect()
                try:
                    with conn.cursor() as cur:
                        cur.execute(ddl)
                        self._ensure_sia_sync_columns(cur)
                        cur.execute("SELECT COUNT(*) AS cnt FROM components;")
                        if cur.fetchone()["cnt"] == 0:
                            cur.executemany(
                                """
                                INSERT INTO components (
                                    component_name, category, specification,
                                    quantity, source_notes, inspection_status
                                ) VALUES (%s, %s, %s, %s, %s, %s);
                                """,
                                DEFAULT_COMPONENTS,
                            )
                    conn.commit()
                finally:
                    conn.close()

                self.connected = True
                self.last_error = None
                return True, None
            except Exception as exc:
                self.connected = False
                self.last_error = str(exc).strip()
                return False, self.last_error

    @staticmethod
    def _ensure_sia_sync_columns(cur):
        """Non-destructively migrate existing IPT2 databases with SIA101 sync columns."""
        migrations = (
            "ALTER TABLE components ADD COLUMN IF NOT EXISTS sia_synced BOOLEAN NOT NULL DEFAULT FALSE;",
            "ALTER TABLE measurement_runs ADD COLUMN IF NOT EXISTS sia_run_id VARCHAR(64);",
            "ALTER TABLE measurement_runs ADD COLUMN IF NOT EXISTS sia_synced BOOLEAN NOT NULL DEFAULT FALSE;",
            "ALTER TABLE measurement_runs ADD COLUMN IF NOT EXISTS sia_synced_at TIMESTAMP;",
            "ALTER TABLE measurement_runs ADD COLUMN IF NOT EXISTS sia_deleted_synced BOOLEAN NOT NULL DEFAULT FALSE;",
            "ALTER TABLE telemetry_logs ADD COLUMN IF NOT EXISTS sia_synced BOOLEAN NOT NULL DEFAULT FALSE;",
            "ALTER TABLE sign_tests ADD COLUMN IF NOT EXISTS sia_synced BOOLEAN NOT NULL DEFAULT FALSE;",
        )
        for stmt in migrations:
            cur.execute(stmt)
        cur.execute(
            """
            UPDATE measurement_runs
            SET sia_run_id = 'IPT2-RUN-' || LPAD(run_id::TEXT, 4, '0')
            WHERE sia_run_id IS NULL;
            """
        )

    @staticmethod
    def _new_sia_run_id(prefix="IPT2"):
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"{prefix}-{stamp}-{uuid.uuid4().hex[:6].upper()}"

    # ------------------------------------------------------------------
    # TABLE 1: COMPONENTS CRUD
    # ------------------------------------------------------------------
    def list_components(self, category="ALL", status="ALL", search=""):
        clauses = []
        params = []
        if category and category != "ALL":
            clauses.append("category = %s")
            params.append(category)
        if status and status != "ALL":
            clauses.append("inspection_status = %s")
            params.append(status)
        if search:
            clauses.append("(component_name ILIKE %s OR specification ILIKE %s)")
            like = f"%{search}%"
            params.extend([like, like])
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM components {where} ORDER BY component_id ASC;",
                params,
            )
            return [dict(r) for r in cur.fetchall()]

    def add_component(self, name, category, spec, quantity, source_notes, inspection_status):
        name = name.strip()
        if not name:
            raise ValueError("Component name cannot be empty.")
        qty = int(quantity)
        if qty <= 0:
            raise ValueError("Quantity must be a positive integer.")
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO components (
                    component_name, category, specification, quantity, source_notes, inspection_status
                ) VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *;
                """,
                (name, category, spec.strip(), qty, source_notes.strip(), inspection_status),
            )
            row = dict(cur.fetchone())
            conn.commit()
            return row

    def update_component(self, component_id, name, category, spec, quantity, source_notes, inspection_status):
        name = name.strip()
        if not name:
            raise ValueError("Component name cannot be empty.")
        qty = int(quantity)
        if qty <= 0:
            raise ValueError("Quantity must be a positive integer.")
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE components
                SET component_name = %s,
                    category = %s,
                    specification = %s,
                    quantity = %s,
                    source_notes = %s,
                    inspection_status = %s,
                    sia_synced = FALSE,
                    last_updated = NOW()
                WHERE component_id = %s
                RETURNING *;
                """,
                (name, category, spec.strip(), qty, source_notes.strip(), inspection_status, int(component_id)),
            )
            row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None

    def delete_component(self, component_id):
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM components WHERE component_id = %s;", (int(component_id),))
            conn.commit()

    # ------------------------------------------------------------------
    # TABLE 2: MEASUREMENT_RUNS CRUD + SOFT DELETE
    # ------------------------------------------------------------------
    @staticmethod
    def compute_run_metrics(energy_mwh, steps_count):
        mwh = float(energy_mwh)
        steps = int(steps_count)
        if mwh < 0:
            raise ValueError("Energy (mWh) cannot be negative.")
        if steps <= 0:
            raise ValueError("Steps count must be greater than 0.")
        joules = round(mwh * 3.6, 2)
        j_per_step = round(joules / steps, 4)
        return joules, j_per_step

    def list_runs(self, include_deleted=False, status="ALL", search=""):
        clauses = []
        params = []
        if not include_deleted:
            clauses.append("r.is_deleted = FALSE")
        if status and status != "ALL":
            clauses.append("r.status = %s")
            params.append(status)
        if search:
            clauses.append("(COALESCE(r.operator_name, '') ILIKE %s OR c.component_name ILIKE %s)")
            like = f"%{search}%"
            params.extend([like, like])
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT r.*, c.component_name
                FROM measurement_runs r
                JOIN components c ON c.component_id = r.component_id
                {where}
                ORDER BY r.run_id DESC;
                """,
                params,
            )
            return [dict(r) for r in cur.fetchall()]

    def create_run(
        self,
        component_id,
        operator_name="",
        steps_count=100,
        energy_mwh=0.0,
        adc_peak_volts=0.0,
        charging_path="Path A",
        status="Pending",
    ):
        joules, j_per_step = self.compute_run_metrics(energy_mwh, steps_count)
        sia_run_id = self._new_sia_run_id("IPT2")
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO measurement_runs (
                    component_id, operator_name, steps_count,
                    energy_mwh, energy_joules, joules_per_step,
                    adc_peak_volts, charging_path, status, sia_run_id, sia_synced
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE)
                RETURNING *;
                """,
                (
                    int(component_id),
                    operator_name.strip() or "QCU Researcher",
                    int(steps_count),
                    round(float(energy_mwh), 2),
                    joules,
                    j_per_step,
                    round(float(adc_peak_volts), 2),
                    charging_path,
                    status,
                    sia_run_id,
                ),
            )
            row = dict(cur.fetchone())
            conn.commit()
            return row

    def update_run(
        self,
        run_id,
        component_id,
        operator_name,
        steps_count,
        energy_mwh,
        adc_peak_volts,
        charging_path,
        status,
    ):
        joules, j_per_step = self.compute_run_metrics(energy_mwh, steps_count)
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE measurement_runs
                SET component_id = %s,
                    operator_name = %s,
                    steps_count = %s,
                    energy_mwh = %s,
                    energy_joules = %s,
                    joules_per_step = %s,
                    adc_peak_volts = %s,
                    charging_path = %s,
                    status = %s,
                    sia_synced = FALSE
                WHERE run_id = %s
                RETURNING *;
                """,
                (
                    int(component_id),
                    operator_name.strip() or "QCU Researcher",
                    int(steps_count),
                    round(float(energy_mwh), 2),
                    joules,
                    j_per_step,
                    round(float(adc_peak_volts), 2),
                    charging_path,
                    status,
                    int(run_id),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None

    def soft_delete_run(self, run_id, deleted=True):
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE measurement_runs
                SET is_deleted = %s,
                    sia_synced = FALSE,
                    sia_deleted_synced = FALSE
                WHERE run_id = %s;
                """,
                (bool(deleted), int(run_id)),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # TABLE 3: TELEMETRY_LOGS
    # ------------------------------------------------------------------
    def insert_telemetry_log(self, run_id, step_number, adc_raw, adc_voltage, baud_rate=115200):
        raw_clamped = max(0, min(1023, int(adc_raw)))
        volts = round(float(adc_voltage), 2)
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO telemetry_logs (
                    run_id, step_number, adc_raw, adc_voltage, baud_rate
                ) VALUES (%s, %s, %s, %s, %s)
                RETURNING *;
                """,
                (int(run_id), int(step_number), raw_clamped, volts, int(baud_rate)),
            )
            log_row = dict(cur.fetchone())
            # Keep parent measurement_run peak voltage & step count synced if higher
            cur.execute(
                """
                UPDATE measurement_runs
                SET adc_peak_volts = GREATEST(adc_peak_volts, %s)
                WHERE run_id = %s;
                """,
                (volts, int(run_id)),
            )
            conn.commit()
            return log_row

    def list_telemetry_logs(self, run_id=None, limit=100):
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            if run_id is not None:
                cur.execute(
                    """
                    SELECT * FROM telemetry_logs
                    WHERE run_id = %s
                    ORDER BY log_id DESC
                    LIMIT %s;
                    """,
                    (int(run_id), int(limit)),
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM telemetry_logs
                    ORDER BY log_id DESC
                    LIMIT %s;
                    """,
                    (int(limit),),
                )
            return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # TABLE 4: SIGN_TESTS CRUD
    # ------------------------------------------------------------------
    @staticmethod
    def compute_sign_power_mw(load_ma):
        ma = float(load_ma)
        if ma < 0 or ma > 5000:
            raise ValueError("Load current (mA) must be between 0 and 5000 mA.")
        return round(5.0 * ma, 2)

    def list_sign_tests(self, sign_mode="ALL", run_id=None):
        clauses = []
        params = []
        if sign_mode and sign_mode != "ALL":
            clauses.append("s.sign_mode = %s")
            params.append(sign_mode)
        if run_id is not None:
            clauses.append("s.run_id = %s")
            params.append(int(run_id))
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT s.*, r.operator_name, r.charging_path
                FROM sign_tests s
                JOIN measurement_runs r ON r.run_id = s.run_id
                {where}
                ORDER BY s.test_id DESC;
                """,
                params,
            )
            return [dict(r) for r in cur.fetchall()]

    def add_sign_test(
        self,
        run_id,
        sign_mode,
        load_ma,
        runtime_minutes,
        status="Completed",
        is_available=True,
    ):
        resistor = "1.5 kΩ" if sign_mode == "Full" else "10 kΩ"
        power_mw = self.compute_sign_power_mw(load_ma)
        rt_min = round(float(runtime_minutes), 2)
        if rt_min < 0:
            raise ValueError("Runtime minutes cannot be negative.")
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sign_tests (
                    run_id, sign_mode, resistor_value, load_ma, power_mw,
                    runtime_minutes, status, is_available
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *;
                """,
                (
                    int(run_id),
                    sign_mode,
                    resistor,
                    round(float(load_ma), 2),
                    power_mw,
                    rt_min,
                    status,
                    bool(is_available),
                ),
            )
            row = dict(cur.fetchone())
            conn.commit()
            return row

    def update_sign_test(self, test_id, sign_mode, load_ma, runtime_minutes, status, is_available):
        resistor = "1.5 kΩ" if sign_mode == "Full" else "10 kΩ"
        power_mw = self.compute_sign_power_mw(load_ma)
        rt_min = round(float(runtime_minutes), 2)
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sign_tests
                SET sign_mode = %s,
                    resistor_value = %s,
                    load_ma = %s,
                    power_mw = %s,
                    runtime_minutes = %s,
                    status = %s,
                    is_available = %s,
                    sia_synced = FALSE,
                    last_updated = NOW()
                WHERE test_id = %s
                RETURNING *;
                """,
                (
                    sign_mode,
                    resistor,
                    round(float(load_ma), 2),
                    power_mw,
                    rt_min,
                    status,
                    bool(is_available),
                    int(test_id),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None

    def delete_sign_test(self, test_id):
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM sign_tests WHERE test_id = %s;", (int(test_id),))
            conn.commit()

    # ------------------------------------------------------------------
    # SUMMARY, TIME-HORIZON ANALYTICS, CADENCE & CSV EXPORT
    # ------------------------------------------------------------------
    def get_dashboard_summary(self):
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE is_deleted = FALSE) AS active_runs,
                    COALESCE(SUM(energy_joules) FILTER (WHERE is_deleted = FALSE), 0) AS total_joules,
                    COALESCE(MAX(adc_peak_volts) FILTER (WHERE is_deleted = FALSE), 0) AS max_peak_volts
                FROM measurement_runs;
                """
            )
            run_stats = dict(cur.fetchone())
            cur.execute(
                """
                SELECT
                    COUNT(*) AS log_cnt,
                    COALESCE(SUM(LEAST(1.05, GREATEST(0.35, adc_voltage * 0.062))), 0) AS log_joules
                FROM telemetry_logs t
                JOIN measurement_runs r ON r.run_id = t.run_id
                WHERE r.is_deleted = FALSE;
                """
            )
            log_row = dict(cur.fetchone())
            cur.execute("SELECT COUNT(*) AS cnt FROM sign_tests;")
            sign_cnt = cur.fetchone()["cnt"]
            cur.execute("SELECT COUNT(*) AS cnt FROM components;")
            comp_cnt = cur.fetchone()["cnt"]
        total_j = max(float(run_stats["total_joules"]), float(log_row["log_joules"]))
        return {
            "active_runs": int(run_stats["active_runs"]),
            "total_joules": round(total_j, 2),
            "max_peak_volts": float(run_stats["max_peak_volts"]),
            "telemetry_count": int(log_row["log_cnt"]),
            "sign_tests_count": int(sign_cnt),
            "components_count": int(comp_cnt),
        }

    def get_cadence_spm(self, minutes=5):
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.recorded_at
                FROM telemetry_logs t
                JOIN measurement_runs r ON r.run_id = t.run_id
                WHERE r.is_deleted = FALSE
                  AND t.recorded_at >= NOW() - (%s || ' minutes')::INTERVAL
                ORDER BY t.recorded_at ASC;
                """,
                (int(minutes),),
            )
            rows = cur.fetchall()
        if not rows:
            return 0.0
        if len(rows) == 1:
            return 1.0
        span_min = max(0.25, (datetime.now() - rows[0]["recorded_at"]).total_seconds() / 60.0)
        return round(len(rows) / span_min, 1)

    def get_period_counters(self):
        """Returns step counts and harvested Joules across 1h, 10h, 24h, 48h, and 7d windows."""
        windows = [("1h", 1), ("10h", 10), ("24h", 24), ("48h", 48), ("7d", 168)]
        out = {}
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            for key, hrs in windows:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS steps,
                        COALESCE(SUM(LEAST(1.05, GREATEST(0.35, t.adc_voltage * 0.062))), 0) AS joules
                    FROM telemetry_logs t
                    JOIN measurement_runs r ON r.run_id = t.run_id
                    WHERE r.is_deleted = FALSE
                      AND t.recorded_at >= NOW() - (%s || ' hours')::INTERVAL;
                    """,
                    (hrs,),
                )
                row = cur.fetchone()
                j = round(float(row["joules"]), 2)
                out[key] = {
                    "steps": int(row["steps"]),
                    "joules": j,
                    "mwh": round(j / 3.6, 2),
                }
        return out

    def get_timeseries(self, window="1h"):
        """Buckets telemetry_logs by real recorded_at timestamps for 1h, 10h, 24h, 48h, or 7d."""
        presets = {
            "1h": (3600, 180, "%H:%M"),         # 20 buckets (3 min each)
            "10h": (36000, 1800, "%H:%M"),      # 20 buckets (30 min each)
            "24h": (86400, 3600, "%H:%M"),      # 24 buckets (1 hr each)
            "48h": (172800, 7200, "%m/%d %H:%M"),  # 24 buckets (2 hr each)
            "7d": (604800, 43200, "%a %H:%M"),  # 14 buckets (12 hr each)
        }
        span_sec, bucket_sec, fmt = presets.get(window, presets["1h"])
        now_dt = datetime.now()
        start_dt = now_dt - timedelta(seconds=span_sec)
        num_buckets = int(span_sec // bucket_sec)

        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.recorded_at, t.adc_voltage
                FROM telemetry_logs t
                JOIN measurement_runs r ON r.run_id = t.run_id
                WHERE r.is_deleted = FALSE
                  AND t.recorded_at >= %s
                ORDER BY t.recorded_at ASC;
                """,
                (start_dt,),
            )
            rows = cur.fetchall()

        buckets = [{"steps": 0, "joules": 0.0} for _ in range(num_buckets)]
        for r in rows:
            idx = int((r["recorded_at"] - start_dt).total_seconds() / bucket_sec)
            if idx < 0:
                continue
            if idx >= num_buckets:
                idx = num_buckets - 1
            buckets[idx]["steps"] += 1
            buckets[idx]["joules"] += analytics.estimate_step_joules(r["adc_voltage"])

        labels = []
        steps = []
        joules = []
        for i, b in enumerate(buckets):
            end_dt = start_dt + timedelta(seconds=(i + 1) * bucket_sec)
            labels.append(end_dt.strftime(fmt))
            steps.append(b["steps"])
            joules.append(round(b["joules"], 2))

        return {
            "window": window,
            "labels": labels,
            "steps": steps,
            "joules": joules,
            "total_steps": sum(steps),
            "total_joules": round(sum(joules), 2),
        }

    def seed_demo_7d(self):
        """Seeds 7 days of realistic QCU campus foot traffic tagged 'Demo Shift Sim'."""
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM measurement_runs WHERE operator_name = 'Demo Shift Sim';")
            cur.execute("SELECT component_id FROM components ORDER BY component_id ASC LIMIT 1;")
            comp_row = cur.fetchone()
            if not comp_row:
                conn.commit()
                return 0
            cid = comp_row["component_id"]

            now_dt = datetime.now()
            total_inserted = 0
            # Create 1 daily run per day for the past 7 days + sample telemetry_logs timestamps
            for day_ago in range(6, -1, -1):
                day_dt = now_dt - timedelta(days=day_ago)
                day_steps = []
                for hr in range(24):
                    slot_dt = day_dt.replace(hour=hr, minute=15, second=0, microsecond=0)
                    if slot_dt > now_dt:
                        continue
                    if 7 <= hr <= 9 or 11 <= hr <= 14 or 17 <= hr <= 19:
                        n_samples = random.randint(12, 22)
                    elif 10 <= hr <= 16:
                        n_samples = random.randint(5, 10)
                    else:
                        n_samples = random.randint(0, 2)
                    for s in range(n_samples):
                        ts = slot_dt + timedelta(minutes=random.randint(0, 58), seconds=random.randint(0, 59))
                        if ts > now_dt:
                            continue
                        raw = random.randint(610, 960)
                        volts = round((raw / 1023.0) * 3.30 * 4.30, 2)
                        day_steps.append((raw, volts, ts))

                if not day_steps:
                    continue
                total_j = round(sum(analytics.estimate_step_joules(v) for _, v, _ in day_steps), 2)
                mwh = round(total_j / 3.6, 2)
                jps = round(total_j / len(day_steps), 4)
                peak_v = max(v for _, v, _ in day_steps)
                cur.execute(
                    """
                    INSERT INTO measurement_runs (
                        component_id, run_date, operator_name, steps_count,
                        energy_mwh, energy_joules, joules_per_step,
                        adc_peak_volts, charging_path, status, sia_run_id, sia_synced
                    ) VALUES (%s, %s, 'Demo Shift Sim', %s, %s, %s, %s, %s, 'Path A', 'Completed', %s, FALSE)
                    RETURNING run_id;
                    """,
                    (cid, day_dt, len(day_steps), mwh, total_j, jps, peak_v, self._new_sia_run_id("DEMO")),
                )
                rid = cur.fetchone()["run_id"]
                log_rows = [
                    (rid, idx + 1, raw, volts, 115200, ts)
                    for idx, (raw, volts, ts) in enumerate(sorted(day_steps, key=lambda x: x[2]))
                ]
                cur.executemany(
                    """
                    INSERT INTO telemetry_logs (
                        run_id, step_number, adc_raw, adc_voltage, baud_rate, recorded_at, sia_synced
                    ) VALUES (%s, %s, %s, %s, %s, %s, TRUE);
                    """,
                    log_rows,
                )
                total_inserted += len(log_rows)
            conn.commit()
            return total_inserted

    def list_demo_sia_run_ids(self):
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT sia_run_id FROM measurement_runs WHERE operator_name = 'Demo Shift Sim' AND sia_run_id IS NOT NULL;"
            )
            return [r["sia_run_id"] for r in cur.fetchall()]

    def clear_demo_data(self):
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM measurement_runs WHERE operator_name = 'Demo Shift Sim';")
            deleted = cur.rowcount
            conn.commit()
            return deleted

    # ------------------------------------------------------------------
    # SIA101 WEB BRIDGE OFFLINE SYNC QUEUE HELPERS
    # ------------------------------------------------------------------
    def get_unsynced_runs(self):
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT run_id, sia_run_id, run_date, steps_count, energy_mwh,
                       energy_joules, adc_peak_volts, charging_path, status, sia_synced_at
                FROM measurement_runs
                WHERE is_deleted = FALSE
                  AND sia_synced = FALSE
                  AND sia_run_id IS NOT NULL
                  AND (status != 'Pending' OR energy_joules > 0)
                ORDER BY run_id ASC;
                """
            )
            return [dict(r) for r in cur.fetchall()]

    def get_pending_soft_deletes(self):
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT run_id, sia_run_id
                FROM measurement_runs
                WHERE is_deleted = TRUE
                  AND sia_deleted_synced = FALSE
                  AND sia_run_id IS NOT NULL
                ORDER BY run_id ASC;
                """
            )
            return [dict(r) for r in cur.fetchall()]

    def mark_run_synced(self, run_id, deleted_synced=False):
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            if deleted_synced:
                cur.execute(
                    """
                    UPDATE measurement_runs
                    SET sia_synced = TRUE, sia_deleted_synced = TRUE, sia_synced_at = NOW()
                    WHERE run_id = %s;
                    """,
                    (int(run_id),),
                )
            else:
                cur.execute(
                    """
                    UPDATE measurement_runs
                    SET sia_synced = TRUE, sia_synced_at = NOW()
                    WHERE run_id = %s;
                    """,
                    (int(run_id),),
                )
            conn.commit()

    def get_unsynced_live_logs(self, limit=250):
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.log_id, t.run_id, t.step_number, t.adc_raw, t.adc_voltage,
                       t.recorded_at, r.charging_path
                FROM telemetry_logs t
                JOIN measurement_runs r ON r.run_id = t.run_id
                WHERE t.sia_synced = FALSE
                  AND r.is_deleted = FALSE
                  AND COALESCE(r.operator_name, '') != 'Demo Shift Sim'
                ORDER BY t.log_id ASC
                LIMIT %s;
                """,
                (int(limit),),
            )
            return [dict(r) for r in cur.fetchall()]

    def mark_logs_synced(self, log_ids):
        if not log_ids:
            return
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE telemetry_logs SET sia_synced = TRUE WHERE log_id = ANY(%s);",
                ([int(i) for i in log_ids],),
            )
            conn.commit()

    def get_unsynced_sign_tests(self):
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.*, r.sia_run_id
                FROM sign_tests s
                JOIN measurement_runs r ON r.run_id = s.run_id
                WHERE s.sia_synced = FALSE
                ORDER BY s.test_id ASC;
                """
            )
            return [dict(r) for r in cur.fetchall()]

    def mark_sign_test_synced(self, test_id):
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE sign_tests SET sia_synced = TRUE WHERE test_id = %s;",
                (int(test_id),),
            )
            conn.commit()

    def get_unsynced_components(self):
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT component_id, component_name, category, specification,
                       quantity, source_notes, inspection_status
                FROM components
                WHERE sia_synced = FALSE
                ORDER BY component_id ASC;
                """
            )
            return [dict(r) for r in cur.fetchall()]

    def mark_component_synced(self, component_id):
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE components SET sia_synced = TRUE WHERE component_id = %s;",
                (int(component_id),),
            )
            conn.commit()

    def get_pending_sync_count(self):
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM measurement_runs
                     WHERE is_deleted = FALSE AND sia_synced = FALSE AND sia_run_id IS NOT NULL
                       AND (status != 'Pending' OR energy_joules > 0))
                    + (SELECT COUNT(*) FROM measurement_runs
                       WHERE is_deleted = TRUE AND sia_deleted_synced = FALSE AND sia_run_id IS NOT NULL)
                    + (SELECT COUNT(DISTINCT t.run_id) FROM telemetry_logs t
                       JOIN measurement_runs r ON r.run_id = t.run_id
                       WHERE t.sia_synced = FALSE AND r.is_deleted = FALSE
                         AND COALESCE(r.operator_name, '') != 'Demo Shift Sim')
                    + (SELECT COUNT(*) FROM sign_tests WHERE sia_synced = FALSE)
                    + (SELECT COUNT(*) FROM components WHERE sia_synced = FALSE)
                AS pending_cnt;
                """
            )
            return int(cur.fetchone()["pending_cnt"] or 0)

    def export_runs_csv(self):
        rows = self.list_runs(include_deleted=False)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "run_id",
                "component_name",
                "run_date",
                "operator_name",
                "steps_count",
                "energy_mwh",
                "energy_joules",
                "joules_per_step",
                "adc_peak_volts",
                "charging_path",
                "status",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r["run_id"],
                    r["component_name"],
                    str(r["run_date"])[:19],
                    r["operator_name"],
                    r["steps_count"],
                    r["energy_mwh"],
                    r["energy_joules"],
                    r["joules_per_step"],
                    r["adc_peak_volts"],
                    r["charging_path"],
                    r["status"],
                ]
            )
        return buf.getvalue()
