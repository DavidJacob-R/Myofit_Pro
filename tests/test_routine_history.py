"""
Pruebas del historial de rutinas.

Lo que se cuida aquí es que generar una rutina nueva NO borre las
anteriores. Antes sí lo hacía, y con eso desaparecía el registro de qué
se le había entregado al cliente el mes pasado, que es justo lo que la
pantalla de rutinas enseña ahora.

Usan una base SQLite temporal, no la del usuario.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from myofit_pro.database.engine import DatabaseEngine
from myofit_pro.database.repositories import (
    ClientRepository,
    RoutineRepository,
    TrainerRepository,
)
from myofit_pro.routine_engine import (
    BICEPS,
    DORSAL,
    CatalogExercise,
    MeasuredExercise,
    MuscleCandidates,
    build_plan,
)


@pytest.fixture
def repos():
    with tempfile.TemporaryDirectory() as carpeta:
        engine = DatabaseEngine(Path(carpeta) / "test.db")
        trainers = TrainerRepository(engine.get_session)
        clients = ClientRepository(engine.get_session)
        routines = RoutineRepository(engine.get_session)

        trainer = trainers.register("Entrenador", "t@example.com", "secreto123")
        client = clients.create(
            trainer_id=trainer.id, full_name="Ana López", goal="Hipertrofia",
            experience_level="Intermedio", days_per_week=4,
        )
        yield routines, client


def plan_de_prueba():
    """
    Un plan mínimo pero realista: los nombres de músculo tienen que ser
    los del catálogo, porque las plantillas de días los buscan por nombre.
    """
    return build_plan(
        "Hipertrofia", "Intermedio", 4,
        [
            MuscleCandidates(
                muscle_id=1, muscle_name=BICEPS,
                measured=(
                    MeasuredExercise(1, "Curl con barra", 88.0, 2),
                    MeasuredExercise(2, "Curl martillo", 74.0, 2),
                    MeasuredExercise(3, "Curl concentrado", 62.0, 2),
                ),
            ),
            MuscleCandidates(
                muscle_id=2, muscle_name=DORSAL,
                catalog=(
                    CatalogExercise(4, "Jalón al pecho", True),
                    CatalogExercise(5, "Remo con barra", True),
                ),
            ),
        ],
    )


class TestHistorial:
    def test_generar_dos_veces_conserva_las_dos(self, repos):
        routines, client = repos
        routines.save_plan(client.id, "Primera", plan_de_prueba())
        routines.save_plan(client.id, "Segunda", plan_de_prueba())
        assert len(routines.list_for_client(client.id)) == 2

    def test_la_lista_va_de_la_mas_reciente_a_la_mas_vieja(self, repos):
        routines, client = repos
        primera = routines.save_plan(client.id, "Primera", plan_de_prueba())
        segunda = routines.save_plan(client.id, "Segunda", plan_de_prueba())
        ids = [r.id for r in routines.list_for_client(client.id)]
        assert ids[0] == segunda.id
        assert ids[-1] == primera.id

    def test_get_for_client_devuelve_la_mas_reciente(self, repos):
        routines, client = repos
        routines.save_plan(client.id, "Primera", plan_de_prueba())
        segunda = routines.save_plan(client.id, "Segunda", plan_de_prueba())
        assert routines.get_for_client(client.id).id == segunda.id

    def test_un_cliente_sin_rutinas_devuelve_lista_vacia(self, repos):
        routines, client = repos
        assert routines.list_for_client(client.id) == []

    def test_las_rutinas_traen_sus_ejercicios_cargados(self, repos):
        routines, client = repos
        routines.save_plan(client.id, "Rutina", plan_de_prueba())
        rutina = routines.list_for_client(client.id)[0]
        assert len(rutina.exercises) > 0
        assert all(e.day_index for e in rutina.exercises)


class TestOrigen:
    def test_guarda_de_qué_evaluaciones_salio(self, repos):
        routines, client = repos
        rutina = routines.save_plan(
            client.id, "Rutina", plan_de_prueba(), source_session_ids=[7, 12]
        )
        assert routines.get(rutina.id).source_session_ids == "7,12"

    def test_sin_origen_queda_nulo_y_no_cadena_vacia(self, repos):
        """
        Una cadena vacía haría que la pantalla intentara resolver una
        sesión inexistente; None dice claramente que no hay origen.
        """
        routines, client = repos
        rutina = routines.save_plan(client.id, "Rutina", plan_de_prueba())
        assert routines.get(rutina.id).source_session_ids is None


class TestBorrado:
    def test_borrar_una_no_toca_las_demas(self, repos):
        routines, client = repos
        primera = routines.save_plan(client.id, "Primera", plan_de_prueba())
        segunda = routines.save_plan(client.id, "Segunda", plan_de_prueba())

        routines.delete(primera.id)

        quedan = routines.list_for_client(client.id)
        assert [r.id for r in quedan] == [segunda.id]

    def test_borrar_se_lleva_sus_ejercicios(self, repos):
        routines, client = repos
        rutina = routines.save_plan(client.id, "Rutina", plan_de_prueba())
        routines.delete(rutina.id)
        assert routines.get(rutina.id) is None

    def test_borrar_una_que_no_existe_no_revienta(self, repos):
        routines, _ = repos
        routines.delete(9999)
