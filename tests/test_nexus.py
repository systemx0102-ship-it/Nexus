"""Pruebas de Nexus (solo librería estándar):  python -m unittest discover -s tests -v"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from xml.dom import minidom

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from nexus import exporter, legacy  # noqa: E402
from nexus.config import Config, parse_consecutivo  # noqa: E402
from nexus.parser import analizar, fecha_iso  # noqa: E402
from nexus import anomalias  # noqa: E402
from nexus.scanner import Escaner, consultar_uno  # noqa: E402
from nexus.store import Almacen  # noqa: E402

# ---------------------------------------------------------------- páginas de ejemplo

def pagina_tabla(c, nombre="VENTA DE FRIAS DONDE ANA", estado=None):
    extra = f"<tr><td>Estado:</td><td>{estado}</td></tr>" if estado else ""
    return f"""<html><head><title>Verificaci&oacute;n de Certificado</title>
    <script>var x = "Contribuyente: NO DEBE LEERSE";</script></head><body>
    <table width="600" border="0"><tr><td colspan="2" class="titulo">CERTIFICADO DE SEGURIDAD BOMBERIL</td></tr>
    <tr><td class="lbl"><b>Consecutivo:</b></td><td>{c}</td></tr>
    <tr><td class="lbl">Contribuyente:</td><td>{nombre}</td></tr>
    <tr><td class="lbl">Identificaci&oacute;n:</td><td>326614771</td></tr>
    <tr><td class="lbl">Direcci&oacute;n:</td><td>CARRERA 3 B 51 C 02</td></tr>
    <tr><td class="lbl">Referencia Catastral:</td><td>0107000003590012000000000</td></tr>
    <tr><td class="lbl">Fecha Acta:</td><td>23/09/2024</td></tr>
    <tr><td class="lbl">Fecha Expedici&oacute;n:</td><td>07/01/2026</td></tr>
    <tr><td class="lbl">Fecha Expiraci&oacute;n:</td><td>07/01/2027</td></tr>{extra}
    <tr><td colspan="2">Este certificado no es v&aacute;lido sin la firma del comandante.</td></tr>
    </table></body></html>"""


def pagina_en_linea(c):
    return f"""<div class="cert"><p><strong>N° Certificado:</strong> {c}</p>
    <p><strong>Razón Social:</strong> COMBUSTIBLES Y SERVICIOS LTDA.</p>
    <p><strong>NIT:</strong> 800158532</p><p><strong>Dirección:</strong> CARRERA 38 54 25</p>
    <p><span>Fecha de vencimiento: 07 de enero de 2027</span></p>
    <p><span>Fecha de expedición:</span><span>2026-01-07</span></p></div>"""


def pagina_encabezados(c):
    return f"""<table><tr><th>Consecutivo</th><th>Contribuyente</th><th>Identificación</th><th>Dirección</th>
    <th>Fecha Expedición</th><th>Fecha Expiración</th></tr>
    <tr><td>{c}</td><td>HACEMOS BUENOS MOMENTOS SAS</td><td>901776348</td><td>CARRERA 31 110 42</td>
    <td>16/01/2026</td><td>16/01/2027</td></tr></table>"""


def pagina_inputs(c):
    return f"""<form><label>Contribuyente</label><input type="text" readonly value="ESTACION LA 30">
    <label>Identificación</label><input type="text" readonly value="900123456">
    <input type="hidden" name="csctvo" value="{c}">
    <label>Dirección</label><input type="text" readonly value="CALLE 30 # 12-40">
    <label>Fecha Expiración</label><input type="text" readonly value="31/12/2026"></form>"""


PAGINA_VACIA = "<html><body><h3>No se encontró información para el consecutivo ingresado.</h3></body></html>"
PAGINA_ERROR = "<html><body><h1>HTTP Status 500</h1><pre>java.lang.NullPointerException at servlet</pre></body></html>"


class PruebasLector(unittest.TestCase):
    def test_tabla_etiqueta_valor(self):
        d = analizar(pagina_tabla("00000060624-2026"), "00000060624-2026")
        self.assertEqual(d["estado"], "ok")
        self.assertEqual(d["contribuyente"], "VENTA DE FRIAS DONDE ANA")
        self.assertEqual(d["identificacion"], "326614771")
        self.assertEqual(d["direccion"], "CARRERA 3 B 51 C 02")
        self.assertEqual(d["ref_catastral"], "0107000003590012000000000")
        self.assertEqual(d["fecha_acta"], "2024-09-23")
        self.assertEqual(d["fecha_expedicion"], "2026-01-07")
        self.assertEqual(d["fecha_expiracion"], "2027-01-07")
        self.assertNotIn("NO DEBE LEERSE", json.dumps(d))
        self.assertGreaterEqual(len(d["campos"]), 8)

    def test_texto_en_linea(self):
        d = analizar(pagina_en_linea("00000060625-2026"), "00000060625-2026")
        self.assertEqual(d["estado"], "ok")
        self.assertEqual(d["contribuyente"], "COMBUSTIBLES Y SERVICIOS LTDA.")
        self.assertEqual(d["identificacion"], "800158532")
        self.assertEqual(d["fecha_expiracion"], "2027-01-07")
        self.assertEqual(d["fecha_expedicion"], "2026-01-07")
        self.assertEqual(d["consecutivo"], "00000060625-2026")

    def test_tabla_con_encabezados(self):
        d = analizar(pagina_encabezados("00000060626-2026"), "00000060626-2026")
        self.assertEqual(d["estado"], "ok")
        self.assertEqual(d["contribuyente"], "HACEMOS BUENOS MOMENTOS SAS")
        self.assertEqual(d["direccion"], "CARRERA 31 110 42")
        self.assertEqual(d["fecha_expiracion"], "2027-01-16")

    def test_campos_input(self):
        d = analizar(pagina_inputs("00000060627-2026"), "00000060627-2026")
        self.assertEqual(d["estado"], "ok")
        self.assertEqual(d["contribuyente"], "ESTACION LA 30")
        self.assertEqual(d["fecha_expiracion"], "2026-12-31")

    def test_valor_partido_en_varias_etiquetas(self):
        html = """<table><tr><td>Contribuyente:</td><td><span>VENTA DE</span> <font>FRIAS</font></td></tr>
        <tr><td>Direcci&oacute;n:</td><td><span>CARRERA 3 B</span><span>51 C 02</span></td></tr></table>"""
        d = analizar(html, "x")
        self.assertEqual(d["contribuyente"], "VENTA DE FRIAS")
        self.assertEqual(d["direccion"], "CARRERA 3 B51 C 02")

    def test_vacio_error_anulado_y_otro_consecutivo(self):
        self.assertEqual(analizar(PAGINA_VACIA, "x")["estado"], "vacio")
        self.assertEqual(analizar("", "x")["estado"], "vacio")
        self.assertEqual(analizar(PAGINA_ERROR, "x")["estado"], "error")
        self.assertEqual(analizar(pagina_tabla("00000060624-2026", estado="ANULADO"), "00000060624-2026")["estado"], "invalido")
        self.assertEqual(analizar(pagina_tabla("00000060999-2026"), "00000060624-2026")["estado"], "invalido")

    def test_fechas(self):
        self.assertEqual(fecha_iso("07/01/2026"), "2026-01-07")
        self.assertEqual(fecha_iso("2026-01-07 10:22"), "2026-01-07")
        self.assertEqual(fecha_iso("7 de enero de 2026"), "2026-01-07")
        self.assertIsNone(fecha_iso("sin fecha"))

    def test_consecutivo(self):
        cfg = Config()
        self.assertEqual(parse_consecutivo("62667", cfg, 2026), (62667, 2026))
        self.assertEqual(parse_consecutivo(" 00000062667-2027 ", cfg, 2026), (62667, 2027))
        for malo in ("", "abc", "62667-26", "1;DROP", "../../etc", "62667-2026&x=1", "http://x"):
            with self.assertRaises(ValueError):
                parse_consecutivo(malo, cfg, 2026)


# ---------------------------------------------------------------- servidor simulado

class Simulado:
    """Imita verfCert.do: certificados en `existentes`, 503 aleatorios la primera vez."""

    def __init__(self, existentes, fallar=()):
        self.existentes = set(existentes)
        self.fallar = set(fallar)
        self.pedidos = []
        self.lock = threading.Lock()
        sim = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                c = parse_qs(urlsplit(self.path).query).get("csctvo", [""])[0]
                with sim.lock:
                    sim.pedidos.append(c)
                    fallo = c in sim.fallar
                    sim.fallar.discard(c)
                if fallo:
                    cuerpo, codigo = b"Service Unavailable", 503
                else:
                    n = int(c.split("-")[0])
                    anio = int(c.split("-")[1])
                    html = pagina_tabla(c, escape(f"EMPRESA {n} <script>alert(1)</script>")) if (n, anio) in sim.existentes else PAGINA_VACIA
                    cuerpo, codigo = html.encode("utf-8"), 200
                self.send_response(codigo)
                self.send_header("Content-Type", "text/html; charset=UTF-8")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/Bomberos/verfCert.do"

    def cerrar(self):
        self.srv.shutdown()
        self.srv.server_close()


class PruebasEscaner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.alm = Almacen(os.path.join(self.tmp, "t.db"))

    def tearDown(self):
        self.alm.cerrar()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cfg(self, url, **kw):
        cfg = Config(url_base=url, inicio=1000, anio_inicio=2026, hilos=12, hueco_fin=10, timeout=5, reintentos=4)
        for k, v in kw.items():
            setattr(cfg, k, v)
        cfg.validar()
        return cfg

    def test_escaneo_completo_incremental_y_huecos(self):
        existentes = {(n, 2026) for n in range(1000, 1061) if n not in (1020, 1021)}
        sim = Simulado(existentes, fallar={f"{n:011d}-2026" for n in (1005, 1030, 1050)})
        try:
            cfg = self.cfg(sim.url)
            r = Escaner(cfg, self.alm).ejecutar()
            self.assertTrue(r["completo"], r)
            self.assertEqual(r["nuevos"], 59)
            self.assertEqual(r["ultimo"]["consecutivo"], "00000001060-2026")
            estados = self.alm.estados(2026)
            self.assertEqual(estados[1020], "vacio")
            self.assertTrue(all(estados[n] == "ok" for n in (1005, 1030, 1050)))
            self.assertFalse(any(n > 1060 for n in estados), "no deben quedar vacíos después del último")
            reg = self.alm.uno("00000001010-2026")
            self.assertEqual(reg["contribuyente"], "EMPRESA 1010 <script>alert(1)</script>")  # se guarda como texto

            # 2ª pasada: aparecen 5 nuevos; solo deben consultarse huecos + frontera
            sim.existentes |= {(n, 2026) for n in range(1061, 1066)}
            sim.pedidos.clear()
            r2 = Escaner(cfg, self.alm).ejecutar()
            self.assertEqual(r2["nuevos"], 5)
            self.assertEqual(r2["ultimo"]["consecutivo"], "00000001065-2026")
            self.assertNotIn("00000001010-2026", sim.pedidos, "no se re-consultan los ya validados")
            self.assertLess(len(sim.pedidos), 60)
        finally:
            sim.cerrar()

    def test_anio_nuevo_continua_numeracion(self):
        existentes = {(n, 2026) for n in range(1000, 1010)}
        sim = Simulado(existentes)
        try:
            cfg = self.cfg(sim.url)
            Escaner(cfg, self.alm).ejecutar()
            sim.existentes |= {(n, 2027) for n in range(1010, 1015)}
            cfg.inicio_por_anio = {}
            esc = Escaner(cfg, self.alm)
            esc._anios = lambda: [2026, 2027]  # simula estar en 2027
            r = esc.ejecutar()
            self.assertEqual(r["nuevos"], 5)
            self.assertEqual(self.alm.ultimo()["consecutivo"], "00000001014-2027")
        finally:
            sim.cerrar()

    def test_sin_conexion_aborta_rapido(self):
        cfg = self.cfg("http://127.0.0.1:9/Bomberos/verfCert.do", reintentos=1, hilos=4)
        r = Escaner(cfg, self.alm).ejecutar()
        self.assertFalse(r["completo"])
        self.assertTrue(r["error_fatal"])

    def test_consulta_en_vivo(self):
        sim = Simulado({(1234, 2026)})
        try:
            cfg = self.cfg(sim.url)
            reg = consultar_uno(cfg, self.alm, "1234-2026")
            self.assertEqual(reg["estado"], "ok")
            self.assertEqual(reg["consecutivo"], "00000001234-2026")
            with self.assertRaises(ValueError):
                consultar_uno(cfg, self.alm, "1234&csctvo=1")
        finally:
            sim.cerrar()


# ---------------------------------------------------------------- servidor del panel

class PruebasServidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from nexus import server

        cls.tmp = tempfile.mkdtemp()
        cls.alm = Almacen(os.path.join(cls.tmp, "s.db"))
        cls.alm.guardar([{
            "consecutivo": "00000060624-2026", "numero": 60624, "anio": 2026, "estado": "ok",
            "contribuyente": "<img src=x onerror=alert(1)>", "fecha_expiracion": "2027-01-07",
            "campos": [["Contribuyente", "<img src=x onerror=alert(1)>"]],
        }])
        cfg = Config(url_base="http://127.0.0.1:9/x.do", actualizar_al_iniciar=False, auto_minutos=0)
        cls.app = server.Aplicacion(cfg, cls.alm)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), server._crear_manejador(cls.app))
        cls.app.puerto = srv.server_address[1]
        cls.srv = srv
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.app.puerto}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.alm.cerrar()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def pedir(self, ruta, metodo="GET", cuerpo=None, cabeceras=None, token=True):
        h = dict(cabeceras or {})
        if token:
            h["X-Nexus-Token"] = self.app.token
        datos = None
        if cuerpo is not None:
            datos = json.dumps(cuerpo).encode()
            h.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(self.base + ruta, data=datos, method=metodo, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def test_indice_y_cabeceras(self):
        st, cab, cuerpo = self.pedir("/", token=False)
        self.assertEqual(st, 200)
        self.assertIn(self.app.token.encode(), cuerpo)
        self.assertIn("script-src 'self'", cab["Content-Security-Policy"])
        self.assertEqual(cab["X-Frame-Options"], "DENY")
        self.assertEqual(cab["X-Content-Type-Options"], "nosniff")

    def test_api_exige_token(self):
        self.assertEqual(self.pedir("/api/certificados", token=False)[0], 403)
        self.assertEqual(self.pedir("/api/actualizar", "POST", {}, token=False)[0], 403)
        st, _, cuerpo = self.pedir("/api/certificados")
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(cuerpo)["items"][0]["contribuyente"], "<img src=x onerror=alert(1)>")

    def test_host_y_origen(self):
        self.assertEqual(self.pedir("/", cabeceras={"Host": "evil.example:80"}, token=False)[0], 421)
        self.assertEqual(self.pedir("/api/certificados", cabeceras={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.pedir("/api/certificados", cabeceras={"Sec-Fetch-Site": "cross-site"})[0], 403)

    def test_post_exige_json_y_sin_rutas_raras(self):
        st, _, _ = self.pedir("/api/consultar", "POST", None, cabeceras={"Content-Type": "text/plain"})
        self.assertEqual(st, 400)
        self.assertEqual(self.pedir("/static/../nexus/config.py", token=False)[0], 404)
        self.assertEqual(self.pedir("/api/consultar", "POST", {"consecutivo": "1;rm -rf"})[0], 400)

    def test_exportar(self):
        st, cab, cuerpo = self.pedir("/api/exportar", "POST", {"formato": "xlsx", "consecutivos": None})
        self.assertEqual(st, 200)
        self.assertIn("attachment", cab["Content-Disposition"])
        z = zipfile.ZipFile(io.BytesIO(cuerpo))
        for nombre in z.namelist():
            if nombre.endswith(".xml") or nombre.endswith(".rels"):
                minidom.parseString(z.read(nombre))  # XML bien formado
        st, _, html = self.pedir("/api/exportar", "POST", {"formato": "html"})
        self.assertEqual(st, 200)
        self.assertNotIn(b"<img src=x", html)  # datos embebidos escapados
        self.assertIn(b"Content-Security-Policy", html)

    def test_anomalias_endpoint(self):
        st, _, cuerpo = self.pedir("/api/anomalias")
        self.assertEqual(st, 200)
        datos = json.loads(cuerpo)
        self.assertIn("hallazgos", datos)
        self.assertIn("resumen", datos)
        self.assertIn("etiquetas", datos)
        self.assertEqual(self.pedir("/api/anomalias", token=False)[0], 403)


class PruebasExportarImportar(unittest.TestCase):
    def test_csv_sin_formulas(self):
        cfg = Config()
        datos = exporter.csv_bytes([{"consecutivo": "1-2026", "contribuyente": "=HYPERLINK(\"http://x\")", "estado": "ok"}], cfg)
        self.assertIn("'=HYPERLINK", datos.decode("utf-8-sig"))

    def test_importar_sistema_anterior(self):
        ruta = os.path.join(RAIZ, "Proyect.html")
        if not os.path.exists(ruta):
            self.skipTest("Proyect.html no está")
        regs = legacy.leer(ruta)
        self.assertEqual(len(regs), 1894)
        self.assertEqual(regs[0]["consecutivo"], "00000060624-2026")
        self.assertEqual(regs[0]["contribuyente"], "VENTA DE FRIAS DONDE ANA")
        self.assertEqual(regs[0]["fecha_expiracion"], "2027-01-07")



class PruebasAnomalias(unittest.TestCase):
    def regs(self):
        base = lambda n, **k: dict(
            {"consecutivo": f"{n:011d}-2026", "numero": n, "anio": 2026, "estado": "ok",
             "contribuyente": f"EMPRESA {n}", "identificacion": str(900000000 + n),
             "direccion": f"CALLE {n}", "ref_catastral": f"REF{n}",
             "fecha_acta": "2025-12-01", "fecha_expedicion": "2026-01-07", "fecha_expiracion": "2027-01-07"}, **k)
        return [
            base(1),
            base(2, identificacion="900000001", contribuyente="OTRA EMPRESA"),      # mismo NIT que #1, otro nombre
            base(3, identificacion="900000010", contribuyente="EMPRESA 10"),        # NIT repetido (mismo nombre/NIT que #10)
            base(4, fecha_expedicion="2026-05-01", fecha_expiracion="2026-01-07"),  # expira antes de expedir
            base(5, fecha_expiracion="2026-02-01"),                                 # vigencia corta (~25 días)
            base(6, estado="error", contribuyente=None),                            # sin consultar
            base(10, identificacion="900000010", contribuyente="EMPRESA 10"),       # par del #3
        ]

    def test_detecta_tipos(self):
        r = anomalias.detectar(self.regs())
        tipos = r["resumen"]
        self.assertEqual(tipos.get("nit_distinto_nombre"), 1)
        self.assertEqual(tipos.get("nit_repetido"), 1)
        self.assertEqual(tipos.get("fechas_incoherentes"), 2)
        self.assertEqual(tipos.get("sin_consultar"), 1)
        # Mismo NIT con nombres distintos: ambos consecutivos y severidad alta
        nit = next(h for h in r["hallazgos"] if h["tipo"] == "nit_distinto_nombre")
        self.assertEqual(set(nit["consecutivos"]), {"00000000001-2026", "00000000002-2026"})
        self.assertEqual(nit["severidad"], "alta")
        rep = next(h for h in r["hallazgos"] if h["tipo"] == "nit_repetido")
        self.assertEqual(set(rep["consecutivos"]), {"00000000003-2026", "00000000010-2026"})

    def test_sin_anomalias(self):
        limpio = [dict(consecutivo="00000000009-2026", numero=9, anio=2026, estado="ok",
                       contribuyente="UNICA", identificacion="123", direccion="CALLE 9", ref_catastral="R9",
                       fecha_acta="2025-12-01", fecha_expedicion="2026-01-07", fecha_expiracion="2027-01-07")]
        r = anomalias.detectar(limpio)
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["afectados"], 0)


if __name__ == "__main__":
    unittest.main()
