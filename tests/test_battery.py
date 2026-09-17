"""
Pruebas del cálculo de repetibilidad de la batería de ejercicios.

El coeficiente de variación que muestra el Paso 5 es el número con el
que el entrenador decide si la diferencia entre dos ejercicios es real.
Si estuviera mal calculado, la app estaría avalando decisiones sobre
ruido, así que conviene tenerlo cubierto.

Estas pruebas no necesitan interfaz gráfica: solo tocan las funciones
de cálculo, que son estáticas a propósito.
"""

from __future__ import annotations

import numpy as np
import pytest

from myofit_pro.gui.evaluation_step5_view import EvaluationStep5View, _plural_mediciones

cv = EvaluationStep5View._cv


class TestCoeficienteDeVariacion:
    def test_mediciones_identicas_no_varian(self):
        assert cv([70.0, 70.0, 70.0]) == 0.0

    def test_una_sola_medicion_no_tiene_variacion_calculable(self):
        """Con un solo dato no hay dispersión que medir."""
        assert cv([70.0]) == 0.0

    def test_lista_vacia_no_revienta(self):
        assert cv([]) == 0.0

    def test_coincide_con_el_calculo_manual(self):
        valores = [72.0, 68.0, 70.0, 74.0]
        esperado = float(np.std(valores, ddof=1)) / float(np.mean(valores))
        assert cv(valores) == pytest.approx(esperado)

    def test_usa_la_desviacion_muestral_y_no_la_poblacional(self):
        """
        Con pocas mediciones la diferencia importa: dividir entre n en
        vez de entre n-1 subestima la dispersión, que es justo el error
        que haría ver la medición más confiable de lo que es.
        """
        valores = [72.0, 68.0, 70.0]
        poblacional = float(np.std(valores, ddof=0)) / float(np.mean(valores))
        assert cv(valores) > poblacional

    def test_mas_dispersion_da_mas_coeficiente(self):
        assert cv([69.0, 70.0, 71.0]) < cv([50.0, 70.0, 90.0])

    def test_es_relativo_a_la_media(self):
        """
        Una dispersión de 5 puntos sobre una media de 20 es mucho peor
        que sobre una media de 80. Por eso se usa el coeficiente y no la
        desviación en crudo.
        """
        bajo = cv([15.0, 20.0, 25.0])
        alto = cv([75.0, 80.0, 85.0])
        assert bajo > alto

    def test_media_cero_no_divide_entre_cero(self):
        assert cv([0.0, 0.0]) == 0.0

    def test_recupera_la_dispersion_que_se_le_inyecta(self):
        """
        Con muchas mediciones de una distribución conocida, el
        coeficiente estimado debe acercarse al real.
        """
        rng = np.random.default_rng(4)
        valores = (70.0 * rng.normal(1.0, 0.10, size=500)).tolist()
        assert cv(valores) == pytest.approx(0.10, abs=0.015)


class TestPlural:
    def test_singular(self):
        assert _plural_mediciones(1) == "1 medición"

    @pytest.mark.parametrize("n", [0, 2, 5])
    def test_plural_sin_acento(self, n):
        """El plural de "medición" pierde el acento."""
        texto = _plural_mediciones(n)
        assert texto == f"{n} mediciones"
        assert "mediciónes" not in texto


class TestRankingPorPromedio:
    """
    El ranking promedia las mediciones repetidas de un mismo ejercicio
    antes de comparar. Una sola serie puede salir alta por casualidad, y
    ese promedio es justo lo que hace confiable el orden.
    """

    @staticmethod
    def _ranking(by_exercise: dict[str, list[float]]) -> list[str]:
        return [
            name
            for name, _ in sorted(
                by_exercise.items(),
                key=lambda item: sum(item[1]) / len(item[1]),
                reverse=True,
            )
        ]

    def test_ordena_por_promedio_y_no_por_el_mejor_intento(self):
        """
        "Inestable" tiene el intento más alto (95) pero el promedio más
        bajo. El orden debe seguir al promedio.
        """
        orden = self._ranking(
            {"Inestable": [95.0, 40.0, 45.0], "Consistente": [70.0, 71.0, 69.0]}
        )
        assert orden[0] == "Consistente"

    def test_un_ejercicio_con_una_sola_medicion_tambien_entra(self):
        orden = self._ranking({"Medido tres veces": [60.0, 62.0, 61.0], "Medido una": [80.0]})
        assert orden[0] == "Medido una"
