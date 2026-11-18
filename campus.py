"""Acceso al campus con tu sesión web (la misma cookie que usa el navegador). Solo lectura."""
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Plazo/2"
_CODIGOS_LOGIN = {"servicerequireslogin", "requireloginerror", "invalidsesskey", "sessionerroruser",
                  "sesskey", "notlocalisederrormessage_login"}


class CampusError(Exception):
    def __init__(self, codigo, mensaje=""):
        super().__init__(mensaje or codigo)
        self.codigo = codigo


class SesionCaducada(CampusError):
    def __init__(self, detalle="sesión caducada"):
        super().__init__("sesion", detalle)


def texto_plano(valor):
    if not valor:
        return ""
    t = re.sub(r"<[^>]+>", " ", str(valor))
    t = html.unescape(t).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def numero(texto):
    m = re.search(r"-?\d+(?:[.,]\d+)?", texto or "")
    return float(m.group(0).replace(",", ".")) if m else None


class Campus:
    def __init__(self, sitio, cookies, timeout=30):
        self.sitio = sitio.rstrip("/")
        self.cookies = dict(cookies)
        self.cookies_cambiadas = False
        self.sesskey = None
        self.timeout = timeout

    # ---------- HTTP ----------
    def _absorber(self, respuesta):
        for linea in respuesta.headers.get_all("Set-Cookie") or []:
            par = linea.split(";", 1)[0]
            if "=" in par:
                k, v = par.split("=", 1)
                k, v = k.strip(), v.strip()
                if v and v.lower() != "deleted" and self.cookies.get(k) != v:
                    self.cookies[k] = v
                    self.cookies_cambiadas = True

    def peticion(self, ruta, datos=None, cuerpo_json=None):
        url = ruta if ruta.startswith("http") else self.sitio + ruta
        cabeceras = {"User-Agent": UA, "Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items())}
        cuerpo = None
        if cuerpo_json is not None:
            cuerpo = json.dumps(cuerpo_json).encode()
            cabeceras["Content-Type"] = "application/json"
        elif datos is not None:
            cuerpo = urllib.parse.urlencode(datos).encode()
            cabeceras["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=cuerpo, headers=cabeceras)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            self._absorber(r)
            final = r.geturl()
            texto = r.read().decode("utf-8", "replace")
        if "/login/index.php" in final or not final.startswith(self.sitio):
            raise SesionCaducada("el campus ha mandado a la página de login")
        return texto

    # ---------- sesión ----------
    def iniciar(self):
        pagina = self.peticion("/my/")
        m = re.search(r'"sesskey"\s*:\s*"([^"]+)"', pagina)
        if not m:
            raise SesionCaducada("no hay sesskey en la página")
        self.sesskey = m.group(1)

    def ajax(self, metodo, **args):
        if not self.sesskey:
            self.iniciar()
        q = urllib.parse.urlencode({"sesskey": self.sesskey, "info": metodo})
        texto = self.peticion(f"/lib/ajax/service.php?{q}", cuerpo_json=[{"index": 0, "methodname": metodo, "args": args}])
        try:
            j = json.loads(texto)
        except ValueError:
            raise CampusError("respuesta", "El campus ha devuelto algo que no es JSON")
        if isinstance(j, dict):  # error de toda la petición
            codigo = j.get("errorcode") or (j.get("exception") or {}).get("errorcode") or "error"
            if codigo in _CODIGOS_LOGIN:
                raise SesionCaducada(codigo)
            raise CampusError(codigo, j.get("error") or codigo)
        x = j[0]
        if x.get("error"):
            exc = x.get("exception") or {}
            codigo = exc.get("errorcode") or "error"
            if codigo in _CODIGOS_LOGIN:
                raise SesionCaducada(codigo)
            raise CampusError(codigo, exc.get("message") or codigo)
        return x.get("data")

    def mantener_viva(self):
        self.ajax("core_session_touch")

    def tiempo_restante(self):
        return int((self.ajax("core_session_time_remaining") or {}).get("timeremaining") or 0)

    # ---------- lecturas ----------
    def cursos(self):
        d = self.ajax("core_course_get_enrolled_courses_by_timeline_classification",
                      classification="all", limit=0, offset=0)
        return d.get("courses", [])

    def eventos_mes(self, anio, mes):
        d = self.ajax("core_calendar_get_calendar_monthly_view", year=anio, month=mes, courseid=1,
                      categoryid=0, includenavigation=False, mini=True, day=1)
        return [e for semana in d.get("weeks", []) for dia in semana.get("days", []) for e in dia.get("events") or []]

    def acciones(self, desde):
        """Lo que el campus considera pendiente de hacer: lo ya entregado no aparece."""
        salida, despues = [], None
        for _ in range(8):
            args = {"timesortfrom": desde, "limitnum": 50}
            if despues:
                args["aftereventid"] = despues
            d = self.ajax("core_calendar_get_action_events_by_timesort", **args)
            evs = d.get("events", [])
            salida += evs
            if len(evs) < 50:
                break
            despues = d.get("lastid") or evs[-1]["id"]
        return salida

    def notas_curso(self, id_curso):
        """{id_cm: "8,25 / 10"} sacado del informe de calificaciones del módulo."""
        pagina = self.peticion(f"/grade/report/user/index.php?id={id_curso}")
        notas = {}
        for fila in re.split(r"<tr[\s>]", pagina)[1:]:
            enlace = re.search(r'href="[^"]*/mod/\w+/view\.php\?id=(\d+)', fila)
            celda = re.search(r'<td[^>]*class="[^"]*column-grade[^"]*"[^>]*>(.*?)</td>', fila, re.S)
            if not (enlace and celda):
                continue
            nota = texto_plano(celda.group(1)).split("Acciones")[0].strip()
            if not nota or nota == "-":
                continue
            rango = re.search(r'<td[^>]*class="[^"]*column-range[^"]*"[^>]*>(.*?)</td>', fila, re.S)
            maximo = None
            if rango:
                partes = re.split(r"[–-]", texto_plano(rango.group(1)))
                maximo = partes[-1].strip() if len(partes) > 1 else None
            notas[int(enlace.group(1))] = f"{nota} / {maximo}" if maximo else nota
        return notas

    def notas_globales(self):
        """{id_curso: "7,5"} desde la vista general de calificaciones."""
        pagina = self.peticion("/grade/report/overview/index.php")
        notas = {}
        tabla = re.search(r'<table[^>]*id="overview-grade".*?</table>', pagina, re.S)
        if not tabla:
            return notas
        for fila in re.split(r"<tr[\s>]", tabla.group(0))[1:]:
            celdas = re.findall(r"<td[^>]*>(.*?)</td>", fila, re.S)
            enlace = re.search(r'[?&;]id=(\d+)', fila)
            if enlace and len(celdas) >= 2:
                nota = texto_plano(celdas[1])
                notas[int(enlace.group(1))] = None if nota in ("", "-") else nota
        return notas

    def url_ical(self):
        if not self.sesskey:
            self.iniciar()
        pagina = self.peticion("/calendar/export.php", datos={
            "sesskey": self.sesskey, "_qf__core_calendar_export_form": "1",
            "events[exportevents]": "all", "period[timeperiod]": "recentupcoming",
            "generateurl": "Obtener URL del calendario"})
        m = re.search(r'https?://[^"\'<>\s]+/calendar/export_execute\.php\?[^"\'<>\s]+', html.unescape(pagina))
        return m.group(0) if m else None


def descargar_ical(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def leer_ical(texto):
    """Lista de {id, titulo, inicio, fin} a partir de un iCal de Moodle."""
    from datetime import datetime, timezone
    lineas = []
    for linea in texto.replace("\r\n", "\n").split("\n"):
        if linea[:1] in (" ", "\t") and lineas:
            lineas[-1] += linea[1:]
        else:
            lineas.append(linea)

    def fecha(valor):
        valor = valor.strip()
        for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%d"):
            try:
                d = datetime.strptime(valor, fmt)
                if valor.endswith("Z"):
                    d = d.replace(tzinfo=timezone.utc)
                return int(d.timestamp())
            except ValueError:
                pass
        return None

    eventos, actual = [], None
    for linea in lineas:
        if linea == "BEGIN:VEVENT":
            actual = {}
        elif linea == "END:VEVENT" and actual is not None:
            uid = actual.get("UID", "")
            m = re.match(r"(\d+)@", uid)
            if m and actual.get("DTSTART"):
                eventos.append({"id": int(m.group(1)),
                                "titulo": actual.get("SUMMARY", "").replace(r"\,", ",").replace(r"\;", ";").replace(r"\n", " "),
                                "inicio": fecha(actual["DTSTART"]),
                                "fin": fecha(actual.get("DTEND", "")) if actual.get("DTEND") else None})
            actual = None
        elif actual is not None and ":" in linea:
            clave, valor = linea.split(":", 1)
            actual[clave.split(";", 1)[0].upper()] = valor
    return eventos
