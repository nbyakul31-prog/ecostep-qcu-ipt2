"""Non-blocking USB-C pyserial worker for EcoStep QCU (115,200 baud 8-N-1)."""

import queue
import threading
import time

try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

from . import config


def list_serial_ports():
    if not HAS_SERIAL:
        return [config.DEFAULT_SERIAL_PORT]
    ports = [p.device for p in serial.tools.list_ports.comports()]
    if config.DEFAULT_SERIAL_PORT not in ports:
        ports.insert(0, config.DEFAULT_SERIAL_PORT)
    return ports


class SerialTelemetryWorker:
    def __init__(self, event_queue=None, baudrate=config.DEFAULT_BAUD_RATE):
        self.event_queue = event_queue or queue.Queue(maxsize=256)
        self.baudrate = baudrate
        self.port = config.DEFAULT_SERIAL_PORT
        self._stop_event = threading.Event()
        self._write_lock = threading.Lock()
        self._thread = None
        self._conn = None

        self.connected = False
        self.board_mode = "BENCH"
        self.last_error = None

    def connect(self, port):
        self.disconnect()
        self.port = port
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def disconnect(self):
        self._stop_event.set()
        with self._write_lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.connected = False
        self._push({"kind": "connection", "connected": False, "port": self.port})

    def _push(self, item):
        try:
            self.event_queue.put_nowait(item)
        except queue.Full:
            pass

    def _run_loop(self):
        if not HAS_SERIAL:
            self.last_error = "pyserial is not installed."
            self._push({"kind": "error", "message": self.last_error})
            return

        try:
            conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.35,
            )
            # CH340 brief reset settle window for MicroPython boot
            time.sleep(1.5)
            conn.reset_input_buffer()
            with self._write_lock:
                self._conn = conn
            self.connected = True
            self.last_error = None
            self._push({"kind": "connection", "connected": True, "port": self.port})
            self.send_command("?")
        except Exception as exc:
            self.connected = False
            self.last_error = str(exc)
            self._push({"kind": "error", "message": f"Could not open {self.port}: {exc}"})
            self._push({"kind": "connection", "connected": False, "port": self.port})
            return

        while not self._stop_event.is_set():
            try:
                raw = self._conn.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                self._parse_line(line)
            except Exception as exc:
                if not self._stop_event.is_set():
                    self.last_error = str(exc)
                    self._push({"kind": "error", "message": str(exc)})
                break

        with self._write_lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
        self.connected = False
        self._push({"kind": "connection", "connected": False, "port": self.port})

    def _parse_line(self, line):
        parts = [p.strip() for p in line.split(",")]
        tag = parts[0].upper()

        if tag == "DATA" and len(parts) >= 4:
            try:
                step_num = int(parts[1])
                adc_raw = max(0, min(1023, int(parts[2])))
                adc_volts = float(parts[3])
                self._push(
                    {
                        "kind": "data",
                        "step_number": step_num,
                        "adc_raw": adc_raw,
                        "adc_voltage": adc_volts,
                        "raw_line": line,
                    }
                )
            except ValueError:
                pass
        elif tag == "CAP" and len(parts) >= 3:
            try:
                adc_raw = max(0, min(1023, int(parts[1])))
                adc_volts = float(parts[2])
                self._push({"kind": "cap", "adc_raw": adc_raw, "adc_voltage": adc_volts, "raw_line": line})
            except ValueError:
                pass
        elif tag == "READY" and len(parts) >= 2:
            self.board_mode = parts[1]
            self._push({"kind": "status", "mode": self.board_mode, "raw_line": line})
        elif tag == "MODE" and len(parts) >= 2:
            self.board_mode = parts[1]
            self._push({"kind": "status", "mode": self.board_mode, "raw_line": line})
        else:
            self._push({"kind": "raw", "raw_line": line})

    def send_command(self, cmd):
        clean = cmd.strip()
        if not clean:
            return False
        with self._write_lock:
            if self._conn is not None and self.connected:
                try:
                    self._conn.write((clean + "\n").encode("utf-8"))
                    self._conn.flush()
                    self._push({"kind": "tx", "command": clean})
                    return True
                except Exception as exc:
                    self.last_error = str(exc)
                    self._push({"kind": "error", "message": f"TX failed ({clean}): {exc}"})
        return False
