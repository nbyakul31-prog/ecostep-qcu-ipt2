"""Background SIA101 XML Bridge synchronization client for EcoStep QCU IPT2 Desktop App.

Converts local PostgreSQL telemetry runs and live ESP32 step batches into strictly
XSD-compliant <telemetryRun> XML (excluding operator_name / PII) and syncs them
with the SIA101 Flask Web App (Render or localhost) with offline retry safety.
"""

from datetime import datetime
import queue
import re
import threading
import time
from xml.sax.saxutils import escape

import requests

from . import analytics, config

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._:-]+")


def _format_local_iso(dt_val):
    """Format a datetime (naive local or aware) as ISO-8601 with explicit local timezone offset."""
    if isinstance(dt_val, str):
        dt_val = datetime.fromisoformat(dt_val.replace("Z", "+00:00"))
    if dt_val is None:
        dt_val = datetime.now().astimezone()
    elif dt_val.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo
        dt_val = dt_val.replace(tzinfo=local_tz)
    return dt_val.isoformat(timespec="seconds")


def sanitize_xml_id(raw_id, fallback="IPT2-RUN"):
    cleaned = _SAFE_ID_RE.sub("-", str(raw_id or "").strip()).strip("-")
    if len(cleaned) < 3:
        cleaned = f"{fallback}-{cleaned or '001'}"
    return cleaned[:64]


def build_telemetry_run_xml(
    run_id,
    tile_id,
    recorded_at,
    footsteps,
    capacitor_voltage_v,
    energy_joules,
    led_sign_on=True,
    energy_mwh=None,
    charging_path="Path A",
    sign_mode="Dim",
    run_status="Completed",
):
    """Serialize one run into XSD-compliant <telemetryRun> XML bytes (zero PII / operator_name)."""
    rid = sanitize_xml_id(run_id, fallback="IPT2-RUN")
    tid = sanitize_xml_id(tile_id, fallback="TILE-01")
    ts = _format_local_iso(recorded_at)
    steps = max(0, int(footsteps))
    volts = max(0.0, min(50.0, float(capacitor_voltage_v)))
    joules = max(0.0, float(energy_joules))
    mwh = (
        max(0.0, float(energy_mwh))
        if energy_mwh is not None
        else (round(joules / 3.6, 4) if joules > 0 else 0.0)
    )

    path_clean = charging_path if charging_path in ("Path A", "Path B") else "Path A"
    mode_clean = sign_mode if sign_mode in ("Full", "Dim", "Off") else ("Full" if led_sign_on else "Off")
    led_bool = bool(led_sign_on) and mode_clean != "Off"
    status_clean = run_status if run_status in ("Completed", "Pending", "Invalid") else "Completed"

    xml_text = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<telemetryRun>\n"
        f"  <run_id>{escape(rid)}</run_id>\n"
        f"  <tile_id>{escape(tid)}</tile_id>\n"
        f"  <recorded_at>{escape(ts)}</recorded_at>\n"
        f"  <footsteps>{steps}</footsteps>\n"
        f"  <capacitor_voltage_v>{volts:.3f}</capacitor_voltage_v>\n"
        f"  <energy_joules>{joules:.3f}</energy_joules>\n"
        f"  <led_sign_on>{'true' if led_bool else 'false'}</led_sign_on>\n"
        f"  <energy_mwh>{mwh:.4f}</energy_mwh>\n"
        f"  <charging_path>{escape(path_clean)}</charging_path>\n"
        f"  <sign_mode>{escape(mode_clean)}</sign_mode>\n"
        f"  <run_status>{escape(status_clean)}</run_status>\n"
        "</telemetryRun>\n"
    )
    return xml_text.encode("utf-8")


class SiaBridgeSyncService:
    """Thread-safe offline-first sync worker bridging IPT2 PostgreSQL to SIA101 Flask/Render."""

    def __init__(self, db, event_queue=None, get_sign_mode=None, sia_cfg=None):
        self.db = db
        self.event_queue = event_queue or queue.Queue(maxsize=128)
        self.get_sign_mode = get_sign_mode or (lambda: "Dim")
        self.cfg = sia_cfg or config.load_sia_config()

        self._sync_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread = None
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "EcoStep-QCU-IPT2-Desktop/1.0"})

        self.last_status = "unconfigured"
        self.last_message = "Not configured"
        self.last_synced_at = None

    @property
    def is_configured(self):
        return bool(self.cfg.get("bridge_url") and self.cfg.get("api_key"))

    def update_config(self, bridge_url, api_key, tile_id="TILE-01", auto_sync=True, sync_interval=15):
        self.cfg = {
            "bridge_url": (bridge_url or "").strip().rstrip("/"),
            "api_key": (api_key or "").strip(),
            "tile_id": (tile_id or "TILE-01").strip() or "TILE-01",
            "auto_sync": bool(auto_sync),
            "sync_interval": max(5, min(300, int(sync_interval))),
        }
        self._wake_event.set()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="sia-sync-worker", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self._wake_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        try:
            self._session.close()
        except Exception:
            pass

    def trigger_sync(self):
        """Wake the background worker immediately to upload pending items."""
        self._wake_event.set()

    def _emit(self, status, message, queued=0, detail=None, log_tag="info"):
        self.last_status = status
        self.last_message = message
        try:
            self.event_queue.put_nowait(
                {
                    "status": status,
                    "message": message,
                    "queued": queued,
                    "detail": detail,
                    "log_tag": log_tag,
                }
            )
        except queue.Full:
            pass

    def _headers(self, content_type=None, api_key_override=None):
        headers = {"X-API-Key": api_key_override if api_key_override is not None else self.cfg["api_key"]}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def test_connection(self, bridge_url=None, api_key=None):
        """Verify bridge reachability (/api/health) and API key (/api/verify-key)."""
        url = (bridge_url if bridge_url is not None else self.cfg["bridge_url"]).strip().rstrip("/")
        key = (api_key if api_key is not None else self.cfg["api_key"]).strip()
        if not url:
            return False, "Enter your SIA Web App URL (e.g. https://your-app.onrender.com)."
        if not url.startswith(("http://", "https://")):
            return False, "Bridge URL must start with http:// or https://."
        if not key:
            return False, "Enter your SIA Bridge API Key (EQC_API_KEY)."

        try:
            health_resp = self._session.get(f"{url}/api/health", timeout=35)
            if health_resp.status_code != 200:
                return False, f"Health check returned HTTP {health_resp.status_code}."
            health_data = health_resp.json()
        except requests.Timeout:
            return False, "Connection timed out (Render free tier may still be waking up — retry once)."
        except Exception as exc:
            return False, f"Cannot reach {url}: {exc}"

        try:
            verify_resp = self._session.get(
                f"{url}/api/verify-key",
                headers=self._headers(api_key_override=key),
                timeout=20,
            )
            if verify_resp.status_code == 200:
                engine = health_data.get("engine", "db")
                total_runs = health_data.get("total_runs", 0)
                return True, f"Connected & API Key verified ({engine}, {total_runs} runs online)."
            if verify_resp.status_code == 401:
                return False, "Server is online, but X-API-Key was rejected (HTTP 401)."
            if verify_resp.status_code == 404:
                # Backwards compatibility if Render hasn't finished redeploying /api/verify-key yet
                engine = health_data.get("engine", "db")
                return True, f"Health OK ({engine}). Redeploy SIA web app to enable /api/verify-key."
            return False, f"Key check failed with HTTP {verify_resp.status_code}."
        except Exception as exc:
            return False, f"Health OK, but key verification failed: {exc}"

    def _loop(self):
        # Brief initial pause so DB finishes boot initialization first
        self._wake_event.wait(timeout=2.0)
        while not self._stop_event.is_set():
            self._wake_event.clear()
            if self.db.connected and self.is_configured:
                self.sync_once()
            elif not self.is_configured:
                queued = self.db.get_pending_sync_count() if self.db.connected else 0
                self._emit("unconfigured", "Not Configured", queued=queued)

            wait_sec = self.cfg.get("sync_interval", 15) if self.cfg.get("auto_sync", True) else 3600
            self._wake_event.wait(timeout=wait_sec)

    def sync_once(self):
        """Synchronize unsynced runs, live step batches, soft-deletes, sign tests, and components."""
        summary = {
            "runs_synced": 0,
            "live_batches_synced": 0,
            "deletes_synced": 0,
            "sign_tests_synced": 0,
            "components_synced": 0,
            "failed": 0,
            "auth_error": False,
        }
        if not self.db.connected:
            return summary
        if not self.is_configured:
            self._emit("unconfigured", "Not Configured", queued=self.db.get_pending_sync_count())
            return summary

        if not self._sync_lock.acquire(blocking=False):
            return summary

        try:
            url = self.cfg["bridge_url"]
            tile_id = self.cfg.get("tile_id", "TILE-01")
            current_sign_mode = self.get_sign_mode() or "Dim"
            queued_before = self.db.get_pending_sync_count()

            if queued_before > 0:
                self._emit("syncing", f"Syncing ({queued_before})...", queued=queued_before)

            # 1. Measurement Runs (100-Step Benchmarks & Completed Trials)
            for run in self.db.get_unsynced_runs():
                xml_bytes = build_telemetry_run_xml(
                    run_id=run["sia_run_id"],
                    tile_id=tile_id,
                    recorded_at=run["run_date"],
                    footsteps=run["steps_count"],
                    capacitor_voltage_v=run["adc_peak_volts"],
                    energy_joules=run["energy_joules"],
                    led_sign_on=current_sign_mode != "Off",
                    energy_mwh=run["energy_mwh"],
                    charging_path=run["charging_path"],
                    sign_mode=current_sign_mode,
                    run_status=run["status"],
                )
                method = "PUT" if run.get("sia_synced_at") else "POST"
                try:
                    resp = self._session.request(
                        method,
                        f"{url}/api/ingest",
                        data=xml_bytes,
                        headers=self._headers("application/xml"),
                        timeout=35,
                    )
                    if resp.status_code == 405 and method == "PUT":
                        resp = self._session.post(
                            f"{url}/api/ingest",
                            data=xml_bytes,
                            headers=self._headers("application/xml"),
                            timeout=35,
                        )
                except requests.RequestException as exc:
                    summary["failed"] += 1
                    self._emit(
                        "offline",
                        f"Offline ({self.db.get_pending_sync_count()} queued)",
                        queued=self.db.get_pending_sync_count(),
                        detail=f"SIA bridge unreachable (kept in local PG queue): {exc}",
                        log_tag="err",
                    )
                    return summary

                if resp.status_code == 401:
                    summary["auth_error"] = True
                    summary["failed"] += 1
                    self._emit(
                        "auth_error",
                        "Auth Error (401)",
                        queued=self.db.get_pending_sync_count(),
                        detail="SIA API key rejected (HTTP 401). Open Bridge Setup to update X-API-Key.",
                        log_tag="err",
                    )
                    return summary
                if resp.status_code in (200, 201):
                    self.db.mark_run_synced(run["run_id"])
                    summary["runs_synced"] += 1
                    try:
                        body = resp.json()
                        alert = body.get("alert") or {}
                        if alert.get("triggered") and alert.get("status") == "SENT":
                            self._emit(
                                "syncing",
                                "Alert Sent",
                                queued=self.db.get_pending_sync_count(),
                                detail=f"SIA high-voltage email alert triggered for {run['sia_run_id']}: {alert.get('detail', '')}",
                                log_tag="status",
                            )
                    except ValueError:
                        pass
                else:
                    summary["failed"] += 1
                    self._emit(
                        "error",
                        f"Sync Error ({resp.status_code})",
                        queued=self.db.get_pending_sync_count(),
                        detail=f"Run #{run['run_id']} rejected ({resp.status_code}): {resp.text[:160]}",
                        log_tag="err",
                    )

            # 2. Propagate Soft-Deletes on measurement_runs
            for del_run in self.db.get_pending_soft_deletes():
                sia_id = del_run["sia_run_id"]
                try:
                    resp = self._session.delete(
                        f"{url}/api/runs/{sia_id}",
                        headers=self._headers(),
                        timeout=25,
                    )
                except requests.RequestException:
                    summary["failed"] += 1
                    break

                if resp.status_code == 401:
                    summary["auth_error"] = True
                    summary["failed"] += 1
                    self._emit("auth_error", "Auth Error (401)", queued=self.db.get_pending_sync_count(), log_tag="err")
                    return summary
                if resp.status_code in (200, 404):
                    self.db.mark_run_synced(del_run["run_id"], deleted_synced=True)
                    summary["deletes_synced"] += 1
                else:
                    summary["failed"] += 1

            # 3. Live ESP32 / Quick-Step Telemetry Batches (telemetry_logs)
            live_logs = self.db.get_unsynced_live_logs(limit=250)
            if live_logs:
                by_run = {}
                for row in live_logs:
                    by_run.setdefault(row["run_id"], []).append(row)

                for run_id, batch in by_run.items():
                    min_id = batch[0]["log_id"]
                    max_id = batch[-1]["log_id"]
                    peak_v = max(float(r["adc_voltage"]) for r in batch)
                    total_j = round(sum(analytics.estimate_step_joules(r["adc_voltage"]) for r in batch), 3)
                    total_mwh = round(total_j / 3.6, 4)
                    latest_ts = batch[-1]["recorded_at"]
                    c_path = batch[-1].get("charging_path") or "Path A"
                    live_xml_id = f"IPT2-LIVE-R{run_id}-L{min_id}-{max_id}"

                    xml_bytes = build_telemetry_run_xml(
                        run_id=live_xml_id,
                        tile_id=tile_id,
                        recorded_at=latest_ts,
                        footsteps=len(batch),
                        capacitor_voltage_v=peak_v,
                        energy_joules=total_j,
                        led_sign_on=current_sign_mode != "Off",
                        energy_mwh=total_mwh,
                        charging_path=c_path,
                        sign_mode=current_sign_mode,
                        run_status="Completed",
                    )
                    try:
                        resp = self._session.post(
                            f"{url}/api/ingest",
                            data=xml_bytes,
                            headers=self._headers("application/xml"),
                            timeout=35,
                        )
                    except requests.RequestException as exc:
                        summary["failed"] += 1
                        self._emit(
                            "offline",
                            f"Offline ({self.db.get_pending_sync_count()} queued)",
                            queued=self.db.get_pending_sync_count(),
                            detail=f"SIA bridge offline; live steps buffered safely in PostgreSQL ({exc})",
                            log_tag="err",
                        )
                        return summary

                    if resp.status_code == 401:
                        summary["auth_error"] = True
                        summary["failed"] += 1
                        self._emit("auth_error", "Auth Error (401)", queued=self.db.get_pending_sync_count(), log_tag="err")
                        return summary
                    if resp.status_code in (200, 201):
                        self.db.mark_logs_synced([r["log_id"] for r in batch])
                        summary["live_batches_synced"] += 1
                    else:
                        summary["failed"] += 1

            # 4. 5V Sign Verification Tests (sign_tests)
            for st in self.db.get_unsynced_sign_tests():
                load_ma = float(st["load_ma"])
                if load_ma <= 0 or load_ma > 500.0:
                    # Exceeds SIA's 500 mA polyfuse safety bound; skip without blocking queue
                    self.db.mark_sign_test_synced(st["test_id"])
                    continue
                payload = {
                    "external_id": f"IPT2-SIGN-{st['test_id']}",
                    "run_id": st.get("sia_run_id") or f"IPT2-RUN-{st['run_id']}",
                    "sign_mode": st["sign_mode"],
                    "resistor_value": st["resistor_value"],
                    "load_ma": load_ma,
                    "runtime_minutes": float(st["runtime_minutes"]),
                    "status": st["status"],
                    "is_available": bool(st["is_available"]),
                }
                try:
                    resp = self._session.post(
                        f"{url}/api/sign-tests",
                        json=payload,
                        headers=self._headers("application/json"),
                        timeout=25,
                    )
                except requests.RequestException:
                    summary["failed"] += 1
                    break

                if resp.status_code == 401:
                    summary["auth_error"] = True
                    summary["failed"] += 1
                    self._emit("auth_error", "Auth Error (401)", queued=self.db.get_pending_sync_count(), log_tag="err")
                    return summary
                if resp.status_code in (200, 201):
                    self.db.mark_sign_test_synced(st["test_id"])
                    summary["sign_tests_synced"] += 1
                elif resp.status_code == 400:
                    # Validation mismatch: mark synced so bad legacy row doesn't loop forever
                    self.db.mark_sign_test_synced(st["test_id"])
                else:
                    summary["failed"] += 1

            # 5. Hardware Asset Inventory (components)
            for comp in self.db.get_unsynced_components():
                payload = {
                    "external_id": f"IPT2-COMP-{comp['component_id']}",
                    "upsert_by_name": True,
                    "component_name": comp["component_name"],
                    "category": comp["category"],
                    "specification": comp["specification"],
                    "quantity": int(comp["quantity"]),
                    "source_notes": comp.get("source_notes") or "",
                    "inspection_status": comp["inspection_status"],
                }
                try:
                    resp = self._session.post(
                        f"{url}/api/components",
                        json=payload,
                        headers=self._headers("application/json"),
                        timeout=25,
                    )
                except requests.RequestException:
                    summary["failed"] += 1
                    break

                if resp.status_code == 401:
                    summary["auth_error"] = True
                    summary["failed"] += 1
                    self._emit("auth_error", "Auth Error (401)", queued=self.db.get_pending_sync_count(), log_tag="err")
                    return summary
                if resp.status_code in (200, 201):
                    self.db.mark_component_synced(comp["component_id"])
                    summary["components_synced"] += 1
                elif resp.status_code == 400:
                    self.db.mark_component_synced(comp["component_id"])
                else:
                    summary["failed"] += 1

            remaining = self.db.get_pending_sync_count()
            total_pushed = (
                summary["runs_synced"]
                + summary["live_batches_synced"]
                + summary["deletes_synced"]
                + summary["sign_tests_synced"]
                + summary["components_synced"]
            )
            if summary["failed"] == 0:
                self.last_synced_at = datetime.now().strftime("%H:%M:%S")
                detail = None
                if total_pushed > 0:
                    parts = []
                    if summary["runs_synced"]:
                        parts.append(f"{summary['runs_synced']} run(s)")
                    if summary["live_batches_synced"]:
                        parts.append(f"{summary['live_batches_synced']} live batch(es)")
                    if summary["deletes_synced"]:
                        parts.append(f"{summary['deletes_synced']} soft-delete(s)")
                    if summary["sign_tests_synced"]:
                        parts.append(f"{summary['sign_tests_synced']} sign test(s)")
                    if summary["components_synced"]:
                        parts.append(f"{summary['components_synced']} component(s)")
                    detail = f"Synced {', '.join(parts)} -> {url}"
                self._emit(
                    "synced",
                    f"Synced ({self.last_synced_at})" if remaining == 0 else f"Synced ({remaining} left)",
                    queued=remaining,
                    detail=detail,
                    log_tag="rx_data",
                )
            else:
                self._emit(
                    "offline",
                    f"Queued ({remaining} pending)",
                    queued=remaining,
                    detail=f"SIA sync paused with {remaining} pending item(s); retrying automatically.",
                    log_tag="err",
                )
            return summary
        finally:
            self._sync_lock.release()

    def delete_remote_runs_async(self, sia_run_ids):
        if not (self.is_configured and sia_run_ids):
            return

        def _job():
            url = self.cfg["bridge_url"]
            for rid in sia_run_ids:
                if not rid:
                    continue
                try:
                    self._session.delete(f"{url}/api/runs/{rid}", headers=self._headers(), timeout=20)
                except requests.RequestException:
                    pass

        threading.Thread(target=_job, daemon=True).start()

    def delete_remote_sign_test_async(self, test_id):
        if not self.is_configured:
            return

        def _job():
            url = self.cfg["bridge_url"]
            try:
                self._session.delete(
                    f"{url}/api/sign-tests/external/IPT2-SIGN-{int(test_id)}",
                    headers=self._headers(),
                    timeout=20,
                )
            except requests.RequestException:
                pass

        threading.Thread(target=_job, daemon=True).start()

    def delete_remote_component_async(self, component_id):
        if not self.is_configured:
            return

        def _job():
            url = self.cfg["bridge_url"]
            try:
                self._session.delete(
                    f"{url}/api/components/external/IPT2-COMP-{int(component_id)}",
                    headers=self._headers(),
                    timeout=20,
                )
            except requests.RequestException:
                pass

        threading.Thread(target=_job, daemon=True).start()
