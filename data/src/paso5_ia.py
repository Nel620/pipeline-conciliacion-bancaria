import os
import json
import time
from datetime import datetime
import logging

# Errores transitorios que sí vale la pena reintentar (servidor saturado,
# rate limit, timeout). Un 503 "UNAVAILABLE" cae aquí.
CODIGOS_REINTENTABLES = {429, 500, 502, 503, 504}

# Preferencia de modelo: si hay varios disponibles para esta API key,
# priorizamos "flash" (más rápido/barato) sobre "pro". Se recorre en
# orden y se usa el primero que exista en la lista real de Google.
PREFERENCIA_MODELOS = ["flash", "pro"]

# Límite de casos que se envían a la IA para clasificar. No es que solo
# existan estos casos: es un tope para no mandar un prompt gigante (costo
# y límites de tokens). Por eso es CRÍTICO ordenar por severidad ANTES
# de cortar (ver casos_alerta_ordenados más abajo) — si no, se corre el
# riesgo de dejar afuera justo los casos más graves.
LIMITE_CASOS_ALERTA = 30

# Segundos de pausa entre la llamada 1 (reporte ejecutivo) y la llamada 2
# (clasificación de alertas). Los planes gratuitos de Gemini tienen un
# límite muy bajo de solicitudes POR MINUTO (ej. 5 RPM en gemini-2.5-flash).
# Si las dos llamadas —más sus reintentos— caen muy pegadas, se agota ese
# límite y la segunda llamada recibe 429 aunque el día no esté agotado.
# Espaciarlas da tiempo a que la ventana de "por minuto" se libere.
ESPERA_ENTRE_LLAMADAS_IA = 15


def _descubrir_modelo(client):
    """
    Le pregunta al servidor de Google, en tiempo real, qué modelos están
    activos para esta API key y soportan generateContent. Evita
    hardcodear nombres de modelo que pueden cambiar o no estar
    disponibles según la cuenta/región.
    """
    try:
        modelos_disponibles = client.models.list()
    except Exception as e:
        raise RuntimeError(f"No se pudo consultar la lista de modelos de Google: {e}")

    nombres_compatibles = [
        m.name for m in modelos_disponibles
        if "generateContent" in getattr(m, "supported_methods", getattr(m, "supported_actions", []))
    ]

    if not nombres_compatibles:
        raise RuntimeError("La API key no tiene ningún modelo disponible que soporte generateContent.")

    logging.info(f"Modelos disponibles para esta API key: {nombres_compatibles}")

    # Elegir por preferencia (flash antes que pro), si no hay coincidencia
    # se usa el primero que devolvió el servidor.
    for preferencia in PREFERENCIA_MODELOS:
        for nombre in nombres_compatibles:
            if preferencia in nombre.lower():
                return nombre
    return nombres_compatibles[0]


def _generar_con_reintentos(client, model, contents, intentos=4, espera_inicial=2):
    """
    Llama a client.models.generate_content con reintentos y backoff
    exponencial (2s, 4s, 8s, 16s...). Evita que un pico de demanda de
    Gemini (503 UNAVAILABLE) tumbe la fase 5 en el primer intento.
    """
    for intento in range(1, intentos + 1):
        try:
            return client.models.generate_content(model=model, contents=contents)
        except Exception as e:
            codigo = getattr(e, "code", None) or getattr(e, "status_code", None)
            es_reintentable = codigo in CODIGOS_REINTENTABLES or "UNAVAILABLE" in str(e) or "503" in str(e) or "429" in str(e)
            if not es_reintentable or intento == intentos:
                raise
            espera = espera_inicial * (2 ** (intento - 1))
            logging.warning(
                f"Intento {intento}/{intentos} falló ({e}). Reintentando en {espera}s..."
            )
            time.sleep(espera)


def ejecutar_analisis_ia(df_limpio, ruta_reporte=None, ruta_alertas=None):
    """
    Fase 5: genera dos entregables con IA a partir de datos YA calculados
    en Python (la IA no calcula cifras, solo las redacta/clasifica):

      1) Reporte ejecutivo para Gerencia de Riesgo (.md), con una
         "trampa de control" (👮 control de calidad): si la IA no repite
         la cifra exacta de alertas críticas que le dimos, se asume que
         alucinó y el reporte NO se guarda; se detiene la fase con error.

      2) Listado operativo de alertas para el equipo de Cartera (.json),
         limpio de bloques de markdown, listo para que un flujo externo
         (ej. n8n) lo adjunte a un correo o lo procese. Se seleccionan
         los LIMITE_CASOS_ALERTA casos más críticos (por mora y valor,
         no los primeros del archivo), y cada caso incluye un "insight"
         con cifras reales, no solo una etiqueta de prioridad. El JSON
         trae además un "panorama_general" con la lectura del lote.
    """
    logging.info("Iniciando fase 5: Análisis y Clasificación con IA...")

    # Import perezoso: si el paquete 'google-genai' no está instalado,
    # el resto del pipeline (fases 1-4, que ya generaron tus archivos)
    # no se ve afectado. Antes un ImportError aquí tumbaba TODO main.py
    # incluso antes de leer el Excel.
    try:
        from google import genai
    except ImportError:
        logging.error("❌ Falta la librería 'google-genai'. Instálala con: pip install google-genai")
        return False

    # 1. Validar credenciales
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logging.error("❌ Error: Falta GEMINI_API_KEY en el entorno (.env).")
        return False

    client = genai.Client(api_key=api_key)

    # 1.b Descubrir dinámicamente qué modelo usar (nada de nombres fijos)
    try:
        modelo = _descubrir_modelo(client)
        logging.info(f"🔍 Modelo seleccionado automáticamente: {modelo}")
    except Exception as e:
        logging.error(f"❌ No se pudo determinar un modelo disponible: {e}")
        return False

    fecha_hoy = datetime.now().strftime("%Y-%m-%d_%H%M")

    # Nombres corporativos listos para que n8n (o cualquier flujo) los
    # adjunte directamente al correo correspondiente.
    if not ruta_reporte:
        ruta_reporte = f"1_Resumen_Ejecutivo_Gerencia_Riesgo_{fecha_hoy}.md"
    if not ruta_alertas:
        ruta_alertas = f"2_Alertas_Operativas_Equipo_Cartera_{fecha_hoy}.json"

    # 2. Consolidar el resumen estructurado en memoria (Python calcula,
    # la IA solo redacta/clasifica sobre estas cifras ya correctas)
    analisis = {
        "resumen_general": {
            "total_transacciones": len(df_limpio),
            "valor_total_neto": float(df_limpio["valor_neto"].sum()),
            "ingresos": int((df_limpio["tipo_movimiento"] == "Ingreso").sum()),
            "egresos": int((df_limpio["tipo_movimiento"] == "Egreso").sum()),
            "mora_promedio": float(df_limpio["dias_mora"].mean()),
            "casos_mora_critica": int((df_limpio["dias_mora"] > 30).sum()),
            "pendientes": int((df_limpio["estado_conciliacion"] == "Pendiente").sum()),
            "rechazados": int((df_limpio["estado_conciliacion"] == "Rechazado").sum()),
            "diferencias": int((df_limpio["estado_conciliacion"] == "Diferencia").sum()),
        },
        "por_empresa": df_limpio.groupby("empresa").agg(
            transacciones=("transaccion_id", "count"), valor_total=("valor_neto", "sum"), mora_promedio=("dias_mora", "mean")
        ).reset_index().to_dict(orient="records"),
    }

    # =====================================================================
    # ARCHIVO 1: PARA GERENCIA DE RIESGO (Resumen Estratégico + Control IA)
    # =====================================================================
    total_alertas_reales = analisis["resumen_general"]["casos_mora_critica"]
    balance_neto_real = analisis["resumen_general"]["valor_total_neto"]

    prompt_reporte = f"""
    ROL: Auditor Interno de Riesgo Bancario Senior. Directo y sin adornos, pero con criterio
    analítico — no eres una calculadora que solo repite cifras en viñetas.

    DATOS DE ENTRADA CONFIABLES (MANDATORIOS, no recalcules, no inventes cifras adicionales):
    - Alertas críticas detectadas: {total_alertas_reales}
    - Balance total neto: {balance_neto_real} COP

    JSON DE RESPALDO (única fuente de verdad; todo lo que digas debe poder rastrearse a este JSON):
    {json.dumps(analisis, ensure_ascii=False, indent=2)}

    ESTRUCTURA OBLIGATORIA (usa estos 4 encabezados exactos, en este orden, nada más):

    ## Panorama general
    2-3 líneas relacionando las cifras entre sí (ej: qué proporción del total de transacciones
    está en alerta, si el balance negativo se explica por concentración de egresos o de una
    empresa/banco puntual). Solo relaciones calculables directamente del JSON.

    ## Hallazgos de riesgo
    Viñetas cortas. Cada una dice POR QUÉ importa la cifra, no solo la repite.
    Mal: "33 transacciones pendientes." Bien: "33 transacciones pendientes retrasan el cierre
    contable y son el principal cuello de botella de conciliación."

    ## Preguntas que Gerencia debería hacer
    Entre 3 y 5 preguntas concretas y accionables que un auditor le haría al equipo operativo
    a partir de estos datos (ej: qué banco o empresa concentra la mora, por qué hay diferencias
    contables). Son preguntas para investigar, NO respuestas — no inventes la causa.

    ## Recomendación y siguiente paso
    1-2 acciones concretas y priorizadas. Nada genérico tipo "mejorar procesos": di qué proceso,
    con qué dato del JSON lo sustentas y qué área debería ejecutarla.

    REGLAS:
    1. Usa explícitamente la cifra exacta entregada ({total_alertas_reales} alertas) al menos
       una vez, tal cual, sin recalcular.
    2. No inventes causas, responsables ni cifras que no estén en el JSON.
    3. Cero relleno: si una sección no tiene un hallazgo real, dilo en una línea corta y sigue.
    4. Prohibido texto introductorio ("Aquí está el reporte..."). Empieza directo en
       "## Panorama general".
    """

    try:
        respuesta = _generar_con_reintentos(client, modelo, prompt_reporte)
        texto_informe = respuesta.text

        # 👮 LA TRAMPA DE CONTROL: si la IA no repite la cifra real de
        # alertas, asumimos que alucinó y NO se guarda el reporte.
        if str(total_alertas_reales) in texto_informe:
            with open(ruta_reporte, "w", encoding="utf-8") as f:
                f.write(texto_informe)
            logging.info(f"✅ CONTROL PASADO: Reporte ejecutivo guardado en: {ruta_reporte}")
        else:
            logging.error("❌ ALERTA CRÍTICA: LA IA ESTÁ ALUCINANDO EN EL REPORTE.")
            raise ValueError("🛑 Pipeline bloqueado: el reporte de la IA falló el control de calidad.")

    except Exception as e:
        logging.error(f"❌ Error generando reporte ejecutivo: {e}")
        return False

    # ⏳ Pausa deliberada antes de la segunda llamada, para no pegarle dos
    # solicitudes casi simultáneas al mismo límite de "solicitudes por minuto".
    logging.info(f"⏳ Esperando {ESPERA_ENTRE_LLAMADAS_IA}s antes de la siguiente llamada a la IA (cuidar el límite por minuto)...")
    time.sleep(ESPERA_ENTRE_LLAMADAS_IA)

    # =====================================================================
    # ARCHIVO 2: PARA EQUIPO OPERATIVO DE CARTERA (Listado de Acción JSON)
    # =====================================================================
    casos_alerta = df_limpio[(df_limpio["dias_mora"] > 30) | (df_limpio["estado_conciliacion"].isin(["Pendiente", "Diferencia", "Rechazado"]))].copy()

    # Ordenar por severidad ANTES de cortar al límite: primero los de más
    # días de mora, y como criterio de desempate, el mayor valor en juego
    # (valor absoluto, porque un egreso grande es tan crítico como un
    # ingreso grande). Así los 30 que le llegan a la IA son de verdad los
    # más urgentes, no simplemente "los primeros del archivo".
    casos_alerta["_valor_absoluto"] = casos_alerta["valor_neto"].abs()
    casos_alerta_ordenados = casos_alerta.sort_values(
        by=["dias_mora", "_valor_absoluto"], ascending=[False, False]
    )

    total_casos_alerta = len(casos_alerta_ordenados)
    if total_casos_alerta > LIMITE_CASOS_ALERTA:
        logging.warning(
            f"⚠️  Hay {total_casos_alerta} casos de alerta, pero solo se envían a la IA "
            f"los {LIMITE_CASOS_ALERTA} más críticos (mayor mora y mayor valor). "
            f"El resto queda disponible en 'Detalle_Anomalias' del reporte Excel (Paso 3)."
        )

    casos_alerta_resumen = casos_alerta_ordenados[
        ["transaccion_id", "empresa", "estado_conciliacion", "valor_neto", "dias_mora"]
    ].head(LIMITE_CASOS_ALERTA).to_dict(orient="records")

    prompt_alertas = f"""
    ROL: Analista Operativo de Riesgo Bancario, con criterio propio, no un clasificador plano.

    INSTRUCCIONES ESTRICTAS:
    1. Clasifica ÚNICAMENTE las transacciones proporcionadas en el JSON adjunto. NO inventes, agregues ni elimines ningún 'transaccion_id'.
    2. Para cada caso, asigna:
       - "prioridad": Alta, Media o Baja.
       - "insight": UNA frase (máx. 20 palabras) que explique POR QUÉ importa este caso, usando las cifras reales del caso (mora, valor, estado). No genérico, no relleno.
       - "accion_recomendada": el paso concreto siguiente (a quién escalar, qué hacer, en qué plazo).
    3. Además del listado, agrega al inicio del JSON una clave "panorama_general": 1-2 frases con la conclusión global de este lote de casos (patrón que se repite, concentración de riesgo, empresa o banco más afectado), usando SOLO los datos entregados.
    4. Devuelve la respuesta ESTRICTAMENTE en formato JSON válido, con esta forma exacta:
       {{"panorama_general": "...", "casos": [{{"transaccion_id": "...", "prioridad": "...", "insight": "...", "accion_recomendada": "..."}}]}}
    5. Cero texto introductorio ni cierre. Entrega solo el código JSON puro.

    DATOS REALES A CLASIFICAR ({len(casos_alerta_resumen)} de {total_casos_alerta} casos totales, los más críticos por mora y valor):
    {json.dumps(casos_alerta_resumen, ensure_ascii=False, indent=2)}
    """

    try:
        respuesta_alertas = _generar_con_reintentos(client, modelo, prompt_alertas)
        # Limpiar posibles bloques de markdown (```json ... ```) en la respuesta
        texto_limpio = respuesta_alertas.text.replace("```json", "").replace("```", "").strip()

        with open(ruta_alertas, "w", encoding="utf-8") as f:
            f.write(texto_limpio)
        logging.info(f"✅ Alertas operativas guardadas en: {ruta_alertas}")
    except Exception as e:
        logging.error(f"❌ Error clasificando alertas: {e}")

        # Crear un JSON de respaldo para que el pipeline continúe
        error_json = {
            "estado": "ERROR",
            "motivo": str(e),
            "panorama_general": "No fue posible generar la clasificación automática porque la IA no respondió correctamente.",
            "casos": []
        }

        with open(ruta_alertas, "w", encoding="utf-8") as f:
            json.dump(error_json, f, ensure_ascii=False, indent=4)

        logging.warning(f"⚠️ Se creó un JSON de respaldo en: {ruta_alertas}")

        return False

    return True
