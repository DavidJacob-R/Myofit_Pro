"""Generador de datos sintéticos para la validación de algoritmos.

Posición en el flujo
--------------------
Fuera del flujo de la aplicación. Produce conjuntos de datos con la misma
forma que los que la aplicación acumula, para poder ejercitar la cadena de
modelado antes de disponer de historial real. `myofit_pro.ml.benchmark`
es su consumidor principal.

Alcance
-------
Este módulo permite:

- verificar la integridad de la cadena de modelado: que las variables
  llegan completas, que la validación cruzada está correctamente
  construida y que no existe fuga de información entre particiones;
- estimar la curva de aprendizaje, es decir, cuántos clientes hacen falta
  para que un modelo supere a la predicción por la media;
- comparar algoritmos en condiciones idénticas;
- demostrar problemas metodológicos, como la fuga por cliente.

Este módulo **no** permite:

- validar la hipótesis fisiológica. Los datos proceden de las fórmulas
  codificadas en `GroundTruth`. Que un modelo las recupere demuestra que
  el modelo sabe ajustar lo que se le ha inyectado, no que la edad o el
  porcentaje de grasa expliquen realmente la fatiga en personas;
- informar de un coeficiente de determinación como si describiera el
  mundo real.

En resumen, valida el código, no la ciencia. Esta última solo se valida
con los clientes reales del gimnasio.

Relaciones simuladas
--------------------
Las direcciones siguen lo reportado por la literatura de electromiografía
de superficie; las magnitudes son arbitrarias. Se exportan a
``verdad_base.json`` para poder comprobar si un algoritmo las recupera.

- El tejido adiposo subcutáneo atenúa la amplitud sEMG por interponerse
  entre el músculo y el electrodo.
- Una mayor experiencia de entrenamiento se asocia a mejor reclutamiento
  de unidades motoras y, por tanto, a mayor activación relativa.
- La fatiga se modela como la caída de la frecuencia mediana repetición a
  repetición, más rápida en personas menos entrenadas y de más edad.
- Cada cliente tiene una afinidad propia por cada ejercicio: el mismo
  ejercicio no activa igual el mismo músculo en dos personas. Es
  precisamente lo que los sensores pueden descubrir y una tabla no.
- Cada cliente tiene un efecto aleatorio propio, de modo que sus
  evaluaciones se parecen entre sí más que a las de otros. Esta
  dependencia es la que obliga a validar agrupando por cliente.

Uso
---
::

    uv run python -m myofit_pro.ml.synthetic --clientes 60 --salida datos/

See Also
--------
myofit_pro.ml.benchmark : Consumidor de estos datos.
myofit_pro.ml.within_subject : Análisis del diseño alternativo.

References
----------
.. [1] Nordander, C. et al. (2003). "Influence of the subcutaneous fat
       layer, as measured by ultrasound, on the surface EMG amplitude".
       *European Journal of Applied Physiology*, 89(6), 514-519.
.. [2] Gelman, A. y Hill, J. (2006). *Data Analysis Using Regression and
       Multilevel/Hierarchical Models*. Cambridge University Press.
       Capítulo 12, sobre efectos aleatorios por grupo.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from myofit_pro.body_composition import (
    PRIMARY_GOAL_NAMES,
    SEX_FEMALE,
    SEX_MALE,
    bmi,
    deurenberg_body_fat,
    navy_body_fat,
)

#: Músculos del catálogo reducido. Basta con cuatro para que los datos
#: tengan la estructura anidada músculo-ejercicio de los reales.
MUSCLES = ("Bíceps braquial", "Tríceps braquial", "Cuádriceps", "Dorsal ancho")

#: Ejercicios disponibles para cada músculo del catálogo reducido.
EXERCISES = {
    "Bíceps braquial": ("Curl con barra", "Curl inclinado", "Curl martillo", "Curl predicador"),
    "Tríceps braquial": ("Fondos", "Extensión en polea", "Press francés", "Patada de tríceps"),
    "Cuádriceps": ("Sentadilla", "Prensa", "Extensión de rodilla", "Zancadas"),
    "Dorsal ancho": ("Dominadas", "Remo con barra", "Jalón al pecho", "Remo en polea"),
}

#: Niveles de experiencia, en orden creciente. El índice más uno es el
#: valor numérico que entra en las fórmulas generadoras.
EXPERIENCE_LEVELS = ("Principiante", "Intermedio", "Avanzado")


@dataclass
class GroundTruth:
    """Coeficientes con los que se generan los datos sintéticos.

    Se serializan a ``verdad_base.json`` para poder contrastar si un
    algoritmo recupera las relaciones inyectadas. Un modelo incapaz de
    recuperar una relación presente por construcción tampoco encontrará
    las que pueda haber en los datos reales.

    Attributes
    ----------
    activacion_base : float
        Activación media de partida, en porcentaje de la contracción
        voluntaria máxima.
    activacion_por_grasa : float
        Variación de la activación por cada 10 puntos de grasa corporal
        por encima del 20 %. Negativa: el tejido adiposo atenúa la señal.
    activacion_por_experiencia : float
        Variación por nivel de experiencia, de 1 a 3.
    activacion_por_edad : float
        Variación por cada 10 años por encima de los 30.
    activacion_ruido : float
        Desviación típica del error de medición de la activación.
    fatiga_base : float
        Pendiente de partida de la frecuencia mediana, en hercios por
        repetición. Negativa, porque el espectro desciende con la fatiga.
    fatiga_por_experiencia : float
        Variación de la pendiente por nivel de experiencia. Positiva: a
        mayor entrenamiento, caída más lenta.
    fatiga_por_edad : float
        Variación por cada 10 años por encima de los 30.
    fatiga_por_grasa : float
        Variación por cada 10 puntos de grasa por encima del 20 %.
    fatiga_ruido : float
        Desviación típica del error de la pendiente.
    fatiga_minima, fatiga_maxima : float
        Límites fisiológicos de la pendiente. El extremo superior es
        próximo a cero pero negativo: una persona muy entrenada se fatiga
        poco, pero el espectro no asciende de forma sostenida a lo largo
        de una serie.
    efecto_cliente_activacion, efecto_cliente_fatiga : float
        Desviación típica del efecto aleatorio de cada cliente. Es la
        fuente de dependencia que obliga a validar por grupo.
    afinidad_ejercicio : float
        Desviación típica de la afinidad de un cliente por un ejercicio
        concreto. Es idiosincrásica: no se deduce de la edad ni del peso,
        solo midiendo a esa persona, y constituye la razón de ser de los
        sensores.
    efecto_ejercicio_poblacional : float
        Desviación típica del efecto medio de cada ejercicio, común a
        todos los clientes. A diferencia de la afinidad, sí se aprende
        del historial de unos clientes y se aplica a un cliente nuevo.
    notas : list of str
        Advertencias que acompañan al archivo exportado.
    """

    activacion_base: float = 62.0
    activacion_por_grasa: float = -3.2
    activacion_por_experiencia: float = 4.5
    activacion_por_edad: float = -1.8
    activacion_ruido: float = 4.0

    fatiga_base: float = -2.6
    fatiga_por_experiencia: float = 0.55
    fatiga_por_edad: float = -0.30
    fatiga_por_grasa: float = -0.18
    fatiga_ruido: float = 0.35

    fatiga_minima: float = -6.0
    fatiga_maxima: float = -0.15

    efecto_cliente_activacion: float = 6.0
    efecto_cliente_fatiga: float = 0.5

    afinidad_ejercicio: float = 7.0

    efecto_ejercicio_poblacional: float = 5.5

    notas: list[str] = field(
        default_factory=lambda: [
            "Las direcciones siguen la literatura de sEMG; las magnitudes son inventadas.",
            "Recuperar estos coeficientes valida el algoritmo, no la hipótesis.",
        ]
    )


def _experience_number(level: str) -> int:
    """Convierte un nivel de experiencia en su valor numérico, de 1 a 3."""
    return EXPERIENCE_LEVELS.index(level) + 1


def generate_clients(n: int, rng: np.random.Generator) -> pd.DataFrame:
    """Genera fichas de cliente con la estructura que captura la aplicación.

    Parameters
    ----------
    n : int
        Clientes a generar.
    rng : numpy.random.Generator
        Generador de números aleatorios.

    Returns
    -------
    pandas.DataFrame
        Una fila por cliente, con las columnas de la ficha más
        ``experience_num``, la codificación numérica del nivel.

    Notes
    -----
    Las variables antropométricas se generan correlacionadas, como en la
    población real: la estatura depende del sexo, el peso de la estatura
    a través del índice de masa corporal, y la grasa corporal del sexo y
    de las circunferencias. Generarlas de forma independiente produciría
    combinaciones imposibles y, lo que es peor, dejaría a los modelos
    con predictores no correlacionados entre sí, que es el caso
    favorable y no el real.

    El porcentaje de grasa se calcula por el método de circunferencias y
    se recurre a Deurenberg solo si aquel no es aplicable, replicando la
    jerarquía que sigue la aplicación.
    """
    rows = []
    for client_id in range(1, n + 1):
        sex = SEX_MALE if rng.random() < 0.55 else SEX_FEMALE
        age = int(np.clip(rng.normal(34, 11), 16, 70))

        if sex == SEX_MALE:
            height = float(np.clip(rng.normal(174, 7), 152, 198))
            base_bmi = rng.normal(26.0, 3.6)
            neck = float(np.clip(rng.normal(38.5, 2.4), 30, 50))
        else:
            height = float(np.clip(rng.normal(161, 6.5), 143, 185))
            base_bmi = rng.normal(24.8, 4.2)
            neck = float(np.clip(rng.normal(32.5, 2.0), 27, 43))

        base_bmi = float(np.clip(base_bmi, 17.0, 40.0))
        weight = round(base_bmi * (height / 100.0) ** 2, 1)

        # La cintura se correlaciona con el IMC más una variación propia:
        # dos personas con el mismo IMC pueden tener cinturas distintas, y
        # esa diferencia es justamente lo que detecta el método de
        # circunferencias.
        waist = float(
            np.clip(
                (58 if sex == SEX_FEMALE else 62) + 1.55 * base_bmi + rng.normal(0, 4.5),
                58, 145,
            )
        )
        hip = (
            float(np.clip(waist + rng.normal(14, 5), waist + 2, waist + 35))
            if sex == SEX_FEMALE
            else None
        )

        body_fat = navy_body_fat(sex, height, neck, waist, hip)
        if body_fat is None:
            body_fat = deurenberg_body_fat(bmi(height, weight), age, sex)

        # Distribución de experiencia sesgada hacia el principiante, como
        # en la clientela de un gimnasio.
        experience = str(rng.choice(EXPERIENCE_LEVELS, p=[0.45, 0.38, 0.17]))
        days = int(rng.choice([3, 4, 5], p=[0.45, 0.35, 0.20]))
        goal = str(rng.choice(PRIMARY_GOAL_NAMES, p=[0.25, 0.45, 0.30]))

        rows.append(
            {
                "client_id": client_id,
                "sex": sex,
                "age_years": age,
                "height_cm": round(height, 1),
                "weight_kg": weight,
                "bmi": round(bmi(height, weight), 2),
                "neck_cm": round(neck, 1),
                "waist_cm": round(waist, 1),
                "hip_cm": round(hip, 1) if hip else None,
                "body_fat_pct": round(body_fat, 1),
                "body_fat_source": "medidas",
                "experience_level": experience,
                "experience_num": _experience_number(experience),
                "days_per_week": days,
                "goal": goal,
            }
        )

    return pd.DataFrame(rows)


def generate_evaluations(
    clients: pd.DataFrame,
    rng: np.random.Generator,
    truth: GroundTruth,
    evals_per_client: tuple[int, int] = (2, 9),
) -> pd.DataFrame:
    """Genera las evaluaciones sEMG de un conjunto de clientes.

    Parameters
    ----------
    clients : pandas.DataFrame
        Fichas de cliente, tal como las devuelve `generate_clients`.
    rng : numpy.random.Generator
        Generador de números aleatorios.
    truth : GroundTruth
        Coeficientes generadores.
    evals_per_client : tuple of int, default=(2, 9)
        Rango cerrado de evaluaciones por cliente.

    Returns
    -------
    pandas.DataFrame
        Una fila por evaluación, con los identificadores de sesión y
        cliente, el músculo y ejercicio medidos, y las dos variables
        objetivo: ``fatigue_slope_hz_per_rep`` y
        ``mean_activation_pct``.

    Notes
    -----
    El número de evaluaciones por cliente es deliberadamente desigual: en
    la práctica unos clientes se evalúan una vez y otros doce. Un
    conjunto equilibrado ocultaría que los clientes con más historial
    dominan el entrenamiento del modelo.

    El efecto poblacional de cada ejercicio se sortea una sola vez, fuera
    del bucle de clientes, lo que lo hace común a todos y por tanto
    aprendible del historial ajeno. La afinidad, en cambio, se sortea
    dentro del bucle y solo es observable midiendo a esa persona.
    """
    rows = []
    session_id = 0

    exercise_effect = {
        exercise: rng.normal(0, truth.efecto_ejercicio_poblacional)
        for muscle in MUSCLES
        for exercise in EXERCISES[muscle]
    }

    for _, client in clients.iterrows():
        # Constante en todas las evaluaciones de este cliente: es la
        # fuente de dependencia que obliga a validar por grupo.
        client_offset_act = rng.normal(0, truth.efecto_cliente_activacion)
        client_offset_fat = rng.normal(0, truth.efecto_cliente_fatiga)

        affinity = {
            exercise: rng.normal(0, truth.afinidad_ejercicio)
            for muscle in MUSCLES
            for exercise in EXERCISES[muscle]
        }

        experience = int(client["experience_num"])
        age_term = (client["age_years"] - 30) / 10.0
        fat_term = (client["body_fat_pct"] - 20) / 10.0

        n_evals = int(rng.integers(evals_per_client[0], evals_per_client[1] + 1))
        for _ in range(n_evals):
            session_id += 1
            muscle = str(rng.choice(MUSCLES))
            exercise = str(rng.choice(EXERCISES[muscle]))

            activation = (
                truth.activacion_base
                + truth.activacion_por_grasa * fat_term
                + truth.activacion_por_experiencia * experience
                + truth.activacion_por_edad * age_term
                + client_offset_act
                + exercise_effect[exercise]
                + affinity[exercise]
                + rng.normal(0, truth.activacion_ruido)
            )
            activation = float(np.clip(activation, 15, 99))

            # Se acota para descartar pendientes positivas, que
            # implicarían un espectro ascendiendo a lo largo de la serie.
            fatigue_slope = float(
                np.clip(
                    truth.fatiga_base
                    + truth.fatiga_por_experiencia * experience
                    + truth.fatiga_por_edad * age_term
                    + truth.fatiga_por_grasa * fat_term
                    + client_offset_fat
                    + rng.normal(0, truth.fatiga_ruido),
                    truth.fatiga_minima,
                    truth.fatiga_maxima,
                )
            )

            # La contracción máxima en microvoltios depende fuertemente de
            # la colocación del electrodo: dos sensores sobre el mismo
            # músculo llegaron a diferir en un factor de 1,7 con este
            # hardware, y esa variabilidad se reproduce aquí.
            mvc_uv = float(
                np.clip(
                    rng.normal(620, 180) * (1.0 - 0.12 * fat_term),
                    120, 2200,
                )
            )
            placement_noise = rng.normal(1.0, 0.22)

            reps = int(np.clip(rng.normal(11, 3), 5, 20))
            median_freq_start = float(np.clip(rng.normal(108, 12), 70, 150))

            rows.append(
                {
                    "session_id": session_id,
                    "client_id": int(client["client_id"]),
                    "muscle": muscle,
                    "exercise": exercise,
                    "reps": reps,
                    "mvc_uv": round(mvc_uv, 1),
                    "mvc_channel_a_uv": round(mvc_uv * placement_noise, 1),
                    "mvc_channel_b_uv": round(mvc_uv * (2 - placement_noise), 1),
                    "median_freq_start_hz": round(median_freq_start, 1),
                    "fatigue_slope_hz_per_rep": round(fatigue_slope, 3),
                    "mean_activation_pct": round(activation, 1),
                    "peak_activation_pct": round(
                        float(np.clip(activation + abs(rng.normal(9, 4)), 20, 100)), 1
                    ),
                }
            )

    return pd.DataFrame(rows)


def build_dataset(
    n_clients: int = 60, seed: int = 7
) -> tuple[pd.DataFrame, pd.DataFrame, GroundTruth]:
    """Genera el conjunto de datos completo.

    Parameters
    ----------
    n_clients : int, default=60
        Clientes a generar.
    seed : int, default=7
        Semilla del generador, para reproducibilidad.

    Returns
    -------
    clients : pandas.DataFrame
        Fichas de cliente.
    evaluations : pandas.DataFrame
        Evaluaciones sEMG.
    truth : GroundTruth
        Coeficientes empleados en la generación.
    """
    rng = np.random.default_rng(seed)
    truth = GroundTruth()
    clients = generate_clients(n_clients, rng)
    evaluations = generate_evaluations(clients, rng, truth)
    return clients, evaluations, truth


def main() -> None:
    """Genera el conjunto de datos y lo escribe en disco como CSV y JSON."""
    parser = argparse.ArgumentParser(
        description="Genera datos sintéticos para probar algoritmos de predicción."
    )
    parser.add_argument("--clientes", type=int, default=60, help="cuántos clientes generar")
    parser.add_argument("--semilla", type=int, default=7, help="semilla, para reproducir")
    parser.add_argument(
        "--salida", type=Path, default=Path("datos_sinteticos"),
        help="carpeta donde dejar los CSV",
    )
    args = parser.parse_args()

    clients, evaluations, truth = build_dataset(args.clientes, args.semilla)

    args.salida.mkdir(parents=True, exist_ok=True)
    clients.to_csv(args.salida / "clientes.csv", index=False)
    evaluations.to_csv(args.salida / "evaluaciones.csv", index=False)

    # Tabla unida: una fila por evaluación con los datos del cliente
    # repetidos. Es la forma en que se entrega a un modelo.
    merged = evaluations.merge(clients, on="client_id", how="left")
    merged.to_csv(args.salida / "dataset.csv", index=False)

    (args.salida / "verdad_base.json").write_text(
        json.dumps(asdict(truth), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Generados en {args.salida}/")
    print(f"  clientes.csv       {len(clients)} filas")
    print(f"  evaluaciones.csv   {len(evaluations)} filas")
    print(f"  dataset.csv        {len(merged)} filas x {len(merged.columns)} columnas")
    print("  verdad_base.json   los coeficientes reales, para comprobar si se recuperan")
    print()
    print(f"Evaluaciones por cliente: "
          f"min {evaluations.groupby('client_id').size().min()}, "
          f"max {evaluations.groupby('client_id').size().max()}, "
          f"media {evaluations.groupby('client_id').size().mean():.1f}")
    print()
    print("Recordatorio: estos datos prueban el código, no la hipótesis.")


if __name__ == "__main__":
    main()
