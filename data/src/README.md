# Pipeline de Conciliación Bancaria Automatizada

Pipeline en Python que procesa datasets bancarios/empresariales de extremo a extremo: lee un Excel, valida y limpia los datos, genera reportes y gráficas, y produce un análisis ejecutivo con IA (Gemini). Se expone como servicio HTTP para integrarse con flujos externos (ej. n8n).

## Arquitectura

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  JupyterLab   │     │     n8n      │────▶│ python-worker │
│ (exploración) │     │ (orquesta /  │     │  (FastAPI +   │
│               │     │  dispara vía │     │   pipeline)   │
│               │     │   webhook)   │     │               │
└──────┬───────┘     └──────┬───────┘     └──────┬───────┘
       │                     │                     │
       └─────────────────────┴─────────────────────┘
                     volumen compartido: /shared
```

Los tres servicios corren en contenedores Docker independientes y comparten un volumen (`/shared`) donde quedan los archivos de entrada y salida de cada corrida del pipeline.

## Flujo del pipeline (`main.py`)

1. **`paso1_lectura.py`** — Lee el Excel de entrada y hace una auditoría inicial (nulos, mora fuera de rango).
2. **`paso_validacion.py`** — Valida el DataFrame crudo con Pandera. Si hay datos corruptos o inconsistentes, el pipeline se detiene aquí con el detalle exacto de las filas problemáticas.
3. **`paso2_limpieza.py`** — Limpia y estandariza los datos, calcula banderas de reglas de negocio (signo, valor neto, fechas, mora) y guarda el archivo limpio.
4. **`paso_validacion.py`** (segunda pasada) — Confirma que la limpieza no dejó ninguna regla de negocio violada.
5. **`paso3_analisis.py`** — Genera un reporte Excel multipestaña con KPIs, resúmenes por empresa/banco/mes/categoría y detalle de anomalías.
6. **`paso4_visualizacion.py`** — Genera gráficas automáticas (ingresos vs egresos, problemas por banco, mora por empresa, heatmap de conciliación).
7. **`paso5_ia.py`** — Usa Gemini para redactar un reporte ejecutivo (.md) y clasificar los casos de alerta más críticos (.json), con control de calidad para detectar alucinaciones.

Cada corrida crea su propia carpeta con timestamp bajo `/shared/processed/`, así puedes correr el pipeline varias veces sin sobrescribir resultados anteriores (ver `config.py`).

## Requisitos

- Docker y Docker Compose
- Una API key de Google Gemini ([Google AI Studio](https://aistudio.google.com/))

## Instalación y arranque

1. Clona el repositorio:
   ```bash
   git clone <url-del-repo>
   cd <carpeta-del-repo>
   ```

2. Copia la plantilla de variables de entorno y completa tus valores:
   ```bash
   cp .env.example .env
   ```
   Edita `.env` con:
   - `JUPYTER_TOKEN`: un token propio para acceder a JupyterLab.
   - `N8N_HOST` / `WEBHOOK_URL`: tu dominio si expones n8n públicamente.
   - `GEMINI_API_KEY`: tu API key de Gemini.

3. Levanta los servicios:
   ```bash
   docker compose up -d
   ```

4. Servicios disponibles:
   - JupyterLab: `http://localhost:8888`
   - n8n: `http://localhost:5678`
   - API del pipeline (python-worker): puerto interno `8000` (no publicado por defecto, solo accesible entre contenedores o vía n8n)

## Uso de la API (`api.py`)

| Método | Ruta         | Descripción                                   |
|--------|--------------|------------------------------------------------|
| GET    | `/`          | Healthcheck (`{"estado": "Python Worker activo"}`) |
| POST   | `/procesar`  | Ejecuta el pipeline completo sobre un archivo   |

Ejemplo de body para `POST /procesar`:
```json
{
  "file_path": "/shared/dataset_bancario_empresarial.xlsx"
}
```

Respuesta:
```json
{
  "estado": "OK",
  "output_dir": "/shared/processed/20260706_153000"
}
```

## Ejecución manual (sin API)

También puedes correr el pipeline directo desde línea de comandos:

```bash
python main.py ruta/al/archivo.xlsx
```

Si no se especifica archivo, el script busca automáticamente el primer `.xlsx` en la carpeta actual.

## Estructura del dataset esperado

El Excel de entrada debe incluir, entre otras, estas columnas obligatorias:

- `transaccion_id`, `empresa`, `banco`
- `dias_mora` (0–365)
- `valor_bruto`, `valor_neto`
- `tipo_movimiento` (`Ingreso` / `Egreso`)
- `estado_conciliacion` (`Conciliado`, `Pendiente`, `Diferencia`, `Rechazado`, `Duplicado`)
- `fecha_operacion`, `fecha_contable`, `fecha_vencimiento`

La validación con Pandera (`paso_validacion.py`) rechaza el archivo si estas reglas no se cumplen, indicando fila y columna exactas.

## Salidas generadas por corrida

Dentro de `/shared/processed/<timestamp>/`:

- `datos_limpios.xlsx` — dataset limpio con banderas de reglas de negocio.
- `reporte_estructurado.xlsx` — reporte analítico multipestaña.
- `graficas_output/` — 4 gráficas en `.png`.
- `reporte_ejecutivo.md` — resumen ejecutivo generado por IA.
- `clasificacion_alertas.json` — casos de alerta priorizados y clasificados por IA.

## Variables de negocio configurables

Editables en `config.py` sin tocar la lógica del pipeline:

- `UMBRAL_MORA_CRITICA_DIAS` (default: 30)
- `UMBRAL_MORA_PROMEDIO_ALERTA` (default: 50)
- `MAX_CASOS_ALERTA_IA` (default: 30)

## Seguridad

- Las claves (`GEMINI_API_KEY`, `JUPYTER_TOKEN`) se cargan desde variables de entorno / `.env`, nunca desde el código.
- El archivo `.env` está excluido del repositorio vía `.gitignore` — nunca lo subas con valores reales.

## Licencia

_Agrega aquí la licencia que corresponda (MIT, propietaria, etc.)._
