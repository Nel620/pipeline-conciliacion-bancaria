import argparse
import logging
import glob
import sys
from dotenv import load_dotenv

import config
import paso1_lectura
import paso2_limpieza
import paso3_analisis
import paso4_visualizacion
import paso5_ia
import paso_validacion

# Configuración central de logs FORZADA para ver el avance en tiempo real en Jupyter
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    force=True  # Esto obliga a Jupyter a mostrarte los logs en pantalla
)

def correr_pipeline_financiero(ruta_dataset="dataset_bancario_empresarial.xlsx"):
    logging.info("==============================================")
    logging.info("INICIANDO AUTOMATIZACIÓN DE CONCILIACIÓN")
    logging.info(f"Dataset de entrada: {ruta_dataset}")
    logging.info(f"Carpeta de resultados de esta corrida: {config.DIR_SALIDA_BASE}")
    logging.info("==============================================")
    
    # Cargar variables de entorno (API Keys)
    load_dotenv()

    # Fase 1: Lectura (acepta cualquier archivo/empresas/fechas)
    df_inicial = paso1_lectura.cargar_y_auditar(ruta_dataset)

    # --- Auditoría estricta con Pandera (datos crudos) ---
    # Si el archivo trae trampas (mora negativa, mora de 900 días,
    # tipo_movimiento inventado, ids duplicados, etc.) se detiene AQUÍ,
    # antes de gastar tiempo limpiando o generando reportes.
    try:
        paso_validacion.validar_dataframe(
            df_inicial,
            paso_validacion.schema_auditoria_inicial,
            etiqueta="Auditoría inicial (Paso 1)",
        )
    except ValueError as e:
        logging.error(str(e))
        sys.exit(1)

    # Fase 2: Limpieza y Reglas de negocio + GUARDADO del archivo limpio.
    ruta_limpio = config.ruta_salida("datos_limpios.xlsx")
    df_limpio = paso2_limpieza.limpiar_datos(df_inicial, ruta_guardado=ruta_limpio)

    # --- Validación estricta con Pandera (datos ya limpios) ---
    # Confirma que la limpieza no dejó ninguna regla de negocio violada
    # (signo del valor, valor neto, fechas, mora) antes de reportar.
    try:
        paso_validacion.validar_dataframe(
            df_limpio,
            paso_validacion.schema_post_limpieza,
            etiqueta="Validación post-limpieza (Paso 2)",
        )
    except ValueError as e:
        logging.error(str(e))
        sys.exit(1)

    # Fase 3: Reportes de Métricas en Excel
    ruta_reporte = config.ruta_salida("reporte_estructurado.xlsx")
    paso3_analisis.analizar_y_reportar(
        df_limpio,
        ruta_reporte=ruta_reporte,
        umbral_mora_promedio=config.UMBRAL_MORA_PROMEDIO_ALERTA,
        umbral_mora_critica=config.UMBRAL_MORA_CRITICA_DIAS,
    )

    # Fase 4: Visualizaciones y Gráficas automáticas
    dir_graficas = config.directorio_salida("graficas_output")
    paso4_visualizacion.generar_visualizaciones(df_limpio, dir_salida=dir_graficas)

    # Fase 5: Interpretación Ejecutiva y Clasificación con IA
    ia_ok = paso5_ia.ejecutar_analisis_ia(
        df_limpio,
        ruta_reporte=config.ruta_salida("reporte_ejecutivo.md"),
        ruta_alertas=config.ruta_salida("clasificacion_alertas.json"),
    )
    if not ia_ok:
        logging.warning("⚠️ La fase de IA no se completó correctamente.")

    logging.info("==============================================")
    logging.info("¡PIPELINE COMPLETO EJECUTADO CON ÉXITO!")
    logging.info(f"Todos los resultados están en: {config.DIR_SALIDA_BASE}")
    logging.info("==============================================")

    return config.DIR_SALIDA_BASE


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline de conciliación bancaria")
    parser.add_argument(
        "dataset",
        nargs="?",
        default=None,
        help="Ruta al archivo Excel con los datos a procesar",
    )
    args = parser.parse_args()

    archivo_a_procesar = args.dataset

    # Si NO pasas un archivo manual, busca el primer Excel automáticamente
    if not archivo_a_procesar:
        archivos_excel = glob.glob("*.xlsx")
        if not archivos_excel:
            logging.error("❌ No se encontró ningún archivo .xlsx en la carpeta.")
            sys.exit(1)

        archivo_a_procesar = archivos_excel[0]
        logging.info(f"🔍 Auto-detectado el archivo: {archivo_a_procesar}")

    correr_pipeline_financiero(archivo_a_procesar)
