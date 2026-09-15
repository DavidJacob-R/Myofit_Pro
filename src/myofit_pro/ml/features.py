"""
Extracción de features desde una ráfaga EMG (arrays de tiempo, µV,
envolvente, RMS) para alimentar los modelos de ml/activation_classifier.py
y ml/fatigue_predictor.py.

Se calculan features clásicos de literatura de sEMG: en el dominio del
tiempo (RMS, MAV, varianza, zero-crossings, waveform length) y en el
dominio de la frecuencia (frecuencia mediana y media del espectro de
potencia vía Welch), este último especialmente relevante para fatiga,
ya que la frecuencia mediana del espectro EMG *disminuye* conforme el
músculo se fatiga (shift hacia bajas frecuencias).
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
from scipy.signal import welch


@dataclass(slots=True)
class BurstFeatures:
    # Dominio del tiempo
    rms: float
    mav: float                # mean absolute value
    variance: float
    zero_crossings: int
    waveform_length: float
    peak_amplitude: float

    # Dominio de la frecuencia (indicadores de fatiga)
    median_freq_hz: float
    mean_freq_hz: float

    def to_dict(self) -> dict:
        return asdict(self)


def extract_features(filtered_signal: np.ndarray, sample_rate_hz: float) -> BurstFeatures:
    """Calcula el set de features de una ráfaga ya filtrada (bandpass + notch)."""
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

    # Densidad espectral de potencia (Welch) para frecuencia mediana/media
    nperseg = min(256, n)
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
    """
    Convierte una lista de (señal_filtrada, sample_rate) en un
    DataFrame de pandas, una fila por ráfaga — listo para entrenar
    con scikit-learn/xgboost/lightgbm.
    """
    import pandas as pd

    rows = [extract_features(signal, fs).to_dict() for signal, fs in bursts]
    return pd.DataFrame(rows)
