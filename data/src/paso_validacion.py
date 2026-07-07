import logging
import pandas as pd
import pandera.pandas as pa
from pandera import Column, Check, DataFrameSchema

"""
Módulo de auditoría/validación de datos con Pandera.

Se ejecuta en DOS puntos del pipeline:

  1) Justo después del Paso 1 (lectura cruda, antes de limpiar nada).
     -> Reglas "de entrada": si el archivo viene corrupto o con trampas
        (mora negativa, mora de 900 días, movimientos sin tipo, etc.)
        se rechaza ANTES de gastar tiempo limpiando o graficando.

  2) Justo después del Paso 2 (datos ya limpios y con columnas de
     reglas de negocio calculadas: regla_signo_valida, etc.)
     -> Reglas "de salida": confirma que la limpieza no dejó nada roto.

Si el archivo NO pasa, el pipeline se detiene con ValueError y te
entrega en `err.failure_cases` la lista EXACTA de filas/columnas
sospechosas (no una suposición ni un promedio: fila por fila).
"""

# ------------------------------------------------------------------
# Esquema 1: Auditoría inicial -> corre sobre el DataFrame crudo que
# devuelve paso1_lectura.cargar_y_auditar()
# ------------------------------------------------------------------
schema_auditoria_inicial = DataFrameSchema(
    {
        "transaccion_id": Column(nullable=False, unique=True, required=True),
        "empresa": Column(nullable=False, required=True),
        "banco": Column(nullable=False, required=True),

        # Regla estricta que pediste: mora fuera de [0, 365] -> rechazo
        "dias_mora": Column(
            checks=Check.in_range(0, 365, include_min=True, include_max=True),
            nullable=False,
            coerce=True,
            required=True,
        ),

        "valor_bruto": Column(coerce=True, nullable=False, required=True),
        "valor_neto": Column(coerce=True, nullable=False, required=True),

        "tipo_movimiento": Column(
            checks=Check.isin(["Ingreso", "Egreso"]),
            nullable=False,
            required=True,
        ),
        "estado_conciliacion": Column(
            checks=Check.isin(
                ["Conciliado", "Pendiente", "Diferencia", "Rechazado", "Duplicado"]
            ),
            nullable=False,
            required=True,
        ),
    },
    strict=False,  # permite columnas extra que no listamos aquí (no las bloquea)
)

# ------------------------------------------------------------------
# Esquema 2: Validación post-limpieza -> corre sobre df_limpio, que ya
# trae las columnas "regla_*" calculadas por paso2_limpieza.py
# ------------------------------------------------------------------
schema_post_limpieza = DataFrameSchema(
    {
        "dias_mora": Column(checks=Check.in_range(0, 365), nullable=False, required=True),
        "valor_neto": Column(nullable=False, required=True),

        # Estas columnas ya son booleanas (True = regla cumplida).
        # Si alguna fila quedó en False, aquí se detecta y se lista.
        "regla_signo_valida": Column(checks=Check.eq(True), required=False),
        "regla_valor_neto_valida": Column(checks=Check.eq(True), required=False),
        "regla_fechas_valida": Column(checks=Check.eq(True), required=False),
        "regla_mora_valida": Column(checks=Check.eq(True), required=False),
    },
    strict=False,
)


def validar_dataframe(df, schema, etiqueta="Validación"):
    """
    Corre `schema` en modo lazy=True (Pandera recolecta TODOS los
    errores del archivo, no se detiene en el primero que encuentra).

    Retorna:
        (df_validado, df_fallas)
        - df_validado: el mismo DataFrame, ya tipado/coercido, si pasó.
        - df_fallas: DataFrame vacío si todo pasó.

    Lanza ValueError si hay al menos una fila sospechosa, deteniendo
    el pipeline. El detalle fila-por-fila queda en err.failure_cases
    dentro de la excepción original (encadenada con `raise ... from`).
    """
    logging.info(f"🔍 Iniciando {etiqueta} con Pandera...")

    try:
        df_validado = schema.validate(df, lazy=True)
    except pa.errors.SchemaErrors as err:
        filas_fallidas = err.failure_cases

        logging.error(
            f"❌ ¡ALERTA! {etiqueta} NO PASÓ LA AUDITORÍA. "
            f"Se encontraron {len(filas_fallidas)} valores sospechosos."
        )
        logging.error("⚠️  Detalle exacto (fila, columna, valor y regla incumplida):")

        for _, fila in filas_fallidas.head(20).iterrows():
            logging.error(
                f"   🚩 Fila {fila.get('index')} | Columna: {fila.get('column')} | "
                f"Valor encontrado: {fila.get('failure_case')} | "
                f"Regla incumplida: {fila.get('check')}"
            )

        if len(filas_fallidas) > 20:
            logging.error(
                f"   ... y {len(filas_fallidas) - 20} filas adicionales. "
                f"Consulta err.failure_cases para verlas todas."
            )

        raise ValueError(
            f"🛑 Pipeline detenido: los datos no pasaron {etiqueta}. "
            f"Corrige el archivo de origen y vuelve a correr el pipeline."
        ) from err

    logging.info(f"✅ {etiqueta} COMPLETA: el archivo es 100% confiable, sin filas sospechosas.")
    return df_validado, pd.DataFrame()
