"""
Repositorios CRUD, equivalentes uno a uno con los de C#:

    TrainerRepository.cs     -> TrainerRepository
    ClientRepository.cs      -> ClientRepository
    MuscleRepository.cs      -> MuscleRepository
    ExerciseRepository.cs    -> ExerciseRepository
    EvaluationRepository.cs  -> EvaluationRepository
    CalibrationRepository.cs -> CalibrationRepository
    RoutineRepository.cs     -> RoutineRepository

Cada repositorio recibe una `Session` de SQLAlchemy por operación
(patrón "unit of work corto"), en vez de mantener una sesión larga
abierta, para evitar problemas de objetos "stale" en la GUI.
"""

from __future__ import annotations

import datetime as dt

import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from myofit_pro.database.models import (
    EvaluationStatus,
    Client,
    EmgReading,
    EvaluationSession,
    Exercise,
    ExerciseResult,
    Muscle,
    MuscleGroup,
    MvcCalibration,
    Routine,
    RoutineExercise,
    Trainer,
)


class TrainerRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def register(self, full_name: str, email: str, plain_password: str) -> Trainer:
        with self._session_factory() as s:
            password_hash = bcrypt.hashpw(
                plain_password.encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")
            trainer = Trainer(full_name=full_name, email=email, password_hash=password_hash)
            s.add(trainer)
            s.commit()
            s.refresh(trainer)
            return trainer

    def authenticate(self, email: str, plain_password: str) -> Trainer | None:
        with self._session_factory() as s:
            trainer = s.scalar(select(Trainer).where(Trainer.email == email))
            if trainer is None:
                return None
            if bcrypt.checkpw(
                plain_password.encode("utf-8"), trainer.password_hash.encode("utf-8")
            ):
                return trainer
            return None

    def update_profile(self, trainer_id: int, full_name: str, email: str) -> None:
        with self._session_factory() as s:
            trainer = s.get(Trainer, trainer_id)
            if trainer:
                trainer.full_name = full_name
                trainer.email = email
                s.commit()

    def change_password(self, trainer_id: int, current_password: str, new_password: str) -> bool:
        """
        Cambia la contraseña solo si `current_password` coincide con la
        actual. Devuelve False si no coincide (la GUI muestra el error).
        """
        with self._session_factory() as s:
            trainer = s.get(Trainer, trainer_id)
            if trainer is None:
                return False
            if not bcrypt.checkpw(
                current_password.encode("utf-8"), trainer.password_hash.encode("utf-8")
            ):
                return False
            trainer.password_hash = bcrypt.hashpw(
                new_password.encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")
            s.commit()
            return True


class ClientRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def list_for_trainer(self, trainer_id: int) -> list[Client]:
        with self._session_factory() as s:
            return list(
                s.scalars(select(Client).where(Client.trainer_id == trainer_id))
            )

    def get(self, client_id: int) -> Client | None:
        with self._session_factory() as s:
            return s.get(Client, client_id)

    def create(self, trainer_id: int, full_name: str, goal: str, **extra) -> Client:
        with self._session_factory() as s:
            client = Client(trainer_id=trainer_id, full_name=full_name, goal=goal, **extra)
            s.add(client)
            s.commit()
            s.refresh(client)
            return client

    def update(self, client_id: int, **fields) -> None:
        with self._session_factory() as s:
            client = s.get(Client, client_id)
            if client:
                for k, v in fields.items():
                    setattr(client, k, v)
                s.commit()

    def delete(self, client_id: int) -> None:
        """
        Borra un cliente y sus calibraciones.

        Las evaluaciones se borran antes, desde `AppState.delete_client`,
        porque además hay que limpiar la señal cruda que vive en DuckDB.
        Las calibraciones sí se van aquí: son datos del cliente y no
        tienen sentido sin él.
        """
        with self._session_factory() as s:
            client = s.get(Client, client_id)
            if client is None:
                return
            for calib in s.scalars(
                select(MvcCalibration).where(MvcCalibration.client_id == client_id)
            ):
                s.delete(calib)
            s.delete(client)
            s.commit()


class MuscleRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def list_groups(self) -> list[MuscleGroup]:
        with self._session_factory() as s:
            return list(s.scalars(select(MuscleGroup)))

    def list_muscles(self, group_id: int | None = None) -> list[Muscle]:
        with self._session_factory() as s:
            stmt = select(Muscle)
            if group_id is not None:
                stmt = stmt.where(Muscle.group_id == group_id)
            return list(s.scalars(stmt))

    def get(self, muscle_id: int) -> Muscle | None:
        with self._session_factory() as s:
            return s.get(Muscle, muscle_id)


class ExerciseRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def list_for_muscle(self, muscle_id: int) -> list[Exercise]:
        with self._session_factory() as s:
            return list(s.scalars(select(Exercise).where(Exercise.muscle_id == muscle_id)))

    def get(self, exercise_id: int) -> Exercise | None:
        with self._session_factory() as s:
            return s.get(Exercise, exercise_id)


class CalibrationRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def save(
        self, client_id: int, muscle_id: int,
        mvc_value_uv: float, mvc_channel_a_uv: float, mvc_channel_b_uv: float,
    ) -> MvcCalibration:
        with self._session_factory() as s:
            calib = MvcCalibration(
                client_id=client_id,
                muscle_id=muscle_id,
                mvc_value_uv=mvc_value_uv,
                mvc_channel_a_uv=mvc_channel_a_uv,
                mvc_channel_b_uv=mvc_channel_b_uv,
            )
            s.add(calib)
            s.commit()
            s.refresh(calib)
            return calib

    def latest_for(self, client_id: int, muscle_id: int) -> MvcCalibration | None:
        with self._session_factory() as s:
            stmt = (
                select(MvcCalibration)
                .where(MvcCalibration.client_id == client_id, MvcCalibration.muscle_id == muscle_id)
                .order_by(MvcCalibration.recorded_at.desc())
            )
            return s.scalars(stmt).first()

    def get(self, calibration_id: int) -> MvcCalibration | None:
        with self._session_factory() as s:
            return s.get(MvcCalibration, calibration_id)

    def list_for_client(self, client_id: int) -> list[MvcCalibration]:
        """Todas las calibraciones de un cliente (para AlertsView y RoutineView)."""
        with self._session_factory() as s:
            stmt = (
                select(MvcCalibration)
                .where(MvcCalibration.client_id == client_id)
                .order_by(MvcCalibration.recorded_at.desc())
            )
            return list(s.scalars(stmt))


class EvaluationRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def start_session(
        self, client_id: int, muscle_id: int, goal: str,
        mvc_calibration_id: int | None = None,
    ) -> EvaluationSession:
        with self._session_factory() as s:
            session_obj = EvaluationSession(
                client_id=client_id, muscle_id=muscle_id, goal=goal,
                mvc_calibration_id=mvc_calibration_id,
                status=EvaluationStatus.IN_PROGRESS.value,
            )
            s.add(session_obj)
            s.commit()
            s.refresh(session_obj)
            return session_obj

    def finish_session(self, session_id: int, overall_score: float) -> None:
        with self._session_factory() as s:
            session_obj = s.get(EvaluationSession, session_id)
            if session_obj:
                session_obj.finished_at = dt.datetime.now()
                session_obj.overall_score = overall_score
                session_obj.status = EvaluationStatus.COMPLETED.value
                s.commit()

    def cancel_session(self, session_id: int) -> None:
        """Marca una evaluación abandonada como cancelada (no la borra:
        conserva el rastro de que se intentó, para el historial)."""
        with self._session_factory() as s:
            session_obj = s.get(EvaluationSession, session_id)
            if session_obj:
                session_obj.status = EvaluationStatus.CANCELLED.value
                session_obj.finished_at = dt.datetime.now()
                s.commit()

    def delete_session(self, session_id: int) -> None:
        """
        Borra una evaluación y todo lo que cuelga de ella.

        Va por los hijos a mano (lecturas -> resultados -> sesión) en vez
        de confiar en un borrado en cascada: SQLite no aplica las llaves
        foráneas a menos que se active `PRAGMA foreign_keys` en cada
        conexión, así que sin esto quedarían ExerciseResult y EmgReading
        apuntando a una sesión que ya no existe.

        La señal cruda vive en DuckDB y se borra aparte, desde la capa
        que tiene acceso a las dos bases (ver `AppState.delete_evaluation`).
        """
        with self._session_factory() as s:
            session_obj = s.get(EvaluationSession, session_id)
            if session_obj is None:
                return

            result_ids = list(
                s.scalars(
                    select(ExerciseResult.id).where(ExerciseResult.session_id == session_id)
                )
            )
            if result_ids:
                for reading in s.scalars(
                    select(EmgReading).where(EmgReading.exercise_result_id.in_(result_ids))
                ):
                    s.delete(reading)
                for result in s.scalars(
                    select(ExerciseResult).where(ExerciseResult.id.in_(result_ids))
                ):
                    s.delete(result)

            # Las rutinas generadas a partir de esta evaluación se
            # conservan: son un entregable que el cliente pudo haberse
            # llevado. Solo se les quita la referencia.
            for routine in s.scalars(select(Routine).where(Routine.session_id == session_id)):
                routine.session_id = None

            s.delete(session_obj)
            s.commit()

    def find_in_progress(self, trainer_id: int) -> EvaluationSession | None:
        """
        La evaluación en curso más reciente de este entrenador, si hay.
        Se usa para avisar al entrar al wizard y para el badge del sidebar.
        """
        with self._session_factory() as s:
            stmt = (
                select(EvaluationSession)
                .join(Client, EvaluationSession.client_id == Client.id)
                .where(
                    Client.trainer_id == trainer_id,
                    EvaluationSession.status == EvaluationStatus.IN_PROGRESS.value,
                )
                .order_by(EvaluationSession.started_at.desc())
            )
            return s.scalars(stmt).first()

    def count_in_progress(self, trainer_id: int) -> int:
        with self._session_factory() as s:
            stmt = (
                select(EvaluationSession)
                .join(Client, EvaluationSession.client_id == Client.id)
                .where(
                    Client.trainer_id == trainer_id,
                    EvaluationSession.status == EvaluationStatus.IN_PROGRESS.value,
                )
            )
            return len(list(s.scalars(stmt)))

    def link_calibration(self, session_id: int, mvc_calibration_id: int) -> None:
        """Enlaza el MVC calculado en el Paso 4 a una sesión ya creada en el Paso 1."""
        with self._session_factory() as s:
            session_obj = s.get(EvaluationSession, session_id)
            if session_obj:
                session_obj.mvc_calibration_id = mvc_calibration_id
                s.commit()

    def add_exercise_result(
        self, session_id: int, exercise_id: int | None,
        series_count: int, avg_activation_pct: float, peak_activation_pct: float,
    ) -> ExerciseResult:
        with self._session_factory() as s:
            result = ExerciseResult(
                session_id=session_id, exercise_id=exercise_id,
                series_count=series_count, avg_activation_pct=avg_activation_pct,
                peak_activation_pct=peak_activation_pct,
            )
            s.add(result)
            s.commit()
            s.refresh(result)
            return result

    def add_reading(
        self, exercise_result_id: int, series_number: int,
        channel_a_mv: float, channel_b_mv: float,
        activation_a_pct: float, activation_b_pct: float,
        duration_sec: float, burst_id: str | None = None,
    ) -> EmgReading:
        with self._session_factory() as s:
            reading = EmgReading(
                exercise_result_id=exercise_result_id, series_number=series_number,
                channel_a_mv=channel_a_mv, channel_b_mv=channel_b_mv,
                activation_a_pct=activation_a_pct, activation_b_pct=activation_b_pct,
                duration_sec=duration_sec, burst_id=burst_id,
            )
            s.add(reading)
            s.commit()
            s.refresh(reading)
            return reading

    def list_for_client(self, client_id: int) -> list[EvaluationSession]:
        with self._session_factory() as s:
            stmt = (
                select(EvaluationSession)
                .where(EvaluationSession.client_id == client_id)
                .order_by(EvaluationSession.started_at.desc())
            )
            return list(s.scalars(stmt))

    def get_with_results(self, session_id: int) -> EvaluationSession | None:
        """
        Trae la sesión con sus ExerciseResult y EmgReading ya cargados
        (selectinload) para que sigan accesibles después de cerrar la
        sesión de SQLAlchemy -- evita DetachedInstanceError al leerlos
        desde la GUI (ej. EvaluationStep6View, ReportView).
        """
        with self._session_factory() as s:
            stmt = (
                select(EvaluationSession)
                .where(EvaluationSession.id == session_id)
                .options(selectinload(EvaluationSession.results).selectinload(ExerciseResult.readings))
            )
            return s.scalars(stmt).first()

    def list_for_trainer_with_results(self, trainer_id: int) -> list[EvaluationSession]:
        """Todas las sesiones de todos los clientes de un entrenador -- para HistoryView."""
        with self._session_factory() as s:
            stmt = (
                select(EvaluationSession)
                .join(Client, EvaluationSession.client_id == Client.id)
                .where(Client.trainer_id == trainer_id)
                .options(selectinload(EvaluationSession.results))
                .order_by(EvaluationSession.started_at.desc())
            )
            return list(s.scalars(stmt))


class RoutineRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def create(self, client_id: int, name: str, session_id: int | None = None) -> Routine:
        with self._session_factory() as s:
            routine = Routine(client_id=client_id, name=name, session_id=session_id)
            s.add(routine)
            s.commit()
            s.refresh(routine)
            return routine

    def add_exercise(
        self, routine_id: int, exercise_id: int, sets: int, reps: int, order_index: int,
    ) -> RoutineExercise:
        with self._session_factory() as s:
            re = RoutineExercise(
                routine_id=routine_id, exercise_id=exercise_id,
                sets=sets, reps=reps, order_index=order_index,
            )
            s.add(re)
            s.commit()
            s.refresh(re)
            return re

    def get_for_client(self, client_id: int) -> Routine | None:
        with self._session_factory() as s:
            stmt = (
                select(Routine)
                .where(Routine.client_id == client_id)
                .options(selectinload(Routine.exercises))
                .order_by(Routine.created_at.desc())
            )
            return s.scalars(stmt).first()