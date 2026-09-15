"""
Clasificador de patrones de activación muscular entre Sensor A y
Sensor B (Filosofía A: mismo músculo, dos porciones).

IMPORTANTE: este módulo es un ESQUELETO listo para entrenar. Hoy no
existe un dataset etiquetado — necesitas acumular evaluaciones reales
(vía EmgBurstStore) y etiquetarlas (ej. un fisioterapeuta marcando
"activación balanceada" / "dominancia A" / "dominancia B" /
"compensación") antes de que `fit()` produzca un modelo útil.

Mientras tanto, `rule_based_label()` da una clasificación heurística
inmediata (sin ML) basada en el ratio RMS_A / RMS_B, para que la app
funcione desde el día uno; cuando haya suficientes datos etiquetados,
`fit()` entrena un modelo real que reemplaza a la heurística.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from sklearn.preprocessing import StandardScaler

from myofit_pro.ml.features import BurstFeatures

LABELS = ("balanceada", "dominancia_a", "dominancia_b", "compensacion")


def rule_based_label(rms_a: float, rms_b: float, threshold_ratio: float = 1.4) -> str:
    """
    Heurística simple sin ML: compara el RMS de ambos canales.
    Sirve de fallback antes de tener datos suficientes para entrenar.
    """
    if rms_a < 1e-6 and rms_b < 1e-6:
        return "sin_actividad"
    ratio = rms_a / max(rms_b, 1e-6)
    if ratio > threshold_ratio:
        return "dominancia_a"
    if ratio < 1.0 / threshold_ratio:
        return "dominancia_b"
    return "balanceada"


def build_feature_row(features_a: BurstFeatures, features_b: BurstFeatures) -> dict:
    """Combina features de ambos canales en un solo registro para el modelo."""
    row = {f"a_{k}": v for k, v in features_a.to_dict().items()}
    row.update({f"b_{k}": v for k, v in features_b.to_dict().items()})
    row["rms_ratio_ab"] = features_a.rms / max(features_b.rms, 1e-6)
    row["mav_ratio_ab"] = features_a.mav / max(features_b.mav, 1e-6)
    return row


class ActivationPatternClassifier:
    """
    Wrapper sobre un RandomForestClassifier de scikit-learn. Se puede
    sustituir por xgboost.XGBClassifier o lightgbm.LGBMClassifier sin
    cambiar la interfaz — ambos implementan fit/predict compatibles.
    """

    def __init__(self):
        self.scaler = StandardScaler()
        self.model = RandomForestClassifier(
            n_estimators=200, max_depth=6, random_state=42, class_weight="balanced"
        )
        self._is_fitted = False

    def fit(self, df: pd.DataFrame, labels: list[str], test_size: float = 0.2) -> dict:
        """
        `df`: una fila por evaluación, columnas = build_feature_row(...).
        `labels`: la etiqueta real de cada fila (ver LABELS).
        Devuelve el classification_report de sklearn sobre el hold-out.
        """
        X_train, X_test, y_train, y_test = train_test_split(
            df, labels, test_size=test_size, random_state=42, stratify=labels
        )
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)

        self.model.fit(X_train_scaled, y_train)
        self._is_fitted = True

        y_pred = self.model.predict(X_test_scaled)
        return classification_report(y_test, y_pred, output_dict=True)

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        if not self._is_fitted:
            raise RuntimeError(
                "El modelo todavía no está entrenado. Usa rule_based_label() "
                "mientras se acumulan datos suficientes para fit()."
            )
        X_scaled = self.scaler.transform(df)
        return self.model.predict(X_scaled)

    def save(self, path: Path | str) -> None:
        joblib.dump({"scaler": self.scaler, "model": self.model}, path)

    @classmethod
    def load(cls, path: Path | str) -> "ActivationPatternClassifier":
        data = joblib.load(path)
        instance = cls()
        instance.scaler = data["scaler"]
        instance.model = data["model"]
        instance._is_fitted = True
        return instance
