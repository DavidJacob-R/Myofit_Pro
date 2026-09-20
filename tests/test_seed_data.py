"""
Pruebas del catálogo y del modo demostración.

Son las dos piezas que ESCRIBEN en la base del usuario, y por eso hay
que cubrirlas: `seed_data` ahora borra ejercicios que salieron del
catálogo, y un fallo ahí se lleva mediciones reales por delante.

Todas corren contra bases temporales, nunca contra `~/.myofit_pro/`.
"""

from __future__ import annotations

from sqlalchemy import select

from myofit_pro import seed_data
from myofit_pro.database.models import Exercise, ExerciseResult, Muscle, RoutineExercise
from myofit_pro.routine_engine import MUSCLE_SIZES


def nombres_del_catalogo() -> set[tuple[str, str]]:
    return {
        (m["name"], nombre)
        for g in seed_data.CATALOG
        for m in g["muscles"]
        for nombre, _ in m["exercises"]
    }


class TestCatalogo:
    def test_carga_todo_el_catalogo(self, seeded_db):
        with seeded_db.get_session() as s:
            assert s.scalar(select(Exercise).where(Exercise.name == "Sentadilla"))
            assert len(list(s.scalars(select(Muscle)))) == 10

    def test_correrlo_dos_veces_no_duplica(self, seeded_db):
        with seeded_db.get_session() as s:
            antes = len(list(s.scalars(select(Exercise))))
        seed_data.seed()
        with seeded_db.get_session() as s:
            assert len(list(s.scalars(select(Exercise)))) == antes

    def test_marca_los_ejercicios_compuestos(self, seeded_db):
        """De esa marca depende el orden dentro de la sesión."""
        with seeded_db.get_session() as s:
            sentadilla = s.scalar(select(Exercise).where(Exercise.name == "Sentadilla"))
            curl = s.scalar(select(Exercise).where(Exercise.name == "Curl concentrado"))
        assert sentadilla.is_compound
        assert not curl.is_compound

    def test_todos_los_musculos_estan_clasificados_por_tamano(self, seeded_db):
        """
        Si un músculo del catálogo no está en MUSCLE_SIZES, el generador
        lo trata como mediano sin avisar y su prescripción sale mal.
        """
        with seeded_db.get_session() as s:
            nombres = {m.name for m in s.scalars(select(Muscle))}
        assert nombres <= set(MUSCLE_SIZES)

    def test_cada_musculo_tiene_suficientes_ejercicios(self, seeded_db):
        """
        La batería sirve para ordenar ejercicios entre sí; con dos o tres
        el orden no descarta nada. La simulación asume seis.
        """
        with seeded_db.get_session() as s:
            for muscle in s.scalars(select(Muscle)):
                cuantos = len(
                    list(s.scalars(select(Exercise).where(Exercise.muscle_id == muscle.id)))
                )
                assert cuantos >= 5, f"{muscle.name} solo tiene {cuantos}"

    def test_cada_musculo_tiene_guia_de_colocacion(self, seeded_db):
        with seeded_db.get_session() as s:
            for muscle in s.scalars(select(Muscle)):
                assert muscle.placement_guide

    def test_no_hay_nombres_repetidos_dentro_de_un_musculo(self, seeded_db):
        with seeded_db.get_session() as s:
            for muscle in s.scalars(select(Muscle)):
                nombres = [
                    e.name
                    for e in s.scalars(select(Exercise).where(Exercise.muscle_id == muscle.id))
                ]
                assert len(nombres) == len(set(nombres))


class TestLimpiezaDeHuerfanos:
    """
    El catálogo se reorganiza —los ejercicios de tirón pasaron de
    trapecio a dorsal— y sin limpieza la base se queda con las dos
    copias. Pero borrar de más costaría mediciones reales.
    """

    def test_borra_lo_que_ya_no_esta_en_el_catalogo(self, seeded_db):
        with seeded_db.get_session() as s:
            muscle = s.scalar(select(Muscle))
            s.add(Exercise(muscle_id=muscle.id, name="Ejercicio inventado"))
            s.commit()

        seed_data.seed()

        with seeded_db.get_session() as s:
            assert s.scalar(select(Exercise).where(Exercise.name == "Ejercicio inventado")) is None

    def test_conserva_lo_que_tiene_mediciones(self, seeded_db, app_state):
        """
        Perder una medición por reordenar una lista sería mucho peor que
        dejar una fila de más.
        """
        client = app_state.client_repo.list_for_trainer(app_state.current_trainer.id)[0]
        sesion = app_state.evaluation_repo.list_for_client(client.id)[0]

        with seeded_db.get_session() as s:
            muscle = s.scalar(select(Muscle))
            fuera = Exercise(muscle_id=muscle.id, name="Fuera del catálogo")
            s.add(fuera)
            s.flush()
            s.add(
                ExerciseResult(
                    session_id=sesion.id, exercise_id=fuera.id,
                    series_count=8, avg_activation_pct=70.0, peak_activation_pct=78.0,
                )
            )
            s.commit()
            guardado = fuera.id

        seed_data.seed()

        with seeded_db.get_session() as s:
            assert s.get(Exercise, guardado) is not None

    def test_conserva_lo_que_esta_en_una_rutina(self, seeded_db, app_state):
        client = app_state.client_repo.list_for_trainer(app_state.current_trainer.id)[0]
        rutina = app_state.routine_repo.create(client_id=client.id, name="Prueba")

        with seeded_db.get_session() as s:
            muscle = s.scalar(select(Muscle))
            fuera = Exercise(muscle_id=muscle.id, name="Fuera pero en rutina")
            s.add(fuera)
            s.flush()
            s.add(RoutineExercise(routine_id=rutina.id, exercise_id=fuera.id, sets=3, reps=10))
            s.commit()
            guardado = fuera.id

        seed_data.seed()

        with seeded_db.get_session() as s:
            assert s.get(Exercise, guardado) is not None

    def test_al_terminar_la_base_coincide_con_el_catalogo(self, seeded_db):
        with seeded_db.get_session() as s:
            en_base = {
                (s.get(Muscle, e.muscle_id).name, e.name)
                for e in s.scalars(select(Exercise))
            }
        assert en_base == nombres_del_catalogo()


class TestModoDemostracion:
    def test_construye_clientes_con_historial(self, temp_home, qapp, monkeypatch):
        """
        Las pantallas de progreso y de rutinas solo enseñan algo con
        varias evaluaciones separadas en el tiempo; eso es justo lo que
        el modo demostración tiene que montar.
        """
        del qapp
        from myofit_pro import demo_data

        monkeypatch.setattr(demo_data, "DEMO_DB", temp_home / "demo.db")
        monkeypatch.setattr(demo_data, "DEMO_DUCKDB", temp_home / "demo.duckdb")

        trainer = demo_data.build()

        from myofit_pro.gui.app_state import AppState

        state = AppState(current_trainer=trainer)
        try:
            clientes = state.client_repo.list_for_trainer(trainer.id)
            assert len(clientes) == len(demo_data.CLIENTES)

            ana = next(c for c in clientes if "Ana" in c.full_name)
            assert len(state.evaluation_repo.list_for_client(ana.id)) >= 3
            assert state.routine_repo.list_for_client(ana.id)
            assert state.muscles_with_history(ana.id)
        finally:
            state.shutdown()

    def test_no_escribe_en_la_base_real(self, temp_home, qapp, monkeypatch):
        """
        Lo más importante de este modo: que el entrenador pueda probarlo
        sin miedo a perder sus datos.
        """
        del qapp
        from myofit_pro import demo_data

        demo_db = temp_home / "demo.db"
        monkeypatch.setattr(demo_data, "DEMO_DB", demo_db)
        monkeypatch.setattr(demo_data, "DEMO_DUCKDB", temp_home / "demo.duckdb")

        import myofit_pro.database.engine as engine_mod

        real = engine_mod.DEFAULT_DB_PATH
        demo_data.build()

        assert demo_db.exists()
        assert engine_mod.DEFAULT_DB_PATH == demo_db
        assert real != demo_db
