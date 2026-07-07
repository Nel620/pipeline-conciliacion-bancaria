# Análisis de Dataset Bancario Empresarial

Proyecto de análisis de datos financieros/bancarios (dataset sintético)
con Python: limpieza, análisis exploratorio, visualización y generación
de reportes ejecutivos con IA (Gemini).

## Estructura
1. `01_exploracion_dataset_bancario.ipynb` – EDA inicial
2. `02_limpieza_dataset_bancario.ipynb` – Limpieza y validación de reglas de negocio
3. `03_analisis_agrupaciones.ipynb` – Agrupaciones y cruces (groupby, crosstab)
4. `04_visualizacion_datos.ipynb` – Gráficas clave del análisis
5. `05_analisis_inteligencia_artificial.ipynb` – Reporte ejecutivo y clasificación de alertas con IA

## Datos
`dataset_bancario_empresarial.xlsx` — datos sintéticos, 150 transacciones.

## Requisitos
pandas, numpy, matplotlib, seaborn, google-genai, python-dotenv

## Nota
El notebook 05 requiere una `GEMINI_API_KEY` en un archivo `.env` (no incluido).
