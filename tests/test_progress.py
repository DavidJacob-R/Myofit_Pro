"""
Pruebas de la comparación de progreso entre evaluaciones.

Estas son las pruebas más importantes del proyecto, porque este módulo
es el que le dice al entrenador "tu cliente mejoró". Si se equivoca, la
app avala decisiones sobre ruido de medición, que es peor que no decir
nada.

Lo que más se cuida aquí es el caso contraintuitivo: a carga fija, MENOS
activación puede ser progreso (adaptación neural). Una app que solo mire
el porcentaje lo reporta al revés.
"""

from __future__ import annotations

import datetime as dt

import pytest

from myofit_pro.progress import (
    CV_POR_DEFECTO,
    FACTOR_ENTRE_SESIONES,
    ExerciseSnapshot,
    SessionSnapshot,
    Verdict,
    classify,
    compare,
    minimal_detectable_change,
    resolve_cv,
    trend_for,
)

HOY = dt.datetime(2026, 9, 17, 10, 0)
HACE_UN_MES = HOY - dt.timedelta(days=28)


def ejercicio(
    exercise_id: int = 1,
    name: str = "Curl con barra",
    activation: float = 70.0,
    load: float | None = 20.0,
    rank: int = 1,
    measurements: int = 2,
) -> ExerciseSnapshot:
    return ExerciseSnapshot(
        exercise_id=exercise_id,
        name=name,
        activation_pct=activation,
        measurements=measurements,
        load_kg=load,
        rank=rank,
    )


def sesion(
    *ejercicios: ExerciseSnapshot,
    fecha: dt.datetime = HOY,
    session_id: int = 1,
    circunferencia: float | None = None,
    cv: float | None = None,
    balance: float | None = None,
) -> SessionSnapshot:
    return SessionSnapshot(
        session_id=session_id,
        date=fecha,
        muscle_id=1,
        muscle_name="Bíceps braquial",
        goal="Hipertrofia",
        exercises=ejercicios,
        circumference_cm=circunferencia,
        repeatability_cv=cv,
        balance_gap=balance,
    )


class TestVeredicto:
    """
    La tabla de decisión completa. `classify` recibe el cambio de
    activación, el cambio de carga y el umbral de ruido.
    """

    def test_menos_activacion_al_mismo_peso_es_progreso(self):
        """
        EL CASO QUE LA INTUICIÓN FALLA.

        Hacer el mismo trabajo con menos actividad eléctrica es
        adaptación neural: el sistema nervioso aprendió a reclutar con
        menos co-activación. Una app que solo mire el porcentaje diría
        que empeoró.
        """
        assert classify(-12.0, 0.0, threshold=8.0) is Verdict.MAS_EFICIENTE

    def test_mas_peso_es_progreso_aunque_baje_la_activacion(self):
        """Levantar más es levantar más, sin importar qué haga la señal."""
        assert classify(-15.0, 6.0, threshold=8.0) is Verdict.MAS_FUERTE

    def test_mas_peso_es_progreso_aunque_suba_la_activacion(self):
        assert classify(15.0, 6.0, threshold=8.0) is Verdict.MAS_FUERTE

    def test_mas_activacion_al_mismo_peso_es_mas_reclutamiento(self):
        assert classify(12.0, 0.0, threshold=8.0) is Verdict.RECLUTA_MAS

    def test_menos_peso_se_reporta_como_tal(self):
        assert classify(0.0, -5.0, threshold=8.0) is Verdict.MENOS_CARGA

    def test_un_cambio_por_debajo_del_umbral_no_es_cambio(self):
        """El corazón de la honestidad del módulo."""
        assert classify(5.0, 0.0, threshold=8.0) is Verdict.SIN_CAMBIO
        assert classify(-5.0, 0.0, threshold=8.0) is Verdict.SIN_CAMBIO

    def test_justo_en_el_umbral_ya_cuenta(self):
        assert classify(8.0, 0.0, threshold=8.0) is Verdict.RECLUTA_MAS

    def test_sin_peso_anotado_no_se_interpreta(self):
        """
        Sin la carga, un cambio de activación puede ser progreso,
        retroceso o ruido. La app lo dice en vez de elegir uno.
        """
        assert classify(20.0, None, threshold=8.0) is Verdict.SIN_CARGA
        assert classify(-20.0, None, threshold=8.0) is Verdict.SIN_CARGA

    def test_sin_peso_pero_sin_cambio_real_si_se_puede_afirmar(self):
        """Que no cambió nada sí se puede decir sin saber el peso."""
        assert classify(2.0, None, threshold=8.0) is Verdict.SIN_CAMBIO

    def test_un_cambio_minimo_de_peso_cuenta_como_el_mismo_peso(self):
        """
        200 gramos no son un cambio de carga: es menos que el salto entre
        dos mancuernas contiguas.
        """
        assert classify(-12.0, 0.2, threshold=8.0) is Verdict.MAS_EFICIENTE


class TestUmbral:
    def test_mas_ruido_exige_mas_diferencia(self):
        assert minimal_detectable_change(0.20, 70.0) > minimal_detectable_change(0.05, 70.0)

    def test_baja_con_la_raiz_del_numero_de_mediciones(self):
        una = minimal_detectable_change(0.10, 70.0, repeats=1)
        cuatro = minimal_detectable_change(0.10, 70.0, repeats=4)
        assert cuatro == pytest.approx(una / 2.0)

    def test_comparar_entre_sesiones_exige_mas_que_dentro_de_una(self):
        """
        Quitar y volver a poner los electrodos agrega ruido, y el umbral
        tiene que reflejarlo o la app declara progreso donde solo hubo
        recolocación.
        """
        dentro = minimal_detectable_change(0.10, 70.0, between_sessions=False)
        entre = minimal_detectable_change(0.10, 70.0, between_sessions=True)
        assert entre == pytest.approx(dentro * FACTOR_ENTRE_SESIONES)

    def test_sin_ruido_cualquier_cambio_es_detectable(self):
        assert minimal_detectable_change(0.0, 70.0) == 0.0

    def test_es_proporcional_al_valor_medido(self):
        """
        5 puntos sobre una media de 20 es mucho peor que sobre una de 80.
        Por eso el umbral se calcula sobre la base y no es una constante.
        """
        assert minimal_detectable_change(0.10, 80.0) > minimal_detectable_change(0.10, 20.0)

    def test_con_la_repetibilidad_por_defecto_el_umbral_es_grande(self):
        """
        Sin datos propios del cliente, el umbral pasa de la mitad del
        valor medido. Es incómodo y es correcto: es exactamente por qué
        hay que medir la repetibilidad real.
        """
        assert minimal_detectable_change(CV_POR_DEFECTO, 70.0) > 35.0


class TestRepetibilidadDelCliente:
    def test_sin_datos_propios_usa_el_valor_conservador(self):
        cv, medido = resolve_cv([sesion(ejercicio())])
        assert cv == CV_POR_DEFECTO
        assert medido is False

    def test_usa_la_repetibilidad_medida_cuando_existe(self):
        cv, medido = resolve_cv([sesion(ejercicio(), cv=0.08)])
        assert cv == pytest.approx(0.08)
        assert medido is True

    def test_promedia_varias_sesiones(self):
        cv, _ = resolve_cv([
            sesion(ejercicio(), cv=0.06, session_id=1),
            sesion(ejercicio(), cv=0.10, session_id=2),
        ])
        assert cv == pytest.approx(0.08)

    def test_ignora_las_sesiones_sin_repetibilidad(self):
        cv, medido = resolve_cv([
            sesion(ejercicio(), cv=None, session_id=1),
            sesion(ejercicio(), cv=0.12, session_id=2),
        ])
        assert cv == pytest.approx(0.12)
        assert medido is True


class TestComparacion:
    def test_la_primera_evaluacion_no_inventa_comparacion(self):
        reporte = compare(None, sesion(ejercicio()))
        assert reporte.is_first
        assert reporte.comparisons[0].verdict is Verdict.NUEVO
        assert "Primera evaluación" in reporte.headline()

    def test_un_ejercicio_nuevo_se_marca_como_nuevo(self):
        antes = sesion(ejercicio(1, "Curl con barra"), fecha=HACE_UN_MES)
        ahora = sesion(
            ejercicio(1, "Curl con barra"),
            ejercicio(2, "Curl martillo", activation=65.0),
        )
        reporte = compare(antes, ahora)
        nuevos = [c for c in reporte.comparisons if c.verdict is Verdict.NUEVO]
        assert [c.name for c in nuevos] == ["Curl martillo"]

    def test_los_ejercicios_que_ya_no_se_midieron_no_aparecen(self):
        """La comparativa habla del presente, no de lo que se dejó de hacer."""
        antes = sesion(
            ejercicio(1, "Curl con barra"),
            ejercicio(2, "Abandonado", activation=50.0),
            fecha=HACE_UN_MES,
        )
        ahora = sesion(ejercicio(1, "Curl con barra"))
        reporte = compare(antes, ahora)
        assert [c.name for c in reporte.comparisons] == ["Curl con barra"]

    def test_calcula_las_diferencias(self):
        antes = sesion(ejercicio(activation=60.0, load=20.0), fecha=HACE_UN_MES)
        ahora = sesion(ejercicio(activation=72.0, load=24.0))
        c = compare(antes, ahora, cv=0.05).comparisons[0]
        assert c.delta_activation == pytest.approx(12.0)
        assert c.delta_load == pytest.approx(4.0)

    def test_cuenta_los_dias_entre_evaluaciones(self):
        reporte = compare(sesion(ejercicio(), fecha=HACE_UN_MES), sesion(ejercicio()))
        assert reporte.days_between == 28

    def test_el_delta_de_carga_es_none_si_falta_en_alguna(self):
        antes = sesion(ejercicio(load=None), fecha=HACE_UN_MES)
        ahora = sesion(ejercicio(load=24.0))
        assert compare(antes, ahora).comparisons[0].delta_load is None

    def test_subir_en_el_ranking_se_detecta(self):
        antes = sesion(ejercicio(rank=3), fecha=HACE_UN_MES)
        ahora = sesion(ejercicio(rank=1))
        assert compare(antes, ahora).comparisons[0].delta_rank == 2

    def test_las_buenas_noticias_van_primero(self):
        antes = sesion(
            ejercicio(1, "Mejoró", activation=60.0, load=20.0),
            ejercicio(2, "Igual", activation=60.0, load=20.0),
            fecha=HACE_UN_MES,
        )
        ahora = sesion(
            ejercicio(1, "Mejoró", activation=60.0, load=30.0),
            ejercicio(2, "Igual", activation=61.0, load=20.0),
        )
        assert [c.name for c in compare(antes, ahora).comparisons] == ["Mejoró", "Igual"]

    def test_el_resumen_cuenta_cuantos_mejoraron(self):
        antes = sesion(
            ejercicio(1, "A", activation=60.0, load=20.0),
            ejercicio(2, "B", activation=60.0, load=20.0),
            fecha=HACE_UN_MES,
        )
        ahora = sesion(
            ejercicio(1, "A", activation=60.0, load=30.0),
            ejercicio(2, "B", activation=61.0, load=20.0),
        )
        assert "1 de 2 ejercicios mejoraron" in compare(antes, ahora).headline()

    def test_avisa_cuando_ninguno_supero_el_ruido(self):
        antes = sesion(ejercicio(activation=60.0, load=20.0), fecha=HACE_UN_MES)
        ahora = sesion(ejercicio(activation=62.0, load=20.0))
        assert "Ningún ejercicio mejoró" in compare(antes, ahora).headline()

    def test_el_umbral_usa_la_repetibilidad_que_se_le_pasa(self):
        antes = sesion(ejercicio(activation=60.0, load=20.0), fecha=HACE_UN_MES)
        ahora = sesion(ejercicio(activation=68.0, load=20.0))

        con_ruido = compare(antes, ahora, cv=0.20).comparisons[0]
        sin_ruido = compare(antes, ahora, cv=0.02).comparisons[0]

        assert con_ruido.verdict is Verdict.SIN_CAMBIO
        assert sin_ruido.verdict is Verdict.RECLUTA_MAS

    def test_una_mejora_real_no_se_pierde_por_ser_estricto(self):
        """
        El umbral protege de falsos positivos, pero una mejora grande con
        buena repetibilidad tiene que pasar. Si no, la app nunca diría
        nada y sería inútil.
        """
        antes = sesion(ejercicio(activation=55.0, load=20.0), fecha=HACE_UN_MES)
        ahora = sesion(ejercicio(activation=80.0, load=20.0))
        assert compare(antes, ahora, cv=0.06).comparisons[0].is_significant


class TestCircunferenciaYBalance:
    def test_la_circunferencia_es_la_medida_directa_de_hipertrofia(self):
        antes = sesion(ejercicio(), fecha=HACE_UN_MES, circunferencia=32.0)
        ahora = sesion(ejercicio(), circunferencia=33.5)
        assert compare(antes, ahora).delta_circumference == pytest.approx(1.5)

    def test_sin_cinta_metrica_no_hay_dato_de_crecimiento(self):
        """
        El sEMG no puede sustituirla: mide actividad eléctrica, no
        tamaño. Si no se midió, la comparativa no lo deduce de la señal.
        """
        antes = sesion(ejercicio(), fecha=HACE_UN_MES, circunferencia=32.0)
        ahora = sesion(ejercicio(), circunferencia=None)
        assert compare(antes, ahora).delta_circumference is None

    def test_el_balance_mejorando_da_un_delta_negativo(self):
        """Menos diferencia entre canales es mejor reclutamiento."""
        antes = sesion(ejercicio(), fecha=HACE_UN_MES, balance=18.0)
        ahora = sesion(ejercicio(), balance=6.0)
        assert compare(antes, ahora).delta_balance == pytest.approx(-12.0)


class TestTendencia:
    def test_ordena_de_la_mas_vieja_a_la_mas_reciente(self):
        sesiones = [
            sesion(ejercicio(activation=70.0), fecha=HOY, session_id=3),
            sesion(ejercicio(activation=60.0), fecha=HACE_UN_MES, session_id=1),
        ]
        valores = [v for _, v in trend_for(sesiones, exercise_id=1)]
        assert valores == [60.0, 70.0]

    def test_salta_las_sesiones_donde_no_se_midio(self):
        sesiones = [
            sesion(ejercicio(1, activation=60.0), fecha=HACE_UN_MES, session_id=1),
            sesion(ejercicio(2, "Otro", activation=99.0), fecha=HOY, session_id=2),
        ]
        assert len(trend_for(sesiones, exercise_id=1)) == 1

    def test_un_ejercicio_que_nunca_se_midio_no_tiene_tendencia(self):
        assert trend_for([sesion(ejercicio())], exercise_id=999) == []


class TestMensajes:
    """El texto que ve el entrenador. Tiene que ser correcto, no solo bonito."""

    def test_el_mensaje_de_mas_fuerte_dice_cuantos_kilos(self):
        antes = sesion(ejercicio(activation=60.0, load=20.0), fecha=HACE_UN_MES)
        ahora = sesion(ejercicio(activation=60.0, load=26.0))
        assert "6 kg" in compare(antes, ahora).comparisons[0].message()

    def test_el_mensaje_de_sin_cambio_dice_el_umbral(self):
        antes = sesion(ejercicio(activation=60.0, load=20.0), fecha=HACE_UN_MES)
        ahora = sesion(ejercicio(activation=61.0, load=20.0))
        assert "umbral" in compare(antes, ahora).comparisons[0].message()

    def test_el_mensaje_sin_carga_explica_por_que_no_se_puede_leer(self):
        antes = sesion(ejercicio(activation=50.0, load=None), fecha=HACE_UN_MES)
        ahora = sesion(ejercicio(activation=80.0, load=None))
        mensaje = compare(antes, ahora, cv=0.05).comparisons[0].message()
        assert "sin el peso" in mensaje

    def test_ningun_veredicto_se_queda_sin_texto(self):
        from myofit_pro.progress import VERDICT_TEXT

        for verdict in Verdict:
            assert verdict in VERDICT_TEXT
