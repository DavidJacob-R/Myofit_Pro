"""Descriptores cuantitativos de una ráfaga sEMG filtrada.

Posición en el flujo
--------------------
Tercera etapa del procesado de señal. `myofit_pro.sensors.channel` entrega
la ventana en bruto, `myofit_pro.sensors.filters` la limpia con el filtro
paso banda y el rechaza banda de red, y este módulo la reduce a un vector
de ocho descriptores. `myofit_pro.ml.fatigue` consume después la
frecuencia mediana, y `myofit_pro.gui.evaluation_step5_view` la amplitud.

Descriptores
------------
Se calculan los descriptores clásicos de la literatura de electromiografía
de superficie, en dos dominios:

- **Tiempo**: valor eficaz, valor absoluto medio, varianza, cruces por
  cero, longitud de onda y amplitud de pico. Cuantifican cuánta señal
  produce el músculo, es decir, el nivel de reclutamiento.
- **Frecuencia**: frecuencia mediana y frecuencia media de la densidad
  espectral de potencia, estimada por el método de Welch. Cuantifican
  *dónde* está la energía del espectro, que es lo que se desplaza con la
  fatiga.

La frecuencia mediana es el indicador de fatiga más establecido: la
velocidad de conducción de las fibras musculares cae al acumularse
metabolitos, y el espectro se desplaza hacia frecuencias bajas. Es un
descenso monótono y reproducible durante una contracción sostenida.

See Also
--------
myofit_pro.sensors.filters : Filtrado previo, obligatorio.
myofit_pro.ml.fatigue : Consumidor de `BurstFeatures.median_freq_hz`.

References
----------
.. [1] Phinyomark, A., Phukpattaranont, P. y Limsakul, C. (2012).
       "Feature reduction and selection for EMG signal classification".
       *Expert Systems with Applications*, 39(8), 7420-7431.
.. [2] De Luca, C. J. (1997). "The use of surface electromyography in
       biomechanics". *Journal of Applied Biomechanics*, 13(2), 135-163.
.. [3] Welch, P. D. (1967). "The use of Fast Fourier Transform for the
       estimation of power spectra". *IEEE Transactions on Audio and
       Electroacoustics*, 15(2), 70-73.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
from scipy.signal import welch

#: Longitud máxima del segmento de Welch, en muestras. A 1000 Hz equivale
#: a 256 ms por segmento y a una resolución espectral de unos 3,9 Hz,
#: suficiente para seguir el desplazamiento de la frecuencia mediana sin
#: dejar la estimación en un solo segmento.
NPERSEG_MAXIMO = 256


@dataclass(slots=True)
class BurstFeatures:
    """Vector de descriptores de una ráfaga sEMG.

    Attributes
    ----------
    rms : float
        Valor eficaz de la señal, en las unidades de entrada. Es el
        descriptor de amplitud de referencia y el que se normaliza contra
        la contracción voluntaria máxima para obtener el porcentaje de
        activación.
    mav : float
        Valor absoluto medio. Alternativa al valor eficaz, menos sensible
        a los picos aislados.
    variance : float
        Varianza de la señal. Para una señal sEMG centrada en cero
        equivale al cuadrado del valor eficaz.
    zero_crossings : int
        Número de cambios de signo. Estima el contenido en frecuencia sin
        calcular el espectro, pero es sensible al ruido de línea base.
    waveform_length : float
        Suma de los valores absolutos de las diferencias entre muestras
        consecutivas. Combina amplitud y frecuencia en un solo valor.
    peak_amplitude : float
        Valor absoluto máximo de la ráfaga.
    median_freq_hz : float
        Frecuencia que divide la densidad espectral de potencia en dos
        mitades de igual área. Indicador de fatiga: desciende conforme se
        reduce la velocidad de conducción de las fibras.
    mean_freq_hz : float
        Centroide de la densidad espectral de potencia. Sigue la misma
        tendencia que la frecuencia mediana pero es más sensible al ruido
        de banda ancha.
    """

    rms: float
    mav: float
    variance: float
    zero_crossings: int
    waveform_length: float
    peak_amplitude: float
    median_freq_hz: float
    mean_freq_hz: float

    def to_dict(self) -> dict:
        """Devuelve los descriptores como diccionario, una clave por campo."""
        return asdict(self)


def extract_features(filtered_signal: np.ndarray, sample_rate_hz: float) -> BurstFeatures:
    """Calcula los descriptores de una ráfaga sEMG.

    Parameters
    ----------
    filtered_signal : numpy.ndarray
        Ventana de señal ya filtrada con paso banda y rechaza banda. Pasar
        la señal en bruto invalida los descriptores de frecuencia: la
        componente de red a 50 o 60 Hz domina el espectro y desplaza la
        frecuencia mediana.
    sample_rate_hz : float
        Frecuencia de muestreo de la señal, en hercios.

    Returns
    -------
    BurstFeatures
        Los ocho descriptores. Si la ventana tiene menos de dos muestras
        se devuelven todos a cero, ya que no hay diferencias que calcular.

    Notes
    -----
    La frecuencia mediana se obtiene por acumulación de la densidad
    espectral: se busca la primera frecuencia cuya potencia acumulada
    alcanza la mitad del total. Es la definición estándar y resulta más
    robusta frente al ruido que localizar el máximo del espectro.

    Una ráfaga sin potencia espectral —señal constante o nula— devuelve
    cero en ambas frecuencias en lugar de propagar una división por cero.

    See Also
    --------
    scipy.signal.welch : Estimador de la densidad espectral empleado.

    Examples
    --------
    >>> import numpy as np
    >>> t = np.arange(0, 1, 0.001)
    >>> senal = np.sin(2 * np.pi * 80 * t)
    >>> f = extract_features(senal, 1000.0)
    >>> round(f.rms, 2)
    0.71
    >>> 70 < f.median_freq_hz < 90
    True
    """
    x = np.asarray(filtered_signal, dtype=np.float64)
    n = len(x)
    if n < 2:
        return BurstFeatures(0, 0, 0, 0, 0, 0, 0, 0)

    rms = float(np.sqrt(np.mean(x ** 2)))
    mav = float(np.mean(np.abs(x)))
    variance = float(np.var(x))
    zero_crossings = int(np.sum(np.diff(np.sign(x)) != 0))
    waveform_length = float(np.sum(np.abs(np.diff(x))))
    peak_amplitude = float(np.max(np.abs(x)))

    nperseg = min(NPERSEG_MAXIMO, n)
    freqs, psd = welch(x, fs=sample_rate_hz, nperseg=nperseg)
    if psd.sum() > 0:
        cumulative = np.cumsum(psd)
        median_idx = np.searchsorted(cumulative, cumulative[-1] / 2.0)
        median_freq = float(freqs[min(median_idx, len(freqs) - 1)])
        mean_freq = float(np.sum(freqs * psd) / np.sum(psd))
    else:
        median_freq = 0.0
        mean_freq = 0.0

    return BurstFeatures(
        rms=rms, mav=mav, variance=variance,
        zero_crossings=zero_crossings, waveform_length=waveform_length,
        peak_amplitude=peak_amplitude,
        median_freq_hz=median_freq, mean_freq_hz=mean_freq,
    )


def features_dataframe(bursts: list[tuple[np.ndarray, float]]):
    """Tabula los descriptores de varias ráfagas.

    Parameters
    ----------
    bursts : list of tuple
        Pares ``(señal filtrada, frecuencia de muestreo)``.

    Returns
    -------
    pandas.DataFrame
        Una fila por ráfaga y una columna por campo de `BurstFeatures`,
        en el orden de declaración.

    Notes
    -----
    `pandas` se importa dentro de la función porque solo lo necesitan los
    análisis por lotes; el procesado en vivo de una evaluación no carga
    la biblioteca.
    """
    import pandas as pd

    rows = [extract_features(signal, fs).to_dict() for signal, fs in bursts]
    return pd.DataFrame(rows)
