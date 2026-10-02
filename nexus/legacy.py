"""Importa los registros del sistema anterior (Proyect.html) para no volver a consultarlos."""
from __future__ import annotations

import re
from html.parser import HTMLParser

from .parser import fecha_iso

_TIPOS = {"ok": "ok", "rejected": "invalido", "error": "error"}
_COLS = ["n", "consecutivo", "contribuyente", "identificacion", "direccion", "ref_catastral",
         "fecha_acta", "fecha_expedicion", "fecha_expiracion", "estado_txt"]
_ETIQUETAS = ["Consecutivo", "Contribuyente", "Identificación", "Dirección", "Ref. catastral",
              "Fecha acta", "Fecha expedición", "Fecha expiración"]


class _Filas(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.filas: list[tuple[dict, list[str]]] = []
        self._tbody = False
        self._fila = None
        self._celda = None

    def handle_starttag(self, tag, attrs):
        if tag == "tbody":
            self._tbody = True
        elif tag == "tr" and self._tbody:
            self._fila = (dict(attrs), [])
        elif tag == "td" and self._fila is not None:
            self._celda = []

    def handle_endtag(self, tag):
        if tag == "td" and self._fila is not None and self._celda is not None:
            self._fila[1].append(re.sub(r"\s+", " ", "".join(self._celda)).strip())
            self._celda = None
        elif tag == "tr" and self._fila is not None:
            self.filas.append(self._fila)
            self._fila = None
        elif tag == "tbody":
            self._tbody = False

    def handle_data(self, data):
        if self._celda is not None:
            self._celda.append(data)


def leer(ruta: str) -> list[dict]:
    with open(ruta, "r", encoding="utf-8", errors="replace") as fh:
        p = _Filas()
        p.feed(fh.read())
    registros = []
    for attrs, celdas in p.filas:
        if len(celdas) < 10:
            continue
        d = dict(zip(_COLS, celdas))
        m = re.match(r"^(\d+)-(\d{4})$", d["consecutivo"])
        if not m:
            continue
        estado = _TIPOS.get(attrs.get("data-kind", "ok"), "ok")
        reg = {
            "consecutivo": d["consecutivo"],
            "numero": int(m.group(1)),
            "anio": int(m.group(2)),
            "estado": estado,
            "contribuyente": d["contribuyente"] or None,
            "identificacion": d["identificacion"] or None,
            "direccion": d["direccion"] or None,
            "ref_catastral": d["ref_catastral"] or None,
            "detalle": "" if estado == "ok" else attrs.get("data-status", ""),
            "origen": "importado",
        }
        for f in ("fecha_acta", "fecha_expedicion", "fecha_expiracion"):
            reg[f] = fecha_iso(d[f]) or (d[f] or None)
        reg["campos"] = [[e, v] for e, v in zip(_ETIQUETAS, celdas[1:9]) if v]
        registros.append(reg)
    return registros
