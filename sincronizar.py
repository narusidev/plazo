"""Lee el campus y actualiza la base de datos. Dos vías:
- con sesión: todo (entregas, notas, tutorías, fechas)
- con iCal: solo fechas, para cuando la sesión ha caducado"""
import logging
import re
import time
from datetime import date, datetime

from campus import CampusError, descargar_ical, leer_ical, numero, texto_plano
from siglas import sigla

log = logging.getLogger("plazo")

DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
TIPOS_PLAZO = {"due", "close"}           # vencimiento de tarea, cierre de cuestionario
MESES_ATRAS, MESES_DELANTE = 2, 8


def fecha_corta(ts):
    if not ts:
        return "sin fecha"
    d = datetime.fromtimestamp(int(ts))
    return f"{DIAS[d.weekday()]} {d.day} {MESES[d.month - 1]}, {d:%H:%M}"


def _meses(hoy, atras, delante):
    a, m = hoy.year, hoy.month - atras
    while m < 1:
        a, m = a - 1, m + 12
    for _ in range(atras + delante + 1):
        yield a, m
        m += 1
        if m > 12:
            a, m = a + 1, 1


def _cmid(evento):
    m = re.search(r"[?&]id=(\d+)", evento.get("url") or "")
    return int(m.group(1)) if m else None


def _titulo(evento):
    if evento.get("activityname"):
        return texto_plano(evento["activityname"])
    t = texto_plano(evento.get("name"))
    return re.sub(r"^(Vencimiento de|Cierre de|Fecha límite de|Se cierra)\s+", "", t, flags=re.I) or "Actividad"


def _curso(evento):
    return (evento.get("course") or {}).get("id") or evento.get("courseid") or None


class _Registro:
    def __init__(self, store, ahora, primera):
        self.store, self.ahora, self.primera = store, ahora, primera
        self.cambios = []

    def cambio(self, entidad, id_, tipo, sig, titulo, antes=None, despues=None):
        if tipo == "nueva" and self.primera:
            return
        self.cambios.append(dict(entidad=entidad, id_entidad=id_, tipo=tipo, sigla=sig, titulo=titulo,
                                 antes=None if antes is None else str(antes),
                                 despues=None if despues is None else str(despues)))

    def guardar_cambios(self):
        for c in self.cambios:
            self.store.ejecutar(
                "INSERT INTO cambio(entidad, id_entidad, tipo, sigla, titulo, antes, despues, detectado) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (c["entidad"], c["id_entidad"], c["tipo"], c["sigla"], c["titulo"], c["antes"], c["despues"], self.ahora))


# ---------------------------------------------------------------- con sesión

def sincronizar_sesion(store, campus):
    ahora = int(time.time())
    primera = store.meta("primera_sync") is None
    reg = _Registro(store, ahora, primera)

    cursos = campus.cursos()
    siglas = {c["id"]: sigla(c.get("fullname") or c.get("shortname") or "") for c in cursos}

    meses = list(_meses(date.today(), MESES_ATRAS, MESES_DELANTE))
    eventos = {}
    for anio, mes in meses:
        for e in campus.eventos_mes(anio, mes):
            eventos[e["id"]] = e
    desde = ahora - 120 * 86400
    acciones = {e["id"]: e for e in campus.acciones(desde)}
    for id_, e in acciones.items():          # actividades más allá de la ventana mensual
        eventos.setdefault(id_, e)

    inicio_ventana = int(datetime(meses[0][0], meses[0][1], 1).timestamp())
    fin_a, fin_m = meses[-1][0] + (meses[-1][1] // 12), meses[-1][1] % 12 + 1
    fin_ventana = int(datetime(fin_a, fin_m, 1).timestamp())

    notas = {}
    for c in cursos:
        try:
            notas.update(campus.notas_curso(c["id"]))
        except CampusError:
            raise
        except Exception as e:  # una página rara no tumba la sincronización
            log.warning("Notas del curso %s: %s", c["id"], e)
    try:
        globales = campus.notas_globales()
    except CampusError:
        raise
    except Exception as e:
        log.warning("Notas globales: %s", e)
        globales = {}

    with store.lock:
        try:
            for c in cursos:
                store.ejecutar(
                    "INSERT INTO modulo(id_curso, nombre, sigla, nota_curso, actualizado) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(id_curso) DO UPDATE SET nombre=excluded.nombre, sigla=excluded.sigla, "
                    "nota_curso=COALESCE(excluded.nota_curso, modulo.nota_curso), actualizado=excluded.actualizado",
                    (c["id"], c.get("fullname") or c.get("shortname"), siglas[c["id"]], globales.get(c["id"]), ahora))

            vistas = set()
            vistos_ev = set()
            for e in eventos.values():
                curso = _curso(e)
                fecha = int(e.get("timesort") or e.get("timestart") or 0) or None
                if e.get("modulename"):
                    if e.get("eventtype") not in TIPOS_PLAZO and e["id"] not in acciones:
                        continue
                    cmid = _cmid(e)
                    if cmid is None or curso not in siglas:
                        continue
                    _guardar_tarea(store, reg, e, cmid, curso, siglas[curso], fecha, acciones, notas, ahora)
                    vistas.add(cmid)
                else:
                    if fecha is None or fecha < ahora - 86400:
                        continue
                    _guardar_evento(store, reg, e, curso if curso in siglas else None, siglas.get(curso), fecha, ahora)
                    vistos_ev.add(e["id"])

            # Desaparecidas: solo dentro de la ventana que hemos leído entera
            for t in store.consultar(
                    "SELECT t.id_cm, t.titulo, m.sigla FROM tarea t JOIN modulo m USING(id_curso) "
                    "WHERE t.fecha_limite BETWEEN ? AND ?", (inicio_ventana, fin_ventana)):
                if t["id_cm"] not in vistas:
                    reg.cambio("tarea", t["id_cm"], "eliminada", t["sigla"], t["titulo"])
                    store.ejecutar("DELETE FROM tarea WHERE id_cm = ?", (t["id_cm"],))
            for ev in store.consultar("SELECT id_evento FROM evento"):
                if ev["id_evento"] not in vistos_ev:
                    store.ejecutar("DELETE FROM evento WHERE id_evento = ?", (ev["id_evento"],))

            reg.guardar_cambios()
            store.poner_meta("ultima_sync", ahora, commit=False)
            store.poner_meta("ultima_sync_completa", ahora, commit=False)
            if primera:
                store.poner_meta("primera_sync", ahora, commit=False)
            store.commit()
        except Exception:
            store.rollback()
            raise

    log.info("Sincronizado con sesión: %d actividades, %d eventos, %d cambios", len(vistas), len(vistos_ev), len(reg.cambios))
    return reg.cambios, recordatorios(store, ahora)


def _guardar_tarea(store, reg, e, cmid, curso, sig, fecha, acciones, notas, ahora):
    titulo = _titulo(e)
    if e["id"] in acciones:
        estado = "pendiente" if (fecha or 0) >= ahora else "vencida"
    else:
        estado = "entregada"
    nota_texto = notas.get(cmid)
    previa = store.uno("SELECT * FROM tarea WHERE id_cm = ?", (cmid,))
    if previa is None:
        previa = store.uno("SELECT * FROM tarea WHERE id_evento = ?", (e["id"],))
    avisos = (0, 0)
    if previa is None:
        de_ical = store.uno("SELECT 1 FROM evento WHERE id_evento = ? AND tipo = 'ical'", (e["id"],))
        if not de_ical:
            reg.cambio("tarea", cmid, "nueva", sig, titulo, None, fecha)
        store.ejecutar("DELETE FROM evento WHERE id_evento = ?", (e["id"],))
    else:
        avisos = (previa["aviso_48h"], previa["aviso_24h"])
        if (previa["fecha_limite"] or None) != fecha:
            reg.cambio("tarea", cmid, "fecha", sig, titulo, previa["fecha_limite"], fecha)
            avisos = (0, 0)
        if nota_texto and nota_texto != previa["nota_texto"]:
            reg.cambio("tarea", cmid, "nota", sig, titulo, previa["nota_texto"], nota_texto)
        if not nota_texto:
            nota_texto = previa["nota_texto"]
        if previa["id_cm"] != cmid:
            store.ejecutar("DELETE FROM tarea WHERE id_cm = ?", (previa["id_cm"],))
    store.ejecutar(
        "INSERT INTO tarea(id_cm, id_evento, id_curso, tipo, titulo, fecha_limite, estado, nota_texto, nota, "
        "aviso_48h, aviso_24h, visto) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(id_cm) DO UPDATE SET id_evento=excluded.id_evento, id_curso=excluded.id_curso, "
        "tipo=excluded.tipo, titulo=excluded.titulo, fecha_limite=excluded.fecha_limite, estado=excluded.estado, "
        "nota_texto=excluded.nota_texto, nota=excluded.nota, aviso_48h=excluded.aviso_48h, "
        "aviso_24h=excluded.aviso_24h, visto=excluded.visto",
        (cmid, e["id"], curso, e.get("modulename"), titulo, fecha, estado, nota_texto,
         numero(nota_texto) if nota_texto else None, avisos[0], avisos[1], ahora))


def _guardar_evento(store, reg, e, curso, sig, inicio, ahora):
    titulo = texto_plano(e.get("name")) or "Evento"
    previo = store.uno("SELECT inicio, tipo FROM evento WHERE id_evento = ?", (e["id"],))
    if previo is None:
        reg.cambio("evento", e["id"], "nueva", sig, titulo, None, inicio)
    elif previo["inicio"] != inicio:
        reg.cambio("evento", e["id"], "fecha", sig, titulo, previo["inicio"], inicio)
    store.ejecutar(
        "INSERT INTO evento(id_evento, id_curso, titulo, tipo, inicio, duracion, visto) VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(id_evento) DO UPDATE SET id_curso=excluded.id_curso, titulo=excluded.titulo, "
        "tipo=excluded.tipo, inicio=excluded.inicio, duracion=excluded.duracion, visto=excluded.visto",
        (e["id"], curso, titulo, e.get("eventtype") or "evento", inicio, int(e.get("timeduration") or 0), ahora))


# ---------------------------------------------------------------- solo iCal

def sincronizar_ical(store, url):
    """Sin sesión: actualiza fechas de lo que ya conocemos y detecta cosas nuevas."""
    ahora = int(time.time())
    reg = _Registro(store, ahora, store.meta("primera_sync") is None)
    eventos = leer_ical(descargar_ical(url))
    with store.lock:
        try:
            for ev in eventos:
                if not ev["inicio"]:
                    continue
                t = store.uno("SELECT t.*, m.sigla FROM tarea t JOIN modulo m USING(id_curso) WHERE id_evento = ?",
                              (ev["id"],))
                if t:
                    if t["fecha_limite"] != ev["inicio"]:
                        reg.cambio("tarea", t["id_cm"], "fecha", t["sigla"], t["titulo"], t["fecha_limite"], ev["inicio"])
                        store.ejecutar("UPDATE tarea SET fecha_limite = ?, aviso_48h = 0, aviso_24h = 0, "
                                       "estado = CASE WHEN estado = 'vencida' AND ? >= ? THEN 'pendiente' ELSE estado END "
                                       "WHERE id_cm = ?", (ev["inicio"], ev["inicio"], ahora, t["id_cm"]))
                    continue
                e = store.uno("SELECT e.*, m.sigla FROM evento e LEFT JOIN modulo m USING(id_curso) WHERE id_evento = ?",
                              (ev["id"],))
                if e:
                    if e["inicio"] != ev["inicio"]:
                        reg.cambio("evento", ev["id"], "fecha", e["sigla"], e["titulo"], e["inicio"], ev["inicio"])
                        store.ejecutar("UPDATE evento SET inicio = ? WHERE id_evento = ?", (ev["inicio"], ev["id"]))
                    continue
                if ev["inicio"] >= ahora:
                    titulo = re.sub(r"^(Vencimiento de|Cierre de)\s+", "", ev["titulo"], flags=re.I)
                    reg.cambio("evento", ev["id"], "nueva", None, titulo, None, ev["inicio"])
                    duracion = (ev["fin"] - ev["inicio"]) if ev.get("fin") else 0
                    store.ejecutar("INSERT INTO evento(id_evento, id_curso, titulo, tipo, inicio, duracion, visto) "
                                   "VALUES (?,?,?,?,?,?,?)", (ev["id"], None, titulo, "ical", ev["inicio"], max(duracion, 0), ahora))
            reg.guardar_cambios()
            store.poner_meta("ultima_sync", ahora, commit=False)
            store.commit()
        except Exception:
            store.rollback()
            raise
    log.info("Sincronizado por iCal: %d eventos, %d cambios", len(eventos), len(reg.cambios))
    return reg.cambios, recordatorios(store, ahora)


# ---------------------------------------------------------------- avisos

def recordatorios(store, ahora):
    """Avisa una vez a 48 h y otra a 24 h de cada entrega pendiente."""
    salida = []
    with store.lock:
        filas = store.consultar(
            "SELECT t.id_cm, t.titulo, t.fecha_limite, t.aviso_48h, t.aviso_24h, m.sigla "
            "FROM tarea t JOIN modulo m USING(id_curso) "
            "WHERE t.estado = 'pendiente' AND t.fecha_limite BETWEEN ? AND ?",
            (ahora, ahora + 48 * 3600))
        for t in filas:
            quedan = t["fecha_limite"] - ahora
            if quedan <= 24 * 3600 and not t["aviso_24h"]:
                salida.append(("Entrega en menos de 24 horas", t))
                store.ejecutar("UPDATE tarea SET aviso_24h = 1, aviso_48h = 1 WHERE id_cm = ?", (t["id_cm"],))
            elif quedan > 24 * 3600 and not t["aviso_48h"]:
                salida.append(("Entrega en menos de 48 horas", t))
                store.ejecutar("UPDATE tarea SET aviso_48h = 1 WHERE id_cm = ?", (t["id_cm"],))
        store.commit()
    return salida


def textos_aviso(cambios, recordatorios_):
    avisos = []
    for c in cambios:
        donde = f"{c['sigla']}: " if c.get("sigla") else ""
        if c["tipo"] == "fecha":
            avisos.append(("Ha cambiado una fecha",
                           f"{donde}{c['titulo']}. Antes {fecha_corta(c['antes'])}, ahora {fecha_corta(c['despues'])}"))
        elif c["tipo"] == "nueva":
            cuando = f", para el {fecha_corta(c['despues'])}" if c.get("despues") else ""
            avisos.append(("Novedad en el campus", f"{donde}{c['titulo']}{cuando}"))
        elif c["tipo"] == "nota":
            avisos.append(("Nota publicada", f"{donde}{c['titulo']}, {c['despues']}"))
    for titulo, t in recordatorios_:
        avisos.append((titulo, f"{t['sigla']}: {t['titulo']}, {fecha_corta(t['fecha_limite'])}"))
    if len(avisos) > 4:
        return [(f"{len(avisos)} novedades en el campus", "Abre Plazo para verlas todas.")]
    return avisos
