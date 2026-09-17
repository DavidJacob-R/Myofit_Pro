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
    """
    Ficha de un cliente.

    Los datos físicos (sexo, edad, estatura, peso) no son decorativos:
    son las variables con las que el generador de rutinas ajusta volumen
    e intensidad, y sirven para comparar la activación medida contra lo
    esperable en alguien de ese perfil. Todos son opcionales para no
    bloquear el alta de un cliente cuando faltan, pero mientras más
    completos, mejor la predicción.

    `full_name` se conserva como el nombre que se muestra en toda la app
    y se mantiene sincronizado con `first_name` + `last_name`. No se
    eliminó a favor de los dos campos nuevos porque las fichas dadas de
    alta antes solo tienen el nombre completo, sin separar.
    """

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id"))
    full_name: Mapped[str] = mapped_column(String(150))
    first_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    goal: Mapped[str] = mapped_column(String(80), default="Hipertrofia")
    sex: Mapped[str | None] = mapped_column(String(20), nullable=True)
    age_years: Mapped[int | None] = mapped_column(nullable=True)
    height_cm: Mapped[float | None] = mapped_column(nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(nullable=True)

    # Circunferencias para el método de la Marina. Opcionales: solo
    # hacen falta si se quiere un porcentaje de grasa que no sea una
    # estimación estadística.
    neck_cm: Mapped[float | None] = mapped_column(nullable=True)
    waist_cm: Mapped[float | None] = mapped_column(nullable=True)
    hip_cm: Mapped[float | None] = mapped_column(nullable=True)

    # Porcentaje de grasa y de dónde salió. La fuente se guarda porque
    # de ella depende si el número sirve como variable de entrada a un
    # modelo o si es solo IMC, edad y sexo reescritos.
    # Ver ml/body_composition.BodyFatSource.
    body_fat_pct: Mapped[float | None] = mapped_column(nullable=True)
    body_fat_source: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Contexto de entrenamiento: cuánto volumen tolera y en cuántos días
    # hay que repartirlo.
    experience_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    days_per_week: Mapped[int | None] = mapped_column(nullable=True)

    birth_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.now)

    trainer: Mapped["Trainer"] = relationship(back_populates="clients")
    evaluations: Mapped[list["EvaluationSession"]] = relationship(back_populates="client")
    calibrations: Mapped[list["MvcCalibration"]] = relationship(back_populates="client")

    @property
    def bmi(self) -> float | None:
        """Índice de masa corporal, o None si falta estatura o peso."""
        from myofit_pro.body_composition import bmi

        return bmi(self.height_cm, self.weight_kg)

    @property
    def body_fat_is_measured(self) -> bool:
        """
        True cuando el porcentaje de grasa es un dato propio del cuerpo
        del cliente (medido, o calculado de circunferencias) y no la
        estimación derivada de IMC, edad y sexo.
        """
        from myofit_pro.body_composition import BodyFatSource

        return self.body_fat_source in (
            BodyFatSource.MEASURED.value,
            BodyFatSource.NAVY.value,
        )

    @property
    def profile_is_complete(self) -> bool:
        """
        True cuando la ficha trae todo lo que el generador de rutinas
        usa. La UI marca las incompletas para que se puedan terminar.

        El porcentaje de grasa no entra en la cuenta: siempre se puede
        estimar a partir de los demás datos, así que nunca falta del
        todo.
        """
        return all(
            (
                self.sex,
                self.age_years,
                self.height_cm,
                self.weight_kg,
                self.experience_level,
                self.days_per_week,
            )
        )


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