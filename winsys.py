"""Integración con Windows: registro, arranque, avisos, ventana y cifrado del token.
Fuera de Windows todo degrada a algo razonable para poder probar."""
import base64
import logging
import os
import shutil
import subprocess
import sys
import webbrowser
from xml.sax.saxutils import escape

import paths

ES_WINDOWS = os.name == "nt"
SIN_VENTANA = 0x08000000  # CREATE_NO_WINDOW
log = logging.getLogger("plazo")


def comando_app():
    """Cómo se lanza esta misma app (exe o script)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = sys.executable
    if ES_WINDOWS:
        w = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(w):
            exe = w
    return f'"{exe}" "{os.path.abspath(sys.argv[0])}"'


def argv_app():
    """Lo mismo que comando_app, en forma de lista para subprocess."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, os.path.abspath(sys.argv[0])]


# ---------- registro (HKCU, sin permisos de administrador) ----------

def _clave_protocolo(esquema):
    return rf"Software\Classes\{esquema}"


def leer_protocolo(esquema):
    if not ES_WINDOWS:
        return None
    import winreg
    try:
        return winreg.QueryValue(winreg.HKEY_CURRENT_USER, _clave_protocolo(esquema) + r"\shell\open\command")
    except OSError:
        return None


def registrar_protocolo(esquema, comando, descripcion):
    if not ES_WINDOWS:
        return
    import winreg
    base = _clave_protocolo(esquema)
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, base, 0, winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f"URL:{descripcion}")
        winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, base + r"\shell\open\command", 0, winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f'{comando} "%1"')


def restaurar_protocolo(esquema, comando_previo):
    """Deja el protocolo como estaba (por si tienes la app oficial de Moodle instalada)."""
    if not ES_WINDOWS:
        return
    import winreg
    base = _clave_protocolo(esquema)
    if comando_previo:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, base + r"\shell\open\command", 0, winreg.KEY_WRITE) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, comando_previo)
        return
    for sub in (r"\shell\open\command", r"\shell\open", r"\shell", ""):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base + sub)
        except OSError:
            pass


_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"


def poner_autostart(activo):
    if not ES_WINDOWS:
        return
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _RUN, 0, winreg.KEY_WRITE) as k:
        if activo:
            winreg.SetValueEx(k, paths.APP, 0, winreg.REG_SZ, comando_app() + " --background")
        else:
            try:
                winreg.DeleteValue(k, paths.APP)
            except OSError:
                pass


def registrar_aumid(icono=None):
    """Nombre e icono que Windows muestra en los avisos."""
    if not ES_WINDOWS:
        return
    import winreg
    ruta = rf"Software\Classes\AppUserModelId\{paths.AUMID}"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, ruta, 0, winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, paths.APP)
        if icono and os.path.exists(icono):
            winreg.SetValueEx(k, "IconUri", 0, winreg.REG_SZ, icono)


# ---------- avisos ----------

def _ps(script):
    codificado = base64.b64encode(script.encode("utf-16-le")).decode()
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
            "-ExecutionPolicy", "Bypass", "-EncodedCommand", codificado]


def _xml(texto):
    return escape(texto, {'"': "&quot;", "'": "&apos;"})


def script_aviso(titulo, cuerpo):
    xml = (
        '<toast activationType="protocol" launch="plazo://abrir">'
        '<visual><binding template="ToastGeneric">'
        f"<text>{_xml(titulo)}</text><text>{_xml(cuerpo)}</text>"
        "</binding></visual></toast>"
    )
    return (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null\n"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null\n"
        "$x = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
        f"$x.LoadXml('{xml}')\n"
        "$t = New-Object Windows.UI.Notifications.ToastNotification $x\n"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{paths.AUMID}').Show($t)\n"
    )


def aviso(titulo, cuerpo):
    log.info("AVISO: %s | %s", titulo, cuerpo)
    if not ES_WINDOWS:
        return
    try:
        subprocess.Popen(_ps(script_aviso(titulo, cuerpo)), creationflags=SIN_VENTANA,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        log.warning("No se pudo mostrar el aviso: %s", e)


# ---------- ventana ----------

def _edge():
    for var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            ruta = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
            if os.path.exists(ruta):
                return ruta
    return shutil.which("msedge")


def abrir_ventana(url):
    """Ventana de app (sin barra de direcciones) con Edge, que viene en todos los Windows."""
    if os.environ.get("PLAZO_SIN_VENTANA"):
        return
    if ES_WINDOWS:
        edge = _edge()
        if edge:
            try:
                subprocess.Popen([edge, f"--app={url}", "--window-size=1180,820"], creationflags=SIN_VENTANA)
                return
            except OSError:
                pass
    webbrowser.open(url)


def acceso_directo_menu_inicio(destino):
    if not ES_WINDOWS:
        return
    def q(s):
        return s.replace("'", "''")
    lnk = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Plazo.lnk")
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%s')\n"
        "$s.TargetPath = '%s'\n$s.WorkingDirectory = '%s'\n"
        "$s.Description = 'Entregas, fechas y notas del campus'\n$s.Save()\n"
    ) % (q(lnk), q(destino), q(os.path.dirname(destino)))
    subprocess.run(_ps(script), creationflags=SIN_VENTANA, timeout=30,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------- token cifrado con DPAPI (solo tu usuario de Windows puede leerlo) ----------

if ES_WINDOWS:
    import ctypes
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _dpapi(datos, proteger):
        buf = ctypes.create_string_buffer(datos, len(datos))
        entrada = _BLOB(len(datos), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        salida = _BLOB()
        crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
        if proteger:
            ok = crypt32.CryptProtectData(ctypes.byref(entrada), ctypes.c_wchar_p("Plazo"), None, None, None,
                                          0x01, ctypes.byref(salida))
        else:
            ok = crypt32.CryptUnprotectData(ctypes.byref(entrada), None, None, None, None, 0x01, ctypes.byref(salida))
        if not ok:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(salida.pbData, salida.cbData)
        finally:
            kernel32.LocalFree(ctypes.cast(salida.pbData, ctypes.c_void_p))


def guardar_secreto(ruta, texto):
    """Guarda texto cifrado con DPAPI: solo tu usuario de Windows en este PC puede leerlo."""
    datos = texto.encode()
    if ES_WINDOWS:
        datos = _dpapi(datos, True)
    tmp = ruta + ".tmp"
    with open(tmp, "wb") as f:
        f.write(datos)
    if not ES_WINDOWS:
        os.chmod(tmp, 0o600)
    os.replace(tmp, ruta)


def leer_secreto(ruta):
    try:
        with open(ruta, "rb") as f:
            datos = f.read()
    except OSError:
        return None
    try:
        if ES_WINDOWS:
            datos = _dpapi(datos, False)
        return datos.decode() or None
    except Exception as e:
        log.warning("No se pudo descifrar %s: %s", os.path.basename(ruta), e)
        return None
