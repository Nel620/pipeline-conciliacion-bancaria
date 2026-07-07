import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import logging

def generar_visualizaciones(df_limpio, dir_salida="graficas_output"):
    logging.info("Iniciando generación de gráficas automáticas...")
    
    # Crear carpeta si no existe
    if not os.path.exists(dir_salida):
        os.makedirs(dir_salida)

    # Configuración visual
    sns.set_style("whitegrid")
    df_limpio["mes"] = df_limpio["fecha_operacion"].dt.to_period("M").astype(str)

    # 1. Ingresos vs Egresos
    plt.figure(figsize=(8, 5))
    df_limpio["tipo_movimiento"].value_counts().plot(kind="bar", color=["#4C72B0", "#DD8452"])
    plt.title("Cantidad de transacciones: Ingresos vs Egresos")
    plt.tight_layout()
    plt.savefig(f"{dir_salida}/1_ingresos_egresos.png")
    plt.close() # CRÍTICO: Liberar memoria

    # 2. Problemas por Banco
    plt.figure(figsize=(8, 5))
    problemas = df_limpio[df_limpio["estado_conciliacion"].isin(["Pendiente", "Diferencia", "Rechazado"])]
    problemas["banco"].value_counts().plot(kind="bar", color="#C44E52")
    plt.title("Problemas de conciliación por banco")
    plt.tight_layout()
    plt.savefig(f"{dir_salida}/2_problemas_banco.png")
    plt.close()

    # 3. Mora Promedio por Empresa
    plt.figure(figsize=(8, 5))
    df_limpio.groupby("empresa")["dias_mora"].mean().sort_values().plot(kind="bar", color="#CCB974")
    plt.title("Mora promedio por empresa")
    plt.tight_layout()
    plt.savefig(f"{dir_salida}/3_mora_empresa.png")
    plt.close()

    # 4. Heatmap Banco vs Estado
    plt.figure(figsize=(8, 5))
    tabla_banco_estado = pd.crosstab(df_limpio["banco"], df_limpio["estado_conciliacion"])
    sns.heatmap(tabla_banco_estado, annot=True, fmt="d", cmap="Blues")
    plt.title("Estado de conciliación por banco")
    plt.tight_layout()
    plt.savefig(f"{dir_salida}/4_heatmap_bancos.png")
    plt.close()

    logging.info(f"Visualizaciones guardadas con éxito en la carpeta: {dir_salida}")
    return True
