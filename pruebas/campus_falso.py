"""Campus de Moodle simulado para las pruebas: imita las páginas y llamadas que usa Plazo."""
import json
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def ts(dias, h=23, m=59):
    return int((datetime.now() + timedelta(days=dias)).replace(hour=h, minute=m, second=0, microsecond=0).timestamp())


def datos_iniciales():
    return {
        "sesion_valida": True,
        "cursos": [
            {"id": 11, "fullname": "Digitalización Aplicada a los Sectores Productivos (gs) - AND"},
            {"id": 14, "fullname": "Implantacion de Sistemas Operativos - AND"},
            {"id": 15, "fullname": "Lenguajes de Marcas y Sistemas de Gestión de Información - AND"},
            {"id": 16, "fullname": "Planificacion y Administracion de Redes - AND"},
        ],
        "actividades": [
            {"ev": 1001, "cm": 9101, "curso": 11, "mod": "assign", "nombre": "Prueba Abierta 1 UD02", "fecha": ts(0), "entregada": True, "nota": "8,25"},
            {"ev": 1002, "cm": 9102, "curso": 11, "mod": "assign", "nombre": "Prueba Abierta 1 UD03", "fecha": ts(22), "entregada": False},
            {"ev": 1003, "cm": 9105, "curso": 14, "mod": "assign", "nombre": "Prueba Abierta 1 UD03", "fecha": ts(0), "entregada": True},
            {"ev": 1004, "cm": 9108, "curso": 14, "mod": "assign", "nombre": "Prueba Abierta 1 UD01", "fecha": ts(-35), "entregada": False},
            {"ev": 1005, "cm": 9109, "curso": 15, "mod": "assign", "nombre": "Prueba Abierta 1 UD02", "fecha": ts(1), "entregada": False},
            {"ev": 1006, "cm": 9106, "curso": 16, "mod": "assign", "nombre": "Prueba Abierta 1 UD03", "fecha": ts(8), "entregada": False},
            {"ev": 1007, "cm": 9110, "curso": 15, "mod": "quiz", "nombre": "Cuestionario recuperación UD01", "fecha": ts(150), "entregada": False},
        ],
        "eventos": [
            {"id": 501, "nombre": "Videotutoría PAR UD03", "inicio": ts(1, 16, 0), "dur": 3600, "curso": 16},
            {"id": 502, "nombre": "Instalación de máquinas virtuales", "inicio": ts(1, 18, 0), "dur": 3600, "curso": None},
        ],
    }


class CampusFalso:
    def __init__(self):
        self.d = datos_iniciales()
        self.lock = threading.Lock()
        campus = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _logueado(self):
                return campus.d["sesion_valida"] and "MoodleSession=buena" in (self.headers.get("Cookie") or "")

            def _enviar(self, codigo, cuerpo, tipo="text/html; charset=utf-8", extra=None):
                b = cuerpo.encode() if isinstance(cuerpo, str) else cuerpo
                self.send_response(codigo)
                self.send_header("Content-Type", tipo)
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _redirigir_login(self):
                self._enviar(303, "", extra={"Location": f"http://127.0.0.1:{campus.puerto}/login/index.php"})

            def do_GET(self):
                ruta, _, q = self.path.partition("?")
                qs = dict(urllib.parse.parse_qsl(q))
                if ruta == "/login/index.php":
                    return self._enviar(200, '<a href="/auth/oauth2/login.php?id=1">Office 365</a>')
                if ruta == "/calendar/export_execute.php":
                    return self._enviar(200, campus.ical(), "text/calendar")
                if not self._logueado():
                    return self._redirigir_login()
                if ruta == "/my/":
                    return self._enviar(200, '<script>M.cfg = {"wwwroot":"x","sesskey":"SK123","userid":5};</script>',
                                        extra={"Set-Cookie": "MOODLEID1_=abc; path=/"})
                if ruta == "/grade/report/user/index.php":
                    return self._enviar(200, campus.informe(int(qs["id"])))
                if ruta == "/grade/report/overview/index.php":
                    return self._enviar(200, campus.vista_general())
                self._enviar(404, "no")

            def do_POST(self):
                ruta, _, q = self.path.partition("?")
                qs = dict(urllib.parse.parse_qsl(q))
                cuerpo = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if not self._logueado():
                    if ruta == "/lib/ajax/service.php":
                        return self._enviar(200, json.dumps([{"error": True, "exception": {"errorcode": "servicerequireslogin", "message": "login"}}]), "application/json")
                    return self._redirigir_login()
                if ruta == "/lib/ajax/service.php":
                    if qs.get("sesskey") != "SK123":
                        return self._enviar(200, json.dumps({"error": "sesskey", "errorcode": "invalidsesskey"}), "application/json")
                    llamada = json.loads(cuerpo)[0]
                    return self._enviar(200, json.dumps([{"error": False, "data": campus.ajax(llamada["methodname"], llamada["args"])}]), "application/json")
                if ruta == "/calendar/export.php":
                    url = f"http://127.0.0.1:{campus.puerto}/calendar/export_execute.php?userid=5&amp;authtoken=TOK&amp;preset_what=all&amp;preset_time=recentupcoming"
                    return self._enviar(200, f'<div class="generalbox calendarurl">URL del calendario: {url}</div>')
                self._enviar(404, "no")

        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.puerto = self.servidor.server_address[1]
        self.sitio = f"http://127.0.0.1:{self.puerto}"
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()

    def parar(self):
        self.servidor.shutdown()

    # ---- contenido ----
    def _evento(self, a):
        return {"id": a["ev"], "name": f"Vencimiento de {a['nombre']}" if a["mod"] == "assign" else f"Cierre de {a['nombre']}",
                "activityname": a["nombre"], "modulename": a["mod"], "eventtype": "due" if a["mod"] == "assign" else "close",
                "timestart": a["fecha"], "timesort": a["fecha"], "timeduration": 0, "course": {"id": a["curso"]},
                "url": f"{self.sitio}/mod/{a['mod']}/view.php?id={a['cm']}"}

    def ajax(self, metodo, args):
        d = self.d
        if metodo == "core_course_get_enrolled_courses_by_timeline_classification":
            return {"courses": d["cursos"], "nextoffset": 0}
        if metodo == "core_calendar_get_calendar_monthly_view":
            ini = datetime(args["year"], args["month"], 1).timestamp()
            fin = datetime(args["year"] + args["month"] // 12, args["month"] % 12 + 1, 1).timestamp()
            evs = [self._evento(a) for a in d["actividades"] if ini <= a["fecha"] < fin]
            evs += [{"id": e["id"], "name": e["nombre"], "modulename": "", "eventtype": "user", "timestart": e["inicio"],
                     "timesort": e["inicio"], "timeduration": e["dur"], "course": {"id": e["curso"]} if e["curso"] else None,
                     "url": f"{self.sitio}/?redirect=0"} for e in d["eventos"] if ini <= e["inicio"] < fin]
            return {"weeks": [{"days": [{"events": evs}]}]}
        if metodo == "core_calendar_get_action_events_by_timesort":
            evs = [self._evento(a) for a in sorted(d["actividades"], key=lambda a: a["fecha"])
                   if not a["entregada"] and a["fecha"] >= args["timesortfrom"]]
            return {"events": evs, "firstid": 0, "lastid": evs[-1]["id"] if evs else 0}
        if metodo == "core_session_touch":
            return True
        if metodo == "core_session_time_remaining":
            return {"userid": 5, "timeremaining": 28800}
        raise ValueError(metodo)

    def informe(self, curso):
        filas = ""
        for a in self.d["actividades"]:
            if a["curso"] != curso:
                continue
            filas += (f'<tr><th class="level2 column-itemname"><a href="{self.sitio}/mod/{a["mod"]}/view.php?id={a["cm"]}">'
                      f'<span class="accesshide">Tarea</span>{a["nombre"]}</a></th>'
                      f'<td class="level2 column-grade">{a.get("nota", "-")}<div class="dropdown">Acciones Análisis</div></td>'
                      f'<td class="level2 column-range">0,00&ndash;10,00</td></tr>')
        return f'<table class="generaltable user-grade"><tr><th class="column-itemname">Ítem</th></tr>{filas}</table>'

    def vista_general(self):
        filas = "".join(f'<tr><td class="cell c0"><a href="{self.sitio}/grade/report/user/index.php?id={c["id"]}">{c["fullname"]}</a></td>'
                        f'<td class="cell c1">{"8,25" if c["id"] == 11 else "-"}</td></tr>' for c in self.d["cursos"])
        return f'<table id="overview-grade" class="generaltable"><tbody>{filas}</tbody></table>'

    def ical(self):
        def f(t):
            return datetime.fromtimestamp(t, timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        partes = ["BEGIN:VCALENDAR", "VERSION:2.0"]
        for a in self.d["actividades"]:
            partes += ["BEGIN:VEVENT", f"UID:{a['ev']}@127.0.0.1", f"SUMMARY:Vencimiento de {a['nombre']}",
                       f"DTSTART:{f(a['fecha'])}", f"DTEND:{f(a['fecha'])}", "END:VEVENT"]
        for e in self.d["eventos"]:
            partes += ["BEGIN:VEVENT", f"UID:{e['id']}@127.0.0.1", f"SUMMARY:{e['nombre']}",
                       f"DTSTART:{f(e['inicio'])}", f"DTEND:{f(e['inicio'] + e['dur'])}", "END:VEVENT"]
        partes.append("END:VCALENDAR")
        return "\r\n".join(partes) + "\r\n"
