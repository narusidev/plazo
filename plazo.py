"""Plazo: entregas, fechas y notas del campus de CESUR en tu escritorio.

  Plazo.exe                     abre la ventana (y arranca el proceso residente si no está)
  Plazo.exe --background        solo el residente: sincroniza, mantiene la sesión y avisa
  Plazo.exe --login             ventana para entrar en el campus con Office 365
  Plazo.exe --autoprueba FICH   comprobación del empaquetado (la usa GitHub Actions)
"""
import hmac
import json
import logging
import logging.handlers
import mimetypes
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import actualizar
import paths
import winsys
from campus import Campus, CampusError, SesionCaducada
from sincronizar import sincronizar_ical, sincronizar_sesion, textos_aviso
from store import Store
from version import VERSION

log = logging.getLogger("plazo")
ESTATICOS = {"style.css", "app.js", "favicon.png"}
CADA_MANTENER = 10 * 60          # toque a la sesión para que no caduque
CADA_RENOVAR = 3 * 3600          # intentos de renovación silenciosa
CADA_ACTUALIZAR = 6 * 3600


def configurar_log():
    h = logging.handlers.RotatingFileHandler(paths.LOG, maxBytes=512_000, backupCount=1, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)


def cargar_cookies():
    datos = winsys.leer_secreto(paths.SESION)
    try:
        return json.loads(datos)["cookies"] if datos else None
    except (ValueError, KeyError):
        return None


# ---------------------------------------------------------------- residente

class App:
    def __init__(self):
        self.cfg = paths.leer_config()
        self.store = Store(paths.DB)
        self.clave = secrets.token_urlsafe(24)
        self.puerto = None
        self.sincronizando = False
        self.error = None
        self.sesion = "ninguna"            # activa | caducada | ninguna
        self.avisado_caducada = False
        self.campus = None
        self.proxima = 0.0
        self.proximo_toque = 0.0
        self.proxima_renovacion = 0.0
        self.proxima_actualizacion = time.time() + 90
        self.proceso_login = None
        self.actualizacion_error = None
        self.despertar = threading.Event()
        self.salir = threading.Event()
        self._cargar_campus()

    def _cargar_campus(self):
        cookies = cargar_cookies()
        if cookies:
            self.campus = Campus(self.cfg["sitio"], cookies)
            self.sesion = "activa"
        else:
            self.campus = None
            self.sesion = "caducada" if self.store.meta("ultima_sync_completa") else "ninguna"

    def _guardar_cookies(self):
        if self.campus and self.campus.cookies_cambiadas:
            winsys.guardar_secreto(paths.SESION, json.dumps({"cookies": self.campus.cookies, "creado": time.time()}))
            self.campus.cookies_cambiadas = False

    def _caducada(self, motivo):
        log.info("Sesión caducada: %s", motivo)
        paths.borrar(paths.SESION)
        self.campus = None
        self.sesion = "caducada"

    # ---- renovación sin molestar ----
    def _renovar_en_silencio(self):
        if time.time() < self.proxima_renovacion or not winsys.ES_WINDOWS:
            return False
        self.proxima_renovacion = time.time() + CADA_RENOVAR
        try:
            subprocess.run(winsys.argv_app() + ["--login", "--silencioso"], timeout=150,
                           creationflags=winsys.SIN_VENTANA)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("Renovación silenciosa: %s", e)
        self._cargar_campus()
        return self.campus is not None

    # ---- sincronización (solo desde el hilo del bucle) ----
    def _sync(self):
        self.sincronizando = True
        cambios, recordatorios = [], []
        try:
            hecho = False
            for intento in range(2):
                if not self.campus:
                    break
                try:
                    cambios, recordatorios = sincronizar_sesion(self.store, self.campus)
                    self._guardar_cookies()
                    self.sesion = "activa"
                    self.avisado_caducada = False
                    self.proximo_toque = time.time() + CADA_MANTENER
                    hecho = True
                    if not winsys.leer_secreto(paths.ICAL):
                        url = self.campus.url_ical()
                        if url:
                            winsys.guardar_secreto(paths.ICAL, url)
                            log.info("URL del iCal guardada")
                    break
                except SesionCaducada as e:
                    self._caducada(e)
                    if intento == 0 and not self._renovar_en_silencio():
                        break
            if not hecho:
                url = winsys.leer_secreto(paths.ICAL)
                if url:
                    cambios, recordatorios = sincronizar_ical(self.store, url)
                    hecho = True
                if self.sesion == "caducada" and not self.avisado_caducada:
                    self.avisado_caducada = True
                    winsys.aviso("La sesión del campus ha caducado",
                                 "Las fechas siguen al día. Para ver entregas y notas, abre Plazo y vuelve a entrar.")
            self.error = None
            for titulo, cuerpo in textos_aviso(cambios, recordatorios):
                winsys.aviso(titulo, cuerpo)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            log.warning("Sin conexión: %s", e)
            self.error = "No he podido llegar al campus. Lo vuelvo a intentar en 10 minutos."
        except CampusError as e:
            log.error("Campus: %s %s", e.codigo, e)
            self.error = f"El campus ha respondido con un error: {e}"
        except Exception as e:
            log.exception("Fallo inesperado")
            self.error = f"Fallo inesperado: {e}"
        finally:
            self.sincronizando = False
        intervalo = 600 if self.error else int(self.cfg.get("intervalo_min", 120)) * 60
        self.proxima = time.time() + intervalo

    def _mantener(self):
        self.proximo_toque = time.time() + CADA_MANTENER
        try:
            self.campus.mantener_viva()
            self._guardar_cookies()
        except SesionCaducada as e:
            self._caducada(e)
            if self._renovar_en_silencio():
                self.pedir_sync()
        except Exception as e:
            log.info("Toque de sesión fallido: %s", e)

    def _buscar_actualizacion(self):
        self.proxima_actualizacion = time.time() + CADA_ACTUALIZAR
        if not actualizar.puede_actualizarse():
            return
        try:
            info = actualizar.comprobar()
            if info and actualizar.aplicar(info):
                self.salir.set()
            self.actualizacion_error = None
        except Exception as e:
            log.warning("Actualización: %s", e)
            self.actualizacion_error = str(e)

    def bucle(self):
        while not self.salir.is_set():
            ahora = time.time()
            if self.campus is None and cargar_cookies():   # acaba de terminar un login
                self._cargar_campus()
                self.proxima = 0
            if (self.campus or winsys.leer_secreto(paths.ICAL)) and ahora >= self.proxima:
                self._sync()
            elif self.campus and ahora >= self.proximo_toque:
                self._mantener()
            if ahora >= self.proxima_actualizacion:
                self._buscar_actualizacion()
            self.despertar.wait(15)
            self.despertar.clear()

    def pedir_sync(self):
        self.proxima = 0
        self.despertar.set()

    # ---- login ----
    def iniciar_login(self):
        if self.proceso_login and self.proceso_login.poll() is None:
            return
        if not winsys.ES_WINDOWS:
            raise ValueError("La ventana de inicio de sesión solo funciona en Windows")
        self.proxima_renovacion = time.time() + CADA_RENOVAR
        self.proceso_login = subprocess.Popen(winsys.argv_app() + ["--login"], creationflags=winsys.SIN_VENTANA)

    def esperando_login(self):
        return bool(self.proceso_login and self.proceso_login.poll() is None)

    # ---- estado para la interfaz ----
    def estado(self):
        s = self.store
        sitio = self.cfg["sitio"]
        tareas = s.consultar(
            "SELECT t.*, m.sigla, m.nombre AS modulo FROM tarea t JOIN modulo m USING(id_curso) "
            "ORDER BY t.fecha_limite IS NULL, t.fecha_limite")
        for t in tareas:
            t["url"] = f"{sitio}/mod/{t['tipo']}/view.php?id={t['id_cm']}"
        ical = bool(winsys.leer_secreto(paths.ICAL))
        ultima = int(s.meta("ultima_sync") or 0) or None
        return {
            "conectado": bool(self.campus or ical or ultima),
            "sesion": self.sesion,
            "ical": ical,
            "esperando_login": self.esperando_login(),
            "sitio": sitio,
            "ultima_sync": ultima,
            "ultima_sync_completa": int(s.meta("ultima_sync_completa") or 0) or None,
            "sincronizando": self.sincronizando,
            "error": self.error,
            "autostart": bool(self.cfg.get("autostart")),
            "ruta_bd": paths.DB,
            "version": VERSION,
            "actualizacion_error": self.actualizacion_error,
            "ahora": int(time.time()),
            "modulos": s.consultar("SELECT * FROM modulo ORDER BY sigla"),
            "tareas": tareas,
            "eventos": s.consultar(
                "SELECT e.*, m.sigla FROM evento e LEFT JOIN modulo m USING(id_curso) ORDER BY e.inicio"),
            "cambios": s.consultar("SELECT * FROM cambio ORDER BY id_cambio DESC LIMIT 80"),
        }

    def aplicar_ajustes(self, datos):
        if "autostart" in datos:
            self.cfg["autostart"] = bool(datos["autostart"])
            winsys.poner_autostart(self.cfg["autostart"])
        if "sitio" in datos:
            sitio = str(datos["sitio"]).strip().rstrip("/")
            if not sitio.startswith(("https://", "http://")):
                raise ValueError("La dirección del campus tiene que empezar por https://")
            if sitio != self.cfg["sitio"]:
                self.cfg["sitio"] = sitio
                self.desconectar()
        paths.guardar_config(self.cfg)

    def desconectar(self):
        paths.borrar(paths.SESION)
        paths.borrar(paths.ICAL)
        self.campus = None
        self.sesion = "ninguna"


def handler_para(app):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, codigo, datos):
            cuerpo = json.dumps(datos, ensure_ascii=False).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def _host_ok(self):
            # Frena ataques de DNS rebinding: solo peticiones dirigidas a 127.0.0.1
            return self.headers.get("Host") in (f"127.0.0.1:{app.puerto}", f"localhost:{app.puerto}")

        def _clave_ok(self, clave):
            return bool(clave) and hmac.compare_digest(clave, app.clave)

        def do_GET(self):
            if not self._host_ok():
                return self._json(403, {"error": "host"})
            ruta, _, query = self.path.partition("?")
            if ruta == "/":
                k = dict(p.split("=", 1) for p in query.split("&") if "=" in p).get("k", "")
                if not self._clave_ok(k):
                    return self._json(403, {"error": "clave"})
                return self._fichero("index.html")
            if ruta.startswith("/ui/") and ruta[4:] in ESTATICOS:
                return self._fichero(ruta[4:])
            if not self._clave_ok(self.headers.get("X-Plazo-Key", "")):
                return self._json(403, {"error": "clave"})
            if ruta == "/api/ping":
                return self._json(200, {"ok": True, "version": VERSION})
            if ruta == "/api/state":
                return self._json(200, app.estado())
            return self._json(404, {"error": "no existe"})

        def _fichero(self, nombre):
            with open(paths.recurso("ui", nombre), "rb") as f:
                cuerpo = f.read()
            tipo = mimetypes.guess_type(nombre)[0] or "application/octet-stream"
            if tipo.startswith("text/") or tipo.endswith("javascript"):
                tipo += "; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'")
            self.end_headers()
            self.wfile.write(cuerpo)

        def do_POST(self):
            if not self._host_ok() or not self._clave_ok(self.headers.get("X-Plazo-Key", "")):
                return self._json(403, {"error": "clave"})
            largo = min(int(self.headers.get("Content-Length") or 0), 16_384)
            try:
                datos = json.loads(self.rfile.read(largo) or b"{}")
            except ValueError:
                datos = {}
            ruta = self.path.partition("?")[0]
            try:
                if ruta == "/api/sync":
                    app.pedir_sync()
                elif ruta == "/api/login":
                    app.iniciar_login()
                elif ruta == "/api/despertar":
                    app.pedir_sync()
                elif ruta == "/api/logout":
                    app.desconectar()
                elif ruta == "/api/cambios/leidos":
                    app.store.ejecutar("UPDATE cambio SET leido = 1 WHERE leido = 0")
                    app.store.commit()
                elif ruta == "/api/ajustes":
                    app.aplicar_ajustes(datos)
                elif ruta == "/api/actualizar":
                    app.proxima_actualizacion = 0
                    app.despertar.set()
                elif ruta == "/api/abrir":
                    url = str(datos.get("url", ""))
                    if not url.startswith(app.cfg["sitio"] + "/"):
                        return self._json(400, {"error": "Solo abro enlaces del campus"})
                    webbrowser.open(url)
                elif ruta == "/api/salir":
                    app.salir.set()
                    app.despertar.set()
                else:
                    return self._json(404, {"error": "no existe"})
            except ValueError as e:
                return self._json(400, {"error": str(e)})
            return self._json(200, {"ok": True})
    return H


def residente_vivo():
    r = paths.leer_json(paths.RESIDENT)
    if not r:
        return None
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{r['puerto']}/api/ping", headers={"X-Plazo-Key": r["clave"]})
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                return r
    except (OSError, KeyError, ValueError):
        pass
    return None


def avisar_residente(r, ruta):
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{r['puerto']}{ruta}", data=b"{}",
                                     headers={"X-Plazo-Key": r["clave"], "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3).close()
    except OSError:
        pass


def limpiar_version_1():
    p = paths.leer_json(paths.PENDING)
    if p:
        winsys.restaurar_protocolo("moodlemobile", p.get("previo"))
        paths.borrar(paths.PENDING)
    paths.borrar(paths.TOKEN_V1)


def arrancar_residente(abrir):
    app = App()
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), handler_para(app))
    app.puerto = servidor.server_address[1]
    url = f"http://127.0.0.1:{app.puerto}/?k={app.clave}"
    paths.escribir_json(paths.RESIDENT, {"puerto": app.puerto, "clave": app.clave, "pid": os.getpid(), "url": url})

    try:
        limpiar_version_1()
        winsys.registrar_protocolo("plazo", winsys.comando_app(), "Plazo")
        winsys.registrar_aumid(paths.recurso("ui", "favicon.png"))
        winsys.poner_autostart(bool(app.cfg.get("autostart")))
    except OSError as e:
        log.warning("Registro de Windows: %s", e)
    actualizar.limpiar_restos()

    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    threading.Thread(target=app.bucle, daemon=True).start()
    log.info("Plazo %s residente en el puerto %s", VERSION, app.puerto)
    if abrir:
        winsys.abrir_ventana(url)
    app.salir.wait()
    servidor.shutdown()
    r = paths.leer_json(paths.RESIDENT)
    if r and r.get("pid") == os.getpid():
        paths.borrar(paths.RESIDENT)


# ---------------------------------------------------------------- instalación

def instalar_si_hace_falta(args):
    """La primera vez se copia a %LOCALAPPDATA%\\Programs\\Plazo y crea el acceso del menú Inicio.
    Si ya había otra versión abierta, la cierra para poder sustituirla."""
    if not (getattr(sys, "frozen", False) and winsys.ES_WINDOWS):
        return False
    carpeta = os.path.join(os.environ["LOCALAPPDATA"], "Programs", "Plazo")
    destino = os.path.join(carpeta, "Plazo.exe")
    if os.path.normcase(os.path.abspath(sys.executable)) == os.path.normcase(destino):
        return False
    os.makedirs(carpeta, exist_ok=True)
    for intento in range(12):
        try:
            shutil.copy2(sys.executable, destino)
            break
        except PermissionError:
            r = residente_vivo()
            if r:
                avisar_residente(r, "/api/salir")
            time.sleep(1)
    else:
        log.error("No he podido copiar Plazo a %s", destino)
        return False
    try:
        winsys.acceso_directo_menu_inicio(destino)
    except Exception as e:
        log.warning("Acceso directo: %s", e)
    subprocess.Popen([destino] + args, creationflags=winsys.SIN_VENTANA)
    return True


def autoprueba(fichero):
    try:
        import sqlite3  # noqa: F401
        import webview  # noqa: F401
        from webview.platforms import edgechromium  # noqa: F401
        assert os.path.exists(paths.recurso("ui", "app.js"))
        resultado = "ok"
    except Exception:
        resultado = traceback.format_exc()
    with open(fichero, "w", encoding="utf-8") as f:
        f.write(resultado)


def main(args):
    if args[:1] == ["--autoprueba"]:
        return autoprueba(args[1] if len(args) > 1 else "autoprueba.txt")
    configurar_log()
    if "--login" in args:
        import login
        ok = login.iniciar_sesion(silencioso="--silencioso" in args)
        r = residente_vivo()
        if ok and r:
            avisar_residente(r, "/api/despertar")
        return
    if instalar_si_hace_falta([a for a in args if a == "--background"]):
        return
    if "--tras-actualizar" in args:
        for _ in range(40):          # espera a que el proceso viejo suelte el sitio
            if not residente_vivo():
                break
            time.sleep(0.5)
        winsys.aviso("Plazo actualizado", f"Ya tienes la versión {VERSION}.")
    fondo = "--background" in args
    r = residente_vivo()
    if r:
        if not fondo:
            winsys.abrir_ventana(r["url"])
        return
    arrancar_residente(abrir=not fondo)


if __name__ == "__main__":
    main(sys.argv[1:])
