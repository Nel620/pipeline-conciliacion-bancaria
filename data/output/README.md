# Guía de archivos generados por esta corrida

Esta carpeta contiene los resultados de una ejecución del pipeline de conciliación bancaria. 

| Archivo                          | Contenido                                                                 | Generado por |
|-----------------------------------|----------------------------------------------------------------------------|--------------|
| `reporte_estructurado.xlsx`       | Reporte analítico multipestaña: resumen general, por empresa, por banco, por mes, por categoría, conciliación vs. riesgo y detalle de anomalías | Paso 3 |
| `graficas_output/1_ingresos_egresos.png` | Cantidad de transacciones: Ingresos vs. Egresos | Paso 4 |
| `graficas_output/2_problemas_banco.png`  | Transacciones con problemas de conciliación (Pendiente, Diferencia, Rechazado), agrupadas por banco | Paso 4 |
| `graficas_output/3_mora_empresa.png`     | Mora promedio (días) por empresa | Paso 4 |
| `graficas_output/4_heatmap_bancos.png`   | Mapa de calor: estado de conciliación por banco | Paso 4 |
| `reporte_ejecutivo.md`            | Resumen ejecutivo redactado por IA (Gemini) para Gerencia de Riesgo: panorama general, hallazgos, preguntas clave y recomendación | Paso 5 |
| `clasificacion_alertas.json`     | Listado de los casos de alerta más críticos (mayor mora / mayor valor), con prioridad e insight asignados por IA | Paso 5 |

## Notas

- `reporte_ejecutivo.md` incluye una validación automática: si la IA no repite la cifra exacta de alertas críticas calculada por el pipeline, el reporte no se genera (para evitar reportes con datos alucinados).
- Si `clasificacion_alertas.json` tiene `"estado": "ERROR"`, significa que la clasificación con IA falló (ej. límite de solicitudes de la API) y se generó un archivo de respaldo. Los casos completos siguen disponibles en la pestaña `Detalle_Anomalias` de `reporte_estructurado.xlsx`.
- Esta carpeta y su contenido **no se suben a Git** (ver `.gitignore` del repositorio).
