import pandas as pd
import logging

def limpiar_datos(df, ruta_guardado=None):
    """
    Limpia y estandariza el DataFrame.
    Si se pasa `ruta_guardado`, exporta el resultado a disco (.xlsx o .csv
    según la extensión) para que el archivo limpio quede persistido y no
    se pierda si una fase posterior del pipeline falla.
    """
    logging.info("Iniciando limpieza y estandarización de datos...")
    df_limpio = df.copy()

    # 1. Formato de columnas (Fechas y booleanos)
    columnas_fecha = ["fecha_operacion", "fecha_contable", "fecha_vencimiento"]
    for col in columnas_fecha:
        df_limpio[col] = pd.to_datetime(df_limpio[col]).dt.normalize()
    
    df_limpio["requiere_revision"] = df_limpio["requiere_revision"].astype(str).str.strip().str.lower().eq("si")

    # 2. Tratar nulos según significado
    df_limpio["motivo_revision"] = df_limpio["motivo_revision"].fillna("No aplica")
    df_limpio["observaciones"] = df_limpio["observaciones"].fillna("")
    df_limpio["responsable"] = df_limpio["responsable"].fillna("Sin asignar")
    df_limpio["centro_costo"] = df_limpio["centro_costo"].fillna("Sin asignar")
    df_limpio["proveedor_cliente"] = df_limpio["proveedor_cliente"].fillna("Sin registro")
    df_limpio["documento_ref"] = df_limpio["documento_ref"].fillna("Sin registro")

    # 3. Estandarizar textos
    cols_cat = ["empresa", "banco", "tipo_movimiento", "categoria", "moneda", "metodo_pago", 
                "centro_costo", "ciudad", "pais", "responsable", "estado_conciliacion", "nivel_riesgo", "canal"]
    for col in cols_cat:
        df_limpio[col] = df_limpio[col].astype(str).str.strip()

    # 4. Validar reglas bancarias (Creación de banderas lógicas)
    df_limpio["regla_signo_valida"] = (df_limpio["tipo_movimiento"] == "Egreso") == (df_limpio["valor_bruto"] < 0)
    df_limpio["regla_valor_neto_valida"] = (df_limpio["valor_neto"] - (df_limpio["valor_bruto"] + df_limpio["impuesto_iva"])).abs() < 0.01
    df_limpio["regla_fechas_valida"] = df_limpio["fecha_contable"] >= df_limpio["fecha_operacion"]
    df_limpio["regla_mora_valida"] = ~((df_limpio["estado_conciliacion"] == "Conciliado") & (df_limpio["dias_mora"] != 0))
    df_limpio["bandera_duplicado_conciliacion"] = df_limpio["estado_conciliacion"] == "Duplicado"
    
    # 5. Reporte silencioso (Logs)
    logging.info(f"Anomalías Signo: {(~df_limpio['regla_signo_valida']).sum()}")
    logging.info(f"Anomalías Valor Neto: {(~df_limpio['regla_valor_neto_valida']).sum()}")
    logging.info(f"Anomalías Fechas: {(~df_limpio['regla_fechas_valida']).sum()}")
    logging.info(f"Anomalías Mora: {(~df_limpio['regla_mora_valida']).sum()}")
    logging.info(f"Duplicados de Negocio: {df_limpio['bandera_duplicado_conciliacion'].sum()}")

    logging.info("Limpieza completada con éxito.")

    # 6. Persistir el archivo limpio (ESTE PASO FALTABA)
    if ruta_guardado:
        try:
            if ruta_guardado.lower().endswith(".csv"):
                df_limpio.to_csv(ruta_guardado, index=False, encoding="utf-8-sig")
            else:
                df_limpio.to_excel(ruta_guardado, index=False, sheet_name="Datos_Limpios")
            logging.info(f"Archivo limpio guardado con éxito en: {ruta_guardado}")
        except Exception as e:
            logging.error(f"Error al guardar el archivo limpio: {e}")

    return df_limpio
