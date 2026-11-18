"""Rutas de datos y recursos de Plazo."""
import json
import os
import sys

APP = "Plazo"
AUMID = "Nacho.Plazo"
SITIO_POR_DEFECTO = "https://campusonline2026.cesurformacion.com"


def _base():
    if os.environ.get("PLAZO_DATA"):
        return os.environ["PLAZO_DATA"]
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
        return os.path.join(local, APP)
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "plazo")


DATA = _base()
os.makedirs(DATA, exist_ok=True)

DB = os.path.join(DATA, "plazo.db")
TOKEN_V1 = os.path.join(DATA, "token.bin")          # restos de la versión 1
SESION = os.path.join(DATA, "sesion.bin")           # cookies del campus, cifradas
ICAL = os.path.join(DATA, "ical.bin")               # URL privada del calendario, cifrada
WEBVIEW = os.path.join(DATA, "navegador")           # perfil de la ventana de login (recuerda Office)
CONFIG = os.path.join(DATA, "config.json")
RESIDENT = os.path.join(DATA, "resident.json")
PENDING = os.path.join(DATA, "login_pendiente.json")  # versión 1
ESTADO_LOGIN = os.path.join(DATA, "login_estado.json")
LOG = os.path.join(DATA, "plazo.log")


def recurso(*partes):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *partes)


_DEFECTO = {"sitio": SITIO_POR_DEFECTO, "autostart": True, "intervalo_min": 120}


def leer_config():
    cfg = dict(_DEFECTO)
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    cfg["sitio"] = cfg["sitio"].strip().rstrip("/")
    return cfg


def guardar_config(cfg):
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG)


def leer_json(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def escribir_json(ruta, datos):
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f)
    os.replace(tmp, ruta)


def borrar(ruta):
    try:
        os.remove(ruta)
    except OSError:
        pass
