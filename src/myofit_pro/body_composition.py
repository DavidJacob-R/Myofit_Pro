"""Composición corporal y codificación de la ficha del cliente.

Este módulo resuelve dos cosas para el resto de la aplicación:

1. Derivar índices antropométricos (IMC, porcentaje de grasa) a partir de
   los datos que el entrenador captura en la ficha del cliente.
2. Convertir esa ficha en un vector de variables numéricas apto para un
   modelo de aprendizaje automático.

Posición en el flujo
--------------------
La ficha se captura en ``gui.client_form`` y se persiste en
``database.models.Client``. Las propiedades ``Client.bmi`` y
``Client.body_fat_is_measured`` delegan aquí. El generador de rutinas
(``routine_engine``) consume ``GOALS`` y ``EXPERIENCE_LEVELS``.

Los sensores no intervienen: el sEMG es un amplificador pasivo del
biopotencial muscular y no puede estimar grasa corporal. La vía eléctrica
para ello es la bioimpedancia, que inyecta corriente alterna en torno a
los 50 kHz; la adquisición de esta aplicación muestrea a 1 kHz con un
pasa-banda de 2 a 499 Hz, dos órdenes de magnitud por debajo.

Procedencia del dato de grasa
-----------------------------
Existen tres vías para obtener el porcentaje de grasa y **no son
equivalentes como variable de entrada a un modelo**. La distinción se
persiste en ``Client.body_fat_source`` y está documentada en
`BodyFatSource`


--------
myofit_pro.routine_engine : Consume los objetivos y niveles de experiencia.
myofit_pro.ml.benchmark : Evalúa qué modelos aprovechan estas variables.

References
----------
.. [1] Deurenberg, P., Weststrate, J. A., & Seidell, J. C. (1991).
       "Body mass index as a measure of body fatness: age- and
       sex-specific prediction formulas". *British Journal of Nutrition*,
       65(2), 105-114.
.. [2] Hodgdon, J. A., & Beckett, M. B. (1984). "Prediction of percent
       body fat for U.S. Navy men and women from body circumferences and
       height". Naval Health Research Center, Report No. 84-11.
.. [3] World Health Organization (2000). "Obesity: preventing and
       managing the global epidemic". WHO Technical Report Series 894.
.. [4] American Council on Exercise. "Percent body fat norms for men and
       women".
"""

from __future__ import annotations

import math
from enum import Enum

SEX_MALE = "Masculino"

SEX_FEMALE = "Femenino"

#: Objetivos principales de entrenamiento. Se presentan como tarjeta
#: destacada en el alta de cliente y son los que el generador de rutinas
#: diferencia con esquemas propios de series, repeticiones e intensidad.
PRIMARY_GOAL_NAMES = ("Fuerza", "Hipertrofia", "Definición")

#: Objetivos secundarios. Se conservan porque hay fichas dadas de alta
#: con ellos y porque un entrenador que trabaja rehabilitación los
#: necesita, pero no son el caso de uso central y todavia estamos en investigación.
SECONDARY_GOAL_NAMES = ("Rehabilitación", "Resistencia", "Postura")

#: Conjunto completo de objetivos admitidos. `features_for_model` lo
#: recorre para generar las columnas one-hot del objetivo.
GOALS = PRIMARY_GOAL_NAMES + SECONDARY_GOAL_NAMES

#: Niveles de experiencia admitidos, en orden ascendente. El orden es
#: significativo: `experience_to_number` lo codifica como variable
#: ordinal, y el generador de rutinas ajusta volumen y proximidad al
#: fallo en función del nivel.
EXPERIENCE_LEVELS = ("Principiante", "Intermedio", "Avanzado")

#: Límite inferior del rango fisiológico de grasa corporal, en porciento
#:Corresponde a la grasa esencial para subsistir.
MIN_BODY_FAT_PCT = 3.0

#: Límite superior del rango fisiológico de grasa corporal, en porciento.
MAX_BODY_FAT_PCT = 65.0


class BodyFatSource(str, Enum):
    """Procedencia del porcentaje de grasa corporal almacenado.

    El valor se persiste en ``Client.body_fat_source`` junto al
    porcentaje. La distinción determina si el dato constituye información
    independiente o una transformación de variables ya presentes en la
    ficha.

    Attributes
    ----------
    MEASURED : 
        Medido con báscula de bioimpedancia o plicómetro. Información
        real e independiente del resto de la ficha.
    NAVY : 
        Calculado a partir de circunferencias mediante el método de la
        Marina de EUA. También independiente: las circunferencias
        distinguen a dos sujetos con idéntico IMC pero distinta
        distribución de grasa.
    ESTIMATED : 
        Calculado con la fórmula de Deurenberg, que es una combinación
        lineal de IMC, edad y sexo.

    Notes
    -----
    La estimación de Deurenberg es útil para mostrar un valor de
    referencia al entrenador, pero **no aporta información nueva** a un
    modelo que ya recibe IMC, edad y sexo: es esas tres variables
    reescritas. Introducirla como cuarta variable en una regresión
    produce colinealidad perfecta, lo que vuelve inestables los
    coeficientes. Un modelo basado en árboles no falla, pero reparte la
    importancia entre columnas redundantes y dificulta la
    interpretación.

    Por este motivo `features_for_model` excluye los valores con esta
    procedencia. La clase ``TestColinealidad`` de
    ``tests/test_body_composition.py`` lo demuestra numéricamente.
    """

    MEASURED = "medido"
    NAVY = "medidas"
    ESTIMATED = "estimado"


def bmi(height_cm: float | None, weight_kg: float | None) -> float | None:
    """Calcula el índice de masa corporal.
    Returns
    -------
    float or None
        Índice de masa corporal en kg/m². Devuelve ``None`` si falta
        alguno de los dos datos o si la estatura no es positiva.

    """
    if not height_cm or not weight_kg or height_cm <= 0:
        return None
    metres = height_cm / 100.0
    return weight_kg / (metres * metres)


def bmi_category(value: float | None) -> str:
    """Clasifica un índice de masa corporal según los cortes de la OMS.

    ----------
        Índice de masa corporal en kg/m².

    Returns
    -------
        Una de ``"Bajo peso"``, ``"Normal"``, ``"Sobrepeso"`` u
        ``"Obesidad"``. Devuelve ``"—"`` si `value` es ``None``.

    Notes
    -----
    Los cortes son 18.5, 25 y 30 kg/m², aplicables a población adulta
    [3]_. No corrigen por masa muscular, por lo que un sujeto entrenado
    puede clasificarse como sobrepeso sin exceso de grasa.
    """
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
    """Estima el porcentaje de grasa corporal mediante Deurenberg.

    Aplica la ecuación::

        %grasa = 1.20 · IMC + 0.23 · edad − 10.8 · sexo − 5.4

    donde ``sexo`` vale 1 en hombres y 0 en mujeres [1]_.

    Returns
    -------
    float or None
        Porcentaje de grasa acotado al rango
        ``[MIN_BODY_FAT_PCT, MAX_BODY_FAT_PCT]``. Devuelve ``None`` si


    Notes
    -----
    El error típico frente a métodos de referencia es de unos 4 puntos
    porcentuales a nivel poblacional. Es una estimación estadística, no
    una medición: dos sujetos con idéntico IMC, edad y sexo reciben
    exactamente el mismo resultado con independencia de su composición
    real.

    El resultado se acota porque la ecuación es lineal y extrapola fuera
    de los rangos en los que fue ajustada.
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
    """Estima el porcentaje de grasa por circunferencias (método Navy).

    Implementa la forma métrica de las ecuaciones de Hodgdon y Beckett
    [2]_. En hombres::

        %grasa = 495 / (1.0324 − 0.19077·log₁₀(cintura − cuello)
                        + 0.15456·log₁₀(estatura)) − 450

    En mujeres se sustituye ``cintura − cuello`` por
    ``cintura + cadera − cuello`` con coeficientes propios.

    Returns
    -------
    float or None
        Porcentaje de grasa acotado al rango fisiológico, o ``None`` si
        falta algún dato necesario o si las medidas son incoherentes.


    Notes
    -----
    Solo requiere cinta métrica. Su error frente a densitometría es de 3
    a 4 puntos porcentuales, comparable al de Deurenberg en magnitud,
    pero con una diferencia relevante: mide una característica del cuerpo
    que las demás variables de la ficha no contienen.

    Cuando la cintura no supera al cuello (o, en mujeres, cuando cintura
    más cadera no supera al cuello) el logaritmo queda indefinido. Eso
    indica una medida mal tomada, y la función devuelve ``None`` en lugar
    de un valor arbitrario.
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
    """Selecciona el porcentaje de grasa de mejor calidad disponible.

    Evalúa las tres fuentes en orden descendente de calidad y devuelve la
    primera que pueda resolverse.
    ----------
    manual_pct : float or None
        Porcentaje medido con báscula de bioimpedancia o plicómetro.
    sex : str or None
        `SEX_MALE` o `SEX_FEMALE`.
    age_years : int or None
        Edad en años cumplidos.
    height_cm : float or None
        Estatura en centímetros.
    weight_kg : float or None
        Peso en kilogramos.
    neck_cm, waist_cm, hip_cm : float, optional
        Circunferencias para el método Navy.

    Returns
    -------
    tuple of (float or None, str or None)
        Par ``(porcentaje, procedencia)``, donde la procedencia es el
        valor de un miembro de `BodyFatSource`. Ambos elementos son
        ``None`` si no hay datos suficientes para ninguna de las tres
        vías.


    Notes
    -----
    El orden de preferencia es medición directa, circunferencias y, en
    último lugar, Deurenberg. La procedencia se devuelve junto al valor
    porque de ella depende si el dato es admisible como variable de
    entrada a un modelo.
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


#: Cortes de clasificación de grasa corporal por sexo, como pares
#: ``(límite superior, etiqueta)`` en orden ascendente [4]_. Difieren
#: entre sexos porque la grasa esencial es mayor en el cuerpo femenino.
_FAT_RANGES = {
    SEX_MALE: ((6.0, "Esencial"), (14.0, "Atlético"), (18.0, "En forma"),
               (25.0, "Promedio"), (100.0, "Alto")),
    SEX_FEMALE: ((14.0, "Esencial"), (21.0, "Atlético"), (25.0, "En forma"),
                 (32.0, "Promedio"), (100.0, "Alto")),
}


def body_fat_category(pct: float | None, sex: str | None) -> str:
    """Clasifica un porcentaje de grasa según los rangos de referencia.

    Returns
    -------
        Una de ``"Esencial"``, ``"Atlético"``, ``"En forma"``,
        ``"Promedio"`` o ``"Alto"``. Devuelve ``"—"`` si falta el
        porcentaje o el sexo no es reconocido.
    """
    if pct is None or sex not in _FAT_RANGES:
        return "—"
    for limit, label in _FAT_RANGES[sex]:
        if pct < limit:
            return label
    return "Alto"


def features_for_model(client) -> dict[str, float] | None:
    """Codifica la ficha de un cliente como vector de variables.


    Returns
    -------
        Diccionario de nombre de variable a valor. Devuelve ``None`` si
        falta IMC, edad o sexo, de modo que quien llame pueda descartar
        la fila en lugar de imputar ceros.

    Notes
    -----
    Dos decisiones de codificación condicionan la validez del vector:

    **Grasa corporal.** Solo se incluye el valor si su procedencia es
    `BodyFatSource.MEASURED` o `BodyFatSource.NAVY`. Las estimaciones de
    Deurenberg se omiten porque son una combinación lineal de IMC, edad y
    sexo, ya presentes en el vector; incluirlas introduciría colinealidad
    sin aportar señal. La columna auxiliar ``body_fat_is_real`` indica si
    el valor es utilizable, de modo que el modelo pueda distinguir un
    cero imputado de una medición.

    **Objetivo.** Se codifica one-hot y no como entero ordinal. Un valor
    ordinal implicaría que "Definición" se sitúa entre "Fuerza" e
    "Hipertrofia" en alguna escala, lo que carece de sentido.

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


def experience_to_number(level: str | None) -> int:
    """Codifica el nivel de experiencia como variable ordinal.

    Returns
    -------
        1 para principiante, 2 para intermedio y 3 para avanzado.
        Devuelve 0 cuando el nivel no se capturó o no es reconocido.

    Notes
    -----
    A diferencia del objetivo, aquí la codificación ordinal sí es
    apropiada: el orden entre niveles es real y monótono.
    """
    if level not in EXPERIENCE_LEVELS:
        return 0
    return EXPERIENCE_LEVELS.index(level) + 1


def _clamp_body_fat(value: float) -> float:
    """Acota un porcentaje de grasa al rango fisiológicamente posible.

    Notes
    -----
    Ambas ecuaciones son ajustes empíricos y extrapolan mal: Deurenberg
    es lineal y con un IMC muy elevado devuelve porcentajes imposibles.
    El límite inferior corresponde a la grasa esencial.
    """
    return float(min(max(value, MIN_BODY_FAT_PCT), MAX_BODY_FAT_PCT))


def _slug(text: str) -> str:
    """Normaliza un texto para usarlo como nombre de columna.
    """
    table = str.maketrans("áéíóúñÁÉÍÓÚÑ", "aeiounAEIOUN")
    return text.translate(table).lower().replace(" ", "_")
