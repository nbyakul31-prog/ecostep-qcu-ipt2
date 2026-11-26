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


def load_pg_config():
    cfg = {
        "host": os.environ.get("PG_HOST", "127.0.0.1"),
        "port": int(os.environ.get("PG_PORT", "5432")),
        "user": os.environ.get("PG_USER", "postgres"),
        "password": os.environ.get("PG_PASSWORD", ""),
        "dbname": os.environ.get("PG_DB", "ecostep_qcu_db"),
    }
    if os.path.exists(ENV_PATH):
        try:
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k == "PG_HOST" and v:
                        cfg["host"] = v
                    elif k == "PG_PORT" and v.isdigit():
                        cfg["port"] = int(v)
                    elif k == "PG_USER" and v:
                        cfg["user"] = v
                    elif k == "PG_PASSWORD":
                        cfg["password"] = v
                    elif k == "PG_DB" and v:
                        cfg["dbname"] = v
        except OSError:
            pass
    return cfg


def save_pg_config(host, port, user, password, dbname="ecostep_qcu_db"):
    lines = [
        f"PG_HOST={host}",
        f"PG_PORT={int(port)}",
        f"PG_USER={user}",
        f"PG_PASSWORD={password}",
        f"PG_DB={dbname}",
    ]
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
