"""
Estimación de composición corporal a partir de datos que el entrenador
sí puede conseguir en el gimnasio.

Los sensores sEMG no pueden medir esto. La bioimpedancia, que es la vía
eléctrica para estimar grasa corporal, necesita inyectar una corriente
alterna por el cuerpo alrededor de los 50 kHz, y el MYOblue es un
amplificador pasivo que solo lee el biopotencial del músculo. Además
muestreamos a 1000 Hz con un pasa-banda de 2 a 499 Hz, así que esa
frecuencia queda dos órdenes de magnitud fuera de lo observable. Por eso
estos valores entran a mano o se estiman con fórmulas.

Hay tres formas de obtener el porcentaje de grasa, y NO valen lo mismo
como dato de entrada para un modelo de predicción. La diferencia está
explicada en `BodyFatSource`, y es la razón por la que se guarda de
dónde salió el número y no solamente el número.
"""

from __future__ import annotations

import math
from enum import Enum

# Sexo tal como se guarda en la ficha del cliente.
SEX_MALE = "Masculino"
SEX_FEMALE = "Femenino"

# Objetivos de entrenamiento. Viven aquí y no en la capa gráfica porque
# son parte del dominio: el modelo los codifica y el generador de rutinas
# los usa para decidir series y repeticiones. La pantalla solo les pone
# icono y color encima.
#
# Los tres primeros son los que se ofrecen como tarjeta grande en el alta
# y los que el modelo va a separar. Los otros tres se conservan porque ya
# hay fichas dadas de alta con ellos y porque un entrenador que trabaja
# rehabilitación los necesita.
PRIMARY_GOAL_NAMES = ("Fuerza", "Hipertrofia", "Definición")
SECONDARY_GOAL_NAMES = ("Rehabilitación", "Resistencia", "Postura")
GOALS = PRIMARY_GOAL_NAMES + SECONDARY_GOAL_NAMES


class BodyFatSource(str, Enum):
    """
    De dónde salió el porcentaje de grasa. Importa guardarlo.

    MEASURED
        Medido con báscula de bioimpedancia o plicómetro. Es información
        real e independiente del resto de la ficha.

    NAVY
        Calculado de circunferencias (cuello, cintura y cadera). También
        es información independiente: las circunferencias no están
        contenidas en la estatura ni en el peso, así que distinguen a dos
        personas con el mismo IMC pero distinta distribución de grasa.

    ESTIMATED
        Calculado con Deurenberg, que es una combinación lineal de IMC,
        edad y sexo. Sirve para enseñarle un número al entrenador, pero
        NO aporta información nueva a un modelo que ya recibe IMC, edad y
        sexo: es esas tres variables reescritas. Meterlo como cuarta
        variable de una regresión introduce colinealidad perfecta, que
        vuelve inestables los coeficientes. Un modelo de árboles no se
        rompe, pero reparte la importancia entre columnas duplicadas y
        ensucia la interpretación.

        Por eso `features_for_model()` lo excluye.
    """

    MEASURED = "medido"
    NAVY = "medidas"
    ESTIMATED = "estimado"


def bmi(height_cm: float | None, weight_kg: float | None) -> float | None:
    """Índice de masa corporal, o None si falta alguno de los dos datos."""
    if not height_cm or not weight_kg or height_cm <= 0:
        return None
    metres = height_cm / 100.0
    return weight_kg / (metres * metres)


def bmi_category(value: float | None) -> str:
    """Clasificación de IMC según los cortes de la OMS para adultos."""
    if value is None:
        return "—"
    if value < 18.5:
        return "Bajo peso"
    if value < 25:
        return "Normal"
    if value < 30:
        return "Sobrepeso"
    return "Obesidad"


def deurenberg_body_fat(
    bmi_value: float | None,
    age_years: int | None,
    sex: str | None,
) -> float | None:
    """
    Estimación de grasa corporal de Deurenberg:

        %grasa = 1.20 x IMC + 0.23 x edad - 10.8 x sexo - 5.4

    donde sexo vale 1 en hombres y 0 en mujeres.

    Da un número razonable a nivel poblacional (error típico de unos 4
    puntos contra métodos de referencia), pero es una estimación
    estadística y no una medición: dos personas con el mismo IMC, la
    misma edad y el mismo sexo reciben exactamente el mismo resultado,
    aunque una sea fondista y la otra sedentaria.

    Se devuelve acotado a un rango fisiológico porque la fórmula es
    lineal y se dispara fuera de los rangos en los que fue ajustada.
    """
    if bmi_value is None or not age_years or sex not in (SEX_MALE, SEX_FEMALE):
        return None

    sex_term = 1.0 if sex == SEX_MALE else 0.0
    value = 1.20 * bmi_value + 0.23 * age_years - 10.8 * sex_term - 5.4
    return _clamp_body_fat(value)


def navy_body_fat(
    sex: str | None,
    height_cm: float | None,
    neck_cm: float | None,
    waist_cm: float | None,
    hip_cm: float | None = None,
) -> float | None:
    """
    Método de circunferencias de la Marina de EUA, en su forma métrica
    (Hodgdon y Beckett).

    Necesita cinta métrica y nada más. En hombres usa cintura y cuello;
    en mujeres suma la cadera, porque ahí es donde se acumula la
    diferencia de distribución.

    Error de unos 3 a 4 puntos contra densitometría, parecido al de
    Deurenberg en magnitud, pero con una diferencia que importa para lo
    que queremos hacer: este sí mide algo del cuerpo que las otras
    variables de la ficha no contienen.

    La cintura tiene que ser mayor que el cuello (y en mujeres, cintura
    más cadera mayor que el cuello). Si no lo es, la medida está mal
    tomada y se devuelve None en vez de un número inventado.
    """
    if sex not in (SEX_MALE, SEX_FEMALE):
        return None
    if not height_cm or not neck_cm or not waist_cm:
        return None

    if sex == SEX_MALE:
        girth = waist_cm - neck_cm
        if girth <= 0:
            return None
        value = (
            495.0
            / (
                1.0324
                - 0.19077 * math.log10(girth)
                + 0.15456 * math.log10(height_cm)
            )
            - 450.0
        )
    else:
        if not hip_cm:
            return None
        girth = waist_cm + hip_cm - neck_cm
        if girth <= 0:
            return None
        value = (
            495.0
            / (
                1.29579
                - 0.35004 * math.log10(girth)
                + 0.22100 * math.log10(height_cm)
            )
            - 450.0
        )

    return _clamp_body_fat(value)


def resolve_body_fat(
    manual_pct: float | None,
    sex: str | None,
    age_years: int | None,
    height_cm: float | None,
    weight_kg: float | None,
    neck_cm: float | None = None,
    waist_cm: float | None = None,
    hip_cm: float | None = None,
) -> tuple[float | None, str | None]:
    """
    Decide qué porcentaje de grasa se guarda y de dónde salió.

    El orden es por calidad del dato, de mejor a peor:
      1. El que el entrenador midió con báscula o plicómetro.
      2. El calculado de circunferencias.
      3. La estimación de Deurenberg.

    Devuelve (porcentaje, fuente). La fuente se guarda junto al valor
    porque de ella depende si el dato sirve como variable de entrada al
    modelo, ver `BodyFatSource`.
    """
    if manual_pct and manual_pct > 0:
        return (_clamp_body_fat(manual_pct), BodyFatSource.MEASURED.value)

    from_navy = navy_body_fat(sex, height_cm, neck_cm, waist_cm, hip_cm)
    if from_navy is not None:
        return (from_navy, BodyFatSource.NAVY.value)

    estimated = deurenberg_body_fat(bmi(height_cm, weight_kg), age_years, sex)
    if estimated is not None:
        return (estimated, BodyFatSource.ESTIMATED.value)

    return (None, None)


# Rangos de referencia por sexo (American Council on Exercise), usados
# solo para poner una etiqueta legible junto al número.
_FAT_RANGES = {
    SEX_MALE: ((6.0, "Esencial"), (14.0, "Atlético"), (18.0, "En forma"),
               (25.0, "Promedio"), (100.0, "Alto")),
    SEX_FEMALE: ((14.0, "Esencial"), (21.0, "Atlético"), (25.0, "En forma"),
                 (32.0, "Promedio"), (100.0, "Alto")),
}


def body_fat_category(pct: float | None, sex: str | None) -> str:
    """
    Etiqueta del porcentaje de grasa. Depende del sexo: los mismos 20%
    son "en forma" en un hombre y "atlético" en una mujer, porque la
    grasa esencial es mayor en el cuerpo femenino.
    """
    if pct is None or sex not in _FAT_RANGES:
        return "—"
    for limit, label in _FAT_RANGES[sex]:
        if pct < limit:
            return label
    return "Alto"


def features_for_model(client) -> dict[str, float] | None:
    """
    Fila de variables de un cliente, lista para alimentar un modelo.

    Lo que NO está aquí es tan importante como lo que sí:

    - El porcentaje de grasa entra solo si fue medido o calculado de
      circunferencias. Si es una estimación de Deurenberg se omite, y en
      su lugar `body_fat_is_real` queda en 0, porque Deurenberg es una
      combinación lineal de IMC, edad y sexo, que ya están en la fila.
      Duplicar información no agrega señal, solo colinealidad.

    - El objetivo se codifica one-hot y no como 1, 2, 3. Un número
      ordinal le diría al modelo que definición está "entre" fuerza e
      hipertrofia, que no significa nada.

    Devuelve None si falta algo imprescindible, para que el que llame
    pueda descartar la fila en vez de rellenar con ceros.
    """
    bmi_value = client.bmi
    if bmi_value is None or not client.age_years or client.sex not in _FAT_RANGES:
        return None

    row: dict[str, float] = {
        "bmi": bmi_value,
        "age_years": float(client.age_years),
        "height_cm": float(client.height_cm),
        "weight_kg": float(client.weight_kg),
        "sex_male": 1.0 if client.sex == SEX_MALE else 0.0,
        "experience_level": float(experience_to_number(client.experience_level)),
        "days_per_week": float(client.days_per_week or 0),
    }

    real_fat = (
        client.body_fat_pct
        if client.body_fat_source in (BodyFatSource.MEASURED.value, BodyFatSource.NAVY.value)
        else None
    )
    row["body_fat_pct"] = float(real_fat) if real_fat is not None else 0.0
    row["body_fat_is_real"] = 1.0 if real_fat is not None else 0.0

    for goal in GOALS:
        row[f"goal_{_slug(goal)}"] = 1.0 if client.goal == goal else 0.0

    return row


# Nivel de experiencia: afecta cuánto volumen tolera el cliente y qué
# tan rápido se recupera. Se guarda el texto y se convierte a número
# ordinal solo para el modelo, donde el orden sí tiene sentido (más
# experiencia es más experiencia, no una categoría suelta).
EXPERIENCE_LEVELS = ("Principiante", "Intermedio", "Avanzado")


def experience_to_number(level: str | None) -> int:
    """0 cuando no se capturó, 1 a 3 según el nivel."""
    if level not in EXPERIENCE_LEVELS:
        return 0
    return EXPERIENCE_LEVELS.index(level) + 1


def _clamp_body_fat(value: float) -> float:
    """
    Acota a un rango fisiológicamente posible.

    Las dos fórmulas son ajustes empíricos y se disparan fuera de los
    rangos con los que se calibraron: Deurenberg es lineal y con un IMC
    muy alto devuelve porcentajes imposibles. El límite inferior es la
    grasa esencial, por debajo de la cual no hay vida.
    """
    return float(min(max(value, 3.0), 65.0))


def _slug(text: str) -> str:
    """Nombre de columna sin acentos ni espacios."""
    table = str.maketrans("áéíóúñÁÉÍÓÚÑ", "aeiounAEIOUN")
    return text.translate(table).lower().replace(" ", "_")
