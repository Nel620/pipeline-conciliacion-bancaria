import pandas as pd
import logging

# Umbrales por defecto (se pueden sobreescribir vía parámetros de la función,
# así el mismo módulo sirve para cualquier dataset sin editar código).
UMBRAL_MORA_PROMEDIO_ALERTA_DEFAULT = 50
UMBRAL_MORA_CRITICA_DIAS_DEFAULT = 30


def analizar_y_reportar(
    df_limpio,
    ruta_reporte="reporte_financiero.xlsx",
    umbral_mora_promedio=UMBRAL_MORA_PROMEDIO_ALERTA_DEFAULT,
    umbral_mora_critica=UMBRAL_MORA_CRITICA_DIAS_DEFAULT,
):
    logging.info("Iniciando análisis y generación de métricas...")

    # 1. Alertas críticas GENERALIZADAS: se evalúa CUALQUIER banco y
    #    CUALQUIER empresa presentes en el dataset, no un nombre fijo.
    #    Esto es lo que hace el pipeline escalable a datasets nuevos.
    mora_por_banco = df_limpio.groupby("banco")["dias_mora"].mean()
    bancos_criticos = mora_por_banco[mora_por_banco > umbral_mora_promedio]
    for banco, mora in bancos_criticos.items():
        logging.warning(f"¡ALERTA CRÍTICA! {banco} presenta mora promedio de {mora:.1f} días.")

    mora_por_empresa = df_limpio.groupby("empresa")["dias_mora"].mean()
    empresas_criticas = mora_por_empresa[mora_por_empresa > umbral_mora_promedio]
    for empresa, mora in empresas_criticas.items():
        logging.warning(f"¡ALERTA CRÍTICA! {empresa} presenta mora promedio de {mora:.1f} días.")

    pendientes = df_limpio[df_limpio["estado_conciliacion"] == "Pendiente"]
    if not pendientes.empty:
        logging.warning(f"¡ALERTA! Hay {len(pendientes)} transacciones en estado Pendiente (Foco de mora).")

    # 2. Resumen ejecutivo (KPIs de un vistazo, para que el reporte
    #    tenga valor sin necesidad de interpretar tablas dinámicas)
    resumen_general = pd.DataFrame([{
        "rango_fechas": f"{df_limpio['fecha_operacion'].min().date()} a {df_limpio['fecha_operacion'].max().date()}",
        "total_transacciones": len(df_limpio),
        "empresas_distintas": df_limpio["empresa"].nunique(),
        "bancos_distintos": df_limpio["banco"].nunique(),
        "valor_neto_total": df_limpio["valor_neto"].sum(),
        "ingresos_valor": df_limpio.loc[df_limpio["tipo_movimiento"] == "Ingreso", "valor_neto"].sum(),
        "egresos_valor": df_limpio.loc[df_limpio["tipo_movimiento"] == "Egreso", "valor_neto"].sum(),
        "mora_promedio_dias": df_limpio["dias_mora"].mean(),
        "casos_mora_critica": int((df_limpio["dias_mora"] > umbral_mora_critica).sum()),
        "pendientes": int((df_limpio["estado_conciliacion"] == "Pendiente").sum()),
        "rechazados": int((df_limpio["estado_conciliacion"] == "Rechazado").sum()),
        "diferencias": int((df_limpio["estado_conciliacion"] == "Diferencia").sum()),
        "duplicados": int(df_limpio["bandera_duplicado_conciliacion"].sum()) if "bandera_duplicado_conciliacion" in df_limpio.columns else None,
    }])

    # 3. Vistas agrupadas dinámicas (ya eran agnósticas al nombre de la
    #    empresa/banco porque usan groupby; se mantienen)
    resumen_empresa = df_limpio.groupby("empresa").agg(
        transacciones=("transaccion_id", "count"),
        valor_total=("valor_neto", "sum"),
        mora_promedio=("dias_mora", "mean")
    ).reset_index().sort_values("mora_promedio", ascending=False)

    resumen_banco = df_limpio.groupby("banco").agg(
        transacciones=("transaccion_id", "count"),
        valor_total=("valor_neto", "sum"),
        mora_promedio=("dias_mora", "mean")
    ).reset_index().sort_values("mora_promedio", ascending=False)

    resumen_conciliacion = df_limpio.groupby(["estado_conciliacion", "nivel_riesgo"]).size().unstack(fill_value=0)

    # Evolución mensual (requiere que exista fecha_operacion; se calcula
    # aquí en vez de depender de que paso4 ya haya creado la columna "mes")
    df_mensual = df_limpio.copy()
    df_mensual["mes"] = df_mensual["fecha_operacion"].dt.to_period("M").astype(str)
    resumen_mensual = df_mensual.groupby("mes").agg(
        transacciones=("transaccion_id", "count"),
        valor_neto=("valor_neto", "sum"),
        mora_promedio=("dias_mora", "mean")
    ).reset_index()

    resumen_categoria = df_limpio.groupby("categoria").agg(
        transacciones=("transaccion_id", "count"),
        valor_total=("valor_neto", "sum")
    ).reset_index().sort_values("valor_total")

    # Detalle de anomalías: filas que violan alguna regla de negocio,
    # para que el reporte permita AUDITAR, no solo contar.
    columnas_regla = [c for c in df_limpio.columns if c.startswith("regla_")]
    if columnas_regla:
        mascara_anomalia = ~df_limpio[columnas_regla].all(axis=1)
        detalle_anomalias = df_limpio[mascara_anomalia]
    else:
        detalle_anomalias = df_limpio.iloc[0:0]

    # 4. Exportar todo a un Excel multipestaña, con contenido accionable
    try:
        with pd.ExcelWriter(ruta_reporte, engine='openpyxl') as writer:
            resumen_general.to_excel(writer, sheet_name="Resumen_General", index=False)
            resumen_empresa.to_excel(writer, sheet_name="Por_Empresa", index=False)
            resumen_banco.to_excel(writer, sheet_name="Por_Banco", index=False)
            resumen_mensual.to_excel(writer, sheet_name="Por_Mes", index=False)
            resumen_categoria.to_excel(writer, sheet_name="Por_Categoria", index=False)
            resumen_conciliacion.to_excel(writer, sheet_name="Conciliacion_x_Riesgo")
            detalle_anomalias.to_excel(writer, sheet_name="Detalle_Anomalias", index=False)
        logging.info(f"Reporte analítico exportado con éxito en: {ruta_reporte}")
    except Exception as e:
        logging.error(f"Error al exportar el reporte: {e}")

    return True
