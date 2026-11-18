"""Ventana de inicio de sesión (WebView2, el motor de Edge).

Abre el campus, tú entras con Office 365 y, cuando el campus te deja dentro,
Plazo se queda con la cookie de sesión y cierra la ventana. La ventana guarda su
propio perfil, así que Microsoft puede recordarte y la próxima vez no pide el QR.

Modo silencioso: ventana oculta que pulsa el botón de Office 365 por ti. Solo
funciona si Microsoft todavía te recuerda; si pide algo, se rinde sin molestar."""
import json
import logging
import os
import time

import paths
import winsys

log = logging.getLogger("plazo")
JS_PULSAR_OFFICE = """
(function () {
  var a = document.querySelector('a[href*="auth/oauth2/login.php"]');
  if (a) { a.click(); return 'pulsado'; }
  return 'sin boton';
})()
"""


def _dentro(url, sitio):
    return (url or "").startswith(sitio) and "/login/" not in url and "/auth/" not in url


def _cookies(ventana):
    jar = {}
    for c in ventana.get_cookies() or []:
        for nombre, morsel in c.items():
            jar[nombre] = morsel.value
    return jar


def iniciar_sesion(silencioso=False):
    import webview  # solo hace falta en Windows y en este modo

    cfg = paths.leer_config()
    sitio = cfg["sitio"]
    os.makedirs(paths.WEBVIEW, exist_ok=True)
    resultado = {"ok": False}
    ventana = webview.create_window(
        "Plazo: entrar en el campus", sitio + "/login/index.php",
        width=560, height=760, hidden=silencioso, text_select=True)

    def vigilar():
        limite = time.time() + (90 if silencioso else 900)
        pulsado = False
        while time.time() < limite:
            time.sleep(1)
            try:
                url = ventana.get_current_url() or ""
            except Exception:
                continue
            if silencioso and not pulsado and url.startswith(sitio + "/login/"):
                try:
                    pulsado = ventana.evaluate_js(JS_PULSAR_OFFICE) == "pulsado"
                except Exception:
                    pass
            if _dentro(url, sitio):
                time.sleep(1)  # que termine de asentar la cookie
                try:
                    jar = _cookies(ventana)
                except Exception as e:
                    log.error("No pude leer las cookies: %s", e)
                    jar = {}
                if any(k.startswith("MoodleSession") for k in jar):
                    winsys.guardar_secreto(paths.SESION, json.dumps({"cookies": jar, "creado": time.time()}))
                    resultado["ok"] = True
                    log.info("Sesión del campus guardada (%s)", "silenciosa" if silencioso else "con ventana")
                    break
        try:
            ventana.destroy()
        except Exception:
            pass

    webview.start(vigilar, private_mode=False, storage_path=paths.WEBVIEW)
    paths.escribir_json(paths.ESTADO_LOGIN, {"ok": resultado["ok"], "silencioso": silencioso, "cuando": time.time()})
    return resultado["ok"]
