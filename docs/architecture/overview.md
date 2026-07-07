# Arquitectura del Sistema — Estado Actual

Este documento describe la arquitectura del sistema tal como está implementada actualmente: componentes, responsabilidades y flujo de datos. No cubre la evolución histórica del proyecto (ver `evolution.md`) ni el razonamiento detrás de cada decisión (ver `architectural-decisions.md`).

---

## 1. Visión general

El sistema automatiza la conciliación bancaria de un dataset Excel: desde que el archivo llega a Google Drive hasta que los resultados procesados se distribuyen por correo a distintos equipos, con una copia de respaldo en Google Drive.

La arquitectura está compuesta por tres capas con responsabilidades estrictamente separadas:

```
┌─────────────────┐      ┌──────────────────┐      ┌───────────────────────┐
│  Google Drive    │      │       n8n        │      │   Python Worker       │
│  (origen/destino │◄────►│  (orquestación)  │◄────►│   FastAPI + Pipeline  │
│   de archivos)   │      │                  │      │   de conciliación     │
└─────────────────┘      └──────────────────┘      └───────────────────────┘
```

- **n8n no conoce la lógica del pipeline.**
- **El pipeline no conoce n8n.**
- La única vía de comunicación entre ambos es una API REST (`HTTP`).

---

## 2. Componentes

### 2.1 Google Drive
Actúa como punto de entrada (trigger) y como destino de respaldo.

- **Entrada:** una carpeta específica es monitoreada; al aparecer un archivo nuevo, se dispara el flujo.
- **Salida:** al finalizar cada ejecución, se crea una carpeta con nombre basado en fecha/hora y se sube ahí una copia de los artefactos generados.

### 2.2 n8n (orquestador)
Corre en un contenedor Docker (`n8n_app`, imagen `docker.n8n.io/n8nio/n8n:latest`). Es responsable de:

- Detectar archivos nuevos en Google Drive.
- Descargarlos y depositarlos en el volumen compartido `/shared`.
- Invocar la API del Python Worker.
- Construir el catálogo de artefactos esperados.
- Distribuir los artefactos correctos a cada destinatario.
- Leer los archivos de resultado desde disco.
- Enviar los correos correspondientes (Gmail).
- Subir una copia de respaldo a Google Drive.

n8n tiene restringido el acceso a archivos exclusivamente a la ruta `/shared` (`N8N_RESTRICT_FILE_ACCESS_TO=/shared`), y expone su interfaz mediante un host/dominio propio configurado por variables de entorno.

### 2.3 Python Worker (FastAPI)
Corre en un contenedor Docker (`python_worker`, imagen `mi_python_worker`), sin puerto publicado al host (`expose: 8000`, accesible solo dentro de la red interna de Docker).

Expone dos endpoints:

| Método | Ruta | Función |
|---|---|---|
| `GET` | `/` | Health check — confirma que el servicio está activo. |
| `POST` | `/procesar` | Recibe `{"file_path": "..."}`, ejecuta el pipeline y devuelve `{"estado": "OK", "output_dir": "..."}`. |

El Worker **no contiene lógica de negocio**: únicamente importa y ejecuta la función `correr_pipeline_financiero()` del pipeline, y traduce su resultado a una respuesta HTTP.

### 2.4 Pipeline de Conciliación Bancaria (Python)
Es la lógica central del sistema, organizada en fases secuenciales:

1. **Lectura y auditoría inicial** (`paso1_lectura.py`) — carga el Excel, detecta nulos y casos de mora crítica.
2. **Validación de datos crudos** (`paso_validacion.py`, esquema `schema_auditoria_inicial`) — con Pandera, verifica reglas estrictas (rango de mora, tipos de movimiento válidos, IDs únicos, etc.). Si falla, el pipeline se detiene antes de continuar.
3. **Limpieza y reglas de negocio** (`paso2_limpieza.py`) — normaliza fechas y textos, calcula banderas de validez (signo, valor neto, fechas, mora, duplicados) y persiste el archivo limpio en disco.
4. **Validación post-limpieza** (`paso_validacion.py`, esquema `schema_post_limpieza`) — confirma que ninguna regla de negocio quedó violada tras la limpieza.
5. **Análisis y reporte** (`paso3_analisis.py`) — genera un Excel multipestaña con resumen general, vistas por empresa/banco/mes/categoría, cruce conciliación-riesgo y detalle de anomalías.
6. **Visualización** (`paso4_visualizacion.py`) — genera cuatro gráficas (ingresos vs. egresos, problemas por banco, mora por empresa, heatmap banco/estado) en una subcarpeta `graficas_output/`.
7. **Interpretación con IA** (`paso5_ia.py`) — usando Gemini (`google-genai`):
   - Descubre dinámicamente qué modelo usar (prioriza variantes "flash" sobre "pro").
   - Genera un reporte ejecutivo en Markdown, con una verificación de control: si la cifra exacta de alertas críticas no aparece en el texto generado, el reporte se descarta (posible alucinación).
   - Genera una clasificación de alertas operativas en JSON (prioridad, insight, acción recomendada por caso), limitando el envío a los N casos más críticos por mora y valor.
   - Aplica reintentos con backoff exponencial ante errores transitorios (429, 500, 502, 503, 504) y una pausa deliberada entre ambas llamadas para respetar límites de solicitudes por minuto.

**Configuración central** (`config.py`): define la carpeta de salida única por ejecución (`/shared/processed/<timestamp>/`) y los umbrales de negocio (días de mora crítica, mora promedio de alerta, máximo de casos enviados a la IA).

---

## 3. Infraestructura

### 3.1 Contenedores (Docker Compose)

| Servicio | Container name | Imagen | Puertos | Persistencia |
|---|---|---|---|---|
| `jupyterlab` | `jupyterlab` | `jupyter/datascience-notebook:latest` | `8888:8888` | `jupyter_data:/home/jovyan/work`, `shared_data:/shared` |
| `n8n` | `n8n_app` | `docker.n8n.io/n8nio/n8n:latest` | `5678:5678` | `n8n_data:/home/node/.n8n`, `shared_data:/shared` |
| `python-worker` | `python_worker` | `mi_python_worker` | `8000` (solo red interna) | `shared_data:/shared`, `jupyter_data:/work` (solo lectura) |

`python-worker` depende explícitamente de `n8n` en el orden de arranque (`depends_on`).

### 3.2 Volúmenes

- **`jupyter_data`** — código fuente del pipeline, editado desde JupyterLab, montado como solo lectura en `python-worker` bajo `/work`.
- **`shared_data`** — intercambio de archivos de entrada y de resultados (`/shared`) entre los tres servicios.
- **`n8n_data`** — estado interno y configuración de n8n (credenciales, workflows, ejecuciones).

No existe una carpeta o volumen duplicado del pipeline: la única fuente de verdad del código es el volumen `jupyter_data`, al que `python-worker` accede en modo lectura.

### 3.3 Red
No se declara una red Docker nombrada explícitamente en el `docker-compose.yml`; los servicios se resuelven entre sí por nombre de contenedor a través de la red por defecto que crea Docker Compose (por ejemplo, n8n invoca `http://python_worker:8000/procesar`).

---

## 4. Flujo de datos end-to-end

```
1. Archivo Excel subido a carpeta monitoreada en Google Drive
        │
        ▼
2. n8n detecta el archivo (Google Drive Trigger) y lo descarga
        │
        ▼
3. n8n guarda el archivo en /shared/<nombre_archivo>
        │
        ▼
4. n8n hace POST /procesar al Python Worker con { file_path }
        │
        ▼
5. Python Worker ejecuta el pipeline completo (fases 1 a 5 descritas arriba)
        │
        ▼
6. Pipeline genera artefactos en /shared/processed/<timestamp>/:
     - datos_limpios.xlsx
     - reporte_estructurado.xlsx
     - reporte_ejecutivo.md
     - clasificacion_alertas.json
     - graficas_output/*.png (4 imágenes)
        │
        ▼
7. Python Worker responde a n8n con { estado: "OK", output_dir }
        │
        ▼
8. n8n construye un catálogo de los 8 artefactos esperados, usando output_dir
        │
        ├──► Rama A: Distribución por correo
        │       │
        │       ▼
        │    Distribuidor arma 3 paquetes (Analista, Gerencia de Riesgo,
        │    Equipo Operativo de Cartera), cada uno con solo los
        │    artefactos que ese destinatario necesita
        │       │
        │       ▼
        │    Se enriquece cada paquete con correo, asunto y mensaje HTML
        │       │
        │       ▼
        │    Se expande cada paquete en un item por artefacto
        │       │
        │       ▼
        │    Se lee cada archivo desde disco (un único nodo de lectura,
        │    reutilizado para todos los artefactos y destinatarios)
        │       │
        │       ▼
        │    Se reagrupan los binarios leídos por destinatario
        │       │
        │       ▼
        │    Se envía un único correo (Gmail) por destinatario, con sus
        │    adjuntos correspondientes
        │
        └──► Rama B: Respaldo en Google Drive
                │
                ▼
             Se crea una carpeta con nombre basado en fecha/hora
                │
                ▼
             Se combina con la rama A (nodo Merge)
                │
                ▼
             Se sube una copia de los artefactos a esa carpeta de Drive
```

### 4.1 Matriz de distribución de artefactos por destinatario

| Artefacto | Analista | Gerencia de Riesgo | Equipo Operativo de Cartera |
|---|:---:|:---:|:---:|
| `reporte_ejecutivo.md` | ✅ | ✅ | |
| `reporte_estructurado.xlsx` | ✅ | | |
| `datos_limpios.xlsx` | ✅ | ✅ | ✅ |
| `clasificacion_alertas.json` | ✅ | | ✅ |
| Gráfica: ingresos vs. egresos | ✅ | ✅ | |
| Gráfica: problemas por banco | ✅ | ✅ | |
| Gráfica: mora por empresa | ✅ | ✅ | |
| Gráfica: heatmap bancos | ✅ | ✅ | |

El Analista recibe el catálogo completo; Gerencia de Riesgo recibe el reporte ejecutivo, el dataset limpio y las cuatro gráficas; el Equipo Operativo de Cartera recibe únicamente el dataset limpio y la clasificación de alertas.

---

## 5. Contratos de integración

### 5.1 API interna (n8n → Python Worker)

**Request**
```json
POST /procesar
{
  "file_path": "/shared/archivo.xlsx"
}
```

**Response**
```json
{
  "estado": "OK",
  "output_dir": "/shared/processed/20260705_214608"
}
```

### 5.2 Autenticación externa
- **Google Drive:** OAuth 2.0, gestionado como credencial dentro de n8n (usado tanto por el trigger como por la descarga y la subida de respaldo).
- **Gmail:** OAuth 2.0, gestionado como credencial dentro de n8n (usado por el nodo de envío de correo).

---

## 6. Resumen de responsabilidades

| Componente | Responsabilidad | Lo que NO hace |
|---|---|---|
| Google Drive | Origen y respaldo de archivos | No procesa ni transforma datos |
| n8n | Orquestación, distribución, notificación | No contiene lógica de negocio ni ejecuta cálculos financieros |
| FastAPI (Python Worker) | Exponer el pipeline como servicio HTTP | No contiene lógica de negocio propia |
| Pipeline (`main.py` + módulos `paso*`) | Lectura, validación, limpieza, análisis, visualización, interpretación con IA | No conoce n8n ni gestiona el envío de resultados |
| JupyterLab | Entorno de desarrollo y edición del código del pipeline | No participa en la ejecución del flujo de producción |
