# Decisiones Arquitectónicas

Este documento registra las decisiones de diseño más relevantes del sistema: el contexto que las motivó, las alternativas consideradas, la decisión adoptada, sus ventajas y sus limitaciones.

---

## DA-01 — Separar la orquestación (n8n) de la lógica de negocio (pipeline Python)

**Contexto**
El proyecto requiere que un flujo de automatización dispare el procesamiento de datos cada vez que llega un archivo nuevo.

**Problema**
n8n permite ejecutar código directamente mediante nodos de código o de comando, lo cual habría permitido invocar el pipeline sin un servicio intermedio.

**Alternativas consideradas**
- Ejecutar el pipeline directamente desde un nodo de código o de comando dentro de n8n.
- Exponer el pipeline como un servicio HTTP independiente, consumido por n8n mediante un nodo de solicitud HTTP.

**Decisión tomada**
El pipeline se expone como un servicio HTTP (FastAPI); n8n lo consume únicamente a través de una API REST.

**Ventajas**
- n8n no necesita conocer dependencias de Python, versiones de librerías ni el entorno de ejecución del pipeline.
- El pipeline puede probarse, versionarse y ejecutarse de forma independiente del flujo de automatización.
- Permite reemplazar o modificar la capa de orquestación sin tocar la lógica de negocio, y viceversa.

**Desventajas**
- Introduce una capa adicional y, con ella, latencia de red y un punto más de disponibilidad a monitorear.
- Exige mantener un contrato de API estable entre ambos componentes.

**Evidencia:** `api.py`/`app.py` expone `POST /procesar` importando `correr_pipeline_financiero` desde `main.py`; el workflow de n8n invoca ese endpoint mediante un nodo de solicitud HTTP.

---

## DA-02 — Python Worker como servicio independiente

**Contexto**
El pipeline y su entorno de desarrollo (JupyterLab) conviven en el mismo servidor.

**Problema**
Era posible exponer un servidor HTTP desde el propio contenedor de JupyterLab, reutilizando ese entorno para producción.

**Alternativas consideradas**
- Levantar el servidor HTTP dentro del contenedor de JupyterLab.
- Crear un contenedor dedicado exclusivamente a exponer la API del pipeline.

**Decisión tomada**
Un contenedor independiente (`python-worker`), cuya única responsabilidad es recibir solicitudes HTTP, ejecutar el pipeline y devolver la ubicación de los resultados.

**Ventajas**
- JupyterLab conserva su rol de entorno de desarrollo, sin mezclar responsabilidades de producción.
- El Worker puede reiniciarse o reconstruirse sin afectar el entorno de desarrollo interactivo.
- Menor superficie de exposición: el Worker no publica ningún puerto hacia el host, a diferencia de JupyterLab.

**Desventajas**
- Un servicio adicional que desplegar, monitorear y mantener dentro del mismo stack.
- Depende de que el volumen donde vive el código del pipeline esté correctamente montado y estructurado.

**Evidencia:** `docker-compose.yml` (servicio `python-worker`, sin puerto publicado); `Dockerfile` del Worker, que construye una imagen mínima (`python:3.11-slim`), instala dependencias desde `requirements.txt`, copia únicamente el punto de entrada de la API (`app.py`) y expone el puerto `8000` internamente mediante Uvicorn (`uvicorn app:app`).

---

## DA-03 — Uso de Docker y contenedores para toda la infraestructura

**Contexto**
El proyecto necesita correr múltiples servicios heterogéneos (entorno de desarrollo, orquestador, servicio de procesamiento) en un mismo servidor.

**Problema**
Instalar cada servicio directamente sobre el sistema operativo del servidor implica gestión manual de dependencias, versiones y aislamiento entre procesos.

**Alternativas consideradas**
- Instalación nativa de cada servicio sobre el servidor.
- Contenerización de cada servicio con Docker.

**Decisión tomada**
Todos los servicios corren como contenedores Docker, definidos en un único `docker-compose.yml`.

**Ventajas**
- Aislamiento de dependencias entre servicios (Python del pipeline, entorno de n8n, entorno de JupyterLab).
- Reproducibilidad: el mismo stack puede recrearse en otro servidor a partir del mismo archivo de definición.
- Control explícito de qué código está realmente en ejecución mediante imágenes versionadas.

**Desventajas**
- Requiere disciplina operativa: reconstruir la imagen correspondiente tras cada cambio de código y confirmar que el contenedor en ejecución la esté usando realmente.

**Evidencia:** `docker-compose.yml` completo (tres servicios, tres volúmenes nombrados).

---

## DA-04 — Portainer para la gestión del stack

**Contexto**
El stack de Docker Compose debe administrarse (desplegarse, actualizarse, monitorearse) de forma operativa en el servidor.

**Problema**
Gestionar Docker Compose únicamente por línea de comandos es funcional, pero menos accesible para inspección rápida de contenedores, logs y variables de entorno.

**Alternativas consideradas**
- Gestión exclusivamente por CLI (`docker compose`, `docker ps`, `docker logs`).
- Uso de Portainer como interfaz de gestión sobre el mismo Docker Engine.

**Decisión tomada**
El stack se gestiona como un Portainer Stack, usando el mismo `docker-compose.yml` como fuente de definición.

**Ventajas**
- Interfaz visual para inspeccionar contenedores, logs y variables de entorno.
- Facilita el redeploy del stack completo tras cambios en la definición.

**Desventajas**
- Un componente adicional de infraestructura que asegurar y mantener disponible.
- No elimina la necesidad de comprender Docker a bajo nivel para diagnosticar problemas de despliegue.

**Evidencia:** estructura y formato del `docker-compose.yml` (versión `3.8`, servicios y volúmenes con nombre), compatible con un stack administrado por Portainer.

---

## DA-05 — Volumen compartido (`/shared`) como único mecanismo de intercambio de archivos

**Contexto**
n8n, el Python Worker y JupyterLab necesitan intercambiar archivos —el Excel de entrada y los resultados del pipeline— sin acoplarse directamente entre sí.

**Problema**
Los contenedores Docker no comparten archivos por defecto; cada uno cuenta con su propio sistema de archivos aislado.

**Alternativas consideradas**
- Transferir archivos entre servicios como parte del cuerpo de las solicitudes HTTP.
- Montar un volumen Docker nombrado en los servicios involucrados, usando el sistema de archivos como medio de intercambio.

**Decisión tomada**
Un volumen (`shared_data`) montado como `/shared` en los tres servicios.

**Ventajas**
- Evita transferir archivos potencialmente grandes codificados dentro de solicitudes HTTP.
- El contrato entre n8n y el Worker se simplifica a intercambiar únicamente rutas de archivo, no contenido binario.
- Los archivos persisten aunque los contenedores se recreen, mientras el volumen no se elimine.

**Desventajas**
- Acopla a los tres servicios a una misma convención de rutas; modificarla exige coordinar los tres servicios a la vez.
- No existe aislamiento de archivos entre ejecuciones más allá de la organización por carpetas con timestamp.

**Evidencia:** `docker-compose.yml` (volumen `shared_data` presente en los tres servicios); `config.py` (rutas de salida basadas en `/shared`); contrato de la API (intercambio de rutas, no de archivos).

---

## DA-06 — Reutilizar el volumen de JupyterLab como origen del código del pipeline, montado como solo lectura

**Contexto**
El código del pipeline se edita desde JupyterLab. El Python Worker necesita acceso a ese mismo código para importarlo y ejecutarlo.

**Problema**
Era necesario decidir cómo el Worker accede al código del pipeline: copiándolo dentro de su propia imagen, mediante un volumen dedicado exclusivamente al pipeline, o reutilizando el volumen ya existente de JupyterLab.

**Alternativas consideradas**
- Copiar el código del pipeline dentro de la imagen del Worker en tiempo de construcción.
- Crear un volumen dedicado exclusivamente al pipeline.
- Reutilizar el volumen de JupyterLab, montándolo en el Worker en modo solo lectura.

**Decisión tomada**
El volumen de JupyterLab se monta en el Python Worker en modo solo lectura, exponiendo el código del pipeline sin duplicarlo.

**Ventajas**
- Una única fuente de verdad para el código del pipeline: lo que se edita en JupyterLab es exactamente lo que ejecuta el Worker.
- Elimina pasos de sincronización o reconstrucción de imagen ante cada cambio de lógica del pipeline.
- El montaje en modo solo lectura reduce el riesgo de que el Worker modifique el código fuente.

**Desventajas**
- Acopla la disponibilidad y la estructura interna del pipeline a la estructura del volumen de JupyterLab.
- La carpeta del pipeline contiene, junto a los módulos activos, archivos de referencia de versiones anteriores de la API (no utilizados por la imagen de producción, que solo incorpora el punto de entrada definido explícitamente en su propio Dockerfile). Se recomienda retirar esos archivos de referencia para mantener la carpeta del pipeline libre de artefactos no utilizados.

**Evidencia:** `docker-compose.yml` (volumen de JupyterLab montado como solo lectura en `python-worker`); `Dockerfile` del Worker, que construye la imagen copiando exclusivamente su propio punto de entrada (`app.py`) y `requirements.txt`, sin depender de los archivos del volumen del pipeline para su propia ejecución.

---

## DA-07 — Pandera para validación de datos en dos puntos del pipeline

**Contexto**
El pipeline procesa datasets bancarios que pueden llegar con inconsistencias: mora fuera de rango, fechas incoherentes, tipos de movimiento inválidos, identificadores duplicados.

**Problema**
Detectar errores de datos únicamente mediante revisión manual o mensajes de advertencia no garantiza que el pipeline se detenga ante datos corruptos, ni deja un registro estructurado de qué fila y qué regla incumplió.

**Alternativas consideradas**
- Validaciones manuales dispersas en el código.
- Validación declarativa de esquemas mediante una librería dedicada, aplicada en dos puntos del flujo: sobre los datos crudos y sobre los datos ya limpios.

**Decisión tomada**
Dos esquemas de validación con Pandera, ejecutados en modo de recolección exhaustiva de errores, que detienen el pipeline ante cualquier violación de regla.

**Ventajas**
- Detiene el pipeline antes de invertir tiempo en limpieza o generación de reportes si el archivo de entrada está corrupto.
- Provee el detalle exacto de fila, columna, valor y regla incumplida, en lugar de un error genérico.
- Verifica también que la limpieza no haya dejado ninguna regla de negocio violada.

**Desventajas**
- Requiere mantener los esquemas sincronizados con cualquier cambio en las columnas o reglas de negocio del dataset.
- Un archivo de entrada con un formato distinto al esperado detiene todo el pipeline, incluso si el resto de los datos es válido.

**Evidencia:** `paso_validacion.py` (esquemas `schema_auditoria_inicial` y `schema_post_limpieza`); `main.py` (invoca la validación inmediatamente después de la lectura y después de la limpieza).

---

## DA-08 — Gemini como motor de interpretación y clasificación

**Contexto**
El pipeline calcula cifras y métricas en Python, pero necesita producir un reporte ejecutivo legible y una clasificación priorizada de alertas para audiencias no técnicas.

**Problema**
Redactar manualmente un reporte ejecutivo y clasificar decenas de casos por prioridad, cada vez que llega un dataset nuevo, no escala.

**Alternativas consideradas**
- Generar el reporte mediante plantillas de texto fijas.
- Usar un modelo de lenguaje para redactar el reporte ejecutivo y clasificar las alertas, a partir de cifras ya calculadas en Python.

**Decisión tomada**
Gemini se utiliza exclusivamente para redactar y clasificar, nunca para calcular cifras de negocio.

**Ventajas**
- El reporte se adapta al contenido real de cada ejecución, incluyendo relaciones entre cifras costosas de codificar como reglas fijas.
- La clasificación de alertas incluye una explicación en lenguaje natural por caso, no solo una etiqueta.
- Separar el cálculo (Python) de la redacción (IA) reduce el riesgo de alucinación numérica.

**Desventajas**
- Dependencia de un servicio externo con límites de tasa y cuota.
- Requiere una salvaguarda de control de calidad para mitigar alucinaciones en el texto generado.
- Introduce latencia adicional al pipeline.

**Evidencia:** `paso5_ia.py` (descubrimiento dinámico de modelo, prompts que restringen al modelo a las cifras entregadas, verificación de la cifra exacta antes de guardar el reporte, reintentos con backoff).

---

## DA-09 — Google Drive como origen del disparador y destino de respaldo

**Contexto**
El sistema necesita un punto de entrada que dispare el proceso automáticamente al llegar un archivo nuevo, y un lugar accesible para que equipos no técnicos revisen resultados.

**Problema**
Se requería un mecanismo de disparo y almacenamiento de archivos accesible para personas no técnicas, sin depender de acceso directo al servidor.

**Alternativas consideradas**
- Subida manual del archivo directamente al servidor.
- Un endpoint expuesto públicamente para recibir el archivo.
- Google Drive como carpeta monitoreada, con autenticación OAuth 2.0, tanto para el disparador de entrada como para el respaldo de salida.

**Decisión tomada**
Google Drive se utiliza como origen del disparador y como destino de la copia de respaldo de cada ejecución.

**Ventajas**
- Interfaz familiar para usuarios no técnicos.
- No requiere exponer públicamente ningún endpoint del servidor para recibir el archivo de entrada.
- El mismo mecanismo de autenticación sirve tanto para el disparador de entrada como para el respaldo de salida.

**Desventajas**
- Introduce una dependencia de disponibilidad y cuota de la API de Google Drive.
- La configuración de la autenticación OAuth 2.0 (pantalla de consentimiento, usuarios de prueba, Redirect URI) exige una puesta a punto cuidadosa antes de la primera ejecución.

**Evidencia:** workflow de n8n (nodo de disparo de Google Drive y nodos de creación de carpeta y subida de archivo).

---

## DA-10 — Gmail como canal de distribución de resultados

**Contexto**
Los resultados del pipeline deben llegar a personas concretas —Analista, Gerencia de Riesgo, Equipo Operativo de Cartera—, cada una con necesidades de información distintas.

**Problema**
Se requería un canal de distribución que soportara adjuntos binarios de distintos formatos y que fuera un canal ya utilizado por las audiencias destinatarias.

**Alternativas consideradas**
- Notificación mediante una herramienta de mensajería.
- Envío de correo electrónico con archivos adjuntos.

**Decisión tomada**
Gmail, mediante autenticación OAuth 2.0, como canal de distribución de los resultados.

**Ventajas**
- Canal universal para las audiencias de negocio destinatarias, sin requerir la adopción de una herramienta nueva.
- Soporta múltiples adjuntos binarios de distintos formatos en un mismo mensaje.

**Desventajas**
- Exige que los adjuntos se preparen como datos binarios con un formato específico antes del envío.
- Un único nodo de envío para todos los destinatarios implica que un error de configuración afecta a la distribución completa.

**Evidencia:** workflow de n8n (nodo de envío de correo con autenticación OAuth 2.0 de Gmail).

---

## DA-11 — Carpetas de salida únicas por ejecución, basadas en timestamp

**Contexto**
El pipeline se ejecuta repetidamente, con datasets distintos, y los resultados de cada ejecución deben poder distinguirse entre sí.

**Problema**
Escribir siempre en la misma carpeta de salida provocaría que cada ejecución nueva sobrescribiera los resultados de la anterior, perdiendo trazabilidad e historial.

**Alternativas consideradas**
- Una única carpeta de salida fija, sobrescrita en cada ejecución.
- Una carpeta de salida nueva por ejecución, nombrada con un timestamp.

**Decisión tomada**
Cada ejecución genera su propia carpeta de resultados (`/shared/processed/<timestamp>/`); el mismo criterio de nomenclatura se reutiliza para la carpeta de respaldo en Google Drive.

**Ventajas**
- Trazabilidad y auditoría: cada ejecución queda como un registro histórico independiente.
- Permite comparar resultados de distintas ejecuciones sin sobrescrituras.
- Consistencia entre el almacenamiento local y el respaldo en Drive.

**Desventajas**
- Actualmente no existe un proceso automático de limpieza o expiración de estas carpetas: los resultados se conservan de forma indefinida hasta que se eliminan manualmente, lo que implica un crecimiento continuo del volumen de almacenamiento compartido si no se gestiona de forma periódica.

**Evidencia:** `config.py` (`TIMESTAMP` y `DIR_SALIDA_BASE`); workflow de n8n (carpeta de respaldo en Drive nombrada con el mismo criterio).

---

## DA-12 — Múltiples reportes diferenciados por audiencia, en lugar de un reporte único

**Contexto**
Los resultados del pipeline deben servir a audiencias con necesidades distintas: un analista requiere el detalle completo, gerencia necesita una síntesis ejecutiva, y el equipo operativo necesita solo lo accionable.

**Problema**
Un único reporte genérico tiende a ser demasiado denso para gerencia o insuficiente en detalle para el equipo operativo.

**Alternativas consideradas**
- Generar un único artefacto para todos los destinatarios.
- Generar múltiples artefactos especializados y distribuir a cada destinatario solo el subconjunto relevante.

**Decisión tomada**
El pipeline genera un conjunto de artefactos especializados (Excel analítico, reporte ejecutivo, clasificación de alertas, gráficas), y n8n distribuye a cada destinatario únicamente los que necesita, mediante la arquitectura de catálogo y distribuidor.

**Ventajas**
- Cada destinatario recibe solo la información relevante para su rol.
- Los artefactos evolucionan de forma independiente entre sí.
- El mismo conjunto de artefactos base puede reutilizarse en distintas combinaciones sin regenerar el pipeline por audiencia.

**Desventajas**
- Aumenta el número de artefactos que el pipeline debe generar y que n8n debe catalogar y distribuir correctamente.
- Exige mantener sincronizado el catálogo de artefactos esperados con lo que el pipeline realmente genera.

**Evidencia:** `main.py` (genera explícitamente cada artefacto); workflow de n8n (nodo distribuidor con paquetes diferenciados por destinatario).

---

## DA-13 — Restricción del acceso a archivos de n8n exclusivamente a `/shared`

**Contexto**
n8n puede, por defecto, acceder a rutas arbitrarias del sistema de archivos del contenedor donde corre, si un nodo lo permite.

**Problema**
Sin restricción, un nodo mal configurado podría leer o escribir fuera del área destinada al intercambio de archivos del proyecto.

**Alternativas consideradas**
- Dejar el acceso a archivos de n8n sin restricción explícita.
- Restringir el acceso exclusivamente a la ruta compartida del proyecto.

**Decisión tomada**
El acceso a archivos de n8n se restringe exclusivamente a `/shared` mediante configuración explícita del servicio.

**Ventajas**
- Reduce la superficie de exposición ante nodos mal configurados.
- Refuerza a nivel de infraestructura el mismo límite que ya impone la arquitectura de intercambio de archivos.

**Desventajas**
- Cualquier necesidad futura de que n8n acceda a una ruta fuera de `/shared` exigiría modificar esta restricción explícitamente.

**Evidencia:** `docker-compose.yml` (`N8N_RESTRICT_FILE_ACCESS_TO=/shared`).

---

## Consideraciones operativas y riesgos

- **JupyterLab se expone directamente en el puerto `8888` sin token de autenticación configurado.** Cualquier actor con acceso de red al servidor podría interactuar con ese entorno de ejecución de código. Se recomienda establecer un token de acceso antes de exponer este servicio en una red no controlada.
- **n8n se publica directamente en el puerto `5678`**, además de resolverse mediante el dominio configurado en sus variables de entorno. Conviene revisar que el firewall del servidor limite el acceso directo a este puerto si el acceso previsto es únicamente a través del dominio.
- **No existe una política automática de retención** para las carpetas de resultados generadas en `/shared/processed/`; su crecimiento depende de la gestión manual del espacio de almacenamiento.
