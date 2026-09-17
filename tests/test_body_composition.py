"""
Pruebas de las fórmulas de composición corporal.

Los sensores sEMG no pueden medir grasa corporal: la bioimpedancia
necesita inyectar corriente y el MYOblue es un amplificador pasivo. Por
eso estos números salen de fórmulas sobre datos que el entrenador
captura a mano, y por eso conviene que las fórmulas estén cubiertas.

La prueba que más importa es `TestColinealidad`: demuestra con números
por qué la estimación de Deurenberg no puede tratarse como una variable
más al alimentar un modelo.
"""

from __future__ import annotations

import pytest

from myofit_pro.body_composition import (
    GOALS,
    SEX_FEMALE,
    SEX_MALE,
    BodyFatSource,
    bmi,
    bmi_category,
    body_fat_category,
    deurenberg_body_fat,
    experience_to_number,
    features_for_model,
    navy_body_fat,
    resolve_body_fat,
)
from myofit_pro.database.models import Client


class TestBmi:
    def test_formula(self):
        assert bmi(178, 82.5) == pytest.approx(26.04, abs=0.01)

    @pytest.mark.parametrize(
        "height,weight", [(None, 60.0), (165.0, None), (0.0, 60.0)]
    )
    def test_sin_datos_devuelve_none(self, height, weight):
        assert bmi(height, weight) is None

    @pytest.mark.parametrize(
        "value,expected",
        [(17.0, "Bajo peso"), (22.0, "Normal"), (27.0, "Sobrepeso"),
         (33.0, "Obesidad"), (None, "—")],
    )
    def test_clasificacion(self, value, expected):
        assert bmi_category(value) == expected


class TestDeurenberg:
    def test_formula_hombre(self):
        # 1.20 x 26.04 + 0.23 x 28 - 10.8 x 1 - 5.4
        assert deurenberg_body_fat(26.04, 28, SEX_MALE) == pytest.approx(21.49, abs=0.05)

    def test_el_sexo_desplaza_el_resultado_10_8_puntos(self):
        """El término de sexo es una constante, no una interacción."""
        hombre = deurenberg_body_fat(26.04, 28, SEX_MALE)
        mujer = deurenberg_body_fat(26.04, 28, SEX_FEMALE)
        assert mujer - hombre == pytest.approx(10.8, abs=0.01)

    @pytest.mark.parametrize(
        "bmi_value,age,sex",
        [(None, 28, SEX_MALE), (26.0, None, SEX_MALE), (26.0, 28, None)],
    )
    def test_sin_alguno_de_los_tres_no_hay_estimacion(self, bmi_value, age, sex):
        assert deurenberg_body_fat(bmi_value, age, sex) is None

    def test_se_acota_a_un_rango_posible(self):
        """
        La fórmula es lineal y se dispara fuera de los rangos con los que
        se ajustó: con un IMC de 60 devolvería más del 70% de grasa.
        """
        assert deurenberg_body_fat(60.0, 60, SEX_FEMALE) <= 65.0
        assert deurenberg_body_fat(12.0, 18, SEX_MALE) >= 3.0


class TestNavy:
    def test_hombre(self):
        value = navy_body_fat(SEX_MALE, height_cm=178, neck_cm=38, waist_cm=88)
        assert value == pytest.approx(18.7, abs=0.2)

    def test_mujer(self):
        value = navy_body_fat(
            SEX_FEMALE, height_cm=165, neck_cm=32, waist_cm=74, hip_cm=96
        )
        assert value == pytest.approx(27.4, abs=0.2)

    def test_en_mujeres_la_cadera_es_obligatoria(self):
        assert navy_body_fat(SEX_FEMALE, 165, 32, 74) is None

    def test_en_hombres_la_cadera_no_hace_falta(self):
        assert navy_body_fat(SEX_MALE, 178, 38, 88) is not None

    def test_medida_imposible_devuelve_none(self):
        """
        Cintura menor que cuello es una medida mal tomada. Vale más
        devolver None que un número inventado que nadie va a cuestionar.
        """
        assert navy_body_fat(SEX_MALE, 178, neck_cm=40, waist_cm=38) is None

    def test_mas_cintura_es_mas_grasa(self):
        delgado = navy_body_fat(SEX_MALE, 178, 38, 80)
        ancho = navy_body_fat(SEX_MALE, 178, 38, 100)
        assert ancho > delgado


class TestResolveBodyFat:
    """El orden de preferencia entre las tres fuentes."""

    MEDIDAS = dict(sex=SEX_MALE, age_years=28, height_cm=178, weight_kg=82.5)
    CINTAS = dict(neck_cm=38.0, waist_cm=88.0)

    def test_el_dato_medido_gana_sobre_todo(self):
        pct, source = resolve_body_fat(17.5, **self.MEDIDAS, **self.CINTAS)
        assert pct == pytest.approx(17.5)
        assert source == BodyFatSource.MEASURED.value

    def test_las_circunferencias_ganan_sobre_la_estimacion(self):
        pct, source = resolve_body_fat(None, **self.MEDIDAS, **self.CINTAS)
        assert source == BodyFatSource.NAVY.value
        assert pct == pytest.approx(18.7, abs=0.2)

    def test_sin_cintas_cae_a_la_estimacion(self):
        pct, source = resolve_body_fat(None, **self.MEDIDAS)
        assert source == BodyFatSource.ESTIMATED.value
        assert pct == pytest.approx(21.5, abs=0.2)

    def test_sin_nada_no_inventa(self):
        assert resolve_body_fat(None, None, None, None, None) == (None, None)


class TestColinealidad:
    """
    Por qué la estimación de Deurenberg no sirve como variable de entrada.

    Deurenberg es 1.20 x IMC + 0.23 x edad - 10.8 x sexo - 5.4, o sea una
    combinación lineal de tres variables que el modelo ya recibe. No
    aporta información: es esas tres reescritas.
    """

    def test_deurenberg_no_distingue_cuerpos_distintos(self):
        """
        Tres personas con el mismo IMC, edad y sexo, pero con 20 cm de
        diferencia de cintura. Deurenberg les da el mismo número; el
        método de circunferencias las separa por más de 14 puntos.
        """
        bmi_value = bmi(178, 82.5)
        estimaciones = {
            deurenberg_body_fat(bmi_value, 28, SEX_MALE) for _ in (80, 88, 100)
        }
        assert len(estimaciones) == 1, "Deurenberg debería dar siempre lo mismo aquí"

        medidos = [navy_body_fat(SEX_MALE, 178, 38, w) for w in (80, 88, 100)]
        assert max(medidos) - min(medidos) > 14.0

    def test_deurenberg_es_funcion_exacta_de_imc_edad_y_sexo(self):
        """
        Si se puede reconstruir a partir de las otras columnas, es una
        columna duplicada. Esto es lo que vuelve inestables los
        coeficientes de una regresión lineal.
        """
        for bmi_value, age, sex in ((22.0, 25, SEX_MALE), (31.0, 47, SEX_FEMALE)):
            esperado = (
                1.20 * bmi_value
                + 0.23 * age
                - 10.8 * (1.0 if sex == SEX_MALE else 0.0)
                - 5.4
            )
            assert deurenberg_body_fat(bmi_value, age, sex) == pytest.approx(esperado)


class TestFeaturesForModel:
    def _client(self, **overrides):
        fields = dict(
            full_name="Ana Pérez", goal="Definición", sex=SEX_FEMALE, age_years=30,
            height_cm=165.0, weight_kg=60.0,
            experience_level="Intermedio", days_per_week=4,
        )
        fields.update(overrides)
        return Client(**fields)

    def test_la_estimacion_no_entra_como_variable(self):
        client = self._client(
            body_fat_pct=28.0, body_fat_source=BodyFatSource.ESTIMATED.value
        )
        row = features_for_model(client)
        assert row["body_fat_pct"] == 0.0
        assert row["body_fat_is_real"] == 0.0

    @pytest.mark.parametrize(
        "source", [BodyFatSource.MEASURED.value, BodyFatSource.NAVY.value]
    )
    def test_el_dato_real_si_entra(self, source):
        row = features_for_model(self._client(body_fat_pct=24.5, body_fat_source=source))
        assert row["body_fat_pct"] == pytest.approx(24.5)
        assert row["body_fat_is_real"] == 1.0

    def test_el_objetivo_va_one_hot(self):
        """
        Codificarlo como 1, 2, 3 le diría al modelo que definición está
        "entre" fuerza e hipertrofia, que no significa nada.
        """
        row = features_for_model(self._client(goal="Definición"))
        activos = [k for k in row if k.startswith("goal_") and row[k] == 1.0]
        assert activos == ["goal_definicion"]
        assert len([k for k in row if k.startswith("goal_")]) == len(GOALS)

    def test_ficha_incompleta_devuelve_none(self):
        """Mejor descartar la fila que rellenarla con ceros."""
        assert features_for_model(self._client(age_years=None)) is None
        assert features_for_model(self._client(sex=None)) is None
        assert features_for_model(self._client(height_cm=None)) is None


class TestEtiquetas:
    def test_la_grasa_se_clasifica_distinto_por_sexo(self):
        """
        El mismo 20% es "promedio" en un hombre y "atlético" en una
        mujer, porque la grasa esencial del cuerpo femenino es mayor. Por
        eso la clasificación no se puede hacer sin saber el sexo.
        """
        assert body_fat_category(20.0, SEX_MALE) == "Promedio"
        assert body_fat_category(20.0, SEX_FEMALE) == "Atlético"

    def test_los_cortes_siguen_los_rangos_de_referencia(self):
        """Rangos del American Council on Exercise, por sexo."""
        for pct, expected in ((4.0, "Esencial"), (10.0, "Atlético"),
                              (16.0, "En forma"), (22.0, "Promedio"), (30.0, "Alto")):
            assert body_fat_category(pct, SEX_MALE) == expected

        for pct, expected in ((12.0, "Esencial"), (18.0, "Atlético"),
                              (23.0, "En forma"), (28.0, "Promedio"), (35.0, "Alto")):
            assert body_fat_category(pct, SEX_FEMALE) == expected

    def test_sin_sexo_no_hay_clasificacion(self):
        assert body_fat_category(20.0, None) == "—"

    @pytest.mark.parametrize(
        "level,expected",
        [("Principiante", 1), ("Intermedio", 2), ("Avanzado", 3), (None, 0), ("raro", 0)],
    )
    def test_experiencia_a_numero(self, level, expected):
        assert experience_to_number(level) == expected
