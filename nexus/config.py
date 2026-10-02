"""Configuración: valores por defecto + `config.json` opcional en la raíz del proyecto."""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field, fields

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
WEB_DIR = os.path.join(ROOT, "web")
CONFIG_PATH = os.path.join(ROOT, "config.json")
LEGACY_HTML = os.path.join(ROOT, "Proyect.html")

URL_OFICIAL = "https://appbaq.barranquilla.gov.co:9191/Bomberos/verfCert.do"


@dataclass
class Config:
    # Origen de los datos.
    url_base: str = URL_OFICIAL
    parametro: str = "csctvo"
    digitos: int = 11
    # Primer consecutivo del sistema (00000060624-2026).
    inicio: int = 60624
    anio_inicio: int = 2026
    # Si en algún año el consecutivo vuelve a empezar, ej. {"2027": 1}.
    # Si no se indica, Nexus asume que la numeración continúa y además lo detecta solo.
    inicio_por_anio: dict = field(default_factory=dict)

    # Velocidad.
    hilos: int = 24            # consultas simultáneas (se reduce solo si el servidor se satura)
    timeout: float = 20.0      # segundos por consulta
    reintentos: int = 4
    hueco_fin: int = 30        # consecutivos vacíos seguidos para dar por encontrado el último

    # Seguridad / red.
    verificar_ssl: bool = True
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )

    # Panel.
    puerto: int = 8765
    actualizar_al_iniciar: bool = True
    auto_minutos: int = 30     # 0 = sin actualización automática mientras el panel está abierto
    dias_por_vencer: int = 30

    @classmethod
    def cargar(cls, path: str = CONFIG_PATH) -> "Config":
        cfg = cls()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                datos = json.load(fh)
            validos = {f.name for f in fields(cls)}
            for clave, valor in datos.items():
                if clave in validos:
                    setattr(cfg, clave, valor)
        cfg.validar()
        return cfg

    def validar(self) -> None:
        if not re.match(r"^https?://[^/\s]+/\S*$", self.url_base):
            raise ValueError("url_base inválida")
        if not re.match(r"^[A-Za-z0-9_]+$", self.parametro):
            raise ValueError("parametro inválido")
        self.hilos = max(1, min(int(self.hilos), 64))
        self.reintentos = max(1, min(int(self.reintentos), 10))
        self.hueco_fin = max(5, min(int(self.hueco_fin), 500))
        self.digitos = max(1, min(int(self.digitos), 15))
        self.inicio_por_anio = {int(k): int(v) for k, v in (self.inicio_por_anio or {}).items()}

    def a_dict(self) -> dict:
        return asdict(self)

    # ---- consecutivos -------------------------------------------------------

    def consecutivo(self, numero: int, anio: int) -> str:
        return f"{int(numero):0{self.digitos}d}-{int(anio)}"

    def url(self, consecutivo: str) -> str:
        return f"{self.url_base}?{self.parametro}={consecutivo}"


_RE_CONSEC = re.compile(r"^\s*0*(\d{1,15})\s*(?:[-/ ]\s*(\d{4}))?\s*$")


def parse_consecutivo(texto: str, cfg: Config, anio_defecto: int) -> tuple[int, int]:
    """Convierte '62667', '62667-2026' o '00000062667-2026' en (numero, año).

    Lanza ValueError si el texto no es un consecutivo válido: así nunca se arma una URL
    con datos arbitrarios.
    """
    m = _RE_CONSEC.match(texto or "")
    if not m:
        raise ValueError("Consecutivo inválido. Usa por ejemplo 62667 o 00000062667-2026")
    numero = int(m.group(1))
    anio = int(m.group(2)) if m.group(2) else int(anio_defecto)
    if numero <= 0 or len(str(numero)) > cfg.digitos or not 2000 <= anio <= 2100:
        raise ValueError("Consecutivo fuera de rango")
    return numero, anio
