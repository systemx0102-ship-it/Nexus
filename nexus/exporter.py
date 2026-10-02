"""Exportación a Excel (.xlsx real), CSV y HTML portable, sin dependencias externas."""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import re
import zipfile
from datetime import date, datetime
from xml.sax.saxutils import escape

from .config import WEB_DIR, Config

COLUMNAS = [
    # (título, clave, tipo, ancho)
    ("Consecutivo", "consecutivo", "texto", 19),
    ("Contribuyente", "contribuyente", "texto", 44),
    ("Identificación", "identificacion", "texto", 15),
    ("Dirección", "direccion", "texto", 34),
    ("Ref. catastral", "ref_catastral", "texto", 28),
    ("Fecha acta", "fecha_acta", "fecha", 12),
    ("Fecha expedición", "fecha_expedicion", "fecha", 12),
    ("Fecha expiración", "fecha_expiracion", "fecha", 12),
    ("Vigencia", "_vigencia", "texto", 12),
    ("Estado", "_estado", "texto", 12),
    ("Actividad", "actividad", "texto", 30),
    ("Enlace", "_enlace", "enlace", 12),
]
_ESTADOS = {"ok": "Validado", "invalido": "No válido", "vacio": "Sin certificado", "error": "Error"}
_ILEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _fecha(valor) -> date | None:
    if not valor or not isinstance(valor, str):
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", valor)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def vigencia(reg: dict, dias_por_vencer: int = 30, hoy: date | None = None) -> str:
    if reg.get("estado") != "ok":
        return ""
    fin = _fecha(reg.get("fecha_expiracion"))
    if not fin:
        return "Sin fecha"
    restantes = (fin - (hoy or date.today())).days
    if restantes < 0:
        return "Vencido"
    if restantes <= dias_por_vencer:
        return "Por vencer"
    return "Vigente"


def _valor(reg: dict, clave: str, cfg: Config):
    if clave == "_vigencia":
        return vigencia(reg, cfg.dias_por_vencer)
    if clave == "_estado":
        return _ESTADOS.get(reg.get("estado"), reg.get("estado") or "")
    if clave == "_enlace":
        return cfg.url(reg["consecutivo"])
    return reg.get(clave) or ""


def _fecha_texto(valor) -> str:
    d = _fecha(valor)
    return d.strftime("%d/%m/%Y") if d else (valor or "")


# ---- CSV ------------------------------------------------------------------------

def _anti_formula(texto: str) -> str:
    """Evita inyección de fórmulas al abrir el CSV en Excel."""
    return "'" + texto if texto[:1] in ("=", "+", "-", "@", "\t", "\r") else texto


def csv_bytes(registros: list[dict], cfg: Config) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    w.writerow([t for t, *_ in COLUMNAS])
    for r in registros:
        fila = []
        for _, clave, tipo, _ in COLUMNAS:
            v = _valor(r, clave, cfg)
            fila.append(_anti_formula(_fecha_texto(v) if tipo == "fecha" else str(v)))
        w.writerow(fila)
    return ("﻿" + buf.getvalue()).encode("utf-8")


# ---- XLSX -----------------------------------------------------------------------

def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _x(texto) -> str:
    return escape(_ILEGAL.sub("", str(texto)))


def xlsx_bytes(registros: list[dict], cfg: Config) -> bytes:
    filas = []
    cab = "".join(
        f'<c r="{_col(i)}1" t="inlineStr" s="1"><is><t>{_x(t)}</t></is></c>' for i, (t, *_) in enumerate(COLUMNAS)
    )
    filas.append(f'<row r="1">{cab}</row>')
    base = date(1899, 12, 30)
    for n, r in enumerate(registros, start=2):
        celdas = []
        for i, (_, clave, tipo, _) in enumerate(COLUMNAS):
            ref = f"{_col(i)}{n}"
            v = _valor(r, clave, cfg)
            if tipo == "fecha" and _fecha(v):
                celdas.append(f'<c r="{ref}" s="2"><v>{(_fecha(v) - base).days}</v></c>')
            elif tipo == "enlace":
                formula = 'HYPERLINK("' + str(v).replace('"', '""') + '","Abrir")'
                celdas.append(f'<c r="{ref}" t="str" s="3"><f>{_x(formula)}</f><v>Abrir</v></c>')
            elif v != "":
                celdas.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{_x(v)}</t></is></c>')
        filas.append(f'<row r="{n}">{"".join(celdas)}</row>')
    ultima = f"{_col(len(COLUMNAS) - 1)}{max(1, len(registros) + 1)}"
    anchos = "".join(
        f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, (*_, w) in enumerate(COLUMNAS)
    )
    hoja = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>"
        f"<cols>{anchos}</cols><sheetData>{''.join(filas)}</sheetData>"
        f'<autoFilter ref="A1:{ultima}"/></worksheet>'
    )
    estilos = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<numFmts count="1"><numFmt numFmtId="164" formatCode="dd/mm/yyyy"/></numFmts>'
        '<fonts count="3"><font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>'
        '<font><u/><sz val="11"/><color rgb="FF1F5FBF"/><name val="Calibri"/></font></fonts>'
        '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF1B2A41"/><bgColor indexed="64"/></patternFill></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
        '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )
    libro = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Certificados" sheetId="1" r:id="rId1"/></sheets>'
        f'<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">Certificados!$A$1:${_col(len(COLUMNAS) - 1)}${max(1, len(registros) + 1)}</definedName></definedNames>'
        "</workbook>"
    )
    archivos = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": libro,
        "xl/styles.xml": estilos,
        "xl/worksheets/sheet1.xml": hoja,
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, contenido in archivos.items():
            z.writestr(nombre, contenido)
    return out.getvalue()


# ---- HTML portable ----------------------------------------------------------------

def _sha256(texto: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(texto.encode("utf-8")).digest()).decode() + "'"


def html_portable(registros: list[dict], meta: dict) -> bytes:
    """Un solo archivo .html con el panel y los datos (solo lectura), para compartir."""
    with open(os.path.join(WEB_DIR, "index.html"), encoding="utf-8") as fh:
        plantilla = fh.read()
    with open(os.path.join(WEB_DIR, "app.css"), encoding="utf-8") as fh:
        css = fh.read()
    with open(os.path.join(WEB_DIR, "app.js"), encoding="utf-8") as fh:
        js = fh.read()
    datos = json.dumps({"items": registros, "meta": meta}, ensure_ascii=False, separators=(",", ":"))
    datos = datos.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    csp = (
        f"default-src 'none'; script-src {_sha256(js)}; style-src {_sha256(css)}; img-src data:; "
        "base-uri 'none'; form-action 'none'"
    )
    html = plantilla
    html = html.replace('<meta name="nexus-token" content="{{TOKEN}}">', "")
    html = html.replace('content="servidor"', 'content="portable"')
    html = html.replace("<!--CSP-->", f'<meta http-equiv="Content-Security-Policy" content="{csp}">')
    html = html.replace('<link rel="stylesheet" href="/static/app.css">', f"<style>{css}</style>")
    html = html.replace(
        '<script src="/static/app.js"></script>',
        f'<script type="application/json" id="nexus-data">{datos}</script><script>{js}</script>',
    )
    return html.encode("utf-8")


def nombre_archivo(ext: str) -> str:
    return f"certificados_bomberos_{datetime.now().strftime('%Y-%m-%d_%H%M')}.{ext}"
