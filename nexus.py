#!/usr/bin/env python3
"""Nexus · Certificados de Bomberos de Barranquilla.

Uso:
  python nexus.py                       Abre el panel (y actualiza automáticamente)
  python nexus.py actualizar            Trae los certificados nuevos desde la consola
  python nexus.py consultar 62667       Consulta un consecutivo en vivo
  python nexus.py muestra 62667         Diagnóstico: guarda la página original y muestra lo que se leyó
  python nexus.py exportar datos.xlsx   Exporta todo (.xlsx, .csv o .html portable)
  python nexus.py importar Proyect.html Importa los registros del sistema anterior

Opciones: --hilos N  --puerto N  --no-abrir  --sin-actualizar  --sin-verificar-ssl
"""
from __future__ import annotations

import argparse
import http.client
import os
import ssl
import sys
import threading
import time

if sys.version_info < (3, 8):
    sys.exit("Nexus necesita Python 3.8 o superior: https://www.python.org/downloads/")

from nexus import __version__, exporter, legacy  # noqa: E402
from nexus.client import ClienteHTTP  # noqa: E402
from nexus.config import DATA_DIR, LEGACY_HTML, Config, parse_consecutivo  # noqa: E402
from nexus.parser import analizar  # noqa: E402
from nexus.scanner import Escaner, Progreso, consultar_uno  # noqa: E402
from nexus.store import Almacen  # noqa: E402

UTF8 = (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "") == "utf8"
for flujo in (sys.stdout, sys.stderr):
    try:
        flujo.reconfigure(errors="replace")
    except Exception:
        pass


def _almacen() -> Almacen:
    alm = Almacen(os.path.join(DATA_DIR, "nexus.db"))
    if alm.total() == 0 and os.path.exists(LEGACY_HTML):
        regs = legacy.leer(LEGACY_HTML)
        if regs:
            alm.guardar(regs, origen="importado")
            print(f"  Importados {len(regs):,} registros del sistema anterior (Proyect.html).".replace(",", "."))
    return alm


def _barra(fraccion: float, ancho: int = 28) -> str:
    lleno, vacio = ("█", "░") if UTF8 else ("#", "-")
    n = int(max(0.0, min(1.0, fraccion)) * ancho)
    return lleno * n + vacio * (ancho - n)


def _miles(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def cmd_actualizar(cfg: Config, args) -> int:
    alm = _almacen()
    prog = Progreso()
    esc = Escaner(cfg, alm, prog)
    resultado = {}
    hilo = threading.Thread(target=lambda: resultado.update(esc.ejecutar(revisar_vacios=not args.sin_vacios)), daemon=True)
    print(f"\n  Nexus {__version__} · actualizando con hasta {cfg.hilos} consultas simultáneas\n")
    hilo.start()
    try:
        while hilo.is_alive():
            hilo.join(0.25)
            e = prog.a_dict()
            frac = e["hechos"] / e["total"] if e["total"] else 0
            linea = (f"\r  {_barra(frac)} {_miles(e['hechos'])}/{_miles(e['total'])}  "
                     f"{e['velocidad']:.0f}/s  nuevos {_miles(e['nuevos'])}  errores {_miles(e['errores'])}  "
                     f"{(e['fase'] or '')[:38]:<38}")
            sys.stdout.write(linea)
            sys.stdout.flush()
    except KeyboardInterrupt:
        print("\n  Deteniendo…")
        esc.detener()
        hilo.join()
    r = resultado
    print("\n")
    if r.get("error_fatal"):
        print(f"  ✗ {r['error_fatal']}" if UTF8 else f"  X {r['error_fatal']}")
    ult = r.get("ultimo") or {}
    print(f"  Consultados: {_miles(r.get('consultados', 0))} en {r.get('segundos', 0)} s")
    print(f"  Nuevos:      {_miles(r.get('nuevos', 0))}")
    print(f"  Errores:     {_miles(r.get('errores', 0))}")
    print(f"  Último:      {ult.get('consecutivo', '-')}  {ult.get('contribuyente') or ''}\n")
    return 0 if r.get("completo") else 1


def cmd_consultar(cfg: Config, args) -> int:
    alm = _almacen()
    reg = consultar_uno(cfg, alm, args.consecutivo)
    estado = reg.get("consulta", {}).get("estado", reg.get("estado"))
    print(f"\n  {reg['consecutivo']}  ·  {estado.upper()}  {reg.get('consulta', {}).get('detalle') or ''}\n")
    for etiqueta, valor in reg.get("campos") or []:
        print(f"  {etiqueta:<28} {valor}")
    print(f"\n  {cfg.url(reg['consecutivo'])}\n")
    return 0 if estado in ("ok", "invalido") else 1


def cmd_muestra(cfg: Config, args) -> int:
    alm = _almacen()
    numero, anio = parse_consecutivo(args.consecutivo, cfg, (alm.anios() or [cfg.anio_inicio])[-1])
    consec = cfg.consecutivo(numero, anio)
    cli = ClienteHTTP(cfg)
    try:
        t0 = time.time()
        resp = cli.obtener(consec)
        ms = (time.time() - t0) * 1000
    finally:
        cli.cerrar()
    carpeta = os.path.join(DATA_DIR, "muestras")
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, f"{consec}.html")
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write(resp.texto)
    datos = analizar(resp.texto, consec)
    print(f"\n  {cfg.url(consec)}")
    print(f"  HTTP {resp.estado} · {len(resp.texto):,} caracteres · {ms:.0f} ms".replace(",", "."))
    print(f"  Página guardada en: {ruta}\n")
    print(f"  Estado detectado: {datos['estado'].upper()}  {datos['detalle']}\n")
    print("  Campos principales:")
    for c in ("consecutivo", "contribuyente", "identificacion", "direccion", "ref_catastral",
              "fecha_acta", "fecha_expedicion", "fecha_expiracion", "estado_pagina", "actividad"):
        print(f"    {c:<18} {datos.get(c) or '—'}")
    print("\n  Todos los campos encontrados en la página:")
    for etiqueta, valor in datos["campos"]:
        print(f"    {etiqueta[:40]:<40} {valor}")
    print("\n  Si algún dato salió mal, envía el archivo guardado para ajustar el lector.\n")
    return 0


def cmd_exportar(cfg: Config, args) -> int:
    alm = _almacen()
    ext = os.path.splitext(args.archivo)[1].lower().lstrip(".")
    regs = alm.completos()
    if ext == "xlsx":
        datos = exporter.xlsx_bytes(regs, cfg)
    elif ext == "csv":
        datos = exporter.csv_bytes(regs, cfg)
    elif ext in ("html", "htm"):
        from nexus.server import Aplicacion

        datos = exporter.html_portable(regs, Aplicacion(cfg, alm).meta())
    else:
        print("  Usa una extensión .xlsx, .csv o .html")
        return 2
    with open(args.archivo, "wb") as fh:
        fh.write(datos)
    print(f"  Exportados {_miles(len(regs))} registros a {args.archivo}")
    return 0


def cmd_importar(cfg: Config, args) -> int:
    alm = Almacen(os.path.join(DATA_DIR, "nexus.db"))
    regs = legacy.leer(args.archivo)
    alm.guardar(regs, origen="importado")
    print(f"  Importados {_miles(len(regs))} registros de {args.archivo}")
    return 0


def cmd_panel(cfg: Config, args) -> int:
    from nexus.server import servir

    alm = _almacen()
    servir(cfg, alm, abrir_navegador=not args.no_abrir, escanear=False if args.sin_actualizar else None)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nexus", description="Certificados de Bomberos de Barranquilla")
    ap.add_argument("--hilos", type=int, help="consultas simultáneas (por defecto 24, máximo 64)")
    ap.add_argument("--puerto", type=int, help="puerto del panel (por defecto 8765)")
    ap.add_argument("--no-abrir", action="store_true", help="no abrir el navegador")
    ap.add_argument("--sin-actualizar", action="store_true", help="no actualizar al abrir el panel")
    ap.add_argument("--sin-verificar-ssl", action="store_true", help="no verificar el certificado SSL (no recomendado)")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("actualizar", help="traer certificados nuevos")
    p.add_argument("--sin-vacios", action="store_true", help="no re-verificar consecutivos vacíos intermedios")
    sub.add_parser("consultar", help="consultar un consecutivo").add_argument("consecutivo")
    sub.add_parser("muestra", help="diagnóstico del lector").add_argument("consecutivo")
    sub.add_parser("exportar", help="exportar a .xlsx/.csv/.html").add_argument("archivo")
    sub.add_parser("importar", help="importar Proyect.html").add_argument("archivo")
    args = ap.parse_args(argv)

    cfg = Config.cargar()
    if args.hilos:
        cfg.hilos = args.hilos
    if args.puerto:
        cfg.puerto = args.puerto
    if args.sin_verificar_ssl:
        cfg.verificar_ssl = False
        print("  ⚠ Verificación SSL desactivada." if UTF8 else "  ! Verificacion SSL desactivada.")
    cfg.validar()

    comandos = {
        "actualizar": cmd_actualizar, "consultar": cmd_consultar, "muestra": cmd_muestra,
        "exportar": cmd_exportar, "importar": cmd_importar, None: cmd_panel,
    }
    try:
        return comandos[args.cmd](cfg, args)
    except ssl.SSLError as e:
        print(f"\n  Error SSL con el servidor de la Alcaldía: {e}")
        print("  Si estás en una red de confianza puedes reintentar con --sin-verificar-ssl\n")
        return 3
    except ValueError as e:
        print(f"  {e}")
        return 2
    except (OSError, http.client.HTTPException) as e:
        print(f"\n  No se pudo conectar con el servidor de la Alcaldía: {e}")
        print("  Revisa tu conexión a internet (el servidor puede no responder fuera de Colombia).\n")
        return 3
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
