import pandas as pd
import logging

# Configuramos alertas de sistema en lugar de usar 'print'
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def cargar_y_auditar(ruta_archivo):
    logging.info(f"Iniciando extracción de: {ruta_archivo}")
    df = pd.read_excel(ruta_archivo)
    
    # Auditoría silenciosa
    nulos = df.isnull().sum().sum()
    if nulos > 0:
        logging.warning(f"Se detectaron {nulos} valores nulos en la base bancaria.")
        
    # Tu alerta de mora adaptada al pipeline
    casos_mora = len(df[df['dias_mora'] > 30])
    if casos_mora > 0:
        logging.warning(f"Alerta: {casos_mora} casos con mora crítica (>30 días).")
        
    logging.info("Lectura y auditoría fase 1 completada con éxito.")
    return df

# Ejecución de prueba
if __name__ == "__main__":
    df_inicial = cargar_y_auditar("dataset_bancario_empresarial.xlsx")
