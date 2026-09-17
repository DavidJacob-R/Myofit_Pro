"""
Simulación del diseño intra-sujeto: cada cliente comparado consigo mismo.

EL DISEÑO QUE SE SIMULA
=======================

1. Tamizaje inicial: el cliente hace una batería con todos los ejercicios
   posibles de un músculo y se mide la activación en cada uno.
2. Con eso se ordenan los ejercicios de mejor a peor PARA ESA PERSONA y se
   arma la rutina con los de arriba.
3. A las 2 o 4 semanas se vuelve a medir para ver si progresó.
4. Se repite, y cada lectura nueva afina la siguiente rutina.

POR QUÉ ESTE DISEÑO ES MEJOR QUE COMPARAR ENTRE PERSONAS
=======================================================

Cada persona tiene un nivel propio de amplitud que depende de su grasa
subcutánea, su masa muscular y su anatomía. Al comparar entre personas,
ese nivel propio es ruido que hay que modelar y que se come casi toda la
capacidad de predicción.

Al comparar a la persona consigo misma, ese nivel propio **se cancela**,
porque está presente por igual en todas sus mediciones. El problema pasa
de "predecir un número" a "ordenar una lista", que es mucho más fácil y
además es lo que de verdad se necesita para armar la rutina.

LA PREGUNTA QUE DECIDE SI FUNCIONA
==================================

Si el curl martillo mide 72% y el predicador 68%, ¿esa diferencia de 4
puntos es real o es ruido de medición?

Todo el diseño depende de eso. Este módulo lo responde por simulación:
dada una repetibilidad de medición, calcula cuántas veces hay que medir
cada ejercicio para que el orden que sale sea el orden verdadero.

DOS TIPOS DE RUIDO, Y NO SON IGUALES
====================================

- **Dentro de la sesión**: los electrodos no se mueven. El ruido viene de
  la variabilidad del gesto y de la fatiga acumulada. Es el caso bueno.

- **Entre sesiones**: los electrodos se quitaron y se volvieron a poner en
  un lugar ligeramente distinto, la piel está en otro estado, y eso
  cambia la ganancia de todo lo que se mida ese día. Es bastante peor.

  Por eso importa tanto que la app normalice contra un MVC tomado en la
  MISMA sesión: ese factor de ganancia aparece igual en el MVC y en la
  medición, así que al dividir se cancela. Sin eso, comparar la semana 0
  con la semana 4 sería comparar dos escalas distintas.

LO QUE LOS SENSORES NO PUEDEN DAR
=================================

Kilos. El sEMG mide activación eléctrica, no carga. El peso de trabajo
sale de una estimación de repetición máxima y del porcentaje que
corresponde al objetivo, no de la señal.

USO
===

    uv run python -m myofit_pro.ml.within_subject
    uv run python -m myofit_pro.ml.within_subject --cv 0.15 --ejercicios 8
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import kendalltau

# Repetibilidad típica reportada para amplitud sEMG normalizada al MVC,
# como coeficiente de variación. Son rangos de la literatura, NO medidos
# con este hardware: hay que medirlos (ver `protocolo_de_repetibilidad`).
CV_DENTRO_SESION = 0.10      # electrodos puestos, mismo día
CV_ENTRE_SESIONES = 0.20     # electrodos re-colocados, otro día


@dataclass(slots=True)
class ScreeningResult:
    repeticiones: int
    cv: float
    acierta_el_mejor: float       # probabilidad de elegir el mejor ejercicio real
    mejor_en_top3: float          # probabilidad de que el mejor real quede en el top 3
    tau_orden: float              # concordancia del orden completo (Kendall, -1 a 1)
    sesiones_necesarias: float    # series totales que implica el tamizaje


def simulate_screening(
    n_exercises: int = 6,
    spread_pct: float = 12.0,
    repeats: int = 1,
    cv: float = CV_DENTRO_SESION,
    trials: int = 4000,
    seed: int = 11,
) -> ScreeningResult:
    """
    Simula el tamizaje inicial de UNA persona, muchas veces.

    `spread_pct` es qué tan separados están los ejercicios entre sí para
    esa persona, en puntos de activación. Es el parámetro más importante
    y el que no conocemos: si todos los ejercicios de un músculo activan
    casi igual en una persona, no hay nada que ordenar por más que se
    mida bien. Si se separan 15 o 20 puntos, ordenarlos es fácil.

    El ruido se aplica de forma multiplicativa porque la variabilidad de
    la amplitud del sEMG es proporcional a la amplitud, no una cantidad
    fija de microvolts.
    """
    rng = np.random.default_rng(seed)

    aciertos = 0
    en_top3 = 0
    taus = []

    for _ in range(trials):
        # Activación verdadera de cada ejercicio para esta persona
        verdad = rng.normal(65.0, spread_pct, size=n_exercises)
        mejor_real = int(np.argmax(verdad))

        # Cada ejercicio se mide `repeats` veces y se promedia
        ruido = rng.normal(1.0, cv, size=(repeats, n_exercises))
        medido = (verdad * ruido).mean(axis=0)

        orden_medido = np.argsort(-medido)
        if int(orden_medido[0]) == mejor_real:
            aciertos += 1
        if mejor_real in orden_medido[:3]:
            en_top3 += 1

        tau = kendalltau(verdad, medido).statistic
        if not np.isnan(tau):
            taus.append(tau)

    return ScreeningResult(
        repeticiones=repeats,
        cv=cv,
        acierta_el_mejor=aciertos / trials,
        mejor_en_top3=en_top3 / trials,
        tau_orden=float(np.mean(taus)),
        sesiones_necesarias=n_exercises * repeats,
    )


def minimal_detectable_change(cv: float, repeats: int = 1, baseline: float = 65.0) -> float:
    """
    Cambio mínimo detectable al 95% de confianza, en puntos de activación.

    Es el umbral por debajo del cual una diferencia NO se puede
    distinguir del ruido de medición. Si el cambio mínimo detectable es
    de 12 puntos y el cliente mejoró 6, la app no tiene forma de saberlo
    y decir que mejoró sería inventar.

    La fórmula es la estándar en medición clínica repetida:

        CMD95 = 1.96 x raíz(2) x error estándar de medición

    El error estándar baja con la raíz del número de mediciones, que es
    la razón por la que medir dos veces ayuda bastante y medir diez veces
    ya casi no.
    """
    sem = baseline * cv / np.sqrt(repeats)
    return float(1.96 * np.sqrt(2) * sem)


def longitudinal_power(
    true_gain_pct: float,
    cv: float = CV_ENTRE_SESIONES,
    repeats: int = 1,
    baseline: float = 65.0,
    trials: int = 20000,
    seed: int = 13,
) -> float:
    """
    Probabilidad de detectar una mejora real entre dos sesiones.

    Simula medir al cliente hoy y dentro de 4 semanas, con el ruido
    propio de haber quitado y vuelto a poner los electrodos, y cuenta
    cuántas veces la diferencia medida supera el cambio mínimo
    detectable.

    Sirve para contestar honestamente "¿en cuántas semanas tiene sentido
    volver a medir?": si la mejora esperada en 4 semanas está por debajo
    del umbral, hay que esperar más o medir más veces.
    """
    rng = np.random.default_rng(seed)
    umbral = minimal_detectable_change(cv, repeats, baseline)

    antes = (baseline * rng.normal(1.0, cv, size=(trials, repeats))).mean(axis=1)
    despues_real = baseline * (1 + true_gain_pct / 100.0)
    despues = (despues_real * rng.normal(1.0, cv, size=(trials, repeats))).mean(axis=1)

    return float(np.mean((despues - antes) > umbral))


def protocolo_de_repetibilidad() -> str:
    """
    Cómo medir la repetibilidad real de ESTE hardware.

    Los números de arriba son de la literatura. Mientras no se midan con
    los MYOblue y con el protocolo de colocación de esta app, todo lo que
    calcula este módulo son hipótesis.
    """
    return (
        "PROTOCOLO PARA MEDIR LA REPETIBILIDAD REAL (una tarde de trabajo)\n"
        "\n"
        "Dentro de la sesión (el ruido bueno):\n"
        "  1. Coloca los electrodos y calibra el MVC.\n"
        "  2. Haz la MISMA serie del MISMO ejercicio 5 veces, con 2 min de\n"
        "     descanso entre cada una para que la fatiga no contamine.\n"
        "  3. El coeficiente de variación de esas 5 activaciones medias es\n"
        "     tu CV dentro de sesión.\n"
        "\n"
        "Entre sesiones (el ruido que decide si el seguimiento sirve):\n"
        "  1. Repite lo anterior en 3 días distintos de la misma semana,\n"
        "     quitando los electrodos entre días.\n"
        "  2. Una semana no alcanza para adaptarse, así que las diferencias\n"
        "     entre días son ruido de medición, no progreso.\n"
        "  3. El CV de las medias de cada día es tu CV entre sesiones.\n"
        "\n"
        "Con esos dos números, vuelve a correr este módulo con --cv y ya no\n"
        "serán hipótesis.\n"
    )


def _tabla_tamizaje(n_exercises: int, spread: float) -> pd.DataFrame:
    rows = []
    for cv in (0.05, 0.10, 0.15, 0.20, 0.25):
        for repeats in (1, 2, 3):
            r = simulate_screening(
                n_exercises=n_exercises, spread_pct=spread, repeats=repeats, cv=cv
            )
            rows.append(
                {
                    "CV": f"{cv:.0%}",
                    "mediciones_por_ejercicio": repeats,
                    "series_totales": r.sesiones_necesarias,
                    "acierta_el_mejor": round(r.acierta_el_mejor, 3),
                    "mejor_en_top3": round(r.mejor_en_top3, 3),
                    "concordancia_orden": round(r.tau_orden, 3),
                }
            )
    return pd.DataFrame(rows)


def _tabla_cambio_detectable() -> pd.DataFrame:
    rows = []
    for cv in (0.05, 0.10, 0.15, 0.20, 0.25):
        for repeats in (1, 2, 3):
            rows.append(
                {
                    "CV": f"{cv:.0%}",
                    "mediciones_por_sesion": repeats,
                    "cambio_minimo_detectable_pts": round(
                        minimal_detectable_change(cv, repeats), 1
                    ),
                    "en_porcentaje_del_valor": f"{minimal_detectable_change(cv, repeats) / 65 * 100:.0f}%",
                }
            )
    return pd.DataFrame(rows)


def _tabla_seguimiento() -> pd.DataFrame:
    rows = []
    for gain in (5, 10, 15, 20, 30):
        row = {"mejora_real": f"{gain}%"}
        for repeats in (1, 2, 3):
            row[f"{repeats} medición(es)"] = round(
                longitudinal_power(gain, CV_ENTRE_SESIONES, repeats), 2
            )
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simula el diseño intra-sujeto: cada cliente contra sí mismo."
    )
    parser.add_argument("--ejercicios", type=int, default=6,
                        help="cuántos ejercicios tiene la batería de tamizaje")
    parser.add_argument("--dispersion", type=float, default=12.0,
                        help="qué tan separados están los ejercicios en esa persona, en puntos")
    parser.add_argument("--cv", type=float, default=None,
                        help="repetibilidad medida, si ya la tienes (ej. 0.12)")
    args = parser.parse_args()

    print("=" * 78)
    print("1. TAMIZAJE INICIAL: ¿el orden que sale es el orden verdadero?")
    print("=" * 78)
    print(
        f"\n  Batería de {args.ejercicios} ejercicios, separados entre sí unos "
        f"{args.dispersion:.0f} puntos\n"
        f"  de activación en esta persona.\n"
    )
    print(_tabla_tamizaje(args.ejercicios, args.dispersion).to_string(index=False))
    print(
        "\n  Cómo leerlo: 'acierta_el_mejor' es la probabilidad de que el ejercicio\n"
        "  que quedó primero sea de verdad el mejor para esa persona. 'series_totales'\n"
        "  es lo que le estás pidiendo al cliente en una sola sesión, y ahí está la\n"
        "  tensión real del diseño: más mediciones dan más certeza, pero una batería\n"
        "  de 18 series seguidas acumula fatiga y contamina justo lo que se mide.\n"
    )

    print("=" * 78)
    print("2. SEGUIMIENTO: ¿qué cambio se puede distinguir del ruido?")
    print("=" * 78)
    print()
    print(_tabla_cambio_detectable().to_string(index=False))
    print(
        "\n  Por debajo de ese umbral, una diferencia no se distingue del ruido de\n"
        "  medición. Decir que el cliente mejoró sería inventar.\n"
    )

    print("=" * 78)
    print("3. ¿CADA CUÁNTO VOLVER A MEDIR?")
    print("=" * 78)
    print(
        f"\n  Probabilidad de detectar una mejora real, con electrodos re-colocados\n"
        f"  (CV entre sesiones de {CV_ENTRE_SESIONES:.0%}):\n"
    )
    print(_tabla_seguimiento().to_string(index=False))
    print(
        "\n  Si en 4 semanas la activación normalizada sube poco, medir a las 4\n"
        "  semanas va a dar resultados que no se distinguen del ruido. Conviene\n"
        "  medir más veces por sesión o espaciar más las lecturas.\n"
    )

    if args.cv is not None:
        print("=" * 78)
        print(f"4. CON TU REPETIBILIDAD MEDIDA (CV = {args.cv:.0%})")
        print("=" * 78)
        for repeats in (1, 2, 3):
            r = simulate_screening(
                n_exercises=args.ejercicios, spread_pct=args.dispersion,
                repeats=repeats, cv=args.cv,
            )
            print(
                f"  {repeats} medición(es) por ejercicio: "
                f"acierta el mejor {r.acierta_el_mejor:.0%}, "
                f"cambio detectable {minimal_detectable_change(args.cv, repeats):.1f} pts"
            )
        print()

    print("=" * 78)
    print(protocolo_de_repetibilidad())


if __name__ == "__main__":
    main()
