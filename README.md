# Nexus · Certificados de Bomberos de Barranquilla

Programa para consultar **automáticamente y muy rápido** los certificados de Bomberos en
`appbaq.barranquilla.gov.co`, desde el consecutivo `00000060624-2026` hasta el último que exista.
Tiene un panel moderno para buscar, filtrar, ver la ficha completa y exportar.

- **Rápido:** hace hasta 24 consultas a la vez y reutiliza las conexiones. En pruebas recorrió
  2.044 consecutivos en ~17 s (con 48 consultas a la vez, ~9 s).
- **Automático:** encuentra solo el último consecutivo y únicamente consulta lo que falta.
  Mientras el panel está abierto se actualiza cada 30 minutos.
- **Completo:** guarda todos los datos que muestre la página del certificado, no solo las columnas principales.
- **Seguro:** funciona solo en tu computador y no necesita instalar librerías externas (detalles abajo).

## 1. Instalar (una sola vez)

1. Instala **Python 3.8 o superior** desde <https://www.python.org/downloads/>.
   En Windows marca la casilla **"Add python.exe to PATH"** durante la instalación.
2. Descarga esta carpeta completa (botón *Code → Download ZIP* en GitHub) y descomprímela.

No hay que instalar nada más.

## 2. Usar

**Windows:** doble clic en **`Iniciar Nexus.bat`**.

**Cualquier sistema:** abre una terminal en la carpeta y ejecuta:

```bash
python nexus.py
```

Se abre el panel en el navegador (`http://127.0.0.1:8765`) y empieza a traer los certificados nuevos.
La primera vez importa automáticamente los 1.894 registros de `Proyect.html` (tu sistema anterior),
así que solo consulta los que faltan.

### En el panel

| Función | Cómo |
|---|---|
| Traer certificados nuevos | Botón **Actualizar** (o tecla `U`). Muestra progreso, velocidad y tiempo restante. |
| Consultar uno en vivo | Recuadro **Consulta en vivo**: escribe `62667` o `00000062667-2026` y Enter. |
| Buscar | Barra de búsqueda (tecla `/`): consecutivo, nombre, NIT/CC, dirección, referencia o fecha. No importan tildes ni mayúsculas. |
| Filtrar | Validados / No válidos / Sin certificado / Errores, y Vigentes / Por vencer (≤30 días) / Vencidos. Las tarjetas de arriba también filtran. |
| Ver todo el certificado | Clic en una fila: se abre la ficha con todos los campos, el enlace oficial y el botón **Re-consultar**. |
| Exportar | **CSV**, **Excel** (.xlsx con fechas reales y filtros) o **HTML portable** (un solo archivo para compartir, solo lectura). Exporta lo que esté filtrado. |

### Desde la consola

```bash
python nexus.py actualizar                 # trae los nuevos y muestra una barra de progreso
python nexus.py actualizar --hilos 48      # aún más rápido (máximo 64)
python nexus.py consultar 62667            # consulta un consecutivo
python nexus.py exportar certificados.xlsx # también .csv o .html
python nexus.py muestra 62667              # diagnóstico del lector (ver abajo)
```

### Actualización diaria sin abrir nada (opcional)

En Windows, con el **Programador de tareas**, crea una tarea diaria que ejecute:

- Programa: `py`
- Argumentos: `-3 nexus.py actualizar`
- Iniciar en: la carpeta de Nexus

## 3. Primera prueba con la página real (importante)

El lector de datos busca las etiquetas de la página ("Contribuyente", "Dirección", "Fecha de expiración"…)
y por eso funciona aunque cambie el diseño. Pero como la página de la Alcaldía no se pudo abrir desde
fuera de Colombia mientras se desarrollaba, **verifícalo una vez**:

```bash
python nexus.py muestra 62667
```

Este comando muestra lo que se leyó y guarda la página original en `data/muestras/`.
Si algún campo aparece vacío o equivocado, envía ese archivo para ajustar el lector.

## 4. Cómo funciona

1. **Huecos:** consulta los consecutivos que falten entre el primero y el último conocido
   (nunca consultados, con error o vacíos).
2. **Nuevos:** avanza desde el último certificado con muchas consultas en paralelo y se detiene
   cuando encuentra 30 consecutivos seguidos sin certificado. Ese es el último del día.
3. **Ritmo automático:** si el servidor empieza a fallar o a saturarse, baja la velocidad a la mitad y
   reintenta con espera. Cuando se recupera, vuelve a subirla. Un fallo pasajero nunca borra un certificado ya validado.
4. **Cambio de año:** en enero consulta automáticamente con `-2027`, siguiendo la misma numeración.
   Si ese año la numeración volviera a empezar desde 1, también lo detecta.

Los datos se guardan en `data/nexus.db` (SQLite).

## 5. Seguridad

- El panel escucha **solo en `127.0.0.1`**: nadie en tu red ni en internet puede entrar.
- Cada vez que abres Nexus se crea un **token secreto** que se exige en todas las llamadas internas.
  Además se revisan las cabeceras `Host` y `Origin`. Así, otras páginas abiertas en tu navegador no pueden leer los datos ni lanzar consultas.
- **Política de seguridad de contenido estricta:** no se cargan scripts externos ni en línea.
  Los datos de la Alcaldía se muestran siempre como texto, nunca como código.
- Los consecutivos se validan antes de armar la URL. Solo se consulta la dirección oficial configurada.
- Se verifica el certificado SSL del servidor. Solo se desactiva si lo pides con `--sin-verificar-ssl`.
- Las exportaciones CSV están protegidas contra inyección de fórmulas en Excel. El HTML portable lleva
  su propia política de seguridad, que bloquea cualquier envío de datos.
- `data/` y `config.json` están en `.gitignore`: tus datos no se suben a GitHub por accidente.
- No usa librerías de terceros: no hay dependencias que se puedan comprometer.

## 6. Configuración (opcional)

Copia `config.ejemplo.json` como `config.json` y cambia lo que necesites:

| Clave | Por defecto | Para qué |
|---|---|---|
| `hilos` | 24 | Consultas simultáneas (1–64). |
| `hueco_fin` | 30 | Vacíos seguidos para dar por encontrado el último. |
| `auto_minutos` | 30 | Actualización automática con el panel abierto (0 = apagada). |
| `actualizar_al_iniciar` | true | Actualizar al abrir el panel. |
| `dias_por_vencer` | 30 | Días para marcar "Por vencer". |
| `inicio` / `anio_inicio` | 60624 / 2026 | Primer consecutivo. |
| `inicio_por_anio` | {} | Solo si la numeración se reinicia en un año, ej. `{"2027": 1}`. |
| `puerto` | 8765 | Puerto del panel. |

## 7. Pruebas

```bash
python -m unittest discover -s tests -v
```

Prueban el lector con varios diseños de página, el escaneo contra un servidor simulado
(con huecos, errores 503 y cambio de año), la seguridad del panel y las exportaciones.
