"""Almacenamiento local en SQLite (data/nexus.db).

Reglas de guardado:
- Un resultado con error de red nunca borra un certificado que ya estaba validado.
- `primera_vez` se conserva para saber qué certificados son nuevos.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime

from .parser import CAMPOS

COLUMNAS = [
    "consecutivo", "numero", "anio", "estado", "contribuyente", "identificacion", "direccion",
    "ref_catastral", "fecha_acta", "fecha_expedicion", "fecha_expiracion", "estado_pagina",
    "actividad", "detalle", "campos", "origen", "primera_vez", "actualizado",
]
LISTADO = [c for c in COLUMNAS if c != "campos"]
FIRMES = ("ok", "invalido")


def ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Almacen:
    def __init__(self, ruta: str):
        os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
        self.ruta = ruta
        self._lock = threading.RLock()
        self.db = sqlite3.connect(ruta, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        with self._lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=NORMAL")
            self.db.execute(
                """CREATE TABLE IF NOT EXISTS certificados(
                    consecutivo TEXT PRIMARY KEY,
                    numero INTEGER NOT NULL,
                    anio INTEGER NOT NULL,
                    estado TEXT NOT NULL,
                    contribuyente TEXT, identificacion TEXT, direccion TEXT, ref_catastral TEXT,
                    fecha_acta TEXT, fecha_expedicion TEXT, fecha_expiracion TEXT,
                    estado_pagina TEXT, actividad TEXT, detalle TEXT, campos TEXT,
                    origen TEXT, primera_vez TEXT, actualizado TEXT)"""
            )
            self.db.execute("CREATE INDEX IF NOT EXISTS ix_anio_num ON certificados(anio, numero)")
            self.db.execute("CREATE TABLE IF NOT EXISTS meta(clave TEXT PRIMARY KEY, valor TEXT)")
        try:
            os.chmod(ruta, 0o600)
        except OSError:
            pass

    def cerrar(self) -> None:
        with self._lock:
            self.db.close()

    # ---- escritura ------------------------------------------------------------

    def guardar(self, registros: list[dict], origen: str = "consulta") -> int:
        """Guarda una tanda en una sola transacción. Devuelve cuántos son nuevos (validados por 1ª vez)."""
        if not registros:
            return 0
        nuevos = 0
        momento = ahora()
        with self._lock:
            cur = self.db.cursor()
            cur.execute("BEGIN")
            try:
                for r in registros:
                    previo = cur.execute(
                        "SELECT estado, primera_vez FROM certificados WHERE consecutivo=?", (r["consecutivo"],)
                    ).fetchone()
                    if previo and previo["estado"] in FIRMES and r["estado"] not in FIRMES:
                        continue  # no perder un certificado bueno por un fallo pasajero
                    primera = previo["primera_vez"] if previo and previo["primera_vez"] else None
                    if r["estado"] in FIRMES and not primera:
                        primera = r.get("primera_vez") or momento
                        if origen != "importado":
                            nuevos += 1
                    fila = {c: r.get(c) for c in COLUMNAS}
                    fila["campos"] = json.dumps(r.get("campos") or [], ensure_ascii=False)
                    fila["origen"] = r.get("origen") or origen
                    fila["primera_vez"] = primera
                    fila["actualizado"] = r.get("actualizado") or momento
                    cur.execute(
                        f"INSERT OR REPLACE INTO certificados({','.join(COLUMNAS)}) "
                        f"VALUES({','.join('?' * len(COLUMNAS))})",
                        [fila[c] for c in COLUMNAS],
                    )
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise
        return nuevos

    def limpiar_cola(self, anio: int, ultimo: int) -> None:
        """Borra vacíos/errores por encima del último certificado real (son consultas 'a futuro')."""
        with self._lock:
            self.db.execute(
                "DELETE FROM certificados WHERE anio=? AND numero>? AND estado NOT IN ('ok','invalido')",
                (anio, ultimo),
            )

    def set_meta(self, clave: str, valor) -> None:
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO meta(clave, valor) VALUES(?, ?)", (clave, json.dumps(valor, ensure_ascii=False))
            )

    # ---- lectura --------------------------------------------------------------

    def meta(self, clave: str, defecto=None):
        with self._lock:
            fila = self.db.execute("SELECT valor FROM meta WHERE clave=?", (clave,)).fetchone()
        return json.loads(fila["valor"]) if fila else defecto

    def total(self) -> int:
        with self._lock:
            return self.db.execute("SELECT COUNT(*) FROM certificados").fetchone()[0]

    def listado(self, desde: str | None = None) -> list[dict]:
        """Todos los registros (sin `campos`); con `desde`, solo los cambiados desde ese momento."""
        sql = f"SELECT {','.join(LISTADO)} FROM certificados"
        args: tuple = ()
        if desde:
            sql += " WHERE actualizado >= ?"
            args = (str(desde)[:19],)
        with self._lock:
            filas = self.db.execute(sql + " ORDER BY anio, numero", args).fetchall()
        return [dict(f) for f in filas]

    def uno(self, consecutivo: str) -> dict | None:
        with self._lock:
            fila = self.db.execute("SELECT * FROM certificados WHERE consecutivo=?", (consecutivo,)).fetchone()
        if not fila:
            return None
        d = dict(fila)
        d["campos"] = json.loads(d["campos"] or "[]")
        return d

    def completos(self, consecutivos: list[str] | None = None) -> list[dict]:
        with self._lock:
            if consecutivos is None:
                filas = self.db.execute("SELECT * FROM certificados ORDER BY anio, numero").fetchall()
            else:
                filas = []
                for i in range(0, len(consecutivos), 500):
                    lote = consecutivos[i:i + 500]
                    filas += self.db.execute(
                        f"SELECT * FROM certificados WHERE consecutivo IN ({','.join('?' * len(lote))})", lote
                    ).fetchall()
                orden = {c: i for i, c in enumerate(consecutivos)}
                filas.sort(key=lambda f: orden.get(f["consecutivo"], 0))
        salida = []
        for f in filas:
            d = dict(f)
            d["campos"] = json.loads(d["campos"] or "[]")
            salida.append(d)
        return salida

    def estados(self, anio: int) -> dict[int, str]:
        with self._lock:
            filas = self.db.execute("SELECT numero, estado FROM certificados WHERE anio=?", (anio,)).fetchall()
        return {f["numero"]: f["estado"] for f in filas}

    def anios(self) -> list[int]:
        with self._lock:
            filas = self.db.execute("SELECT DISTINCT anio FROM certificados WHERE estado IN ('ok','invalido')").fetchall()
        return sorted(f[0] for f in filas)

    def maximo(self, anio: int | None = None) -> int | None:
        with self._lock:
            if anio is None:
                fila = self.db.execute("SELECT MAX(numero) FROM certificados WHERE estado IN ('ok','invalido')").fetchone()
            else:
                fila = self.db.execute(
                    "SELECT MAX(numero) FROM certificados WHERE anio=? AND estado IN ('ok','invalido')", (anio,)
                ).fetchone()
        return fila[0]

    def ultimo(self) -> dict | None:
        with self._lock:
            fila = self.db.execute(
                "SELECT consecutivo, contribuyente, fecha_expedicion FROM certificados "
                "WHERE estado IN ('ok','invalido') ORDER BY anio DESC, numero DESC LIMIT 1"
            ).fetchone()
        return dict(fila) if fila else None


assert set(c for c in CAMPOS) <= set(COLUMNAS), "columnas y campos del lector deben coincidir"
