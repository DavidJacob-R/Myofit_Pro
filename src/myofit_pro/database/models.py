"""
Modelos ORM (SQLAlchemy 2.0, estilo declarativo con Mapped/mapped_column).

Equivalencia directa con los modelos C# de EMGTrainer:

    Trainer.cs           -> Trainer
    Client.cs            -> Client
    MuscleGrups.cs       -> MuscleGroup
    Muscle.cs            -> Muscle
    MvcCalibration.cs    -> MvcCalibration
    EvaluationSession.cs -> EvaluationSession
    ExerciseResult.cs    -> ExerciseResult
    EmgReading.cs        -> EmgReading   (metadatos; la señal cruda va a DuckDB)
    Exercise.cs          -> Exercise
    Routine.cs           -> Routine
    RoutineExercise.cs   -> RoutineExercise
"""

from __future__ import annotations

import datetime as dt
from enum import Enum

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Trainer(Base):
    __tablename__ = "trainers"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str] = mapped_column(String(150), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.now)

    clients: Mapped[list["Client"]] = relationship(back_populates="trainer")


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id"))
    full_name: Mapped[str] = mapped_column(String(150))
    goal: Mapped[str] = mapped_column(String(80), default="Hipertrofia")
    birth_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.now)

    trainer: Mapped["Trainer"] = relationship(back_populates="clients")
    evaluations: Mapped[list["EvaluationSession"]] = relationship(back_populates="client")
    calibrations: Mapped[list["MvcCalibration"]] = relationship(back_populates="client")


class MuscleGroup(Base):
    __tablename__ = "muscle_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))

    muscles: Mapped[list["Muscle"]] = relationship(back_populates="group")


class Muscle(Base):
    __tablename__ = "muscles"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("muscle_groups.id"))
    name: Mapped[str] = mapped_column(String(120))
    placement_guide: Mapped[str | None] = mapped_column(String(500), nullable=True)

    group: Mapped["MuscleGroup"] = relationship(back_populates="muscles")


class MvcCalibration(Base):
    """
    MVC = promedio de Sensor A y Sensor B durante la contracción máxima
    (Filosofía A: ambos sensores sobre el mismo músculo, porciones distintas).
    """

    __tablename__ = "mvc_calibrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    muscle_id: Mapped[int] = mapped_column(ForeignKey("muscles.id"))
    mvc_value_uv: Mapped[float] = mapped_column()       # promedio A+B, en microvolts
    mvc_channel_a_uv: Mapped[float] = mapped_column()   # pico de A (para análisis de balance)
    mvc_channel_b_uv: Mapped[float] = mapped_column()   # pico de B
    recorded_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.now)

    client: Mapped["Client"] = relationship(back_populates="calibrations")


class EvaluationStatus(str, Enum):
    """
    Estado explícito de una sesión de evaluación.

    Antes se infería de `finished_at IS NULL`, pero eso era ambiguo:
    una sesión sin terminar podía estar realmente en curso o haber
    sido abandonada hace semanas. Con este campo la diferencia queda
    registrada y la UI puede ofrecer "retomar" o "cancelar".
    """

    IN_PROGRESS = "en_curso"
    COMPLETED = "completada"
    CANCELLED = "cancelada"


class EvaluationSession(Base):
    __tablename__ = "evaluation_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    muscle_id: Mapped[int] = mapped_column(ForeignKey("muscles.id"))
    mvc_calibration_id: Mapped[int | None] = mapped_column(
        ForeignKey("mvc_calibrations.id"), nullable=True
    )
    goal: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default=EvaluationStatus.IN_PROGRESS.value)
    overall_score: Mapped[float | None] = mapped_column(nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.now)
    finished_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)

    client: Mapped["Client"] = relationship(back_populates="evaluations")
    results: Mapped[list["ExerciseResult"]] = relationship(back_populates="session")


class Exercise(Base):
    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    muscle_id: Mapped[int] = mapped_column(ForeignKey("muscles.id"))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)


class ExerciseResult(Base):
    __tablename__ = "exercise_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("evaluation_sessions.id"))
    exercise_id: Mapped[int | None] = mapped_column(ForeignKey("exercises.id"), nullable=True)
    series_count: Mapped[int] = mapped_column(default=0)
    avg_activation_pct: Mapped[float] = mapped_column(default=0.0)
    peak_activation_pct: Mapped[float] = mapped_column(default=0.0)

    session: Mapped["EvaluationSession"] = relationship(back_populates="results")
    readings: Mapped[list["EmgReading"]] = relationship(back_populates="exercise_result")


class EmgReading(Base):
    """
    Metadatos de una lectura/serie de EMG. La señal cruda (arrays de
    tiempo, µV, envolvente, RMS) NO vive aquí — se guarda en DuckDB
    (ver duckdb_store.py) para no saturar SQLite con series de tiempo
    de alta frecuencia. Este registro solo guarda el resumen y un
    `burst_id` para enlazar con la tabla de DuckDB.
    """

    __tablename__ = "emg_readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    exercise_result_id: Mapped[int] = mapped_column(ForeignKey("exercise_results.id"))
    series_number: Mapped[int] = mapped_column()
    channel_a_mv: Mapped[float] = mapped_column()
    channel_b_mv: Mapped[float] = mapped_column()
    activation_a_pct: Mapped[float] = mapped_column()
    activation_b_pct: Mapped[float] = mapped_column()
    duration_sec: Mapped[float] = mapped_column()
    burst_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # FK lógica a DuckDB
    recorded_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.now)

    exercise_result: Mapped["ExerciseResult"] = relationship(back_populates="readings")


class Routine(Base):
    __tablename__ = "routines"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("evaluation_sessions.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(150))
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.now)

    exercises: Mapped[list["RoutineExercise"]] = relationship(back_populates="routine")


class RoutineExercise(Base):
    __tablename__ = "routine_exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    routine_id: Mapped[int] = mapped_column(ForeignKey("routines.id"))
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id"))
    sets: Mapped[int] = mapped_column(default=3)
    reps: Mapped[int] = mapped_column(default=12)
    order_index: Mapped[int] = mapped_column(default=0)

    routine: Mapped["Routine"] = relationship(back_populates="exercises")