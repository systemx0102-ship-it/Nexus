"""Detector de diferencias / anomalías dentro de los certificados ya consultados.

No consulta nada en la red: solo analiza lo que hay en la base local y marca lo que
no cuadra, para revisarlo a mano. Tipos de hallazgo:

- nit_distinto_nombre · un mismo NIT/CC aparece con NOMBRES distintos (posible error o suplantación).
- nit_repetido        · un mismo NIT/CC aparece en varios certificados con el mismo nombre (duplicado/sucursales).
- fechas_incoherentes · fechas imposibles (expira antes de expedir, acta posterior…) o
                        vigencia muy distinta a un año.
- sin_consultar       · consecutivos dentro del rango que quedaron con error de consulta.

Nota: "misma dirección" o "misma referencia catastral" NO se marcan como anomalía: en centros
comerciales y edificios es normal que decenas de locales las compartan. El NIT/CC sí es único por
contribuyente, así que ahí sí tiene sentido revisar.
"""
from __future__ import annotations

from datetime import date

from .parser import normalizar

SEVERIDADES = {"alta": 3, "media": 2, "baja": 1}
FIRMES = ("ok", "invalido")


def _fecha(valor) -> date | None:
    if not isinstance(valor, str) or len(valor) < 10:
        return None
    try:
        a, m, d = int(valor[0:4]), int(valor[5:7]), int(valor[8:10])
        return date(a, m, d)
    except (ValueError, TypeError):
        return None


def _clave(valor: str) -> str:
    return normalizar(valor).strip(" .,-")


def _hallazgo(tipo, severidad, titulo, detalle, consecutivos):
    return {
        "tipo": tipo,
        "severidad": severidad,
        "titulo": titulo,
        "detalle": detalle,
        "consecutivos": list(dict.fromkeys(consecutivos)),  # únicos, en orden
    }


def _por_nit(registros):
    """Agrupa por NIT/CC. Un NIT es único por contribuyente, así que repetirlo es revisable."""
    grupos: dict[str, list] = {}
    for r in registros:
        nit = (r.get("identificacion") or "").strip()
        if nit and len(_clave(nit)) >= 4:
            grupos.setdefault(_clave(nit), []).append(r)
    hallazgos = []
    for regs in grupos.values():
        if len(regs) < 2:
            continue
        regs = sorted(regs, key=lambda r: (r.get("numero") or 0))
        nit = next((r.get("identificacion") for r in regs if r.get("identificacion")), "")
        nombres = sorted({(r.get("contribuyente") or "—").strip() for r in regs})
        consecutivos = [r["consecutivo"] for r in regs]
        if len({_clave(n) for n in nombres if n != "—"}) > 1:
            hallazgos.append(_hallazgo(
                "nit_distinto_nombre", "alta",
                f"NIT/CC {nit} con {len(nombres)} nombres distintos",
                "Mismo documento, distinto contribuyente: " + " · ".join(nombres[:6]) + (" …" if len(nombres) > 6 else ""),
                consecutivos))
        else:
            hallazgos.append(_hallazgo(
                "nit_repetido", "media",
                f"NIT/CC {nit} en {len(regs)} certificados",
                f"{nombres[0] if nombres else nit} aparece {len(regs)} veces (duplicado o varias sucursales).",
                consecutivos))
    return hallazgos


def _fechas(registros):
    hallazgos = []
    for r in registros:
        if r.get("estado") != "ok":
            continue
        acta = _fecha(r.get("fecha_acta"))
        exped = _fecha(r.get("fecha_expedicion"))
        expira = _fecha(r.get("fecha_expiracion"))
        problemas = []
        severidad = "media"
        if exped and expira and expira <= exped:
            problemas.append("la expiración no es posterior a la expedición")
            severidad = "alta"
        if acta and exped and acta > exped:
            problemas.append("el acta es posterior a la expedición")
            severidad = "alta"
        if exped and expira and expira > exped:
            dias = (expira - exped).days
            if not 300 <= dias <= 430:
                problemas.append(f"vigencia de {dias} días (lo normal es ~1 año)")
        if problemas:
            hallazgos.append(_hallazgo(
                "fechas_incoherentes", severidad,
                r.get("contribuyente") or r["consecutivo"],
                "; ".join(problemas) + f" · acta {r.get('fecha_acta') or '—'}, "
                f"exp. {r.get('fecha_expedicion') or '—'}, vence {r.get('fecha_expiracion') or '—'}",
                [r["consecutivo"]],
            ))
    return hallazgos


def _sin_consultar(registros):
    errores = [r for r in registros if r.get("estado") == "error"]
    if not errores:
        return []
    errores.sort(key=lambda r: (r.get("anio") or 0, r.get("numero") or 0))
    muestra = ", ".join(r["consecutivo"] for r in errores[:8]) + (" …" if len(errores) > 8 else "")
    return [_hallazgo(
        "sin_consultar", "media",
        f"{len(errores)} consecutivos con error de consulta",
        f"No se pudieron leer y conviene reintentar: {muestra}",
        [r["consecutivo"] for r in errores],
    )]


def detectar(registros: list[dict], cfg=None) -> dict:
    """Analiza los registros y devuelve {'hallazgos': [...], 'resumen': {tipo: n}, 'total': n}."""
    firmes = [r for r in registros if r.get("estado") in FIRMES]
    hallazgos = []
    hallazgos += _por_nit(firmes)
    hallazgos += _fechas(firmes)
    hallazgos += _sin_consultar(registros)

    hallazgos.sort(key=lambda h: (-SEVERIDADES.get(h["severidad"], 0), h["tipo"], -len(h["consecutivos"])))
    resumen: dict[str, int] = {}
    for h in hallazgos:
        resumen[h["tipo"]] = resumen.get(h["tipo"], 0) + 1
    afectados = {c for h in hallazgos for c in h["consecutivos"]}
    return {"hallazgos": hallazgos, "resumen": resumen, "total": len(hallazgos), "afectados": len(afectados)}


ETIQUETAS = {
    "nit_distinto_nombre": "NIT/CC con otro nombre",
    "nit_repetido": "NIT/CC repetido",
    "fechas_incoherentes": "Fechas incoherentes",
    "sin_consultar": "Sin consultar (error)",
}
