"""
Pruebas de la simulación intra-sujeto.

Verifican que la simulación se comporte como debe comportarse un
experimento de medición repetida. Si alguna de estas fallara, los
números que produce el módulo no servirían para decidir nada del
protocolo.
"""

from __future__ import annotations

import pytest

from myofit_pro.ml.within_subject import (
    CV_ENTRE_SESIONES,
    longitudinal_power,
    minimal_detectable_change,
    simulate_screening,
)


class TestTamizaje:
    def test_sin_ruido_el_orden_siempre_es_correcto(self):
        """Control de cordura: con medición perfecta no hay error posible."""
        r = simulate_screening(n_exercises=6, spread_pct=12, cv=0.0, trials=300)
        assert r.acierta_el_mejor == 1.0
        assert r.tau_orden == pytest.approx(1.0)

    def test_mas_ruido_empeora_el_orden(self):
        limpio = simulate_screening(cv=0.05, trials=2000)
        sucio = simulate_screening(cv=0.25, trials=2000)
        assert limpio.acierta_el_mejor > sucio.acierta_el_mejor
        assert limpio.tau_orden > sucio.tau_orden

    def test_medir_mas_veces_mejora_el_orden(self):
        una = simulate_screening(repeats=1, cv=0.20, trials=2000)
        tres = simulate_screening(repeats=3, cv=0.20, trials=2000)
        assert tres.acierta_el_mejor > una.acierta_el_mejor

    def test_ejercicios_mas_separados_son_mas_faciles_de_ordenar(self):
        """
        Si todos los ejercicios activan casi igual en esa persona, no hay
        nada que ordenar por más que se mida bien. Es el parámetro que
        todavía no conocemos y el que más decide.
        """
        juntos = simulate_screening(spread_pct=4, cv=0.15, trials=2000)
        separados = simulate_screening(spread_pct=20, cv=0.15, trials=2000)
        assert separados.acierta_el_mejor > juntos.acierta_el_mejor

    def test_el_top3_aguanta_mucho_mejor_que_el_top1(self):
        """
        El hallazgo que cambia qué debería decir la aplicación: acertar
        el mejor es frágil, pero que el mejor esté entre los tres
        primeros es robusto. Conviene recomendar tres ejercicios, no uno.
        """
        r = simulate_screening(cv=0.15, repeats=1, trials=3000)
        assert r.mejor_en_top3 > r.acierta_el_mejor + 0.25

    def test_cuenta_bien_las_series_del_protocolo(self):
        r = simulate_screening(n_exercises=8, repeats=3, trials=100)
        assert r.sesiones_necesarias == 24


class TestCambioDetectable:
    def test_mas_ruido_exige_un_cambio_mayor(self):
        assert minimal_detectable_change(0.20) > minimal_detectable_change(0.05)

    def test_baja_con_la_raiz_del_numero_de_mediciones(self):
        """
        Es la razón por la que medir dos veces ayuda bastante y medir
        diez ya casi no: el error baja con la raíz, no linealmente.
        """
        una = minimal_detectable_change(0.15, repeats=1)
        cuatro = minimal_detectable_change(0.15, repeats=4)
        assert cuatro == pytest.approx(una / 2.0, rel=1e-9)

    def test_sin_ruido_cualquier_cambio_es_detectable(self):
        assert minimal_detectable_change(0.0) == 0.0

    def test_con_ruido_tipico_entre_sesiones_el_umbral_es_grande(self):
        """
        Con la repetibilidad que reporta la literatura para electrodos
        re-colocados, el umbral pasa de la mitad del valor medido. Este
        es el problema central del seguimiento longitudinal y conviene
        que quede fijado en una prueba.
        """
        umbral = minimal_detectable_change(CV_ENTRE_SESIONES, repeats=1)
        assert umbral > 65.0 * 0.5


class TestSeguimiento:
    def test_mejoras_grandes_se_detectan_mas_que_las_chicas(self):
        chica = longitudinal_power(5, cv=0.20, trials=8000)
        grande = longitudinal_power(30, cv=0.20, trials=8000)
        assert grande > chica

    def test_medir_mas_veces_sube_la_deteccion(self):
        una = longitudinal_power(20, cv=0.20, repeats=1, trials=8000)
        tres = longitudinal_power(20, cv=0.20, repeats=3, trials=8000)
        assert tres > una

    def test_con_electrodos_recolocados_una_mejora_normal_casi_no_se_ve(self):
        """
        El resultado incómodo: con una sola medición y el ruido de
        re-colocar electrodos, una mejora real del 10% se detecta menos
        de una de cada cinco veces. Por eso el seguimiento no puede
        basarse en comparar amplitudes absolutas entre sesiones.
        """
        assert longitudinal_power(10, cv=CV_ENTRE_SESIONES, repeats=1, trials=8000) < 0.2

    def test_sin_ruido_cualquier_mejora_real_se_detecta(self):
        assert longitudinal_power(5, cv=0.0, trials=500) == pytest.approx(1.0)
