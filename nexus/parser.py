"""Extrae los datos de la página de verificación de un certificado.

La página se lee por *etiquetas* ("Contribuyente:", "Dirección", "Fecha de expiración"...)
y no por posiciones fijas, así sigue funcionando aunque la Alcaldía mueva el diseño.
Además de los campos principales se guardan TODOS los pares etiqueta → valor que tenga
la página (`campos`), para no perder ningún dato.
"""
from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser

# Campo canónico -> expresión sobre la etiqueta normalizada (minúsculas, sin tildes).
REGLAS = [
    ("consecutivo", r"consecutivo|numero (?:de(?:l)? )?certificado|certificado (?:no|nro|n)\b|^no\.? certificado"),
    ("contribuyente", r"contribuyente|razon social|nombre (?:o razon social|del establecimiento|comercial|del contribuyente|empresa)"
                      r"|^establecimiento$|^propietario$|^nombre$|^titular$|^empresa$|^solicitante$"),
    ("identificacion", r"identificacion|\bnit\b|cedula|^documento|^c\.? ?c\.?$|^no\.? documento"),
    ("direccion", r"direccion|^ubicacion"),
    ("ref_catastral", r"catastr|^referencia$|^ref\.?$|^ref\.? cat"),
    ("fecha_acta", r"\bacta\b"),
    ("fecha_expedicion", r"expedicion|expedido|emision|otorgamiento|otorgado|fecha de generacion|fecha (?:de )?inicio"),
    ("fecha_expiracion", r"expiracion|vencimiento|\bvence\b|vigente hasta|valido hasta|vigencia hasta|fecha (?:de )?fin"),
    ("estado_pagina", r"^estado"),
    ("actividad", r"actividad|^ciiu|^uso$|^tipo de establecimiento"),
]
_REGLAS = [(campo, re.compile(rx)) for campo, rx in REGLAS]

CAMPOS = [c for c, _ in REGLAS]
FECHAS = ("fecha_acta", "fecha_expedicion", "fecha_expiracion")

_VACIO = re.compile(
    r"no existe|no se encontr|no encontrad|no hay (?:datos|registros|informacion|resultados)|sin resultados"
    r"|no registra|no se hallo|no esta registrad|no se encuentra|no corresponde|no fue encontrad"
)
_INVALIDO = re.compile(r"anulad|revocad|invalid|no (?:es )?valid|cancelad|suspendid|falso|no autentic")
_ERROR_SERVIDOR = re.compile(r"exception|error interno|java\.|stack ?trace|servlet|http status 5\d\d|error 5\d\d")
_RE_CONSEC = re.compile(r"\b(\d{5,15})\s*-\s*(\d{4})\b")

# Etiquetas que no dividen el texto (van dentro de una misma frase).
_EN_LINEA = {"a", "abbr", "sup", "sub", "small", "wbr", "acronym", "cite", "q", "nobr"}
_IGNORAR = {"script", "style", "noscript", "template", "head", "title", "svg"}


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto or "")
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    t = t.lower().replace("º", "o").replace("°", "o")
    return re.sub(r"\s+", " ", t).strip()


def _limpio(texto: str) -> str:
    return re.sub(r"\s+", " ", (texto or "").replace("\xa0", " ")).strip()


class _Lector(HTMLParser):
    """Convierte el HTML en una secuencia de textos y, aparte, en filas de tablas."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tokens: list[str] = []
        self.filas: list[list[str]] = []
        self._buf: list[str] = []
        self._ignorar = 0
        self._tablas: list[dict] = []
        self.titulo = ""
        self._en_titulo = False

    # -- texto plano
    def _cortar(self):
        txt = _limpio("".join(self._buf))
        if txt:
            self.tokens.append(txt)
        self._buf = []

    # -- celdas
    def _celda_actual(self):
        if self._tablas and self._tablas[-1]["celda"] is not None:
            return self._tablas[-1]["celda"]
        return None

    def _cerrar_celda(self):
        if self._tablas:
            t = self._tablas[-1]
            if t["celda"] is not None and t["fila"] is not None:
                t["fila"].append(_limpio("".join(t["celda"])))
            t["celda"] = None

    def _cerrar_fila(self):
        if self._tablas:
            self._cerrar_celda()
            t = self._tablas[-1]
            if t["fila"]:
                self.filas.append(t["fila"])
            t["fila"] = None

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._en_titulo = True
        if tag in _IGNORAR:
            self._ignorar += 1
            return
        if self._ignorar:
            return
        if tag not in _EN_LINEA:
            self._cortar()
        if tag == "br":
            celda = self._celda_actual()
            if celda is not None:
                celda.append(" ")
        if tag == "table":
            self._tablas.append({"fila": None, "celda": None})
        elif tag == "tr" and self._tablas:
            self._cerrar_fila()
            self._tablas[-1]["fila"] = []
        elif tag in ("td", "th") and self._tablas:
            t = self._tablas[-1]
            self._cerrar_celda()
            if t["fila"] is None:
                t["fila"] = []
            t["celda"] = []
        elif tag == "input":
            a = dict(attrs)
            if (a.get("type") or "text").lower() not in ("hidden", "submit", "button", "image", "reset", "checkbox", "radio"):
                valor = _limpio(a.get("value") or "")
                if valor:
                    self.tokens.append(valor)
                    celda = self._celda_actual()
                    if celda is not None:
                        celda.append(" " + valor + " ")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "title":
            self._en_titulo = False
        if tag in _IGNORAR:
            self._ignorar = max(0, self._ignorar - 1)
            return
        if self._ignorar:
            return
        if tag not in _EN_LINEA:
            self._cortar()
        if tag in ("td", "th"):
            self._cerrar_celda()
        elif tag == "tr":
            self._cerrar_fila()
        elif tag == "table" and self._tablas:
            self._cerrar_fila()
            self._tablas.pop()

    def handle_data(self, data):
        if self._en_titulo:
            self.titulo += data
        if self._ignorar:
            return
        self._buf.append(data)
        celda = self._celda_actual()
        if celda is not None:
            celda.append(data)

    def cerrar(self):
        self.close()
        self._cortar()
        while self._tablas:
            self._cerrar_fila()
            self._tablas.pop()


def _campo_de(etiqueta: str) -> str | None:
    n = normalizar(etiqueta).strip(" :.-*#")
    if not n or len(n) > 60:
        return None
    for campo, rx in _REGLAS:
        if rx.search(n):
            return campo
    return None


def _es_etiqueta(texto: str) -> bool:
    t = texto.strip()
    if not t or len(t) > 70:
        return False
    if t.endswith(":"):
        return bool(re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]", t))
    if re.search(r"\d{3,}", t):
        return False
    return _campo_de(t) is not None and len(t) <= 45


def _separar_en_linea(texto: str):
    """'Contribuyente: VENTA DE FRIAS' -> ('Contribuyente', 'VENTA DE FRIAS')."""
    m = re.match(r"^([^:\d]{2,50}?)\s*:\s*(.+)$", texto)
    if m and re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]", m.group(1)):
        return m.group(1).strip(), m.group(2).strip()
    return None


def _pares_de_texto(tokens: list[str]) -> list[tuple[str, str]]:
    pares = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if _es_etiqueta(tok):
            valor = ""
            if i + 1 < len(tokens) and not _es_etiqueta(tokens[i + 1]):
                valor = tokens[i + 1]
                i += 1
            pares.append((tok.rstrip(" :").strip(), valor))
        else:
            dividido = _separar_en_linea(tok)
            if dividido:
                pares.append(dividido)
        i += 1
    return pares


def _pares_de_tablas(filas: list[list[str]]) -> list[tuple[str, str]]:
    """Celdas completas: 'etiqueta | valor' en la misma fila, o fila de encabezados con valores debajo."""
    pares = []
    for fila in filas:
        i = 0
        while i < len(fila) - 1:
            etq, val = fila[i], fila[i + 1]
            if _es_etiqueta(etq) and val and not _es_etiqueta(val):
                pares.append((etq.rstrip(" :").strip(), val))
                i += 2
            else:
                i += 1
    for a, b in zip(filas, filas[1:]):
        if len(a) >= 2 and len(a) == len(b):
            n_etq = sum(1 for c in a if _es_etiqueta(c) or _campo_de(c))
            n_val = sum(1 for c in b if c and not (_es_etiqueta(c) or _campo_de(c)))
            if n_etq >= max(2, len(a) * 0.6) and n_val >= max(1, len(b) * 0.5):
                pares.extend((x.rstrip(" :").strip(), y) for x, y in zip(a, b) if x)
    return pares


# ---- fechas -----------------------------------------------------------------

_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "sep": 9,
    "sept": 9, "oct": 10, "nov": 11, "dic": 12,
}


def fecha_iso(texto: str) -> str | None:
    """Devuelve 'AAAA-MM-DD' a partir de 07/01/2026, 2026-01-07, '7 de enero de 2026'..."""
    if not texto:
        return None
    t = normalizar(texto)
    m = re.search(r"\b(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})\b", t)
    if m:
        a, mes, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b", t)
        if m:
            d, mes, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            m = re.search(r"\b(\d{1,2})\s*(?:de\s+|[/\-. ])\s*([a-z]{3,10})\.?\s*(?:de(?:l)?\s+|[/\-. ])\s*(\d{4})\b", t)
            if not m or m.group(2) not in _MESES:
                return None
            d, mes, a = int(m.group(1)), _MESES[m.group(2)], int(m.group(3))
    if not (1 <= mes <= 12 and 1 <= d <= 31 and 1990 <= a <= 2100):
        return None
    return f"{a:04d}-{mes:02d}-{d:02d}"


# ---- API ----------------------------------------------------------------------

def analizar(html: str, consecutivo: str = "") -> dict:
    """Devuelve {'estado', 'detalle', 'campos': [[etiqueta, valor], ...], <campos canónicos>}.

    estado: 'ok' (certificado con datos), 'invalido' (la página lo marca anulado / no válido
    o devuelve otro consecutivo), 'vacio' (no existe) o 'error' (página de error del servidor).
    """
    lector = _Lector()
    try:
        lector.feed(html or "")
        lector.cerrar()
    except Exception:  # HTML roto: nos quedamos con lo que se alcanzó a leer
        pass

    vistos = set()
    campos: list[list[str]] = []
    for etiqueta, valor in _pares_de_tablas(lector.filas) + _pares_de_texto(lector.tokens):
        clave = normalizar(etiqueta)
        if not clave or clave in vistos:
            continue
        vistos.add(clave)
        campos.append([etiqueta, valor])

    datos: dict = {c: None for c in CAMPOS}
    for etiqueta, valor in campos:
        campo = _campo_de(etiqueta)
        if campo and not datos[campo] and valor:
            datos[campo] = valor

    texto = normalizar(" ".join(lector.tokens))
    if not datos["consecutivo"]:
        m = _RE_CONSEC.search(" ".join(lector.tokens))
        if m:
            datos["consecutivo"] = f"{m.group(1)}-{m.group(2)}"
    for f in FECHAS:
        if datos[f]:
            datos[f] = fecha_iso(datos[f]) or datos[f]

    tiene_datos = bool(datos["contribuyente"] or datos["identificacion"]) or sum(
        1 for c in ("direccion", "ref_catastral", "fecha_expedicion", "fecha_expiracion") if datos[c]
    ) >= 2

    detalle = ""
    if tiene_datos:
        estado = "ok"
        if datos["estado_pagina"] and _INVALIDO.search(normalizar(datos["estado_pagina"])):
            estado, detalle = "invalido", datos["estado_pagina"]
        elif consecutivo and datos["consecutivo"]:
            pedido = re.sub(r"\D", "", consecutivo)
            leido = re.sub(r"\D", "", datos["consecutivo"])
            if leido and pedido and leido.lstrip("0") != pedido.lstrip("0"):
                estado, detalle = "invalido", f"La página devolvió otro consecutivo: {datos['consecutivo']}"
    else:
        if _ERROR_SERVIDOR.search(texto) and not _VACIO.search(texto):
            estado, detalle = "error", "El servidor devolvió una página de error"
        else:
            estado = "vacio"
            mensaje = next((t for t in lector.tokens if _VACIO.search(normalizar(t)) or _INVALIDO.search(normalizar(t))), "")
            detalle = mensaje[:200] or "Sin certificado registrado"

    datos.update(estado=estado, detalle=detalle, campos=campos, titulo=_limpio(lector.titulo)[:200])
    return datos
