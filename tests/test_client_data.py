"""
Pruebas de la ficha del cliente y del borrado de datos.

Los datos físicos (sexo, edad, estatura, peso) entran al generador de
rutinas, así que importa que un dato faltante se distinga de un cero: un
cliente sin peso registrado no pesa cero kilos.

El borrado se prueba aparte porque SQLite no aplica las llaves foráneas
si no se activa `PRAGMA foreign_keys` en cada conexión. Sin eso, borrar
una evaluación dejaba resultados y lecturas apuntando a una sesión que
ya no existía, y el borrado se hace a mano por esa razón.
"""

from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy import select, text

from myofit_pro.database.engine import DatabaseEngine
from myofit_pro.database.models import (
    Client,
    EmgReading,
    EvaluationSession,
    ExerciseResult,
    MvcCalibration,
)
from myofit_pro.database.repositories import (
    CalibrationRepository,
    ClientRepository,
    EvaluationRepository,
    TrainerRepository,
)


@pytest.fixture()
def engine(tmp_path):
    return DatabaseEngine(tmp_path / "test.db")


@pytest.fixture()
def trainer(engine):
    return TrainerRepository(engine.get_session).register(
        "Ana Gutiérrez", "ana@test.mx", "clave1234"
    )


class TestPerfilFisico:
    def test_imc_se_calcula_de_estatura_y_peso(self):
        client = Client(full_name="X", height_cm=165.0, weight_kg=60.0)
        assert client.bmi == pytest.approx(22.04, abs=0.01)

    @pytest.mark.parametrize(
        "height,weight",
        [(None, 60.0), (165.0, None), (None, None), (0.0, 60.0)],
    )
    def test_sin_medidas_el_imc_es_none(self, height, weight):
        """
        None y no cero: un cero se promediaría con los demás clientes y
        arrastraría el resultado hacia abajo sin que se note.
        """
        client = Client(full_name="X", height_cm=height, weight_kg=weight)
        assert client.bmi is None

    COMPLETE = {
        "sex": "Femenino",
        "age_years": 30,
        "height_cm": 165.0,
        "weight_kg": 60.0,
        "experience_level": "Intermedio",
        "days_per_week": 4,
    }

    def test_ficha_completa_necesita_todos_los_datos(self):
        assert Client(full_name="X", **self.COMPLETE).profile_is_complete is True

    @pytest.mark.parametrize("missing", sorted(COMPLETE))
    def test_falta_cualquiera_y_la_ficha_esta_incompleta(self, missing):
        fields = dict(self.COMPLETE)
        fields[missing] = None
        assert Client(full_name="X", **fields).profile_is_complete is False

    def test_la_grasa_no_cuenta_para_la_ficha_completa(self):
        """
        Siempre se puede estimar a partir de los demás datos, así que
        nunca falta del todo y marcar la ficha como incompleta por eso
        sería una alerta que nadie puede resolver.
        """
        client = Client(full_name="X", **self.COMPLETE)
        assert client.body_fat_pct is None
        assert client.profile_is_complete is True

    def test_los_datos_fisicos_se_guardan_y_se_releen(self, engine, trainer):
        repo = ClientRepository(engine.get_session)
        created = repo.create(
            trainer.id, full_name="Ana Pérez", first_name="Ana", last_name="Pérez",
            goal="Definición", sex="Femenino", age_years=30,
            height_cm=165.0, weight_kg=60.0,
        )
        stored = repo.get(created.id)
        assert stored is not None
        assert (stored.first_name, stored.last_name) == ("Ana", "Pérez")
        assert stored.goal == "Definición"
        assert stored.bmi == pytest.approx(22.04, abs=0.01)

    def test_editar_puede_borrar_un_dato(self, engine, trainer):
        """Poder dejar un campo vacío otra vez, no solo llenarlo."""
        repo = ClientRepository(engine.get_session)
        client = repo.create(
            trainer.id, full_name="Ana Pérez", goal="Definición",
            height_cm=165.0, weight_kg=60.0,
        )
        repo.update(client.id, weight_kg=None)
        assert repo.get(client.id).weight_kg is None


class TestMigracionDeFichasViejas:
    """
    Una base creada antes de que existieran estos campos tiene datos
    reales, así que abrirla con la versión nueva no debe costar nada.
    """

    def _base_vieja(self, path):
        """Crea una base con el esquema anterior de `clients`."""
        engine = DatabaseEngine(path)
        with engine.engine.begin() as conn:
            for column in ("first_name", "last_name", "sex", "age_years",
                           "height_cm", "weight_kg"):
                conn.execute(text(f"ALTER TABLE clients DROP COLUMN {column}"))
            conn.execute(
                text(
                    "INSERT INTO clients (trainer_id, full_name, goal, created_at) "
                    "VALUES (1, 'Emiliano Vargas Ruiz', 'Hipertrofia', '2025-01-01')"
                )
            )
        return path

    def test_agrega_las_columnas_que_faltan(self, tmp_path):
        path = self._base_vieja(tmp_path / "vieja.db")
        engine = DatabaseEngine(path)   # aquí corre la migración
        with engine.get_session() as s:
            client = s.scalars(select(Client)).one()
            assert client.full_name == "Emiliano Vargas Ruiz"
            assert client.sex is None
            assert client.profile_is_complete is False

    def test_parte_el_nombre_en_nombre_y_apellidos(self, tmp_path):
        path = self._base_vieja(tmp_path / "vieja.db")
        engine = DatabaseEngine(path)
        with engine.get_session() as s:
            client = s.scalars(select(Client)).one()
            assert client.first_name == "Emiliano"
            assert client.last_name == "Vargas Ruiz"

    def test_correrla_dos_veces_no_falla(self, tmp_path):
        path = self._base_vieja(tmp_path / "vieja.db")
        DatabaseEngine(path)
        DatabaseEngine(path)   # no debe intentar agregar lo que ya está


class TestBorradoDeEvaluaciones:
    def _evaluacion_con_datos(self, engine, trainer):
        client = ClientRepository(engine.get_session).create(
            trainer.id, full_name="Ana Pérez", goal="Definición"
        )
        repo = EvaluationRepository(engine.get_session)
        session = repo.start_session(client.id, muscle_id=1, goal="Definición")
        result = repo.add_exercise_result(session.id, None, 10, 70.0, 88.0)
        reading = repo.add_reading(result.id, 1, 0.6, 0.5, 70.0, 66.0, 12.0, "b1")
        repo.finish_session(session.id, 77.0)
        return client, session, result, reading

    def test_borra_resultados_y_lecturas(self, engine, trainer):
        _, session, result, reading = self._evaluacion_con_datos(engine, trainer)

        EvaluationRepository(engine.get_session).delete_session(session.id)

        with engine.get_session() as s:
            assert s.get(EvaluationSession, session.id) is None
            assert s.get(ExerciseResult, result.id) is None
            assert s.get(EmgReading, reading.id) is None

    def test_no_toca_las_demas_evaluaciones(self, engine, trainer):
        client, session, _, _ = self._evaluacion_con_datos(engine, trainer)
        repo = EvaluationRepository(engine.get_session)
        otra = repo.start_session(client.id, muscle_id=2, goal="Definición")

        repo.delete_session(session.id)

        with engine.get_session() as s:
            assert s.get(EvaluationSession, otra.id) is not None

    def test_borrar_una_inexistente_no_revienta(self, engine):
        EvaluationRepository(engine.get_session).delete_session(9999)

    def test_borrar_un_cliente_se_lleva_sus_calibraciones(self, engine, trainer):
        client = ClientRepository(engine.get_session).create(
            trainer.id, full_name="Ana Pérez", goal="Definición"
        )
        calib = CalibrationRepository(engine.get_session).save(
            client_id=client.id, muscle_id=1,
            mvc_value_uv=620.0, mvc_channel_a_uv=640.0, mvc_channel_b_uv=600.0,
        )

        ClientRepository(engine.get_session).delete(client.id)

        with engine.get_session() as s:
            assert s.get(Client, client.id) is None
            assert s.get(MvcCalibration, calib.id) is None


class TestBorradoDeSenal:
    """La señal cruda vive en DuckDB y se borra aparte de SQLite."""

    def test_borra_solo_las_rafagas_de_esa_sesion(self, tmp_path):
        from myofit_pro.database.duckdb_store import EmgBurstStore

        store = EmgBurstStore(tmp_path / "bursts.duckdb")
        arr = np.arange(10, dtype=float)
        for session_id in (1, 1, 2):
            store.save_burst(
                client_id=1, session_id=session_id, muscle_id=1, sensor_index=0,
                sample_rate_hz=1000.0, times=arr, micro_volts=arr,
                filtered=arr, envelope=arr, rms=arr,
            )

        assert store.delete_bursts_for_session(1) == 2
        assert len(store.load_bursts_for_session(1)) == 0
        assert len(store.load_bursts_for_session(2)) == 1

    def test_borrar_una_sesion_sin_senal_devuelve_cero(self, tmp_path):
        from myofit_pro.database.duckdb_store import EmgBurstStore

        store = EmgBurstStore(tmp_path / "bursts.duckdb")
        assert store.delete_bursts_for_session(42) == 0
