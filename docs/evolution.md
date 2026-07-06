# Evolución del Proyecto

Este documento reconstruye la evolución del proyecto, desde el primer script de limpieza de datos hasta la arquitectura actualmente en producción. Describe qué existía en cada etapa, qué limitación apareció y qué se modificó como respuesta, hasta llegar al sistema descrito en `overview.md`.

---

## Etapa 1 — Limpieza de datos

El proyecto comenzó como un script de Python enfocado en limpiar y estandarizar un dataset bancario: normalización de fechas y textos, tratamiento de nulos y detección de inconsistencias básicas. En esta etapa no existía automatización ni interpretación de resultados; el valor del script se limitaba a dejar los datos en condiciones confiables para un análisis posterior.

Una vez limpio el dato, surgió la necesidad de interpretarlo y comunicarlo, no solo de depurarlo.

---

## Etapa 2 — Incorporación de inteligencia artificial al análisis

Se incorporó generación de análisis mediante un modelo de lenguaje (Gemini) para producir interpretación ejecutiva y clasificación de alertas a partir de las cifras ya calculadas en Python. El diseño adoptado desde el inicio evitó que el modelo calculara cifras de negocio: su función quedó limitada a redactar y clasificar sobre datos ya validados, reduciendo el riesgo de resultados numéricos incorrectos.

Ejecutar manualmente este análisis cada vez que llegaba un archivo nuevo dejó de ser sostenible, lo que impulsó la necesidad de automatizar el proceso completo.

---

## Etapa 3 — Infraestructura base: JupyterLab y n8n

El servidor en DigitalOcean ya contaba con JupyterLab y n8n desplegados, pensados originalmente para automatizar directamente combinando ambos servicios, sin una capa de servicio intermedia. Esta decisión de infraestructura previa condicionó el diseño posterior: cuando fue necesario separar la lógica del pipeline de la orquestación, la solución natural fue extender el mismo stack con un tercer servicio, en lugar de migrar a una infraestructura distinta.

---

## Etapa 4 — Integración de n8n con Google Drive

Se configuró la integración entre n8n y Google Drive mediante OAuth 2.0: pantalla de consentimiento, aplicación en modo de usuarios externos, usuarios de prueba, credencial OAuth tipo aplicación web, Redirect URI y habilitación de la Google Drive API. Con esta integración, n8n quedó en condiciones de detectar archivos nuevos en una carpeta de Drive y descargarlos automáticamente.

---

## Etapa 5 — Persistencia y volumen compartido entre servicios

Con JupyterLab y n8n operando en contenedores independientes, se identificó que dos contenedores Docker no comparten archivos entre sí por defecto: cada uno cuenta con su propio sistema de archivos interno, y solo lo que está montado como volumen sobrevive a la recreación del contenedor. Se incorporó un volumen compartido (`shared_data`), montado en ambos servicios, específicamente para permitir el intercambio de archivos entre JupyterLab y n8n. Esta arquitectura de volúmenes es la misma que hoy sostiene la comunicación entre los tres servicios del stack.

---

## Etapa 6 — Pipeline ejecutable únicamente por consola

El pipeline de conciliación bancaria —lectura, limpieza, análisis, visualización e interpretación con IA— ya estaba desarrollado como un conjunto de módulos de Python, pero solo podía ejecutarse manualmente:

```bash
python main.py archivo.xlsx
```

No existía forma de que n8n u otro sistema disparara el pipeline directamente; cada ejecución requería intervención manual en una terminal. Esta limitación llevó al rediseño descrito en la siguiente etapa. El modo de ejecución por consola se conservó como capacidad del pipeline (mediante `argparse` y detección automática del archivo de entrada), y sigue siendo válido para pruebas locales.

---

## Etapa 7 — Introducción del Python Worker y separación de responsabilidades

Se diseñó un tercer servicio, un Python Worker con FastAPI, cuya única responsabilidad es recibir una solicitud HTTP, ejecutar el pipeline y devolver la ubicación de los resultados. Los cambios que hicieron posible esta transición fueron:

- Creación de una API con dos endpoints: `GET /` (estado del servicio) y `POST /procesar` (ejecución del pipeline).
- Importación directa del pipeline desde el volumen compartido, evitando duplicar el código dentro de la imagen del Worker.
- Modificación de `correr_pipeline_financiero()` para que retornara la ruta de salida (`config.DIR_SALIDA_BASE`), permitiendo que la API informe dónde quedaron los resultados.
- Configuración de la carpeta de salida del pipeline sobre el volumen compartido (`/shared/processed/<timestamp>`).
- Organización del código en dos ubicaciones separadas: una para la API (Dockerfile, punto de entrada `app.py`, dependencias) y otra exclusiva para el pipeline, evitando duplicación de lógica.
- Montaje del volumen donde vive el código del pipeline como solo lectura dentro del Worker, en lugar de copiarlo dentro de la imagen.

El resultado fue la transformación de un script de ejecución manual en un servicio HTTP reutilizable:

```
POST /procesar  { "file_path": "/shared/archivo.xlsx" }
→  { "estado": "OK", "output_dir": "/shared/processed/20260705_214608" }
```

Este fue el cambio central de toda la evolución del proyecto: pasar de un pipeline que solo podía ejecutarse desde consola a un servicio desacoplado, reutilizable y consumible por una herramienta de automatización, sin alterar la lógica de procesamiento existente.

---

## Etapa 8 — Consolidación operativa del despliegue

Durante la puesta en producción del Worker se resolvieron distintos aspectos de despliegue: verificación de que un contenedor en ejecución correspondiera realmente a la imagen esperada, reconstrucción de la imagen tras cambios de código, y confirmación de la disponibilidad del servicio mediante pruebas HTTP directas. Este proceso dejó como práctica estable un protocolo de verificación —reconstruir la imagen, redeployar el contenedor e inspeccionar que el contenido interno coincide con el código fuente actual— que se mantiene como parte del flujo operativo del proyecto.

---

## Etapa 9 — Primera automatización completa en n8n

Con Google Drive conectado y el Python Worker respondiendo por HTTP, se construyó una primera versión funcional del flujo completo: detección del archivo en Drive, descarga, guardado en `/shared`, solicitud HTTP al Worker, lectura de cada archivo de resultado y envío por Gmail con los adjuntos correspondientes, incluyendo la configuración necesaria para que Gmail aceptara los archivos como datos binarios.

Esta primera versión leía cada uno de los ocho artefactos generados mediante un nodo independiente, lo que resultaba funcional pero no escalable: agregar un artefacto nuevo implicaba agregar un nodo nuevo, y no existía una forma limpia de dirigir distintos artefactos a distintos destinatarios sin multiplicar nodos y ramas del flujo.

En esta misma etapa se diagnosticó, mediante revisión de logs, un caso real de límite de cuota en la API de Gemini (errores por agotamiento de solicitudes), lo que llevó a diferenciar claramente entre un error del modelo, del prompt, del pipeline o de la infraestructura antes de intervenir el flujo de automatización.

---

## Etapa 10 — Rediseño de la distribución: catálogo, distribuidor y configuración de destinatarios

Se rediseñó la capa de distribución de resultados en n8n para eliminar la dependencia de un nodo de lectura por archivo y por destinatario. La arquitectura resultante introdujo tres responsabilidades independientes, cada una como un nodo de código dedicado:

1. **Catálogo de Artefactos** — construye la lista completa de artefactos esperados (nombre, archivo, ruta, tipo), a partir de la ruta de salida devuelta por la API.
2. **Distribuidor** — decide qué artefactos necesita cada área (Analista, Gerencia de Riesgo, Equipo Operativo de Cartera), sin leer archivos ni enviar correos.
3. **Configuración de Destinatarios** — enriquece cada paquete con correo, asunto y mensaje, sin modificar los artefactos.

Este rediseño eliminó la necesidad de un nodo de lectura por archivo, de condicionales por destinatario y de ramas duplicadas del flujo, sustituyéndolos por una arquitectura organizada por responsabilidad.

---

## Etapa 11 — Expansión de artefactos y ajuste de rutas

Se incorporó un nodo de expansión que transforma cada paquete de artefactos en items individuales, propagando explícitamente el destinatario, correo, asunto y mensaje durante la expansión, de modo que esta información se preserve incluso después de que el nodo de lectura de archivos modifica la estructura de los datos.

En paralelo, se corrigió una inconsistencia entre las rutas asumidas en el catálogo y la ubicación real de las gráficas generadas por el pipeline, que se almacenan en una subcarpeta dedicada (`graficas_output`). Con este ajuste, un único nodo de lectura quedó operando correctamente para todos los artefactos y destinatarios, sin perder el contexto de a quién correspondía cada archivo.

---

## Etapa 12 — Respaldo automático en Google Drive

Al flujo de distribución por correo se sumó una segunda rama, ejecutada en paralelo: la creación de una carpeta con nombre basado en fecha y hora dentro de Google Drive, y la subida de una copia de los artefactos generados a esa carpeta. Esta rama complementa la distribución por correo con un respaldo trazable y organizado cronológicamente, coherente con el mismo criterio de organización por timestamp que ya se aplicaba a las carpetas de resultados del pipeline.

---

## Etapa 13 — Resiliencia ante límites de tasa de la API de Gemini

Se incorporaron mecanismos explícitos para operar de forma confiable frente a los límites de uso de la API de Gemini:

- Reintentos con backoff exponencial ante errores transitorios del servicio.
- Una pausa deliberada entre la llamada que genera el reporte ejecutivo y la que clasifica las alertas, para evitar agotar el límite de solicitudes por minuto.
- Descubrimiento dinámico del modelo disponible para la API Key en uso, en lugar de un nombre de modelo fijo.
- Una verificación de control de calidad: si la cifra exacta de alertas críticas no aparece en el texto generado, el reporte se descarta antes de guardarse, como salvaguarda ante posibles resultados no confiables del modelo.

Con esto, una falla puntual en la fase de interpretación con IA deja de comprometer el resto del pipeline: los artefactos de limpieza, análisis y visualización ya quedan generados y persistidos antes de llegar a esta fase.

---

## Estado consolidado

El resultado de esta evolución es la arquitectura descrita en `overview.md`: tres servicios desacoplados (n8n, Python Worker, JupyterLab), comunicados mediante una API REST y un volumen de archivos compartido, con un pipeline de cinco fases que valida, limpia, analiza, visualiza e interpreta los datos, y un flujo de distribución en n8n que entrega a cada destinatario únicamente la información que necesita, con respaldo automático en Google Drive.

Las carpetas de resultados generadas en cada ejecución (`/shared/processed/<timestamp>/`) se conservan de forma indefinida; actualmente no existe un proceso automático de limpieza o expiración, por lo que la gestión del espacio de almacenamiento depende de una intervención manual periódica.

## Línea de tiempo resumida

| Etapa | Hito |
|---|---|
| 1 | Script de limpieza de datos |
| 2 | Incorporación de IA generativa al análisis |
| 3 | Infraestructura base: JupyterLab y n8n |
| 4 | Integración de n8n con Google Drive (OAuth 2.0) |
| 5 | Volumen compartido entre servicios |
| 6 | Pipeline ejecutable solo por consola |
| 7 | Introducción del Python Worker (FastAPI) |
| 8 | Consolidación operativa del despliegue |
| 9 | Primera automatización completa en n8n |
| 10 | Rediseño de la distribución (catálogo, distribuidor, configuración de destinatarios) |
| 11 | Expansión de artefactos y ajuste de rutas |
| 12 | Respaldo automático en Google Drive |
| 13 | Resiliencia ante límites de tasa de Gemini |
