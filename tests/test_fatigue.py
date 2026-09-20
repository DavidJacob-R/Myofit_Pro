"""
Pruebas de la detección de fatiga por caída de frecuencia mediana.

Se construyen señales sintéticas con una frecuencia conocida que baja (o
no) a lo largo de la serie, y se comprueba que el módulo la siga. Si
fallaran, la tarjeta de fatiga del reporte estaría inventando.
"""

from __future__ import annotations

import numpy as np
import pytest

from myofit_pro.ml.fatigue import (
    CAIDA_MINIMA_PCT,
    fatigue_from_signal,
    fatigue_trend,
    median_frequencies,
)

FS = 1000.0


def señal(frecuencias_hz: list[float], segundos_por_tramo: float = 1.0) -> np.ndarray:
    """
    Concatena tramos senoidales con ruido, cada uno a su frecuencia.

    El ruido es necesario: una senoidal pura tiene un espectro de una
    sola línea y Welch la resuelve perfecto, que no es el caso del EMG.
    """
    rng = np.random.default_rng(3)
    tramos = []
    for hz in frecuencias_hz:
        n = int(FS * segundos_por_tramo)
        t = np.arange(n) / FS
        tramos.append(np.sin(2 * np.pi * hz * t) + 0.25 * rng.normal(size=n))
    return np.concatenate(tramos)


class TestFrecuenciasPorVentana:
    def test_sigue_la_frecuencia_que_se_le_inyecta(self):
        valores = median_frequencies(señal([120, 100, 80, 60]), FS, windows=4)
        assert len(valores) == 4
        assert valores == sorted(valores, reverse=True)

    def test_una_señal_corta_no_da_ventanas(self):
        assert median_frequencies(np.zeros(100), FS) == []

    def test_no_devuelve_menos_de_tres_ventanas(self):
        """Con dos puntos cualquier recta ajusta perfecto y no dice nada."""
        assert median_frequencies(np.random.default_rng(1).normal(size=500), FS) == []


class TestTendencia:
    def test_una_caida_sostenida_es_fatiga(self):
        r = fatigue_from_signal(señal([130, 115, 100, 85, 70, 55]), FS)
        assert r.is_fatiguing
        assert r.drop_pct > CAIDA_MINIMA_PCT
        assert r.slope_hz_per_window < 0

    def test_una_frecuencia_estable_no_es_fatiga(self):
        r = fatigue_from_signal(señal([100, 100, 100, 100, 100, 100]), FS)
        assert not r.is_fatiguing

    def test_una_caida_minima_no_cuenta_como_fatiga(self):
        """Por debajo del umbral es variación normal de la serie."""
        r = fatigue_from_signal(señal([100, 99, 98, 99, 97, 98]), FS)
        assert not r.is_fatiguing

    def test_una_caida_erratica_no_cuenta_como_fatiga(self):
        """
        Bajar mucho pero sin orden no es fatiga progresiva. El R² es lo
        que separa una cosa de la otra.
        """
        r = fatigue_trend([120.0, 60.0, 130.0, 55.0, 125.0, 58.0])
        assert not r.is_fatiguing
        assert r.r2 < 0.3

    def test_la_frecuencia_subiendo_no_es_fatiga(self):
        r = fatigue_trend([60.0, 75.0, 90.0, 105.0, 120.0])
        assert not r.is_fatiguing
        assert r.slope_hz_per_window > 0

    def test_menos_de_tres_ventanas_no_se_evalua(self):
        assert fatigue_trend([100.0, 80.0]).windows == 0

    def test_una_señal_en_silencio_no_revienta(self):
        r = fatigue_trend([0.0, 0.0, 0.0, 0.0])
        assert not r.is_fatiguing
        assert r.drop_pct == 0.0

    def test_la_caida_se_mide_sobre_la_recta_y_no_sobre_los_extremos(self):
        """
        Una ventana atípica al final no debe decidir el resultado: la
        caída sale del ajuste, no de restar el último menos el primero.
        """
        con_atipico = fatigue_trend([100.0, 95.0, 90.0, 85.0, 20.0])
        crudo = (100.0 - 20.0) / 100.0 * 100.0
        assert con_atipico.drop_pct < crudo

    def test_el_resumen_dice_el_porcentaje_cuando_hay_fatiga(self):
        r = fatigue_from_signal(señal([130, 115, 100, 85, 70, 55]), FS)
        assert "%" in r.summary and "Fatiga" in r.summary

    def test_el_resumen_lo_dice_cuando_no_hay_señal(self):
        assert "Sin señal" in fatigue_trend([]).summary


class TestRangos:
    @pytest.mark.parametrize("valores", [
        [100.0, 90.0, 80.0, 70.0],
        [50.0, 50.0, 50.0],
        [10.0, 20.0, 30.0, 40.0, 50.0],
    ])
    def test_el_r2_siempre_esta_entre_cero_y_uno(self, valores):
        assert 0.0 <= fatigue_trend(valores).r2 <= 1.0
