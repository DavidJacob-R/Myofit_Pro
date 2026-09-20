"""Análisis de viabilidad del diseño intra-sujeto por simulación.

Posición en el flujo
--------------------
Fuera del flujo de la aplicación. Es una herramienta de línea de órdenes
que justifica dos decisiones de diseño del producto: cuántas veces hay que
medir cada ejercicio en la batería de tamizaje, y cada cuántas semanas
tiene sentido repetir la evaluación. Sus conclusiones están incorporadas a
`myofit_pro.progress` en forma de umbrales.

El diseño que se simula
-----------------------
1. Tamizaje inicial: el cliente ejecuta una batería con todos los
   ejercicios disponibles de un músculo y se registra su activación en
   cada uno.
2. Los ejercicios se ordenan de mayor a menor activación *para esa
   persona* y la rutina se construye con los primeros.
3. Transcurridas dos a cuatro semanas se repite la medición para evaluar
   el progreso.
4. Cada nueva lectura refina la rutina siguiente.

Por qué intra-sujeto y no entre sujetos
---------------------------------------
La amplitud sEMG de una persona depende de su espesor de tejido adiposo
subcutáneo, su masa muscular y su anatomía. Al comparar entre personas,
ese nivel individual constituye la mayor fuente de varianza y absorbe casi
toda la capacidad predictiva de cualquier modelo.

Al comparar a una persona consigo misma, ese nivel se cancela por estar
presente por igual en todas sus mediciones. El problema pasa de estimar un
valor absoluto a ordenar una lista, que es a la vez más fácil y más
próximo a lo que la aplicación necesita.

La pregunta que decide la viabilidad
------------------------------------
Si un ejercicio mide 72 % y otro 68 %, ¿esa diferencia de cuatro puntos es
real o es ruido de medición? Este módulo la responde por simulación de
Montecarlo: dada una repetibilidad conocida, estima cuántas repeticiones
por ejercicio hacen falta para que el orden observado coincida con el
orden verdadero.

Dos fuentes de ruido
--------------------
- **Dentro de la sesión**: los electrodos permanecen colocados. La
  variabilidad procede de la ejecución del gesto y de la fatiga
  acumulada.
- **Entre sesiones**: los electrodos se retiran y se recolocan en una
  posición ligeramente distinta, y el estado de la piel cambia. Ambos
  factores alteran la ganancia de todo lo que se mida ese día, lo que
  hace esta fuente sustancialmente mayor.

  De ahí la importancia de normalizar contra una contracción voluntaria
  máxima tomada en la misma sesión: el factor de ganancia afecta por
  igual al máximo y a la medición, de modo que el cociente lo elimina.
  Sin esa normalización, comparar la semana 0 con la semana 4 sería
  comparar dos escalas distintas.

Limitaciones
------------
Los coeficientes de variación por defecto proceden de la literatura, no
de medidas tomadas con los sensores MYOblue de este proyecto. Mientras no
se midan con el protocolo que documenta `protocolo_de_repetibilidad`,
todos los resultados de este módulo son hipótesis condicionadas a ese
parámetro.

La electromiografía de superficie no mide carga. El peso de trabajo
procede de una estimación de repetición máxima y del porcentaje asociado
al objetivo, nunca de la señal.

Uso
---
::

    uv run python -m myofit_pro.ml.within_subject
    uv run python -m myofit_pro.ml.within_subject --cv 0.15 --ejercicios 8

See Also
--------
myofit_pro.progress : Aplica estos umbrales a los datos reales.
myofit_pro.ml.benchmark : Análisis paralelo del diseño entre sujetos.

References
----------
.. [1] Weir, J. P. (2005). "Quantifying test-retest reliability using the
       intraclass correlation coefficient and the SEM". *Journal of
       Strength and Conditioning Research*, 19(1), 231-240.
.. [2] Kendall, M. G. (1938). "A new measure of rank correlation".
       *Biometrika*, 30(1-2), 81-93.
.. [3] Burden, A. (2010). "How should we normalize electromyograms
       obtained from healthy participants?". *Journal of
       Electromyography and Kinesiology*, 20(6), 1023-1035.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import kendalltau

#: Coeficiente de variación de la amplitud sEMG normalizada dentro de una
#: misma sesión, con los electrodos sin recolocar. Valor de referencia de
#: la literatura, pendiente de medir con este hardware.
CV_DENTRO_SESION = 0.10

#: Coeficiente de variación entre sesiones, con los electrodos retirados y
#: recolocados. Valor de referencia de la literatura, pendiente de medir
#: con este hardware.
CV_ENTRE_SESIONES = 0.20


@dataclass(slots=True)
class ScreeningResult:
    """Resultado de una simulación de tamizaje.

    Attributes
    ----------
    repeticiones : int
        Mediciones realizadas por ejercicio en la simulación.
    cv : float
        Coeficiente de variación supuesto.
    acierta_el_mejor : float
        Proporción de simulaciones en las que el ejercicio de mayor
        activación medida coincide con el de mayor activación verdadera.
    mejor_en_top3 : float
        Proporción de simulaciones en las que el mejor ejercicio
        verdadero queda entre los tres primeros del orden medido. Es el
        criterio operativo, ya que la rutina toma varios ejercicios por
        músculo y no solo el primero.
    tau_orden : float
        Tau de Kendall medio entre el orden verdadero y el medido, de -1
        a 1. Resume la concordancia del ranking completo.
    sesiones_necesarias : float
        Series totales que la batería exige al cliente en una sesión,
        igual al producto de ejercicios por repeticiones.
    """

    repeticiones: int
    cv: float
    acierta_el_mejor: float
    mejor_en_top3: float
    tau_orden: float
    sesiones_necesarias: float


def simulate_screening(
    n_exercises: int = 6,
    spread_pct: float = 12.0,
    repeats: int = 1,
    cv: float = CV_DENTRO_SESION,
    trials: int = 4000,
    seed: int = 11,
) -> ScreeningResult:
    """Simula por Montecarlo el tamizaje inicial de un cliente.

    Parameters
    ----------
    n_exercises : int, default=6
        Ejercicios que componen la batería de tamizaje.
    spread_pct : float, default=12.0
        Desviación típica de la activación verdadera entre los ejercicios
        de esa persona, en puntos de porcentaje.
    repeats : int, default=1
        Mediciones por ejercicio, promediadas antes de ordenar.
    cv : float, default=CV_DENTRO_SESION
        Coeficiente de variación de la medición.
    trials : int, default=4000
        Simulaciones a ejecutar.
    seed : int, default=11
        Semilla del generador, para reproducibilidad.

    Returns
    -------
    ScreeningResult
        Probabilidades de acierto y concordancia media del orden.

    Notes
    -----
    `spread_pct` es el parámetro determinante y el peor conocido: si
    todos los ejercicios de un músculo activan de forma similar en una
    persona, no hay orden que recuperar por precisa que sea la medición;
    si difieren en 15 o 20 puntos, el orden se recupera incluso con
    repetibilidad mediocre.

    El ruido se aplica de forma multiplicativa porque la variabilidad de
    la amplitud sEMG es proporcional a la propia amplitud, no una
    cantidad fija de microvoltios.
    """
    rng = np.random.default_rng(seed)

    aciertos = 0
    en_top3 = 0
    taus = []

    for _ in range(trials):
        verdad = rng.normal(65.0, spread_pct, size=n_exercises)
        mejor_real = int(np.argmax(verdad))

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
    """Calcula el cambio mínimo detectable al 95 % de confianza.

    Parameters
    ----------
    cv : float
        Coeficiente de variación de la medición.
    repeats : int, default=1
        Mediciones promediadas por sesión.
    baseline : float, default=65.0
        Valor de referencia sobre el que se expresa la variabilidad, en
        puntos de activación.

    Returns
    -------
    float
        Umbral en puntos de activación. Una diferencia inferior no es
        distinguible del ruido de medición.

    Notes
    -----
    Se aplica la formulación estándar de la medición clínica repetida:

    .. math:: CMD_{95} = 1{,}96 \\sqrt{2}\\, SEM

    donde el error estándar de medición es
    :math:`SEM = baseline \\cdot cv / \\sqrt{repeats}`. El factor
    :math:`\\sqrt{2}` recoge que la diferencia entre dos mediciones
    acumula el error de ambas.

    El error estándar decrece con la raíz del número de mediciones, de
    modo que pasar de una a dos reduce el umbral un 29 % y pasar de nueve
    a diez apenas un 5 %.

    See Also
    --------
    myofit_pro.progress.minimal_detectable_change : Misma fórmula aplicada
        a los datos reales del cliente.
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
    """Estima la potencia estadística del seguimiento entre dos sesiones.

    Parameters
    ----------
    true_gain_pct : float
        Mejora real del cliente entre ambas sesiones, en porcentaje.
    cv : float, default=CV_ENTRE_SESIONES
        Coeficiente de variación entre sesiones.
    repeats : int, default=1
        Mediciones promediadas en cada sesión.
    baseline : float, default=65.0
        Activación de partida, en puntos.
    trials : int, default=20000
        Simulaciones a ejecutar.
    seed : int, default=13
        Semilla del generador.

    Returns
    -------
    float
        Proporción de simulaciones en las que la diferencia observada
        supera el cambio mínimo detectable, es decir, la probabilidad de
        detectar la mejora.

    Notes
    -----
    Determina cada cuántas semanas tiene sentido repetir la evaluación:
    si la mejora esperable en cuatro semanas queda por debajo del umbral,
    medir a las cuatro semanas produce resultados indistinguibles del
    ruido y conviene espaciar más las lecturas o aumentar `repeats`.
    """
    rng = np.random.default_rng(seed)
    umbral = minimal_detectable_change(cv, repeats, baseline)

    antes = (baseline * rng.normal(1.0, cv, size=(trials, repeats))).mean(axis=1)
    despues_real = baseline * (1 + true_gain_pct / 100.0)
    despues = (despues_real * rng.normal(1.0, cv, size=(trials, repeats))).mean(axis=1)

    return float(np.mean((despues - antes) > umbral))


def protocolo_de_repetibilidad() -> str:
    """Devuelve el protocolo para medir la repetibilidad de este hardware.

    Returns
    -------
    str
        Texto del protocolo, listo para imprimir.

    Notes
    -----
    `CV_DENTRO_SESION` y `CV_ENTRE_SESIONES` proceden de la literatura.
    Hasta que se midan con los sensores MYOblue y el protocolo de
    colocación de esta aplicación, los resultados del módulo son
    hipótesis condicionadas a esos valores.
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
    """Tabula el acierto del tamizaje para varios niveles de repetibilidad."""
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
    """Tabula el cambio mínimo detectable por repetibilidad y repeticiones."""
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
    """Tabula la potencia del seguimiento para varias mejoras reales."""
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
    """Ejecuta el análisis completo e imprime sus tres tablas."""
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
