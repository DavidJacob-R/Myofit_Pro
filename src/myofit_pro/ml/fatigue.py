"""Detección de fatiga muscular por desplazamiento espectral.

Posición en el flujo
--------------------
Cuarta etapa del procesado de señal, posterior a `myofit_pro.ml.features`.
Recibe la señal filtrada de una serie completa y devuelve un veredicto de
fatiga que `myofit_pro.gui.evaluation_step5_view` muestra junto a los
resultados de la evaluación.

Fundamento
----------
Al acumularse metabolitos durante una contracción sostenida, la velocidad
de conducción de las fibras musculares disminuye y el espectro de potencia
de la señal sEMG se desplaza hacia frecuencias bajas. La frecuencia
mediana desciende de forma aproximadamente lineal mientras dura el
esfuerzo.

Es un indicador más fiable que la amplitud, que varía por causas ajenas a
la fatiga: posición de los electrodos, espesor del tejido adiposo
subcutáneo, temperatura de la piel y técnica de ejecución. La frecuencia
mediana, al ser una propiedad de la forma del espectro y no de su escala,
es insensible a esos factores.

Método
------
La serie se divide en ventanas de igual longitud, se calcula la frecuencia
mediana de cada una y se ajusta una recta por mínimos cuadrados. Se
declara fatiga cuando concurren tres condiciones: pendiente negativa,
coeficiente de determinación por encima de `R2_MINIMO` y caída relativa
por encima de `CAIDA_MINIMA_PCT`. Exigir las tres evita confundir una
caída errática, que es ruido, con un descenso progresivo, que es fatiga.

Alcance
-------
El veredicto describe lo ocurrido durante la serie medida. No predice la
fatiga de series futuras ni sustituye la percepción de esfuerzo del
cliente.

See Also
--------
myofit_pro.ml.features : Cálculo de la frecuencia mediana por ventana.

References
----------
.. [1] De Luca, C. J. (1984). "Myoelectrical manifestations of localized
       muscular fatigue in humans". *Critical Reviews in Biomedical
       Engineering*, 11(4), 251-279.
.. [2] Merletti, R. y Parker, P. A. (2004). *Electromyography:
       Physiology, Engineering, and Non-Invasive Applications*. IEEE
       Press / Wiley-Interscience.
.. [3] Cifrek, M., Medved, V., Tonković, S. y Ostojić, S. (2009).
       "Surface EMG based muscle fatigue evaluation in biomechanics".
       *Clinical Biomechanics*, 24(4), 327-340.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from myofit_pro.ml.features import extract_features

#: Ventanas en que se divide una serie. Por debajo de cuatro la recta se
#: ajusta al ruido; muy por encima, cada ventana queda demasiado corta
#: para que su espectro sea estable.
VENTANAS_POR_SERIE = 6

#: Muestras mínimas por ventana. A 1000 Hz equivalen a 0,25 s, el orden
#: de duración de una contracción concéntrica.
MUESTRAS_MINIMAS = 256

#: Caída mínima de la frecuencia mediana, en porcentaje del valor
#: inicial, para declarar fatiga. Por debajo de este umbral la variación
#: queda dentro de lo que cambia entre repeticiones sin que el músculo se
#: esté fatigando.
CAIDA_MINIMA_PCT = 8.0

#: Coeficiente de determinación mínimo del ajuste lineal. Una caída
#: pronunciada pero errática no es fatiga progresiva.
R2_MINIMO = 0.3


@dataclass(slots=True)
class FatigueResult:
    """Veredicto de fatiga de una serie.

    Attributes
    ----------
    slope_hz_per_window : float
        Pendiente de la recta ajustada, en hercios por ventana. Un valor
        negativo indica que la frecuencia mediana está descendiendo.
    drop_pct : float
        Caída total a lo largo de la serie, en porcentaje de la
        frecuencia inicial. Se mide sobre la recta ajustada, no sobre los
        valores extremos observados.
    r2 : float
        Coeficiente de determinación del ajuste, entre 0 y 1. Mide hasta
        qué punto el descenso es progresivo en lugar de errático.
    is_fatiguing : bool
        Veredicto: cierto solo si la pendiente es negativa, `r2` alcanza
        `R2_MINIMO` y `drop_pct` alcanza `CAIDA_MINIMA_PCT`.
    windows : int
        Ventanas efectivamente analizadas. Cero indica que la señal no
        daba para un ajuste y que el resto de campos no son
        interpretables.
    """

    slope_hz_per_window: float
    drop_pct: float
    r2: float
    is_fatiguing: bool
    windows: int

    @property
    def summary(self) -> str:
        """Veredicto redactado para mostrar en la interfaz."""
        if self.windows == 0:
            return "Sin señal suficiente para evaluar fatiga"
        if self.is_fatiguing:
            return f"Fatiga durante la serie: la frecuencia cayó {self.drop_pct:.0f}%"
        if self.drop_pct > 0:
            return f"Sin fatiga apreciable ({self.drop_pct:.0f}% de caída)"
        return "Sin fatiga apreciable"


def median_frequencies(
    filtered_signal: np.ndarray,
    sample_rate_hz: float,
    windows: int = VENTANAS_POR_SERIE,
) -> list[float]:
    """Calcula la frecuencia mediana de cada ventana de una serie.

    Parameters
    ----------
    filtered_signal : numpy.ndarray
        Señal de la serie completa, ya filtrada.
    sample_rate_hz : float
        Frecuencia de muestreo, en hercios.
    windows : int, default=VENTANAS_POR_SERIE
        Número de ventanas deseado. Se reduce si la señal no da para
        tantas con `MUESTRAS_MINIMAS` cada una.

    Returns
    -------
    list of float
        Frecuencia mediana de cada ventana, en orden temporal. Lista
        vacía si no se alcanzan tres ventanas válidas, ya que un ajuste a
        dos puntos pasa por ellos exactamente y su coeficiente de
        determinación carece de significado.
    """
    x = np.asarray(filtered_signal, dtype=np.float64)
    if x.size < MUESTRAS_MINIMAS * 3:
        return []

    posibles = min(windows, int(x.size // MUESTRAS_MINIMAS))
    if posibles < 3:
        return []

    bordes = np.linspace(0, x.size, posibles + 1, dtype=int)
    valores = []
    for inicio, fin in zip(bordes[:-1], bordes[1:]):
        trozo = x[inicio:fin]
        if trozo.size < 2:
            continue
        valores.append(extract_features(trozo, sample_rate_hz).median_freq_hz)
    return valores


def fatigue_trend(median_freqs_hz: list[float]) -> FatigueResult:
    """Ajusta la tendencia de la frecuencia mediana y emite el veredicto.

    Parameters
    ----------
    median_freqs_hz : list of float
        Frecuencias medianas por ventana, en orden temporal, tal como las
        devuelve `median_frequencies`.

    Returns
    -------
    FatigueResult
        Veredicto. Con menos de tres ventanas, o si ninguna frecuencia es
        positiva, se devuelve un resultado neutro con ``windows = 0``.

    Notes
    -----
    La caída relativa se mide entre los extremos de la recta ajustada y
    no entre la primera y la última observación, de modo que una ventana
    atípica al principio o al final de la serie no determine el
    resultado.
    """
    n = len(median_freqs_hz)
    if n < 3:
        return FatigueResult(0.0, 0.0, 0.0, False, 0)

    x = np.arange(n, dtype=np.float64)
    y = np.asarray(median_freqs_hz, dtype=np.float64)

    if not np.any(y > 0):
        return FatigueResult(0.0, 0.0, 0.0, False, 0)

    slope, intercept = np.polyfit(x, y, 1)
    y_pred = slope * x + intercept
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # La caída se mide sobre la recta ajustada y no sobre el primer y
    # último punto crudos: así una ventana atípica al principio o al
    # final no decide el resultado.
    inicio = float(intercept)
    final = float(slope * (n - 1) + intercept)
    drop_pct = (inicio - final) / inicio * 100.0 if inicio > 0 else 0.0

    is_fatiguing = slope < 0 and r2 >= R2_MINIMO and drop_pct >= CAIDA_MINIMA_PCT

    return FatigueResult(
        slope_hz_per_window=float(slope),
        drop_pct=float(drop_pct),
        r2=float(max(r2, 0.0)),
        is_fatiguing=bool(is_fatiguing),
        windows=n,
    )


def fatigue_from_signal(
    filtered_signal: np.ndarray,
    sample_rate_hz: float,
    windows: int = VENTANAS_POR_SERIE,
) -> FatigueResult:
    """Evalúa la fatiga de una serie a partir de su señal.

    Encadena `median_frequencies` y `fatigue_trend`.

    Parameters
    ----------
    filtered_signal : numpy.ndarray
        Señal de la serie completa, ya filtrada.
    sample_rate_hz : float
        Frecuencia de muestreo, en hercios.
    windows : int, default=VENTANAS_POR_SERIE
        Número de ventanas deseado.

    Returns
    -------
    FatigueResult
        Veredicto de fatiga.
    """
    return fatigue_trend(median_frequencies(filtered_signal, sample_rate_hz, windows))
