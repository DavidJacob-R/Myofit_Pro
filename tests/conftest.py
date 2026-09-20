"""
Apoyo común de las pruebas.

Lo que hay aquí es la base de datos de prueba: cada prueba que toca la
GUI necesita una base propia, poblada y aislada, y montarla a mano en
cada archivo sería repetir cincuenta líneas.

AISLAMIENTO
===========

`app_state` redirige los dos almacenes (SQLite y DuckDB) a una carpeta
temporal ANTES de que nadie los abra, y repone los singletons al
terminar. Sin eso una prueba escribiría en `~/.myofit_pro/`, que es
donde vive la base real del entrenador.
"""

from __future__ import annotations

import datetime as dt
import tempfile
from pathlib import Path

import pytest


def _reset_singletons(engine_mod, duckdb_mod) -> None:
    engine_mod._default_engine = None
    duckdb_mod._default_store = None


@pytest.fixture
def temp_home(monkeypatch):
    """Carpeta temporal en la que apuntan las dos bases de datos."""
    import myofit_pro.database.duckdb_store as duckdb_mod
    import myofit_pro.database.engine as engine_mod

    original_db = engine_mod.DEFAULT_DB_PATH
    original_duck = duckdb_mod.DEFAULT_DUCKDB_PATH

    with tempfile.TemporaryDirectory() as carpeta:
        raiz = Path(carpeta)
        monkeypatch.setattr(engine_mod, "DEFAULT_DB_PATH", raiz / "test.db")
        monkeypatch.setattr(duckdb_mod, "DEFAULT_DUCKDB_PATH", raiz / "test.duckdb")
        _reset_singletons(engine_mod, duckdb_mod)
        try:
            yield raiz
        finally:
            store = duckdb_mod._default_store
            if store is not None:
                try:
                    store.close()
                except Exception:
                    pass
            engine_mod.DEFAULT_DB_PATH = original_db
            duckdb_mod.DEFAULT_DUCKDB_PATH = original_duck
            _reset_singletons(engine_mod, duckdb_mod)


@pytest.fixture
def seeded_db(temp_home):
    """Base temporal con el catálogo de músculos y ejercicios cargado."""
    from myofit_pro import seed_data
    from myofit_pro.database.engine import get_engine

    engine = get_engine()
    seed_data.seed()
    return engine


@pytest.fixture
def app_state(seeded_db, qapp):
    """
    `AppState` sobre la base temporal, con un entrenador y un cliente
    con evaluaciones ya hechas.

    `qapp` viene de pytest-qt y garantiza que hay una QApplication: sin
    ella construir cualquier widget revienta.
    """
    del qapp  # solo se necesita que exista

    from myofit_pro.database import (
        CalibrationRepository,
        ClientRepository,
        EvaluationRepository,
        ExerciseRepository,
        MuscleRepository,
        TrainerRepository,
    )
    from myofit_pro.database.models import EvaluationSession
    from myofit_pro.gui.app_state import AppState

    trainers = TrainerRepository(seeded_db.get_session)
    clients = ClientRepository(seeded_db.get_session)
    muscles = MuscleRepository(seeded_db.get_session)
    exercises = ExerciseRepository(seeded_db.get_session)
    calibs = CalibrationRepository(seeded_db.get_session)
    evals = EvaluationRepository(seeded_db.get_session)

    trainer = trainers.register("Entrenador", "t@example.com", "secreto123")
    client = clients.create(
        trainer_id=trainer.id, full_name="Ana López", goal="Hipertrofia",
        first_name="Ana", last_name="López", sex="Femenino", age_years=28,
        height_cm=165.0, weight_kg=60.0, experience_level="Intermedio",
        days_per_week=4,
    )

    biceps = next(m for m in muscles.list_muscles() if "Bíceps" in m.name)
    catalogo = exercises.list_for_muscle(biceps.id)[:3]
    hoy = dt.datetime.now()

    # Dos evaluaciones separadas cuatro semanas: lo mínimo para que la
    # comparación de progreso y el historial agrupado tengan qué mostrar.
    for vuelta, cuando in enumerate((hoy - dt.timedelta(days=28), hoy)):
        calib = calibs.save(client.id, biceps.id, 900.0, 880.0, 920.0)
        sesion = evals.start_session(client.id, biceps.id, "Hipertrofia", calib.id)
        for indice, ejercicio in enumerate(catalogo):
            valor = 80.0 - indice * 12.0 + vuelta * 5.0
            resultado = evals.add_exercise_result(
                sesion.id, ejercicio.id, 8, valor, valor + 6, load_kg=20.0 + vuelta * 2
            )
            evals.add_reading(
                resultado.id, 1, 0.9, 0.85, valor + 3, valor - 3, 30.0, None
            )
        evals.set_session_measurements(
            sesion.id, circumference_cm=31.0 + vuelta, repeatability_cv=0.05
        )
        evals.finish_session(sesion.id, 70.0 + vuelta)

        with seeded_db.get_session() as s:
            obj = s.get(EvaluationSession, sesion.id)
            obj.started_at = cuando
            s.commit()

    state = AppState(current_trainer=trainer)
    state.active_client = client
    yield state
    state.shutdown()


@pytest.fixture
def client_fixture(app_state):
    """El cliente de ejemplo de `app_state`."""
    return app_state.client_repo.list_for_trainer(app_state.current_trainer.id)[0]
