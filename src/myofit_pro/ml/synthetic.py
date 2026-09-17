"""
Generador de datos sintéticos para probar algoritmos antes de tener
historial real.

PARA QUÉ SIRVE Y PARA QUÉ NO
============================

Sirve para:
  - Validar que la tubería funciona: que las variables llegan bien, que
    la validación cruzada está bien armada y que no hay fuga de datos.
  - Medir cuántos clientes hacen falta antes de que un modelo sea mejor
    que predecir el promedio (la curva de aprendizaje).
  - Comparar algoritmos entre sí bajo condiciones idénticas.
  - Demostrar problemas metodológicos, como la fuga por cliente.

NO sirve para:
  - Decidir si la idea es válida fisiológicamente. Estos datos salen de
    fórmulas que escribimos nosotros. Si un modelo recupera esas
    fórmulas, lo único que se demostró es que el modelo sabe ajustar lo
    que le pusimos, no que la edad y la grasa corporal de verdad
    expliquen la fatiga en personas reales.
  - Reportar un R² como si significara algo del mundo real.

Dicho de otra forma: esto prueba el código, no la ciencia. La ciencia
solo se prueba con los clientes reales del gimnasio.

LAS RELACIONES QUE SE SIMULAN
=============================

Están puestas con la dirección que reporta la literatura de sEMG, pero
las magnitudes son inventadas. Se exportan en `verdad_base.json` para
poder comprobar si un algoritmo las recupera.

  - La grasa subcutánea atenúa la amplitud del sEMG, porque el tejido se
    interpone entre el músculo y el electrodo.
  - Más experiencia de entrenamiento se asocia a mejor reclutamiento de
    unidades motoras, así que más activación relativa al MVC.
  - La fatiga se mide como la caída de la frecuencia mediana repetición
    a repetición. Cae más rápido en personas con menos entrenamiento y
    con más edad.
  - Cada cliente tiene una afinidad propia por cada ejercicio: el mismo
    ejercicio no activa igual el mismo músculo en dos personas. Esto es
    justo lo que los sensores pueden descubrir y una tabla no.
  - Cada cliente tiene un efecto aleatorio propio, así que sus
    evaluaciones se parecen entre sí. Esto NO es un detalle: es lo que
    obliga a validar agrupando por cliente (ver `benchmark.py`).

USO
===

    uv run python -m myofit_pro.ml.synthetic --clientes 60 --salida datos/
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

# Catálogo mínimo para que los datos tengan forma de los reales.
MUSCLES = ("Bíceps braquial", "Tríceps braquial", "Cuádriceps", "Dorsal ancho")

EXERCISES = {
    "Bíceps braquial": ("Curl con barra", "Curl inclinado", "Curl martillo", "Curl predicador"),
    "Tríceps braquial": ("Fondos", "Extensión en polea", "Press francés", "Patada de tríceps"),
    "Cuádriceps": ("Sentadilla", "Prensa", "Extensión de rodilla", "Zancadas"),
    "Dorsal ancho": ("Dominadas", "Remo con barra", "Jalón al pecho", "Remo en polea"),
}

EXPERIENCE_LEVELS = ("Principiante", "Intermedio", "Avanzado")


@dataclass
class GroundTruth:
    """
    Los coeficientes con los que se generaron los datos.

    Se guardan aparte para poder preguntarle a un algoritmo si los
    recuperó. Si un modelo no puede recuperar una relación que SÍ está
    en los datos, tampoco va a encontrar la que esté en los reales.
    """

    # Activación media (% del MVC) durante una serie
    activacion_base: float = 62.0
    activacion_por_grasa: float = -3.2      # por cada 10 puntos de grasa sobre 20
    activacion_por_experiencia: float = 4.5  # por nivel (1 a 3)
    activacion_por_edad: float = -1.8        # por cada 10 años sobre 30
    activacion_ruido: float = 4.0

    # Pendiente de la frecuencia mediana, en Hz por repetición.
    # Negativa: el espectro baja conforme el músculo se fatiga.
    fatiga_base: float = -2.6
    fatiga_por_experiencia: float = 0.55     # más entrenado, cae más lento
    fatiga_por_edad: float = -0.30           # por cada 10 años sobre 30
    fatiga_por_grasa: float = -0.18          # por cada 10 puntos sobre 20
    fatiga_ruido: float = 0.35

    # Límites fisiológicos de la pendiente. El extremo superior es casi
    # cero y no positivo: alguien muy entrenado se fatiga poco, pero el
    # espectro no sube conforme hace repeticiones.
    fatiga_minima: float = -6.0
    fatiga_maxima: float = -0.15

    # Dispersión del efecto aleatorio de cada cliente. Es lo que hace
    # que dos evaluaciones del mismo cliente se parezcan más entre sí
    # que a las de otro cliente.
    efecto_cliente_activacion: float = 6.0
    efecto_cliente_fatiga: float = 0.5

    # Cuánto varía la afinidad de un cliente por un ejercicio concreto.
    # Es idiosincrásico: no se puede deducir de la edad ni del peso, solo
    # midiendo a esa persona. Es la razón de existir de los sensores.
    afinidad_ejercicio: float = 7.0

    # Efecto poblacional del ejercicio: hay ejercicios que activan más
    # que otros en promedio, para todos. Esto SÍ se aprende de los datos
    # de los demás clientes y sirve para un cliente nuevo.
    efecto_ejercicio_poblacional: float = 5.5

    notas: list[str] = field(
        default_factory=lambda: [
            "Las direcciones siguen la literatura de sEMG; las magnitudes son inventadas.",
            "Recuperar estos coeficientes valida el algoritmo, no la hipótesis.",
        ]
    )


def _experience_number(level: str) -> int:
    return EXPERIENCE_LEVELS.index(level) + 1


def generate_clients(n: int, rng: np.random.Generator) -> pd.DataFrame:
    """
    Fichas de cliente con la misma forma que las que captura la app.

    Los datos físicos se generan correlacionados como en la población
    real: la estatura depende del sexo, el peso de la estatura, y la
    grasa corporal del sexo y la edad. Generarlos independientes daría
    combinaciones imposibles (mujeres de 190 cm y 45 kg) y haría que
    cualquier modelo se viera mejor de lo que es, porque tendría
    variables sin correlación entre sí, que es el caso fácil.
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

        # Cintura correlacionada con el IMC, que es lo que pasa en la
        # realidad, más una variación propia: dos personas con el mismo
        # IMC pueden tener cinturas distintas, y justo esa diferencia es
        # la que el método de circunferencias detecta.
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

        # La experiencia no es uniforme: hay más principiantes que
        # avanzados en la clientela de cualquier gimnasio.
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
    """
    Evaluaciones sEMG por cliente, con la estructura que dejaría la app.

    El número de evaluaciones por cliente es desigual a propósito: en la
    realidad unos clientes se evalúan una vez y otros doce. Un conjunto
    balanceado escondería el problema de que los clientes con más
    historial dominan el entrenamiento.
    """
    rows = []
    session_id = 0

    # Efecto poblacional de cada ejercicio: el mismo para todos los
    # clientes, así que un modelo lo puede aprender del historial de
    # unos y aplicarlo a un cliente nuevo. Se sortea una sola vez, fuera
    # del bucle de clientes, que es justo lo que lo hace poblacional.
    exercise_effect = {
        exercise: rng.normal(0, truth.efecto_ejercicio_poblacional)
        for muscle in MUSCLES
        for exercise in EXERCISES[muscle]
    }

    for _, client in clients.iterrows():
        # Efecto aleatorio del cliente: constante en todas SUS
        # evaluaciones. Es la razón por la que los datos no son
        # independientes y por la que hay que validar por grupo.
        client_offset_act = rng.normal(0, truth.efecto_cliente_activacion)
        client_offset_fat = rng.normal(0, truth.efecto_cliente_fatiga)

        # Afinidad propia por cada ejercicio
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
                + exercise_effect[exercise]   # aprendible de otros clientes
                + affinity[exercise]          # solo medible en este cliente
                + rng.normal(0, truth.activacion_ruido)
            )
            activation = float(np.clip(activation, 15, 99))

            # La pendiente se acota a valores posibles. Un cliente muy
            # entrenado y joven podía salirse a valores positivos, que
            # significarían un músculo que se desfatiga solo conforme
            # hace repeticiones. El espectro del sEMG baja con la fatiga
            # o se queda plano, nunca sube de forma sostenida.
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

            # El MVC en microvolts NO es un dato limpio: depende mucho de
            # la colocación del electrodo. En hardware real medimos 978 y
            # 1691 µV para el mismo gesto en dos sensores, un factor de
            # 1.7, así que aquí se le mete esa variabilidad.
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
                    # Objetivo 1: qué tan rápido se fatiga esta persona
                    "fatigue_slope_hz_per_rep": round(fatigue_slope, 3),
                    # Objetivo 2: cuánto activa este ejercicio en esta persona
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
    """Genera clientes y evaluaciones con una semilla reproducible."""
    rng = np.random.default_rng(seed)
    truth = GroundTruth()
    clients = generate_clients(n_clients, rng)
    evaluations = generate_evaluations(clients, rng, truth)
    return clients, evaluations, truth


def main() -> None:
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

    # La tabla unida es la que se le da a un modelo: una fila por
    # evaluación, con los datos del cliente repetidos.
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
