"""Motor de escaneo.

Fase 1 · huecos:  consulta lo que falta entre el primer y el último certificado conocido
                  (consecutivos nunca consultados, con error o vacíos).
Fase 2 · nuevos:  avanza desde el último certificado conocido con una ventana deslizante
                  de consultas en paralelo y se detiene cuando encuentra `hueco_fin`
                  consecutivos seguidos sin certificado. Así detecta solo el último.

Solo se consulta lo que hace falta: lo que ya está validado no se vuelve a pedir.
"""
from __future__ import annotations

import random
import ssl
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from datetime import date, datetime

from .client import ClienteHTTP, Limitador
from .config import Config, parse_consecutivo
from .parser import analizar
from .store import FIRMES, Almacen, ahora


class _Transitorio(Exception):
    pass


class Progreso:
    """Estado del escaneo, compartido con el panel (lectura desde otros hilos)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.reiniciar()

    def reiniciar(self, **kw):
        with self._lock:
            self.corriendo = False
            self.fase = ""
            self.mensaje = ""
            self.hechos = 0
            self.total = 0
            self.ok = 0
            self.nuevos = 0
            self.vacios = 0
            self.invalidos = 0
            self.errores = 0
            self.inicio = None
            self.fin = None
            self.ultimo = None
            self.limite = 0
            self.cancelado = False
            self.error_fatal = ""
            for k, v in kw.items():
                setattr(self, k, v)

    def actualizar(self, **kw):
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def sumar(self, **kw):
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, getattr(self, k) + v)

    def a_dict(self) -> dict:
        with self._lock:
            transcurrido = 0.0
            if self.inicio:
                fin = self.fin or time.time()
                transcurrido = max(0.001, fin - self.inicio)
            velocidad = self.hechos / transcurrido if transcurrido else 0.0
            restantes = max(0, self.total - self.hechos)
            return {
                "corriendo": self.corriendo,
                "fase": self.fase,
                "mensaje": self.mensaje,
                "hechos": self.hechos,
                "total": max(self.total, self.hechos),
                "ok": self.ok,
                "nuevos": self.nuevos,
                "vacios": self.vacios,
                "invalidos": self.invalidos,
                "errores": self.errores,
                "ultimo": self.ultimo,
                "limite": self.limite,
                "cancelado": self.cancelado,
                "error_fatal": self.error_fatal,
                "segundos": round(transcurrido, 1),
                "velocidad": round(velocidad, 1),
                "eta": round(restantes / velocidad, 1) if velocidad and self.corriendo else None,
            }


class Escaner:
    def __init__(self, cfg: Config, almacen: Almacen, progreso: Progreso | None = None,
                 cancelar: threading.Event | None = None):
        self.cfg = cfg
        self.almacen = almacen
        self.progreso = progreso or Progreso()
        self.cancelar = cancelar or threading.Event()
        self.cliente: ClienteHTTP | None = None
        self.limitador: Limitador | None = None
        self._buffer: list[dict] = []
        self._ultimo_guardado = 0.0
        self._errores_seguidos = 0
        self._ultimo_error = ""
        self._detenido_por_usuario = False

    # ---- consulta individual ----------------------------------------------------

    def _consultar(self, numero: int, anio: int) -> dict | None:
        cfg = self.cfg
        consec = cfg.consecutivo(numero, anio)
        detalle = ""
        for intento in range(cfg.reintentos):
            if self.cancelar.is_set():
                return None
            try:
                with self.limitador:
                    resp = self.cliente.obtener(consec)
                if resp.estado == 404:
                    datos = {"estado": "vacio", "detalle": "HTTP 404", "campos": []}
                elif resp.estado in (403, 408, 425, 429) or resp.estado >= 500:
                    raise _Transitorio(f"HTTP {resp.estado}")
                elif resp.estado >= 400:
                    datos = {"estado": "error", "detalle": f"HTTP {resp.estado}", "campos": []}
                else:
                    datos = analizar(resp.texto, consec)
                    if datos["estado"] == "error":
                        raise _Transitorio(datos["detalle"])
                self.limitador.exito()
                return self._registro(numero, anio, datos)
            except ssl.SSLCertVerificationError as e:
                detalle = f"Certificado SSL no verificable ({e.reason or e}). Usa --sin-verificar-ssl si confías en la red."
                break
            except Exception as e:  # red, timeout, servidor saturado...
                self.limitador.fallo()
                detalle = str(e) or e.__class__.__name__
                espera = min(8.0, 0.4 * (2 ** intento)) + random.random() * 0.4
                if self.cancelar.wait(espera):
                    return None
        return self._registro(numero, anio, {"estado": "error", "detalle": detalle[:300], "campos": []})

    def _registro(self, numero: int, anio: int, datos: dict) -> dict:
        r = dict(datos)
        r.pop("titulo", None)
        r["consecutivo"] = self.cfg.consecutivo(numero, anio)
        r["numero"] = numero
        r["anio"] = anio
        r["actualizado"] = ahora()
        return r

    # ---- resultados ---------------------------------------------------------------

    def _registrar(self, rec: dict | None) -> None:
        if rec is None:
            return
        estado = rec["estado"]
        p = self.progreso
        p.sumar(hechos=1,
                ok=int(estado == "ok"), vacios=int(estado == "vacio"),
                invalidos=int(estado == "invalido"), errores=int(estado == "error"))
        if estado in FIRMES:
            p.actualizar(ultimo=rec["consecutivo"])
        if estado == "error":
            self._errores_seguidos += 1
            self._ultimo_error = rec.get("detalle") or ""
            if self._errores_seguidos >= max(40, self.cfg.hilos * 2) and not self.cancelar.is_set():
                p.actualizar(error_fatal=f"Sin conexión estable con el servidor de la Alcaldía: {self._ultimo_error}")
                self.cancelar.set()
        else:
            self._errores_seguidos = 0
        self._buffer.append(rec)
        if len(self._buffer) >= 100 or time.time() - self._ultimo_guardado > 1.0:
            self._guardar()
        p.actualizar(limite=int(self.limitador.limite) if self.limitador else 0)

    def _guardar(self) -> None:
        if self._buffer:
            nuevos = self.almacen.guardar(self._buffer)
            self.progreso.sumar(nuevos=nuevos)
            self._buffer = []
        self._ultimo_guardado = time.time()

    # ---- fases ----------------------------------------------------------------------

    def _anios(self) -> list[int]:
        cfg = self.cfg
        hoy = date.today().year
        anios = set(self.almacen.anios()) | {cfg.anio_inicio}
        if hoy >= cfg.anio_inicio:
            anios.add(hoy)
        anios |= {a for a in cfg.inicio_por_anio if a <= hoy}
        return sorted(a for a in anios if a >= cfg.anio_inicio)

    def _inicio_de(self, anio: int, conocidos: list[int]) -> int:
        if anio in self.cfg.inicio_por_anio:
            return self.cfg.inicio_por_anio[anio]
        if anio == self.cfg.anio_inicio:
            return self.cfg.inicio
        return min(conocidos)

    def _huecos(self, anio: int, revisar_vacios: bool) -> list[tuple[int, int]]:
        estados = self.almacen.estados(anio)
        firmes = [n for n, e in estados.items() if e in FIRMES]
        if not firmes:
            return []
        desde = min(self._inicio_de(anio, firmes), min(firmes))
        hasta = max(firmes)
        return [
            (n, anio) for n in range(desde, hasta + 1)
            if estados.get(n) not in FIRMES and (revisar_vacios or estados.get(n) != "vacio")
        ]

    def _lote(self, pool, pares: list[tuple[int, int]]) -> None:
        if not pares:
            return
        futuros = [pool.submit(self._consultar, n, a) for n, a in pares]
        for f in as_completed(futuros):
            self._registrar(f.result())
            if self.cancelar.is_set():
                break

    def _explorar(self, pool, anio: int, frente: int) -> int | None:
        """Avanza desde `frente` hasta encontrar `hueco_fin` consecutivos sin certificado."""
        cfg = self.cfg
        ultimo = frente - 1
        hallado = False
        siguiente = frente
        adelanto = max(cfg.hueco_fin, cfg.hilos)
        en_vuelo: dict = {}
        base = self.progreso.hechos
        while True:
            limite = ultimo + adelanto
            while not self.cancelar.is_set() and siguiente <= limite and len(en_vuelo) < cfg.hilos * 2:
                en_vuelo[pool.submit(self._consultar, siguiente, anio)] = siguiente
                siguiente += 1
            self.progreso.actualizar(total=base + (siguiente - frente) + max(0, limite - siguiente + 1))
            if not en_vuelo:
                break
            listos, _ = wait(list(en_vuelo), return_when=FIRST_COMPLETED)
            for f in listos:
                n = en_vuelo.pop(f)
                rec = f.result()
                self._registrar(rec)
                if rec and rec["estado"] in FIRMES and n > ultimo:
                    ultimo, hallado = n, True
        return ultimo if hallado else None

    def _frontera(self, pool, anio: int) -> None:
        cfg = self.cfg
        previo = self.almacen.maximo(anio)
        if previo:
            frente = previo + 1
        elif anio in cfg.inicio_por_anio:
            frente = cfg.inicio_por_anio[anio]
        elif anio == cfg.anio_inicio:
            frente = cfg.inicio
        else:  # año nuevo: la numeración normalmente continúa
            frente = (self.almacen.maximo() or cfg.inicio - 1) + 1
        ultimo = self._explorar(pool, anio, frente)
        if ultimo is None and not previo and anio not in cfg.inicio_por_anio and anio != cfg.anio_inicio:
            ultimo = self._explorar(pool, anio, 1)  # ¿la numeración se reinició este año?
        self._guardar()
        if not self.cancelar.is_set():
            self.almacen.limpiar_cola(anio, ultimo or previo or 0)

    # ---- API -----------------------------------------------------------------------

    def ejecutar(self, revisar_vacios: bool = True) -> dict:
        cfg = self.cfg
        p = self.progreso
        p.reiniciar(corriendo=True, inicio=time.time(), fase="Preparando", limite=cfg.hilos)
        inicio_iso = ahora()
        self.almacen.set_meta("escaneo_en_curso", inicio_iso)
        self.cliente = ClienteHTTP(cfg)
        self.limitador = Limitador(cfg.hilos)
        pool = ThreadPoolExecutor(max_workers=cfg.hilos, thread_name_prefix="nexus")
        try:
            anios = self._anios()
            pendientes = []
            for a in anios:
                pendientes += self._huecos(a, revisar_vacios)
            if pendientes:
                p.actualizar(fase=f"Completando {len(pendientes):,} consecutivos pendientes".replace(",", "."),
                             total=len(pendientes))
                self._lote(pool, pendientes)
                self._guardar()
            for a in anios:
                if self.cancelar.is_set():
                    break
                p.actualizar(fase=f"Buscando certificados nuevos ({a})")
                self._frontera(pool, a)
        finally:
            self.cancelar.set()  # detiene cualquier consulta que quede en cola
            pool.shutdown(wait=True)
            self._guardar()
            self.cliente.cerrar()
            p.actualizar(corriendo=False, fin=time.time())

        if p.hechos and p.errores == p.hechos and not p.error_fatal:
            p.actualizar(error_fatal=f"No se pudo conectar con el servidor de la Alcaldía: {self._ultimo_error}")
        estado = p.a_dict()
        cancelado_por_usuario = self._detenido_por_usuario and not estado["error_fatal"]
        resumen = {
            "inicio": inicio_iso,
            "fin": ahora(),
            "segundos": estado["segundos"],
            "consultados": estado["hechos"],
            "nuevos": estado["nuevos"],
            "errores": estado["errores"],
            "ultimo": self.almacen.ultimo(),
            "completo": not cancelado_por_usuario and not estado["error_fatal"],
            "error_fatal": estado["error_fatal"],
        }
        self.almacen.set_meta("ultimo_escaneo", resumen)
        self.almacen.set_meta("escaneo_en_curso", None)
        if resumen["completo"]:
            self.almacen.set_meta("ultima_actualizacion", resumen["fin"])
        msg = "Detenido" if cancelado_por_usuario else ("Error de conexión" if estado["error_fatal"] else "Actualizado")
        p.actualizar(fase=msg, cancelado=cancelado_por_usuario)
        return resumen

    def detener(self) -> None:
        self._detenido_por_usuario = True
        self.cancelar.set()


def consultar_uno(cfg: Config, almacen: Almacen, texto: str, cliente: ClienteHTTP | None = None) -> dict:
    """Consulta en vivo un solo consecutivo y lo guarda."""
    anio_defecto = (almacen.anios() or [cfg.anio_inicio])[-1]
    numero, anio = parse_consecutivo(texto, cfg, anio_defecto)
    propio = cliente is None
    esc = Escaner(cfg, almacen)
    esc.cliente = cliente or ClienteHTTP(cfg)
    esc.limitador = Limitador(1, 1)
    try:
        rec = esc._consultar(numero, anio)
    finally:
        if propio:
            esc.cliente.cerrar()
    almacen.guardar([rec])
    guardado = almacen.uno(rec["consecutivo"]) or rec
    guardado["consulta"] = {"estado": rec["estado"], "detalle": rec.get("detalle", ""), "momento": datetime.now().isoformat(timespec="seconds")}
    return guardado
