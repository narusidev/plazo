"""Autoactualización desde las Releases de GitHub.

Comprueba la última versión publicada, descarga Plazo.exe, verifica su SHA-256 con
el que publica GitHub y se sustituye a sí mismo. Windows deja renombrar un .exe que
está en marcha, que es el truco: el viejo pasa a Plazo.old.exe y el nuevo ocupa su sitio."""
import hashlib
import json
import logging
import os
import subprocess
import sys
import urllib.request

import winsys
from version import REPO, VERSION

log = logging.getLogger("plazo")
API = f"https://api.github.com/repos/{REPO}/releases/latest"


def _tupla(v):
    partes = []
    for p in str(v).lstrip("vV").split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        partes.append(int(num) if num else 0)
    return tuple(partes + [0] * (3 - len(partes)))


def comprobar(timeout=15):
    """Devuelve {version, url, tamano, sha256} si hay una versión más nueva; si no, None."""
    req = urllib.request.Request(API, headers={"User-Agent": f"Plazo/{VERSION}",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        rel = json.load(r)
    etiqueta = rel.get("tag_name") or ""
    if rel.get("draft") or rel.get("prerelease") or _tupla(etiqueta) <= _tupla(VERSION):
        return None
    for a in rel.get("assets", []):
        if a.get("name", "").lower() == "plazo.exe":
            digest = a.get("digest") or ""
            return {"version": etiqueta.lstrip("vV"), "url": a["browser_download_url"],
                    "tamano": a.get("size"), "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else None}
    return None


def puede_actualizarse():
    return getattr(sys, "frozen", False) and winsys.ES_WINDOWS


def aplicar(info):
    """Descarga y deja el nuevo .exe en su sitio. Devuelve True si hay que reiniciar."""
    if not puede_actualizarse():
        return False
    actual = os.path.abspath(sys.executable)
    carpeta = os.path.dirname(actual)
    nuevo = os.path.join(carpeta, "Plazo.new.exe")
    viejo = os.path.join(carpeta, "Plazo.old.exe")
    h = hashlib.sha256()
    req = urllib.request.Request(info["url"], headers={"User-Agent": f"Plazo/{VERSION}"})
    with urllib.request.urlopen(req, timeout=120) as r, open(nuevo, "wb") as f:
        primero = True
        while True:
            bloque = r.read(1 << 16)
            if not bloque:
                break
            if primero and not bloque.startswith(b"MZ"):
                raise ValueError("Lo descargado no es un ejecutable de Windows")
            primero = False
            h.update(bloque)
            f.write(bloque)
    tam = os.path.getsize(nuevo)
    if info.get("tamano") and tam != info["tamano"]:
        os.remove(nuevo)
        raise ValueError(f"Tamaño inesperado ({tam} en vez de {info['tamano']})")
    if info.get("sha256") and h.hexdigest() != info["sha256"]:
        os.remove(nuevo)
        raise ValueError("El SHA-256 no coincide con el publicado en GitHub")
    try:
        os.remove(viejo)
    except OSError:
        pass
    os.replace(actual, viejo)
    os.replace(nuevo, actual)
    subprocess.Popen([actual, "--background", "--tras-actualizar", VERSION], creationflags=winsys.SIN_VENTANA)
    log.info("Actualizado %s -> %s", VERSION, info["version"])
    return True


def limpiar_restos():
    if puede_actualizarse():
        for nombre in ("Plazo.old.exe", "Plazo.new.exe"):
            try:
                os.remove(os.path.join(os.path.dirname(sys.executable), nombre))
            except OSError:
                pass
