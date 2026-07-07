# config.py
"""
Configuración central del pipeline.
Aquí viven los umbrales de negocio y la lógica de rutas de salida,
para que el pipeline sea reutilizable con cualquier dataset
(diferentes empresas, bancos, rangos de fecha) sin tocar el código
de cada fase.
"""
import os
from datetime import datetime

# --- Identificador único de esta corrida ---
# Cada ejecución genera sus propios archivos, así puedes correr el
# pipeline muchas veces con datasets distintos sin sobrescribir
# resultados anteriores.
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

# --- Carpeta raíz de salidas ---
DIR_SALIDA_BASE = os.path.join("/shared", "processed", TIMESTAMP)

# --- Umbrales de negocio (ajustables sin tocar la lógica) ---
UMBRAL_MORA_CRITICA_DIAS = 30       # días de mora para marcar un caso como crítico
UMBRAL_MORA_PROMEDIO_ALERTA = 50    # mora promedio (por banco/empresa) que dispara alerta
MAX_CASOS_ALERTA_IA = 30            # máximo de casos que se envían al LLM para clasificar


def ruta_salida(nombre_archivo, subcarpeta=None):
    destino = DIR_SALIDA_BASE if subcarpeta is None else os.path.join(DIR_SALIDA_BASE, subcarpeta)
    os.makedirs(destino, exist_ok=True)
    return os.path.join(destino, nombre_archivo)


def directorio_salida(subcarpeta):
    """
    Devuelve (y crea) una subcarpeta 
    para los pasos que escriben varios archivos en una carpeta (gráficas).
    """
    destino = os.path.join(DIR_SALIDA_BASE, subcarpeta)
    os.makedirs(destino, exist_ok=True)
    return destino
