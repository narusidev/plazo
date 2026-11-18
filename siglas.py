import re
import unicodedata

_CONOCIDAS = [
    ("implantacion de sistemas operativos", "ISO"),
    ("planificacion y administracion de redes", "PAR"),
    ("fundamentos de hardware", "FH"),
    ("gestion de bases de datos", "GBD"),
    ("lenguajes de marcas", "LMSGI"),
    ("digitalizacion aplicada", "DASP"),
    ("sostenibilidad aplicada", "SASP"),
    ("itinerario personal para la empleabilidad", "IPE"),
    ("administracion de sistemas operativos", "ASO"),
    ("servicios de red", "SRI"),
    ("implantacion de aplicaciones web", "IAW"),
    ("administracion de sistemas gestores", "ASGBD"),
    ("seguridad y alta disponibilidad", "SAD"),
    ("ingles", "ING"),
    ("proyecto intermodular", "PI"),
]
_VACIAS = {"de", "del", "la", "las", "el", "los", "y", "a", "al", "en", "para", "gs", "and"}


def _normal(t):
    t = unicodedata.normalize("NFKD", t)
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def sigla(nombre):
    base = re.sub(r"\s*[-(].*$", "", nombre).strip()  # quita " - AND", " (gs)"
    n = _normal(base)
    num = re.search(r"\b(\d)\s*$", n)
    for clave, s in _CONOCIDAS:
        if n.startswith(clave):
            return s + (num.group(1) if num else "")
    palabras = [p for p in re.findall(r"[a-z0-9]+", n) if p not in _VACIAS]
    return ("".join(p[0] for p in palabras[:5]) or "?").upper()
