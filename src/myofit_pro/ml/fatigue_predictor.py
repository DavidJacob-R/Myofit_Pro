"""
Detección de fatiga muscular y de calidad de ejecución del ejercicio.

Fundamento clínico: conforme un músculo se fatiga durante una serie,
el espectro de potencia de la señal EMG se desplaza hacia frecuencias
más bajas (la frecuencia mediana/media cae). Esto es un indicador
mucho más confiable que solo mirar la amplitud (que puede subir o
bajar por muchas razones).

Este módulo, igual que activation_classifier.py, es un ESQUELETO listo
para entrenar. `fatigue_trend_from_reps()` funciona desde el día uno
sin ML (regresión lineal simple sobre la frecuencia mediana repetición
por repetición). `FatigueGradientBooster` es la versión con ML
(XGBoost/LightGBM) para cuando haya historial suficiente por cliente.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor

from myofit_pro.ml.features import BurstFeatures


@dataclass(slots=True)
class FatigueTrendResult:
    slope_hz_per_rep: float          # negativo = fatiga (frecuencia cayendo)
    is_fatiguing: bool
    confidence: float                # R² de la regresión, 0..1


def fatigue_trend_from_reps(median_freqs_hz: list[float]) -> FatigueTrendResult:
    """
    Regresión lineal simple (sin ML) sobre la frecuencia mediana de
    cada repetición dentro de una serie. Sirve de línea base sin
    necesitar datos históricos de entrenamiento.
    """
    n = len(median_freqs_hz)
    if n < 3:
        return FatigueTrendResult(0.0, False, 0.0)

    x = np.arange(n, dtype=np.float64)
    y = np.asarray(median_freqs_hz, dtype=np.float64)

    slope, intercept = np.polyfit(x, y, 1)
    y_pred = slope * x + intercept
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Umbral: caída > 0.5 Hz por repetición con R² razonable = fatiga real
    is_fatiguing = slope < -0.5 and r2 > 0.3

    return FatigueTrendResult(
        slope_hz_per_rep=float(slope), is_fatiguing=is_fatiguing, confidence=float(max(r2, 0)),
    )


def execution_balance_alert(rms_a: float, rms_b: float, expected_ratio: float = 1.0,
                             tolerance: float = 0.35) -> str | None:
    """
    Heurística de "mala ejecución" (Filosofía A): si el balance entre
    las dos porciones del músculo se sale demasiado de lo esperado,
    probablemente el ejercicio se está compensando con una porción.
    Devuelve un mensaje de alerta o None si está dentro de rango.
    """
    if rms_a < 1e-6 or rms_b < 1e-6:
        return None
    ratio = rms_a / rms_b
    deviation = abs(ratio - expected_ratio) / expected_ratio
    if deviation > tolerance:
        dominant = "A" if ratio > expected_ratio else "B"
        return f"Posible compensación: la porción {dominant} está sobre-activándose."
    return None


class FatigueGradientBooster:
    """
    Modelo de ML (XGBoost por defecto) que predice un "índice de
    fatiga" continuo a partir de features de la ráfaga (ver
    ml/features.py) más el número de repetición dentro de la serie.

    Requiere historial etiquetado (ej. RPE reportado por el cliente,
    o número de repeticiones hasta el fallo) para `fit()`. Se puede
    cambiar `backend="lightgbm"` para usar LGBMRegressor en vez de
    XGBRegressor sin tocar el resto del código.
    """

    def __init__(self, backend: str = "xgboost"):
        if backend == "xgboost":
            self.model = XGBRegressor(
                n_estimators=200, max_depth=4, learning_rate=0.05, random_state=42
            )
        elif backend == "lightgbm":
            self.model = LGBMRegressor(
                n_estimators=200, max_depth=4, learning_rate=0.05, random_state=42
            )
        else:
            raise ValueError("backend debe ser 'xgboost' o 'lightgbm'")
        self.backend = backend
        self._is_fitted = False

    def fit(self, df: pd.DataFrame, fatigue_index: list[float]) -> None:
        """`df`: una fila por repetición, columnas = BurstFeatures + rep_number."""
        self.model.fit(df, fatigue_index)
        self._is_fitted = True

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        if not self._is_fitted:
            raise RuntimeError(
                "El modelo todavía no está entrenado. Usa fatigue_trend_from_reps() "
                "mientras se acumula historial suficiente para fit()."
            )
        return self.model.predict(df)

    def save(self, path: Path | str) -> None:
        joblib.dump({"backend": self.backend, "model": self.model}, path)

    @classmethod
    def load(cls, path: Path | str) -> "FatigueGradientBooster":
        data = joblib.load(path)
        instance = cls(backend=data["backend"])
        instance.model = data["model"]
        instance._is_fitted = True
        return instance
