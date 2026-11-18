"""Base de datos local (SQLite). Un único archivo: plazo.db."""
import sqlite3
import threading

VERSION_ESQUEMA = 2

ESQUEMA = """
CREATE TABLE IF NOT EXISTS modulo (
    id_curso     INTEGER PRIMARY KEY,          -- id del curso en Moodle
    nombre       TEXT    NOT NULL,
    sigla        TEXT    NOT NULL,             -- ISO, PAR, GBD...
    nota_curso   TEXT,                         -- nota global tal como la muestra el campus
    actualizado  INTEGER NOT NULL              -- epoch de la última sincronización
);

-- Todo lo que tiene fecha límite: tareas (assign), cuestionarios (quiz)...
CREATE TABLE IF NOT EXISTS tarea (
    id_cm         INTEGER PRIMARY KEY,         -- id de la actividad en el curso (sale en la URL ?id=)
    id_evento     INTEGER UNIQUE,              -- id del evento de calendario (el mismo que trae el iCal)
    id_curso      INTEGER NOT NULL REFERENCES modulo(id_curso) ON DELETE CASCADE,
    tipo          TEXT    NOT NULL,            -- assign, quiz...
    titulo        TEXT    NOT NULL,
    fecha_limite  INTEGER,                     -- epoch
    estado        TEXT    NOT NULL DEFAULT 'pendiente'
                  CHECK (estado IN ('pendiente','entregada','vencida')),
    nota_texto    TEXT,                        -- "8,25 / 10"
    nota          REAL    CHECK (nota IS NULL OR nota >= 0),
    aviso_48h     INTEGER NOT NULL DEFAULT 0,
    aviso_24h     INTEGER NOT NULL DEFAULT 0,
    visto         INTEGER NOT NULL             -- última vez que apareció en el campus
);
CREATE INDEX IF NOT EXISTS idx_tarea_fecha ON tarea(fecha_limite);

-- Tutorías y otros eventos sin entrega
CREATE TABLE IF NOT EXISTS evento (
    id_evento   INTEGER PRIMARY KEY,
    id_curso    INTEGER,                       -- NULL en eventos personales o del sitio
    titulo      TEXT    NOT NULL,
    tipo        TEXT    NOT NULL,              -- user, course, site, ical...
    inicio      INTEGER NOT NULL,
    duracion    INTEGER NOT NULL DEFAULT 0,
    visto       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS cambio (
    id_cambio   INTEGER PRIMARY KEY AUTOINCREMENT,
    entidad     TEXT    NOT NULL CHECK (entidad IN ('tarea','evento')),
    id_entidad  INTEGER NOT NULL,
    tipo        TEXT    NOT NULL CHECK (tipo IN ('nueva','fecha','nota','eliminada')),
    sigla       TEXT,
    titulo      TEXT    NOT NULL,
    antes       TEXT,
    despues     TEXT,
    detectado   INTEGER NOT NULL,
    leido       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (
    clave  TEXT PRIMARY KEY,
    valor  TEXT
);
"""


class Store:
    def __init__(self, ruta):
        self.lock = threading.RLock()
        self._db = sqlite3.connect(ruta, check_same_thread=False, timeout=15)
        self._db.row_factory = sqlite3.Row
        with self.lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version < VERSION_ESQUEMA:
                # La versión 1 nunca llegó a sincronizar: se rehace la base de datos desde cero.
                for t in ("cambio", "evento", "tarea", "modulo", "meta"):
                    self._db.execute(f"DROP TABLE IF EXISTS {t}")
                self._db.execute(f"PRAGMA user_version = {VERSION_ESQUEMA}")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.executescript(ESQUEMA)
            self._db.commit()

    def consultar(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    def uno(self, sql, args=()):
        filas = self.consultar(sql, args)
        return filas[0] if filas else None

    def ejecutar(self, sql, args=()):
        with self.lock:
            return self._db.execute(sql, args)

    def commit(self):
        with self.lock:
            self._db.commit()

    def rollback(self):
        with self.lock:
            self._db.rollback()

    def meta(self, clave, defecto=None):
        fila = self.uno("SELECT valor FROM meta WHERE clave = ?", (clave,))
        return fila["valor"] if fila else defecto

    def poner_meta(self, clave, valor, commit=True):
        self.ejecutar(
            "INSERT INTO meta(clave, valor) VALUES (?, ?) "
            "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
            (clave, None if valor is None else str(valor)),
        )
        if commit:
            self.commit()
