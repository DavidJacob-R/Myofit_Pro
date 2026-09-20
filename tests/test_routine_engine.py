"""
Pruebas del generador de rutinas.

Lo que se verifica es que la rutina salga como se programa de verdad en
un gimnasio —días con varios músculos y cinco o seis ejercicios, no un
músculo suelto por día— y que dependa de lo que se midió.

No necesitan interfaz gráfica ni base de datos: `routine_engine` es
lógica pura a propósito.
"""

from __future__ import annotations

import pytest

from myofit_pro.routine_engine import (
    ABDOMEN,
    BICEPS,
    CUADRICEPS,
    DEFAULT_GOAL,
    DORSAL,
    EXERCISES_PER_SESSION,
    FEMORAL,
    GOAL_SCHEMES,
    HOMBRO,
    MAX_POR_MUSCULO_POR_DIA,
    PANTORRILLA,
    PECHO,
    SPLITS,
    TRAPECIO,
    TRICEPS,
    VOLUME_TARGETS,
    WEEKDAYS,
    CatalogExercise,
    ExerciseSource,
    MeasuredExercise,
    MuscleCandidates,
    build_plan,
    prescription_for,
    ExerciseRole,
    MuscleSize,
    muscle_size,
    rest_days,
    role_for,
    session_minutes,
    split_for,
    weekly_volume_ratio,
)

_ID = iter(range(1, 100_000))


def musculo(
    nombre: str,
    medidos: list[tuple[str, float]] | None = None,
    catalogo: int = 4,
    compuestos: bool = True,
) -> MuscleCandidates:
    """Un músculo con los ejercicios medidos que se le pasen y relleno de catálogo."""
    medidos = medidos or []
    measured = tuple(
        MeasuredExercise(next(_ID), n, pct, 2, compuestos and i == 0)
        for i, (n, pct) in enumerate(medidos)
    )
    catalog = tuple(
        CatalogExercise(next(_ID), f"{nombre[:6]} catálogo {i}", compuestos and i == 0)
        for i in range(catalogo)
    )
    return MuscleCandidates(
        muscle_id=next(_ID), muscle_name=nombre,
        measured=measured, catalog=tuple(
            CatalogExercise(e.exercise_id, e.name, e.is_compound) for e in measured
        ) + catalog,
    )


def gimnasio() -> list[MuscleCandidates]:
    """Todos los músculos del catálogo con algo medido en los principales."""
    return [
        musculo(PECHO, [("Press inclinado", 88.0), ("Press de banca", 80.0)]),
        musculo(TRICEPS, [("Fondos", 84.0), ("Press francés", 76.0)]),
        musculo(HOMBRO),
        musculo(DORSAL, [("Jalón al pecho", 86.0)]),
        musculo(TRAPECIO),
        musculo(BICEPS, [("Predicador", 82.0), ("Martillo", 74.0)]),
        musculo(CUADRICEPS, [("Sentadilla", 91.0)]),
        musculo(FEMORAL),
        musculo(PANTORRILLA, catalogo=2),
        musculo(ABDOMEN),
    ]


class TestPrescripcion:
    def test_cada_objetivo_prescribe_distinto(self):
        fuerza = prescription_for("Fuerza", "Intermedio")
        definicion = prescription_for("Definición", "Intermedio")
        assert fuerza.reps_max < definicion.reps_min
        assert fuerza.rest_sec > definicion.rest_sec
        assert fuerza.load_pct_min > definicion.load_pct_max

    def test_mas_repeticiones_va_con_menos_carga(self):
        """Coherencia de los tres objetivos principales."""
        principales = ["Fuerza", "Hipertrofia", "Definición"]
        ordenados = sorted(
            (GOAL_SCHEMES[g][ExerciseRole.SECUNDARIO] for g in principales),
            key=lambda p: p.reps_min,
        )
        cargas = [p.load_pct_max for p in ordenados]
        assert cargas == sorted(cargas, reverse=True)

    def test_el_principiante_hace_menos_series_y_mas_lejos_del_fallo(self):
        base = prescription_for("Hipertrofia", "Intermedio")
        novato = prescription_for("Hipertrofia", "Principiante")
        assert novato.sets == base.sets - 1
        assert novato.rir > base.rir

    def test_el_avanzado_hace_mas_series_y_mas_cerca_del_fallo(self):
        base = prescription_for("Hipertrofia", "Intermedio")
        experto = prescription_for("Hipertrofia", "Avanzado")
        assert experto.sets == base.sets + 1
        assert experto.rir < base.rir

    def test_nunca_baja_de_dos_series(self):
        assert prescription_for("Rehabilitación", "Principiante").sets >= 2

    def test_las_reservas_no_pueden_ser_negativas(self):
        for goal in GOAL_SCHEMES:
            for role in ExerciseRole:
                assert prescription_for(goal, "Avanzado", role).rir >= 0

    def test_sin_experiencia_se_asume_lo_conservador(self):
        assert prescription_for("Hipertrofia", None) == prescription_for(
            "Hipertrofia", "Principiante"
        )

    def test_la_intensidad_se_expresa_en_porcentaje_del_pr(self):
        """Es el lenguaje del gimnasio, no '1RM'."""
        assert "PR" in prescription_for("Hipertrofia", "Intermedio").load_text

    def test_hasta_dos_minutos_el_descanso_va_en_segundos(self):
        assert prescription_for("Hipertrofia", "Intermedio").rest_text == "90 s"
        assert prescription_for("Fuerza", "Intermedio", ExerciseRole.PRIMARIO).rest_text == "3 min"


class TestPlantillasDeDias:
    """
    Las plantillas son lo que convierte la rutina en algo entrenable: un
    día es un bloque de músculos que trabajan juntos, no un músculo
    suelto.
    """

    @pytest.mark.parametrize("dias", [1, 2, 3, 4, 5, 6])
    def test_hay_plantilla_para_cada_numero_de_dias(self, dias):
        assert len(SPLITS[dias]) == dias

    @pytest.mark.parametrize("dias", [1, 2, 3, 4, 5, 6])
    def test_los_dias_son_de_la_semana_y_no_se_repiten(self, dias):
        nombres = [d.weekday for d in SPLITS[dias]]
        assert all(n in WEEKDAYS for n in nombres)
        assert len(set(nombres)) == len(nombres)

    @pytest.mark.parametrize("dias", [1, 2, 3, 4, 5, 6])
    def test_cada_dia_trabaja_varios_musculos(self, dias):
        """Un día de un solo músculo no es una sesión de gimnasio."""
        if dias >= 3:
            assert all(len(d.muscles) >= 2 for d in SPLITS[dias])

    def test_el_dia_de_empuje_lleva_pecho_hombro_y_triceps(self):
        empuje = next(d for d in SPLITS[5] if d.label == "Empuje")
        assert set(empuje.muscles) == {PECHO, TRICEPS, HOMBRO}

    def test_el_dia_de_tiron_lleva_espalda_y_biceps(self):
        tiron = next(d for d in SPLITS[5] if d.label == "Tirón")
        assert DORSAL in tiron.muscles
        assert BICEPS in tiron.muscles

    def test_los_dias_libres_son_los_que_no_se_entrenan(self):
        libres = rest_days(SPLITS[5])
        assert "Jueves" in libres
        assert "Domingo" in libres
        assert "Lunes" not in libres

    def test_sin_dato_de_dias_se_usa_la_de_tres(self):
        assert split_for(None) == SPLITS[3]

    @pytest.mark.parametrize("dias", [0, -2, 99])
    def test_dias_imposibles_se_acotan(self, dias):
        assert 1 <= len(split_for(dias)) <= 6


class TestSesiones:
    def test_una_sesion_trae_varios_ejercicios_y_no_dos(self):
        """
        El defecto que motivó el rediseño: antes cada día traía dos
        ejercicios de un solo músculo y quedaban días vacíos.
        """
        plan = build_plan("Hipertrofia", "Intermedio", 5, gimnasio())
        assert all(len(d.exercises) >= 4 for d in plan.days)

    def test_no_quedan_dias_vacios(self):
        plan = build_plan("Hipertrofia", "Intermedio", 5, gimnasio())
        assert len(plan.days) == 5
        assert all(d.exercises for d in plan.days)

    def test_cada_dia_sabe_qué_dia_de_la_semana_es(self):
        plan = build_plan("Hipertrofia", "Intermedio", 5, gimnasio())
        assert [d.weekday for d in plan.days] == [d.weekday for d in SPLITS[5]]
        assert all(d.label for d in plan.days)

    def test_el_plan_dice_los_dias_de_descanso(self):
        plan = build_plan("Hipertrofia", "Intermedio", 5, gimnasio())
        assert "Jueves" in plan.rest_days

    def test_un_dia_mezcla_los_musculos_de_su_bloque(self):
        plan = build_plan("Hipertrofia", "Intermedio", 5, gimnasio())
        lunes = plan.days[0]
        assert len(lunes.muscle_names) >= 2

    def test_el_avanzado_entrena_mas_por_sesion_que_el_principiante(self):
        novato = build_plan("Hipertrofia", "Principiante", 5, gimnasio())
        experto = build_plan("Hipertrofia", "Avanzado", 5, gimnasio())
        assert len(experto.exercises) > len(novato.exercises)

    def test_ningun_musculo_repite_mas_del_tope_en_un_dia(self):
        plan = build_plan("Hipertrofia", "Avanzado", 5, gimnasio())
        for dia in plan.days:
            conteo: dict[str, int] = {}
            for e in dia.exercises:
                conteo[e.muscle_name] = conteo.get(e.muscle_name, 0) + 1
            assert max(conteo.values()) <= MAX_POR_MUSCULO_POR_DIA

    def test_los_ejercicios_de_un_musculo_van_seguidos(self):
        plan = build_plan("Hipertrofia", "Intermedio", 5, gimnasio())
        for dia in plan.days:
            ids = [e.muscle_id for e in dia.exercises]
            vistos, anterior = set(), None
            for valor in ids:
                if valor != anterior:
                    assert valor not in vistos
                    vistos.add(valor)
                    anterior = valor

    def test_los_compuestos_van_antes_que_los_de_aislamiento(self):
        """Con el músculo fresco rinde lo que más carga mueve."""
        plan = build_plan("Hipertrofia", "Intermedio", 5, gimnasio())
        for dia in plan.days:
            por_musculo: dict[int, list[bool]] = {}
            for e in dia.exercises:
                por_musculo.setdefault(e.muscle_id, []).append(e.is_compound)
            for compuestos in por_musculo.values():
                # Una vez que aparece un aislamiento no vuelve un compuesto.
                assert compuestos == sorted(compuestos, reverse=True)


class TestSeleccion:
    def test_elige_los_que_mas_activaron_en_esa_persona(self):
        """El corazón del producto: el orden lo decide la medición."""
        plan = build_plan(
            "Hipertrofia", "Intermedio", 5,
            [musculo(PECHO, [("Flojo", 40.0), ("Bueno", 90.0), ("Medio", 65.0)],
                     catalogo=0, compuestos=False)] + gimnasio()[1:],
        )
        del_pecho = [e.name for e in plan.exercises if e.muscle_name == PECHO]
        assert del_pecho[0] == "Bueno"
        assert del_pecho.index("Medio") < del_pecho.index("Flojo")

    def test_lo_medido_va_marcado_como_medido(self):
        plan = build_plan("Hipertrofia", "Intermedio", 5, gimnasio())
        medidos = [e for e in plan.exercises if e.source is ExerciseSource.MEASURED]
        assert medidos
        assert all(e.activation_pct is not None for e in medidos)

    def test_un_musculo_con_lecturas_rellena_con_complementos(self):
        """
        Si el músculo sí se midió pero ese ejercicio no, se puede decir
        que encaja: se sabe cómo responde ese músculo en esta persona.
        """
        plan = build_plan("Hipertrofia", "Avanzado", 5, gimnasio())
        complementos = [
            e for e in plan.exercises if e.source is ExerciseSource.COMPLEMENT
        ]
        assert complementos
        assert all(e.activation_pct is None for e in complementos)

    def test_un_musculo_sin_lecturas_se_marca_como_tal(self):
        """Y no como complemento: no hay nada de qué inferir."""
        plan = build_plan("Hipertrofia", "Intermedio", 5, gimnasio())
        sin_lecturas = [
            e for e in plan.exercises if e.source is ExerciseSource.UNMEASURED
        ]
        assert sin_lecturas
        assert {e.muscle_name for e in sin_lecturas} <= {
            HOMBRO, TRAPECIO, FEMORAL, PANTORRILLA, ABDOMEN
        }

    def test_avisa_de_los_musculos_sin_lecturas(self):
        plan = build_plan("Hipertrofia", "Intermedio", 5, gimnasio())
        assert any("Sin lecturas de" in w for w in plan.warnings)

    def test_sin_ningun_musculo_no_inventa_rutina(self):
        assert build_plan("Hipertrofia", "Intermedio", 5, []).is_empty

    def test_musculos_sin_ejercicios_no_generan_dias(self):
        vacios = [MuscleCandidates(1, PECHO), MuscleCandidates(2, BICEPS)]
        assert build_plan("Hipertrofia", "Intermedio", 5, vacios).is_empty


class TestVolumen:
    def test_ningun_musculo_se_pasa_del_rango(self):
        """
        Pasarse de volumen es el error que lesiona. El generador recorta
        él mismo en vez de proponer de más y luego avisar.
        """
        for goal, (_, high) in VOLUME_TARGETS.items():
            for nivel in ("Principiante", "Intermedio", "Avanzado"):
                for dias in range(1, 7):
                    plan = build_plan(goal, nivel, dias, gimnasio())
                    for muscle, sets in plan.weekly_sets.items():
                        assert sets <= high, f"{goal}/{nivel}/{dias}d: {muscle} {sets}>{high}"

    def test_cuenta_las_series_de_toda_la_semana(self):
        plan = build_plan("Hipertrofia", "Intermedio", 5, gimnasio())
        por_musculo: dict[str, int] = {}
        for e in plan.exercises:
            por_musculo[e.muscle_name] = por_musculo.get(e.muscle_name, 0) + e.prescription.sets
        assert plan.weekly_sets == por_musculo

    def test_avisa_cuando_un_musculo_se_queda_corto(self):
        plan = build_plan("Hipertrofia", "Principiante", 1, gimnasio())
        assert any("por debajo" in w for w in plan.warnings)

    def test_el_recorte_no_deja_un_dia_sin_su_musculo(self):
        plan = build_plan("Hipertrofia", "Avanzado", 6, gimnasio())
        assert all(d.exercises for d in plan.days)


class TestAvisosDeFicha:
    def test_avisa_de_los_datos_que_faltan(self):
        plan = build_plan(None, None, None, gimnasio())
        texto = " ".join(plan.warnings)
        assert "objetivo" in texto
        assert "experiencia" in texto
        assert "días" in texto

    def test_una_ficha_completa_no_genera_avisos_de_ficha(self):
        plan = build_plan("Hipertrofia", "Intermedio", 4, gimnasio())
        assert not any("ficha" in w for w in plan.warnings)

    def test_lleva_la_prescripcion_y_el_rango_aplicados(self):
        plan = build_plan("Fuerza", "Avanzado", 3, gimnasio())
        assert plan.prescription == prescription_for("Fuerza", "Avanzado")
        assert plan.volume_target == VOLUME_TARGETS["Fuerza"]

    def test_lleva_el_objetivo_y_el_nivel_efectivos(self):
        plan = build_plan(None, None, None, gimnasio())
        assert plan.goal == DEFAULT_GOAL
        assert plan.experience == "Principiante"

    def test_el_resultado_es_reproducible(self):
        """
        Generar dos veces con los mismos datos da lo mismo. Si dependiera
        del orden de un diccionario, el cliente vería una rutina distinta
        cada vez sin haber medido nada nuevo.
        """
        datos = gimnasio()
        a = build_plan("Hipertrofia", "Intermedio", 5, datos)
        b = build_plan("Hipertrofia", "Intermedio", 5, datos)
        assert [(d.weekday, [e.name for e in d.exercises]) for d in a.days] == [
            (d.weekday, [e.name for e in d.exercises]) for d in b.days
        ]


class TestUtilidades:
    def test_la_barra_de_volumen_se_llena_al_llegar_al_tope(self):
        assert weekly_volume_ratio(20, (10, 20)) == pytest.approx(100.0)

    def test_la_barra_no_se_pasa_de_cien(self):
        assert weekly_volume_ratio(40, (10, 20)) == 100.0

    def test_la_duracion_crece_con_las_series_y_el_descanso(self):
        assert session_minutes([(6, 90)]) > session_minutes([(3, 90)])
        assert session_minutes([(4, 180)]) > session_minutes([(4, 60)])

    def test_una_sesion_vacia_no_da_cero_minutos(self):
        assert session_minutes([]) >= 1

    def test_el_objetivo_de_ejercicios_por_sesion_sube_con_el_nivel(self):
        assert (
            EXERCISES_PER_SESSION["Principiante"]
            < EXERCISES_PER_SESSION["Intermedio"]
            < EXERCISES_PER_SESSION["Avanzado"]
        )


class TestEsquemaPorEjercicio:
    """
    Lo que el entrenador reclamó: no todos los ejercicios llevan el
    mismo esquema. El papel dentro del bloque y el tamaño del músculo
    cambian series, repeticiones, carga y descanso.
    """

    def test_el_primario_va_mas_pesado_que_el_accesorio(self):
        primario = prescription_for("Hipertrofia", "Intermedio", ExerciseRole.PRIMARIO)
        accesorio = prescription_for("Hipertrofia", "Intermedio", ExerciseRole.ACCESORIO)
        assert primario.load_pct_min > accesorio.load_pct_max
        assert primario.reps_max < accesorio.reps_min
        assert primario.rest_sec > accesorio.rest_sec

    def test_un_musculo_pequeno_lleva_mas_repeticiones_y_menos_carga(self):
        grande = prescription_for(
            "Hipertrofia", "Intermedio", ExerciseRole.SECUNDARIO, MuscleSize.GRANDE
        )
        pequeno = prescription_for(
            "Hipertrofia", "Intermedio", ExerciseRole.SECUNDARIO, MuscleSize.PEQUENO
        )
        assert pequeno.reps_min > grande.reps_min
        assert pequeno.load_pct_max < grande.load_pct_max
        assert pequeno.rest_sec < grande.rest_sec

    def test_el_pectoral_es_grande_y_el_biceps_pequeno(self):
        assert muscle_size(PECHO) is MuscleSize.GRANDE
        assert muscle_size(BICEPS) is MuscleSize.PEQUENO
        assert muscle_size(TRICEPS) is MuscleSize.MEDIO

    def test_un_musculo_desconocido_cae_en_medio(self):
        assert muscle_size("Músculo inventado") is MuscleSize.MEDIO

    def test_el_descanso_queda_en_un_valor_programable(self):
        """Nada de '112 s' ni '2,2 min': se redondea a lo que se pone en
        un cronómetro."""
        for goal in GOAL_SCHEMES:
            for role in ExerciseRole:
                for size in MuscleSize:
                    rest = prescription_for(goal, "Intermedio", role, size).rest_sec
                    assert rest % 15 == 0 or rest % 30 == 0

    def test_las_repeticiones_nunca_se_disparan(self):
        for goal in GOAL_SCHEMES:
            for role in ExerciseRole:
                for size in MuscleSize:
                    p = prescription_for(goal, "Intermedio", role, size)
                    assert p.reps_min <= p.reps_max <= 20


class TestPapeles:
    def test_el_primer_compuesto_es_el_primario(self):
        papel = role_for(1, True, None, MuscleSize.GRANDE)
        assert papel is ExerciseRole.PRIMARIO

    def test_otro_compuesto_es_secundario(self):
        assert role_for(2, True, None, MuscleSize.GRANDE) is ExerciseRole.SECUNDARIO

    def test_un_aislamiento_es_accesorio(self):
        assert role_for(3, False, None, MuscleSize.GRANDE) is ExerciseRole.ACCESORIO

    def test_una_activacion_alta_sube_de_papel(self):
        """
        La vía por la que la medición decide también el CUÁNTO: si el
        ejercicio recluta casi al máximo, se trata como más pesado.
        """
        assert role_for(2, True, 88.0, MuscleSize.GRANDE) is ExerciseRole.PRIMARIO

    def test_una_activacion_baja_baja_de_papel(self):
        assert role_for(2, True, 40.0, MuscleSize.GRANDE) is ExerciseRole.ACCESORIO

    def test_un_musculo_pequeno_nunca_hace_trabajo_de_primario(self):
        """Un bíceps no se entrena a 3 repeticiones con el 90%."""
        papel = role_for(1, True, 95.0, MuscleSize.PEQUENO)
        assert papel is not ExerciseRole.PRIMARIO


class TestVariacionEnLaRutina:
    def test_no_todos_los_ejercicios_llevan_el_mismo_esquema(self):
        """
        El defecto que motivó el cambio: la rutina ponía 5×3-6 al 85% en
        todos los ejercicios, del press de banca a las elevaciones
        laterales.
        """
        plan = build_plan("Hipertrofia", "Intermedio", 5, gimnasio())
        esquemas = {
            (e.prescription.sets, e.prescription.reps_min, e.prescription.load_pct_min)
            for e in plan.exercises
        }
        assert len(esquemas) >= 3

    def test_dentro_de_un_dia_el_primero_va_mas_pesado_que_el_ultimo(self):
        plan = build_plan("Hipertrofia", "Intermedio", 5, gimnasio())
        for dia in plan.days:
            por_musculo: dict[int, list] = {}
            for e in dia.exercises:
                por_musculo.setdefault(e.muscle_id, []).append(e)
            for bloque in por_musculo.values():
                if len(bloque) >= 2:
                    assert bloque[0].prescription.load_pct_min >= (
                        bloque[-1].prescription.load_pct_min
                    )

    def test_el_volumen_cuenta_las_series_reales_de_cada_ejercicio(self):
        plan = build_plan("Hipertrofia", "Intermedio", 5, gimnasio())
        esperado: dict[str, int] = {}
        for e in plan.exercises:
            esperado[e.muscle_name] = esperado.get(e.muscle_name, 0) + e.prescription.sets
        assert plan.weekly_sets == esperado


class TestRotacion:
    """
    El último hueco de cada músculo se sortea. No es variedad por
    variedad: es lo único que introduce variación independiente del
    cliente, y sin ella los datos de dentro de un año no permitirán
    preguntar si un ejercicio causó la mejora o solo la acompañó.
    """

    @staticmethod
    def _biceps_con_seis():
        return [
            MuscleCandidates(
                muscle_id=1, muscle_name=BICEPS,
                measured=tuple(
                    MeasuredExercise(i, f"E{i}", 90.0 - i * 6, 2, False)
                    for i in range(6)
                ),
            )
        ]

    def test_sin_generador_el_resultado_es_determinista(self):
        datos = self._biceps_con_seis()
        a = build_plan("Hipertrofia", "Intermedio", 3, datos)
        b = build_plan("Hipertrofia", "Intermedio", 3, datos)
        assert [e.name for e in a.exercises] == [e.name for e in b.exercises]

    def test_con_generador_el_ultimo_hueco_cambia(self):
        import random

        datos = self._biceps_con_seis()
        elegidos = set()
        for _ in range(60):
            plan = build_plan("Hipertrofia", "Intermedio", 3, datos, rng=random.Random())
            elegidos |= {e.name for e in plan.exercises if e.is_rotation}
        assert len(elegidos) >= 2, f"solo salió {elegidos}"

    def test_los_mejores_medidos_nunca_se_sortean(self):
        """
        El valor del producto es el ranking. La rotación solo mueve el
        último hueco; el primero del ranking entra siempre.
        """
        import random

        datos = self._biceps_con_seis()
        for _ in range(40):
            plan = build_plan("Hipertrofia", "Intermedio", 3, datos, rng=random.Random())
            nombres = [e.name for e in plan.exercises]
            assert "E0" in nombres
            assert not any(e.is_rotation for e in plan.exercises if e.name == "E0")

    def test_solo_se_sortea_un_hueco_por_musculo(self):
        import random

        datos = self._biceps_con_seis()
        for _ in range(30):
            plan = build_plan("Hipertrofia", "Intermedio", 3, datos, rng=random.Random())
            assert sum(1 for e in plan.exercises if e.is_rotation) <= 1

    def test_sin_banca_suficiente_no_sortea_nada(self):
        """Con justo los ejercicios que caben no hay entre qué elegir."""
        import random

        datos = [
            MuscleCandidates(
                muscle_id=1, muscle_name=BICEPS,
                measured=tuple(
                    MeasuredExercise(i, f"E{i}", 90.0 - i * 6, 2, False) for i in range(2)
                ),
            )
        ]
        plan = build_plan("Hipertrofia", "Intermedio", 3, datos, rng=random.Random())
        assert not any(e.is_rotation for e in plan.exercises)

    def test_el_sorteo_reparte_entre_los_candidatos(self):
        """No puede quedarse siempre en el mismo: entonces no rotaría."""
        import collections
        import random

        datos = self._biceps_con_seis()
        cuenta = collections.Counter()
        for _ in range(200):
            plan = build_plan("Hipertrofia", "Intermedio", 3, datos, rng=random.Random())
            for e in plan.exercises:
                if e.is_rotation:
                    cuenta[e.name] += 1
        assert len(cuenta) >= 2
        assert min(cuenta.values()) > 0
