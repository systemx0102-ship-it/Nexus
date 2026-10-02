"""Cliente HTTP rápido: una conexión persistente (keep-alive) por hilo + control de ritmo.

- Reutilizar la conexión evita repetir el saludo TLS en cada consulta: es lo que más
  acelera cuando se consultan miles de consecutivos.
- `Limitador` sube la cantidad de consultas simultáneas mientras el servidor responde
  bien y la baja a la mitad cuando empieza a fallar (AIMD), así va al máximo posible
  sin tumbar ni saturar el servidor de la Alcaldía.
"""
from __future__ import annotations

import gzip
import http.client
import re
import ssl
import threading
import zlib
from urllib.parse import urlsplit

from .config import Config

ERRORES_CONEXION = (
    http.client.RemoteDisconnected,
    http.client.CannotSendRequest,
    http.client.ResponseNotReady,
    http.client.BadStatusLine,
    http.client.IncompleteRead,
    ConnectionError,
    BrokenPipeError,
)


class Respuesta:
    __slots__ = ("estado", "texto")

    def __init__(self, estado: int, texto: str):
        self.estado = estado
        self.texto = texto


class Limitador:
    """Semáforo adaptativo (AIMD)."""

    def __init__(self, maximo: int, minimo: int = 2):
        self.maximo = max(1, maximo)
        self.minimo = max(1, min(minimo, self.maximo))
        self.limite = float(self.maximo)
        self.activos = 0
        self._racha = 0
        self._cv = threading.Condition()

    def __enter__(self):
        with self._cv:
            while self.activos >= int(self.limite):
                self._cv.wait()
            self.activos += 1
        return self

    def __exit__(self, *exc):
        with self._cv:
            self.activos -= 1
            self._cv.notify()

    def exito(self) -> None:
        with self._cv:
            self._racha += 1
            if self.limite < self.maximo and self._racha >= int(self.limite):
                self.limite += 1
                self._racha = 0
                self._cv.notify()

    def fallo(self) -> None:
        with self._cv:
            self._racha = 0
            self.limite = max(float(self.minimo), self.limite / 2)


class ClienteHTTP:
    def __init__(self, cfg: Config):
        partes = urlsplit(cfg.url_base)
        self.https = partes.scheme == "https"
        self.host = partes.hostname or ""
        self.puerto = partes.port or (443 if self.https else 80)
        self.ruta = partes.path or "/"
        self.cfg = cfg
        if self.https:
            if cfg.verificar_ssl:
                self.ctx = ssl.create_default_context()
            else:  # solo si el usuario lo pide explícitamente con --sin-verificar-ssl
                self.ctx = ssl._create_unverified_context()  # noqa: S323
        else:
            self.ctx = None
        self._local = threading.local()
        self._todas: list = []
        self._lock = threading.Lock()

    # ---- conexiones ---------------------------------------------------------

    def _conexion(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            if self.https:
                c = http.client.HTTPSConnection(self.host, self.puerto, timeout=self.cfg.timeout, context=self.ctx)
            else:
                c = http.client.HTTPConnection(self.host, self.puerto, timeout=self.cfg.timeout)
            self._local.conn = c
            self._local.cookies = {}
            with self._lock:
                self._todas.append(c)
        return c

    def _descartar(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            try:
                c.close()
            except Exception:
                pass
        self._local.conn = None

    def cerrar(self) -> None:
        with self._lock:
            for c in self._todas:
                try:
                    c.close()
                except Exception:
                    pass
            self._todas.clear()

    # ---- petición -----------------------------------------------------------

    def obtener(self, consecutivo: str) -> Respuesta:
        ruta = f"{self.ruta}?{self.cfg.parametro}={consecutivo}"
        for intento in range(2):  # 2º intento solo si la conexión keep-alive estaba muerta
            conn = self._conexion()
            cabeceras = {
                "User-Agent": self.cfg.user_agent,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "es-CO,es;q=0.9",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
            }
            cookies = getattr(self._local, "cookies", {})
            if cookies:
                cabeceras["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
            try:
                conn.request("GET", ruta, headers=cabeceras)
                resp = conn.getresponse()
                cuerpo = resp.read()
            except ERRORES_CONEXION:
                self._descartar()
                if intento == 0:
                    continue
                raise
            except Exception:
                self._descartar()
                raise
            self._guardar_cookies(resp)
            if resp.will_close:
                self._descartar()
            return Respuesta(resp.status, _decodificar(cuerpo, resp))
        raise ConnectionError("sin respuesta")

    def _guardar_cookies(self, resp) -> None:
        for linea in resp.headers.get_all("Set-Cookie") or []:
            par = linea.split(";", 1)[0]
            if "=" in par:
                k, v = par.split("=", 1)
                if re.match(r"^[\w.\-]+$", k.strip()):
                    self._local.cookies[k.strip()] = v.strip()


_RE_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([\w\-]+)""", re.I)


def _decodificar(cuerpo: bytes, resp) -> str:
    enc = (resp.getheader("Content-Encoding") or "").lower()
    try:
        if "gzip" in enc:
            cuerpo = gzip.decompress(cuerpo)
        elif "deflate" in enc:
            try:
                cuerpo = zlib.decompress(cuerpo)
            except zlib.error:
                cuerpo = zlib.decompress(cuerpo, -zlib.MAX_WBITS)
    except (OSError, zlib.error):
        pass
    charset = None
    tipo = resp.getheader("Content-Type") or ""
    m = re.search(r"charset=([\w\-]+)", tipo, re.I)
    if m:
        charset = m.group(1)
    else:
        m = _RE_META_CHARSET.search(cuerpo[:4096])
        if m:
            charset = m.group(1).decode("ascii", "ignore")
    for cs in (charset, "utf-8", "cp1252"):
        if not cs:
            continue
        try:
            return cuerpo.decode(cs)
        except (LookupError, UnicodeDecodeError):
            continue
    return cuerpo.decode("latin-1", "replace")
