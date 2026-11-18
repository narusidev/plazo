import os
import sys
import tempfile
import unittest

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))
os.environ.setdefault("PLAZO_DATA", tempfile.mkdtemp(prefix="plazo-pruebas-"))

from campus import Campus, SesionCaducada, leer_ical  # noqa: E402
from campus_falso import CampusFalso, ts  # noqa: E402
from sincronizar import sincronizar_ical, sincronizar_sesion, textos_aviso  # noqa: E402
from store import Store  # noqa: E402
import actualizar  # noqa: E402


class PruebasPlazo(unittest.TestCase):
    def setUp(self):
        self.falso = CampusFalso()
        self.store = Store(os.path.join(tempfile.mkdtemp(), "p.db"))
        self.campus = Campus(self.falso.sitio, {"MoodleSession": "buena"})

    def tearDown(self):
        self.falso.parar()

    def tarea(self, cm):
        return self.store.uno("SELECT * FROM tarea WHERE id_cm = ?", (cm,))

    def test_primera_sincronizacion(self):
        cambios, recordatorios = sincronizar_sesion(self.store, self.campus)
        self.assertEqual(cambios, [])
        self.assertEqual(self.tarea(9101)["estado"], "entregada")
        self.assertEqual(self.tarea(9101)["nota_texto"], "8,25 / 10,00")
        self.assertEqual(self.tarea(9106)["estado"], "pendiente")
        self.assertEqual(self.tarea(9108)["estado"], "vencida")
        self.assertEqual(self.tarea(9110)["tipo"], "quiz")       # cuestionario fuera de la ventana mensual
        self.assertEqual(len(self.store.consultar("SELECT * FROM evento")), 2)
        self.assertEqual(self.store.uno("SELECT nota_curso FROM modulo WHERE id_curso = 11")["nota_curso"], "8,25")
        self.assertEqual([r[1]["id_cm"] for r in recordatorios], [9109])
        self.assertIn("MOODLEID1_", self.campus.cookies)
        self.assertTrue(self.campus.url_ical().endswith("preset_time=recentupcoming"))

    def test_cambios(self):
        sincronizar_sesion(self.store, self.campus)
        d = self.falso.d
        d["actividades"][5]["fecha"] = ts(5)                         # PAR adelantada
        d["actividades"][1]["nota"] = "6,00"                         # nota nueva
        d["actividades"][4]["entregada"] = True                      # LMSGI entregada
        d["actividades"].append({"ev": 1010, "cm": 9120, "curso": 14, "mod": "assign",
                                 "nombre": "Prueba Abierta 2 UD03", "fecha": ts(18), "entregada": False})
        del d["actividades"][2]                                      # desaparece una
        cambios, _ = sincronizar_sesion(self.store, self.campus)
        tipos = sorted((c["tipo"], c["id_entidad"]) for c in cambios)
        self.assertEqual(tipos, [("eliminada", 9105), ("fecha", 9106), ("nota", 9102), ("nueva", 9120)])
        self.assertEqual(self.tarea(9109)["estado"], "entregada")
        self.assertTrue(textos_aviso(cambios, []))

    def test_sesion_caducada(self):
        sincronizar_sesion(self.store, self.campus)
        self.falso.d["sesion_valida"] = False
        with self.assertRaises(SesionCaducada):
            self.campus.mantener_viva()
        with self.assertRaises(SesionCaducada):
            sincronizar_sesion(self.store, Campus(self.falso.sitio, {"MoodleSession": "buena"}))

    def test_ical_detecta_fechas(self):
        sincronizar_sesion(self.store, self.campus)
        url = self.campus.url_ical()
        self.falso.d["sesion_valida"] = False
        self.falso.d["actividades"][5]["fecha"] = ts(4)
        self.falso.d["eventos"][0]["inicio"] = ts(2, 16, 0)
        self.falso.d["actividades"].append({"ev": 1011, "cm": 9130, "curso": 11, "mod": "assign",
                                            "nombre": "Tarea sorpresa", "fecha": ts(9), "entregada": False})
        cambios, _ = sincronizar_ical(self.store, url)
        tipos = sorted((c["entidad"], c["tipo"]) for c in cambios)
        self.assertEqual(tipos, [("evento", "fecha"), ("evento", "nueva"), ("tarea", "fecha")])
        self.assertEqual(self.tarea(9106)["fecha_limite"], ts(4))
        # Cuando vuelve la sesión, la tarea sorpresa pasa a ser tarea sin avisar dos veces
        self.falso.d["sesion_valida"] = True
        cambios, _ = sincronizar_sesion(self.store, self.campus)
        self.assertEqual(cambios, [])
        self.assertEqual(self.tarea(9130)["estado"], "pendiente")

    def test_ical_plegado(self):
        texto = "BEGIN:VEVENT\r\nUID:42@x\r\nSUMMARY:Vencimiento de algo muy\r\n  largo\\, con coma\r\nDTSTART:20261126T225900Z\r\nEND:VEVENT\r\n"
        ev = leer_ical(texto)[0]
        self.assertEqual(ev["id"], 42)
        self.assertEqual(ev["titulo"], "Vencimiento de algo muy largo, con coma")

    def test_versiones(self):
        self.assertGreater(actualizar._tupla("v2.0.10"), actualizar._tupla("2.0.9"))
        self.assertEqual(actualizar._tupla("v2.1"), (2, 1, 0))


if __name__ == "__main__":
    unittest.main()
