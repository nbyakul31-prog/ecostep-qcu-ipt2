"""Configuration & .env loader for EcoStep QCU IPT2 Desktop Application."""

import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)
ASSETS_DIR = os.path.join(APP_DIR, "assets")
LOGO_PATH = os.path.join(ASSETS_DIR, "ecostep_logo.jpg")
ENV_PATH = os.path.join(ROOT_DIR, ".env")
SCHEMA_PATH = os.path.join(APP_DIR, "schema.sql")

DEFAULT_SERIAL_PORT = "COM10"
DEFAULT_BAUD_RATE = 115200


def _read_env_file():
    values = {}
    if not os.path.exists(ENV_PATH):
        return values
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


def _write_env_updates(updates):
    """Update specific keys in .env while preserving unrelated entries."""
    existing = _read_env_file()
    existing.update({k: str(v) for k, v in updates.items()})
    ordered_keys = [
        "PG_HOST",
        "PG_PORT",
        "PG_USER",
        "PG_PASSWORD",
        "PG_DB",
        "SIA_BRIDGE_URL",
        "SIA_API_KEY",
        "SIA_TILE_ID",
        "SIA_AUTO_SYNC",
        "SIA_SYNC_INTERVAL_SEC",
    ]
    lines = []
    written = set()
    for key in ordered_keys:
        if key in existing:
            lines.append(f"{key}={existing[key]}")
            written.add(key)
    for key, val in existing.items():
        if key not in written:
            lines.append(f"{key}={val}")
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def load_pg_config():
    env_vals = _read_env_file()
    cfg = {
        "host": os.environ.get("PG_HOST", "127.0.0.1"),
        "port": int(os.environ.get("PG_PORT", "5432")),
        "user": os.environ.get("PG_USER", "postgres"),
        "password": os.environ.get("PG_PASSWORD", ""),
        "dbname": os.environ.get("PG_DB", "ecostep_qcu_db"),
    }
    if env_vals.get("PG_HOST"):
        cfg["host"] = env_vals["PG_HOST"]
    if env_vals.get("PG_PORT", "").isdigit():
        cfg["port"] = int(env_vals["PG_PORT"])
    if env_vals.get("PG_USER"):
        cfg["user"] = env_vals["PG_USER"]
    if "PG_PASSWORD" in env_vals:
        cfg["password"] = env_vals["PG_PASSWORD"]
    if env_vals.get("PG_DB"):
        cfg["dbname"] = env_vals["PG_DB"]
    return cfg


def save_pg_config(host, port, user, password, dbname="ecostep_qcu_db"):
    _write_env_updates(
        {
            "PG_HOST": host,
            "PG_PORT": int(port),
            "PG_USER": user,
            "PG_PASSWORD": password,
            "PG_DB": dbname,
        }
    )


def load_sia_config():
    env_vals = _read_env_file()

    def _get(key, default=""):
        if key in env_vals:
            return env_vals[key]
        return os.environ.get(key, default)

    raw_url = _get("SIA_BRIDGE_URL", "").strip().rstrip("/")
    raw_interval = _get("SIA_SYNC_INTERVAL_SEC", "15").strip()
    try:
        interval = max(5, min(300, int(raw_interval)))
    except ValueError:
        interval = 15

    return {
        "bridge_url": raw_url,
        "api_key": _get("SIA_API_KEY", "").strip(),
        "tile_id": _get("SIA_TILE_ID", "TILE-01").strip() or "TILE-01",
        "auto_sync": _get("SIA_AUTO_SYNC", "true").strip().lower() in ("1", "true", "yes", "on"),
        "sync_interval": interval,
    }


def save_sia_config(bridge_url, api_key, tile_id="TILE-01", auto_sync=True, sync_interval=15):
    clean_url = (bridge_url or "").strip().rstrip("/")
    clean_tile = (tile_id or "TILE-01").strip() or "TILE-01"
    _write_env_updates(
        {
            "SIA_BRIDGE_URL": clean_url,
            "SIA_API_KEY": (api_key or "").strip(),
            "SIA_TILE_ID": clean_tile,
            "SIA_AUTO_SYNC": "true" if auto_sync else "false",
            "SIA_SYNC_INTERVAL_SEC": max(5, min(300, int(sync_interval))),
        }
    )
