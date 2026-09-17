"""
Pruebas del generador de datos sintéticos y del banco de pruebas.

Lo que se verifica aquí no es que los datos sean "realistas" (eso no se
puede probar), sino que tengan las propiedades estructurales que hacen
útil el experimento:

  - Que sean reproducibles con la misma semilla, para poder comparar
    algoritmos sobre exactamente los mismos datos.
  - Que los cuerpos sean fisiológicamente coherentes, porque variables
    sin correlación entre sí son el caso fácil y harían ver mejor a
    cualquier modelo.
  - Que las evaluaciones del mismo cliente se parezcan entre sí. Esa es
    la propiedad que obliga a validar agrupando por cliente, y si el
    generador no la tuviera, el banco de pruebas no demostraría nada.
"""

from __future__ import annotations

import numpy as np
import pytest

from myofit_pro.body_composition import SEX_FEMALE, SEX_MALE, bmi
from myofit_pro.ml.benchmark import variance_split
from myofit_pro.ml.synthetic import EXERCISES, MUSCLES, build_dataset


@pytest.fixture(scope="module")
def dataset():
    return build_dataset(n_clients=60, seed=7)


class TestReproducibilidad:
    def test_la_misma_semilla_da_los_mismos_datos(self):
        a_clients, a_evals, _ = build_dataset(n_clients=20, seed=3)
        b_clients, b_evals, _ = build_dataset(n_clients=20, seed=3)
        assert a_clients.equals(b_clients)
        assert a_evals.equals(b_evals)

    def test_semillas_distintas_dan_datos_distintos(self):
        a, _, _ = build_dataset(n_clients=20, seed=3)
        b, _, _ = build_dataset(n_clients=20, seed=4)
        assert not a.equals(b)


class TestCoherenciaFisiologica:
    def test_el_imc_cuadra_con_estatura_y_peso(self, dataset):
        clients, _, _ = dataset
        for _, row in clients.iterrows():
            esperado = bmi(row["height_cm"], row["weight_kg"])
            assert row["bmi"] == pytest.approx(esperado, abs=0.02)

    def test_los_rangos_son_posibles(self, dataset):
        clients, _, _ = dataset
        assert clients["age_years"].between(16, 70).all()
        assert clients["height_cm"].between(140, 200).all()
        assert clients["weight_kg"].between(35, 180).all()
        assert clients["body_fat_pct"].between(3, 65).all()

    def test_la_cintura_es_mayor_que_el_cuello(self, dataset):
        """Si no, el método de circunferencias no tendría solución."""
        clients, _, _ = dataset
        assert (clients["waist_cm"] > clients["neck_cm"]).all()

    def test_solo_las_mujeres_traen_cadera(self, dataset):
        """La fórmula femenina la necesita; la masculina no."""
        clients, _, _ = dataset
        mujeres = clients[clients["sex"] == SEX_FEMALE]
        hombres = clients[clients["sex"] == SEX_MALE]
        assert mujeres["hip_cm"].notna().all()
        assert hombres["hip_cm"].isna().all()

    def test_el_peso_correlaciona_con_la_estatura(self, dataset):
        """
        Generarlos independientes daría combinaciones imposibles y haría
        el problema artificialmente fácil.
        """
        clients, _, _ = dataset
        r = clients["height_cm"].corr(clients["weight_kg"])
        assert r > 0.3, f"correlación estatura-peso demasiado baja: {r:.2f}"


class TestEstructuraDeLasEvaluaciones:
    def test_cada_ejercicio_pertenece_a_su_musculo(self, dataset):
        _, evals, _ = dataset
        for _, row in evals.iterrows():
            assert row["muscle"] in MUSCLES
            assert row["exercise"] in EXERCISES[row["muscle"]]

    def test_los_clientes_tienen_distinto_numero_de_evaluaciones(self, dataset):
        """
        Un conjunto balanceado escondería que los clientes con más
        historial dominan el entrenamiento.
        """
        _, evals, _ = dataset
        conteos = evals.groupby("client_id").size()
        assert conteos.min() < conteos.max()

    def test_la_fatiga_siempre_es_negativa(self, dataset):
        """
        La frecuencia mediana BAJA conforme el músculo se fatiga. Una
        pendiente positiva sería un músculo que se desfatiga solo.
        """
        _, evals, _ = dataset
        assert (evals["fatigue_slope_hz_per_rep"] < 0).all()

    def test_la_activacion_esta_en_rango_de_porcentaje(self, dataset):
        _, evals, _ = dataset
        assert evals["mean_activation_pct"].between(15, 100).all()
        assert (evals["peak_activation_pct"] >= evals["mean_activation_pct"]).all()

    def test_los_dos_canales_del_mvc_no_coinciden(self, dataset):
        """
        Medido en hardware real, el mismo gesto dio 978 y 1691 µV en los
        dos sensores solo por la colocación del electrodo. El generador
        reproduce esa dispersión.
        """
        _, evals, _ = dataset
        ratio = evals["mvc_channel_a_uv"] / evals["mvc_channel_b_uv"]
        assert ratio.std() > 0.1


class TestEfectoDeCliente:
    """
    La propiedad que justifica todo el diseño del banco de pruebas.
    """

    def test_las_evaluaciones_del_mismo_cliente_se_parecen(self, dataset):
        """
        Si la variación entre clientes fuera cero, partir al azar no
        causaría fuga y no haría falta GroupKFold. Tiene que ser alta.
        """
        _, evals, _ = dataset
        split = variance_split(evals, "fatigue_slope_hz_per_rep")
        assert split["entre_clientes"] > 0.5

    def test_la_activacion_varia_mucho_dentro_del_mismo_cliente(self, dataset):
        """
        Porque depende del ejercicio, no solo de la persona. Es la razón
        por la que hay que medir a cada cliente en vez de deducir su
        mejor ejercicio de su edad y su peso.
        """
        _, evals, _ = dataset
        split = variance_split(evals, "mean_activation_pct")
        assert split["dentro_del_cliente"] > 0.3

    def test_las_proporciones_suman_uno(self, dataset):
        _, evals, _ = dataset
        split = variance_split(evals, "mean_activation_pct")
        assert split["entre_clientes"] + split["dentro_del_cliente"] == pytest.approx(1.0)


class TestBancoDePruebas:
    def test_agrupar_por_cliente_da_un_resultado_mas_bajo(self, dataset):
        """
        La prueba central: partir al azar infla el resultado porque el
        modelo memoriza clientes que ya vio. Si esta prueba fallara,
        querría decir que el banco no está detectando la fuga.
        """
        from myofit_pro.ml.benchmark import run_target

        clients, evals, _ = dataset
        df = evals.merge(clients, on="client_id", how="left")
        result = run_target(df, "fatigue_slope_hz_per_rep", folds=5)

        arboles = result[result["modelo"].isin(("Random Forest", "Gradient Boosting"))]
        assert (arboles["inflado_por_fuga"] > 0.2).all(), (
            "los modelos de árboles deberían memorizar clientes y verse "
            "mucho mejor con la partición ingenua"
        )

    def test_algun_modelo_le_gana_al_promedio(self, dataset):
        """
        Con 60 clientes ya debería haber señal recuperable. Si ningún
        modelo le gana a predecir la media, el generador no metió
        ninguna relación aprendible.
        """
        from myofit_pro.ml.benchmark import run_target

        clients, evals, _ = dataset
        df = evals.merge(clients, on="client_id", how="left")
        result = run_target(df, "fatigue_slope_hz_per_rep", folds=5)

        baseline = result.loc[result["modelo"] == "Promedio (línea base)", "MAE"].iloc[0]
        assert result["MAE"].min() < baseline * 0.9

    def test_ridge_recupera_el_signo_de_las_relaciones(self, dataset):
        """
        Los datos se generaron con más experiencia = menos fatiga y más
        edad = más fatiga. Un modelo que no recupera eso en datos donde
        SÍ está, tampoco lo va a encontrar en los reales.
        """
        from myofit_pro.ml.benchmark import coefficients

        clients, evals, _ = dataset
        df = evals.merge(clients, on="client_id", how="left")
        coefs = coefficients(df, "fatigue_slope_hz_per_rep").set_index("variable")

        # La pendiente es negativa: acercarla a cero es fatigarse menos.
        assert coefs.loc["experience_num", "coeficiente_estandarizado"] > 0
        assert coefs.loc["age_years", "coeficiente_estandarizado"] < 0


class TestTechoDePrediccion:
    def test_el_techo_es_la_parte_que_varia_entre_clientes(self):
        """
        Un objetivo que solo cambia DENTRO de cada cliente no se puede
        predecir con datos de la ficha, porque la ficha es la misma en
        todas las evaluaciones de esa persona.
        """
        import pandas as pd

        rng = np.random.default_rng(0)
        # Mismo valor por cliente: toda la variación está entre clientes
        entre = pd.DataFrame(
            {"client_id": np.repeat(np.arange(20), 5), "y": np.repeat(rng.normal(size=20), 5)}
        )
        assert variance_split(entre, "y")["techo_r2"] == pytest.approx(1.0)

        # Todos los clientes con la misma media: nada que predecir
        dentro = pd.DataFrame(
            {"client_id": np.repeat(np.arange(20), 5), "y": np.tile([-2.0, -1.0, 0.0, 1.0, 2.0], 20)}
        )
        assert variance_split(dentro, "y")["techo_r2"] == pytest.approx(0.0, abs=1e-9)
