"""Servidor local del panel.

Seguridad:
- Escucha solo en 127.0.0.1: nadie más en la red puede entrar.
- Token aleatorio por sesión, exigido en cada llamada a /api (cabecera X-Nexus-Token):
  otras páginas abiertas en el navegador no pueden leer datos ni lanzar consultas.
- Se valida la cabecera Host (bloquea ataques de DNS rebinding) y el Origin.
- Política de seguridad de contenido (CSP) estricta: sin scripts externos ni en línea.
- Solo se sirven 3 archivos estáticos conocidos (sin recorrido de rutas).
- La URL consultada se arma siempre desde la configuración + un consecutivo validado.
"""
from __future__ import annotations

import gzip
import hmac
import json
import os
import secrets
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import __version__, anomalias, exporter
from .config import WEB_DIR, Config, parse_consecutivo
from .scanner import Escaner, Progreso, consultar_uno
from .store import Almacen, ahora

ESTATICOS = {
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/app.css": ("app.css", "text/css; charset=utf-8"),
}
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
    "font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
MAX_CUERPO = 4 * 1024 * 1024


class Aplicacion:
    def __init__(self, cfg: Config, almacen: Almacen):
        self.cfg = cfg
        self.almacen = almacen
        self.token = secrets.token_urlsafe(32)
        self.progreso = Progreso()
        self.escaner: Escaner | None = None
        self._hilo: threading.Thread | None = None
        self._lock = threading.Lock()
        self.puerto = 0
        self._parar_auto = threading.Event()

    # ---- escaneo en segundo plano ------------------------------------------------

    def escaneando(self) -> bool:
        return bool(self._hilo and self._hilo.is_alive())

    def iniciar_escaneo(self, revisar_vacios: bool = True) -> bool:
        with self._lock:
            if self.escaneando():
                return False
            self.escaner = Escaner(self.cfg, self.almacen, self.progreso)
            self._hilo = threading.Thread(
                target=self._correr, args=(self.escaner, revisar_vacios), name="nexus-escaneo", daemon=True
            )
            self.progreso.actualizar(corriendo=True, fase="Preparando", hechos=0, total=0)
            self._hilo.start()
            return True

    def _correr(self, esc: Escaner, revisar_vacios: bool) -> None:
        try:
            esc.ejecutar(revisar_vacios=revisar_vacios)
        except Exception as e:  # nunca tumbar el servidor por un fallo del escaneo
            self.progreso.actualizar(corriendo=False, fase="Error", error_fatal=str(e))

    def detener(self) -> None:
        if self.escaner:
            self.escaner.detener()

    def ciclo_automatico(self) -> None:
        minutos = self.cfg.auto_minutos
        if minutos <= 0:
            return
        while not self._parar_auto.wait(minutos * 60):
            self.iniciar_escaneo()

    # ---- datos -------------------------------------------------------------------

    def meta(self) -> dict:
        a = self.almacen
        return {
            "version": __version__,
            "url_base": self.cfg.url_base,
            "parametro": self.cfg.parametro,
            "digitos": self.cfg.digitos,
            "dias_por_vencer": self.cfg.dias_por_vencer,
            "auto_minutos": self.cfg.auto_minutos,
            "hilos": self.cfg.hilos,
            "ultima_actualizacion": a.meta("ultima_actualizacion"),
            "ultimo_escaneo": a.meta("ultimo_escaneo"),
            "ultimo": a.ultimo(),
            "total": a.total(),
            "ahora": ahora(),
            "generado": datetime.now().isoformat(timespec="seconds"),
        }


def _crear_manejador(app: Aplicacion):
    hosts_validos = set()

    class Manejador(BaseHTTPRequestHandler):
        server_version = "Nexus"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # silencioso
            pass

        # ---- utilidades ---------------------------------------------------------

        def _enviar(self, codigo: int, cuerpo: bytes, tipo: str, extra: dict | None = None, comprimir: bool = False):
            if comprimir and len(cuerpo) > 1024 and "gzip" in (self.headers.get("Accept-Encoding") or ""):
                cuerpo = gzip.compress(cuerpo, compresslevel=5)
                extra = dict(extra or {}, **{"Content-Encoding": "gzip"})
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), interest-cohort=()")
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(cuerpo)

        def _json(self, codigo: int, datos) -> None:
            cuerpo = json.dumps(datos, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._enviar(codigo, cuerpo, "application/json; charset=utf-8", comprimir=True)

        def _error(self, codigo: int, mensaje: str) -> None:
            self._json(codigo, {"error": mensaje})

        def _host_ok(self) -> bool:
            if not hosts_validos:
                hosts_validos.update({f"127.0.0.1:{app.puerto}", f"localhost:{app.puerto}"})
            return (self.headers.get("Host") or "").lower() in hosts_validos

        def _origen_ok(self) -> bool:
            origen = self.headers.get("Origin")
            if origen and urlsplit(origen).netloc.lower() not in hosts_validos:
                return False
            return (self.headers.get("Sec-Fetch-Site") or "same-origin") in ("same-origin", "none")

        def _token_ok(self) -> bool:
            return hmac.compare_digest((self.headers.get("X-Nexus-Token") or "").encode(), app.token.encode())

        def _cuerpo_json(self) -> dict:
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                raise ValueError("Se esperaba JSON")
            largo = int(self.headers.get("Content-Length") or 0)
            if largo > MAX_CUERPO:
                raise ValueError("Solicitud demasiado grande")
            datos = json.loads(self.rfile.read(largo) or b"{}")
            if not isinstance(datos, dict):
                raise ValueError("JSON inválido")
            return datos

        # ---- GET ------------------------------------------------------------------

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            if not self._host_ok():
                return self._error(421, "Host no permitido")
            url = urlsplit(self.path)
            ruta = url.path
            if ruta in ("/", "/index.html"):
                with open(os.path.join(WEB_DIR, "index.html"), encoding="utf-8") as fh:
                    html = fh.read().replace("{{TOKEN}}", app.token)
                return self._enviar(200, html.encode("utf-8"), "text/html; charset=utf-8")
            if ruta in ESTATICOS:
                nombre, tipo = ESTATICOS[ruta]
                with open(os.path.join(WEB_DIR, nombre), "rb") as fh:
                    return self._enviar(200, fh.read(), tipo, comprimir=True)
            if ruta == "/favicon.ico":
                return self._enviar(204, b"", "image/x-icon")
            if not ruta.startswith("/api/"):
                return self._error(404, "No encontrado")
            if not (self._token_ok() and self._origen_ok()):
                return self._error(403, "Acceso denegado")
            q = parse_qs(url.query)
            try:
                if ruta == "/api/certificados":
                    desde = (q.get("desde") or [None])[0]
                    items = app.almacen.listado(desde=desde)
                    return self._json(200, {"items": items, "meta": app.meta(), "parcial": bool(desde)})
                if ruta == "/api/certificado":
                    texto = (q.get("c") or [""])[0]
                    anio = (app.almacen.anios() or [app.cfg.anio_inicio])[-1]
                    numero, anio = parse_consecutivo(texto, app.cfg, anio)
                    reg = app.almacen.uno(app.cfg.consecutivo(numero, anio))
                    return self._json(200, reg) if reg else self._error(404, "Aún no consultado")
                if ruta == "/api/estado":
                    return self._json(200, {"progreso": app.progreso.a_dict(), "meta": app.meta()})
                if ruta == "/api/anomalias":
                    datos = anomalias.detectar(app.almacen.completos(), app.cfg)
                    datos["etiquetas"] = anomalias.ETIQUETAS
                    return self._json(200, datos)
            except ValueError as e:
                return self._error(400, str(e))
            return self._error(404, "No encontrado")

        # ---- POST -----------------------------------------------------------------

        def do_POST(self):
            if not self._host_ok():
                return self._error(421, "Host no permitido")
            if not (self._token_ok() and self._origen_ok()):
                return self._error(403, "Acceso denegado")
            ruta = urlsplit(self.path).path
            try:
                datos = self._cuerpo_json()
                if ruta == "/api/actualizar":
                    iniciado = app.iniciar_escaneo(revisar_vacios=bool(datos.get("revisar_vacios", True)))
                    return self._json(202 if iniciado else 409, {"iniciado": iniciado, "progreso": app.progreso.a_dict()})
                if ruta == "/api/detener":
                    app.detener()
                    return self._json(200, {"ok": True})
                if ruta == "/api/consultar":
                    reg = consultar_uno(app.cfg, app.almacen, str(datos.get("consecutivo", "")))
                    return self._json(200, reg)
                if ruta == "/api/exportar":
                    return self._exportar(datos)
            except ValueError as e:
                return self._error(400, str(e))
            except Exception as e:
                return self._error(500, f"Error interno: {e.__class__.__name__}")
            return self._error(404, "No encontrado")

        def _exportar(self, datos: dict):
            formato = datos.get("formato")
            lista = datos.get("consecutivos")
            if lista is not None:
                if not isinstance(lista, list) or len(lista) > 200000:
                    raise ValueError("Lista inválida")
                lista = [str(c)[:32] for c in lista]
            registros = app.almacen.completos(lista)
            if formato == "xlsx":
                cuerpo = exporter.xlsx_bytes(registros, app.cfg)
                tipo = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            elif formato == "csv":
                cuerpo = exporter.csv_bytes(registros, app.cfg)
                tipo = "text/csv; charset=utf-8"
            elif formato == "html":
                cuerpo = exporter.html_portable(registros, app.meta())
                tipo = "text/html; charset=utf-8"
            else:
                raise ValueError("Formato no soportado")
            nombre = exporter.nombre_archivo(formato)
            return self._enviar(200, cuerpo, tipo, {"Content-Disposition": f'attachment; filename="{nombre}"'})

    return Manejador


def servir(cfg: Config, almacen: Almacen, abrir_navegador: bool = True, escanear: bool | None = None) -> None:
    app = Aplicacion(cfg, almacen)
    servidor = None
    for puerto in range(cfg.puerto, cfg.puerto + 20):
        try:
            app.puerto = puerto
            servidor = ThreadingHTTPServer(("127.0.0.1", puerto), _crear_manejador(app))
            break
        except OSError:
            continue
    if servidor is None:
        raise SystemExit(f"No hay puertos libres entre {cfg.puerto} y {cfg.puerto + 19}")
    servidor.daemon_threads = True
    url = f"http://127.0.0.1:{app.puerto}/"
    print(f"\n  Nexus {__version__} listo en {url}")
    print("  (Solo accesible desde este computador. Ctrl+C para cerrar.)\n")
    if escanear if escanear is not None else cfg.actualizar_al_iniciar:
        app.iniciar_escaneo()
    threading.Thread(target=app.ciclo_automatico, name="nexus-auto", daemon=True).start()
    if abrir_navegador:
        import webbrowser

        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        servidor.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\n  Cerrando Nexus…")
    finally:
        app._parar_auto.set()
        app.detener()
        if app._hilo:
            app._hilo.join(timeout=10)
        servidor.server_close()
