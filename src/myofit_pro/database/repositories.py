"""Capa de acceso a los datos.

Posición en el flujo
--------------------
Única capa que consulta y modifica el esquema de
`myofit_pro.database.models`. `myofit_pro.gui.app_state` instancia un
repositorio por entidad y se los ofrece al resto de la interfaz, que
nunca abre sesiones de SQLAlchemy por su cuenta.

Repositorios
------------
`TrainerRepository`
    Alta, autenticación y perfil de las cuentas de entrenador.
`ClientRepository`
    Fichas de cliente.
`MuscleRepository`, `ExerciseRepository`
    Consulta del catálogo, que es de solo lectura en ejecución.
`CalibrationRepository`
    Calibraciones de contracción voluntaria máxima.
`EvaluationRepository`
    Sesiones de evaluación, sus resultados y sus lecturas.
`RoutineRepository`
    Rutinas generadas y sus ejercicios.

Gestión de sesiones
-------------------
Cada método abre y cierra su propia sesión de SQLAlchemy, en lugar de
mantener una sesión larga compartida. La alternativa dejaría a la
interfaz operando sobre objetos desvinculados de la base de datos, cuyo
estado podría haber cambiado sin reflejarse.

Los objetos se devuelven ya desvinculados y legibles, gracias a
``expire_on_commit=False``. Cuando un consumidor necesita relaciones
cargadas, el método las solicita explícitamente con
`sqlalchemy.orm.selectinload`, de modo que el acceso posterior a un
atributo no dispare una consulta con la sesión ya cerrada.

See Also
--------
myofit_pro.database.models : Esquema sobre el que operan.
myofit_pro.gui.app_state : Consumidor de todos los repositorios.
"""

from __future__ import annotations

import datetime as dt

import bcrypt
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

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
    """Acceso a las cuentas de entrenador.

    Parameters
    ----------
    session_factory : callable
        Fábrica de sesiones de SQLAlchemy, normalmente
        `myofit_pro.database.engine.DatabaseEngine.get_session`.

    Notes
    -----
    Las contraseñas se almacenan cifradas con bcrypt, que incorpora una
    sal propia en cada hash y un coste configurable. La contraseña en
    claro no se guarda ni se registra en ningún punto.
    """

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def register(self, full_name: str, email: str, plain_password: str) -> Trainer:
        """Da de alta una cuenta de entrenador.

        Parameters
        ----------
        full_name : str
            Nombre completo.
        email : str
            Correo electrónico, que debe ser único.
        plain_password : str
            Contraseña en claro. Se cifra antes de almacenarse.

        Returns
        -------
        Trainer
            La cuenta creada, con su identificador asignado.
        """
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
        """Verifica unas credenciales.

        Parameters
        ----------
        email : str
            Correo de la cuenta.
        plain_password : str
            Contraseña en claro.

        Returns
        -------
        Trainer or None
            La cuenta si las credenciales son correctas, `None` en caso
            contrario. No se distingue entre correo inexistente y
            contraseña incorrecta.
        """
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
        """Actualiza el nombre y el correo de una cuenta.

        Parameters
        ----------
        trainer_id : int
            Cuenta a modificar. Si no existe, la llamada no hace nada.
        full_name : str
            Nuevo nombre completo.
        email : str
            Nuevo correo electrónico.
        """
        with self._session_factory() as s:
            trainer = s.get(Trainer, trainer_id)
            if trainer:
                trainer.full_name = full_name
                trainer.email = email
                s.commit()

    def change_password(self, trainer_id: int, current_password: str, new_password: str) -> bool:
        """Cambia la contraseña previa verificación de la actual.

        Parameters
        ----------
        trainer_id : int
            Cuenta a modificar.
        current_password : str
            Contraseña actual, en claro.
        new_password : str
            Contraseña nueva, en claro.

        Returns
        -------
        bool
            Cierto si el cambio se aplicó. Falso si la cuenta no existe
            o si la contraseña actual no coincide, caso en el que la
            interfaz muestra el error.
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
    """Acceso a las fichas de cliente.

    Parameters
    ----------
    session_factory : callable
        Fábrica de sesiones de SQLAlchemy.
    """

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def list_for_trainer(self, trainer_id: int) -> list[Client]:
        """Lista los clientes de un entrenador.

        Parameters
        ----------
        trainer_id : int
            Entrenador propietario.

        Returns
        -------
        list of Client
            Sus clientes, sin ordenar.
        """
        with self._session_factory() as s:
            return list(
                s.scalars(select(Client).where(Client.trainer_id == trainer_id))
            )

    def get(self, client_id: int) -> Client | None:
        """Recupera una ficha por su identificador.

        Parameters
        ----------
        client_id : int
            Cliente.

        Returns
        -------
        Client or None
            La ficha, o `None` si no existe.
        """
        with self._session_factory() as s:
            return s.get(Client, client_id)

    def create(self, trainer_id: int, full_name: str, goal: str, **extra) -> Client:
        """Da de alta un cliente.

        Parameters
        ----------
        trainer_id : int
            Entrenador propietario.
        full_name : str
            Nombre completo.
        goal : str
            Objetivo de entrenamiento.
        **extra
            Resto de campos de `Client`, todos opcionales.

        Returns
        -------
        Client
            La ficha creada, con su identificador asignado.
        """
        with self._session_factory() as s:
            client = Client(trainer_id=trainer_id, full_name=full_name, goal=goal, **extra)
            s.add(client)
            s.commit()
            s.refresh(client)
            return client

    def update(self, client_id: int, **fields) -> None:
        """Actualiza los campos indicados de una ficha.

        Parameters
        ----------
        client_id : int
            Cliente a modificar. Si no existe, la llamada no hace nada.
        **fields
            Campos de `Client` con sus nuevos valores.
        """
        with self._session_factory() as s:
            client = s.get(Client, client_id)
            if client:
                for k, v in fields.items():
                    setattr(client, k, v)
                s.commit()

    def delete(self, client_id: int) -> None:
        """Elimina un cliente y sus calibraciones.

        Parameters
        ----------
        client_id : int
            Cliente a eliminar. Si no existe, la llamada no hace nada.

        Notes
        -----
        Las evaluaciones deben eliminarse antes, desde
        `myofit_pro.gui.app_state.AppState.delete_client`, porque además
        requieren limpiar las series temporales del almacén DuckDB, al
        que este repositorio no accede. Las calibraciones sí se eliminan
        aquí: carecen de sentido sin su cliente y no tienen datos
        asociados fuera del esquema relacional.
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
    """Consulta del catálogo de grupos y músculos.

    Parameters
    ----------
    session_factory : callable
        Fábrica de sesiones de SQLAlchemy.

    Notes
    -----
    El catálogo es de solo lectura durante la ejecución: lo siembra
    `myofit_pro.seed_data` al arrancar.
    """

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def list_groups(self) -> list[MuscleGroup]:
        """Lista todos los grupos musculares.

        Returns
        -------
        list of MuscleGroup
            Grupos del catálogo.
        """
        with self._session_factory() as s:
            return list(s.scalars(select(MuscleGroup)))

    def list_muscles(self, group_id: int | None = None) -> list[Muscle]:
        """Lista los músculos del catálogo.

        Parameters
        ----------
        group_id : int, optional
            Restringe el resultado a un grupo. Si se omite se devuelven
            todos.

        Returns
        -------
        list of Muscle
            Músculos del catálogo.
        """
        with self._session_factory() as s:
            stmt = select(Muscle)
            if group_id is not None:
                stmt = stmt.where(Muscle.group_id == group_id)
            return list(s.scalars(stmt))

    def get(self, muscle_id: int) -> Muscle | None:
        """Recupera un músculo por su identificador.

        Parameters
        ----------
        muscle_id : int
            Músculo.

        Returns
        -------
        Muscle or None
            El músculo, o `None` si no existe.
        """
        with self._session_factory() as s:
            return s.get(Muscle, muscle_id)


class ExerciseRepository:
    """Consulta del catálogo de ejercicios.

    Parameters
    ----------
    session_factory : callable
        Fábrica de sesiones de SQLAlchemy.
    """

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def list_for_muscle(self, muscle_id: int) -> list[Exercise]:
        """Lista los ejercicios de un músculo.

        Parameters
        ----------
        muscle_id : int
            Músculo.

        Returns
        -------
        list of Exercise
            Ejercicios del catálogo que trabajan ese músculo. Es la
            fuente de los candidatos de
            `myofit_pro.routine_engine.MuscleCandidates`.
        """
        with self._session_factory() as s:
            return list(s.scalars(select(Exercise).where(Exercise.muscle_id == muscle_id)))

    def get(self, exercise_id: int) -> Exercise | None:
        """Recupera un ejercicio por su identificador.

        Parameters
        ----------
        exercise_id : int
            Ejercicio.

        Returns
        -------
        Exercise or None
            El ejercicio, o `None` si no existe.
        """
        with self._session_factory() as s:
            return s.get(Exercise, exercise_id)


class CalibrationRepository:
    """Acceso a las calibraciones de contracción voluntaria máxima.

    Parameters
    ----------
    session_factory : callable
        Fábrica de sesiones de SQLAlchemy.
    """

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def save(
        self, client_id: int, muscle_id: int,
        mvc_value_uv: float, mvc_channel_a_uv: float, mvc_channel_b_uv: float,
    ) -> MvcCalibration:
        """Registra una calibración.

        Parameters
        ----------
        client_id : int
            Cliente calibrado.
        muscle_id : int
            Músculo calibrado.
        mvc_value_uv : float
            Media de ambos canales, en microvoltios. Es el denominador
            del porcentaje de activación de la sesión.
        mvc_channel_a_uv, mvc_channel_b_uv : float
            Pico de cada canal por separado, en microvoltios.

        Returns
        -------
        MvcCalibration
            La calibración creada, con su identificador asignado.
        """
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
        """Recupera la calibración más reciente de un cliente en un músculo.

        Parameters
        ----------
        client_id : int
            Cliente.
        muscle_id : int
            Músculo.

        Returns
        -------
        MvcCalibration or None
            La última calibración registrada, o `None` si no hay
            ninguna.
        """
        with self._session_factory() as s:
            stmt = (
                select(MvcCalibration)
                .where(MvcCalibration.client_id == client_id, MvcCalibration.muscle_id == muscle_id)
                .order_by(MvcCalibration.recorded_at.desc())
            )
            return s.scalars(stmt).first()

    def get(self, calibration_id: int) -> MvcCalibration | None:
        """Recupera una calibración por su identificador.

        Parameters
        ----------
        calibration_id : int
            Calibración.

        Returns
        -------
        MvcCalibration or None
            La calibración, o `None` si no existe.
        """
        with self._session_factory() as s:
            return s.get(MvcCalibration, calibration_id)

    def list_for_client(self, client_id: int) -> list[MvcCalibration]:
        """Lista todas las calibraciones de un cliente.

        Parameters
        ----------
        client_id : int
            Cliente.

        Returns
        -------
        list of MvcCalibration
            Calibraciones de todos sus músculos, de la más reciente a la
            más antigua.
        """
        with self._session_factory() as s:
            stmt = (
                select(MvcCalibration)
                .where(MvcCalibration.client_id == client_id)
                .order_by(MvcCalibration.recorded_at.desc())
            )
            return list(s.scalars(stmt))


class EvaluationRepository:
    """Acceso a las sesiones de evaluación y sus mediciones.

    Es el repositorio con más responsabilidades: cubre el ciclo de vida
    completo de una evaluación, desde su apertura hasta la consulta
    agregada que alimenta al generador de rutinas.

    Parameters
    ----------
    session_factory : callable
        Fábrica de sesiones de SQLAlchemy.
    """

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def start_session(
        self, client_id: int, muscle_id: int, goal: str,
        mvc_calibration_id: int | None = None,
    ) -> EvaluationSession:
        """Abre una sesión de evaluación.

        Parameters
        ----------
        client_id : int
            Cliente evaluado.
        muscle_id : int
            Músculo evaluado.
        goal : str
            Objetivo vigente, copiado de la ficha.
        mvc_calibration_id : int, optional
            Calibración de referencia. Suele enlazarse después con
            `link_calibration`, ya que la calibración se realiza en un
            paso posterior del asistente.

        Returns
        -------
        EvaluationSession
            La sesión creada, en estado
            `myofit_pro.database.models.EvaluationStatus.IN_PROGRESS`.
        """
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
        """Cierra una sesión y registra su puntuación.

        Parameters
        ----------
        session_id : int
            Sesión a cerrar. Si no existe, la llamada no hace nada.
        overall_score : float
            Puntuación global, sobre 100.
        """
        with self._session_factory() as s:
            session_obj = s.get(EvaluationSession, session_id)
            if session_obj:
                session_obj.finished_at = dt.datetime.now()
                session_obj.overall_score = overall_score
                session_obj.status = EvaluationStatus.COMPLETED.value
                s.commit()

    def cancel_session(self, session_id: int) -> None:
        """Marca una sesión como cancelada.

        Parameters
        ----------
        session_id : int
            Sesión a cancelar. Si no existe, la llamada no hace nada.

        Notes
        -----
        La sesión no se elimina: el historial conserva el registro de
        que se intentó la evaluación. Los análisis excluyen las sesiones
        canceladas porque su puntuación nunca se cerró.
        """
        with self._session_factory() as s:
            session_obj = s.get(EvaluationSession, session_id)
            if session_obj:
                session_obj.status = EvaluationStatus.CANCELLED.value
                session_obj.finished_at = dt.datetime.now()
                s.commit()

    def delete_session(self, session_id: int) -> None:
        """Elimina una sesión y todos sus registros dependientes.

        Parameters
        ----------
        session_id : int
            Sesión a eliminar. Si no existe, la llamada no hace nada.

        Notes
        -----
        El borrado recorre la jerarquía de forma explícita —lecturas,
        resultados y por último la sesión— en lugar de confiar en un
        borrado en cascada. SQLite no aplica las restricciones de clave
        foránea salvo que se active ``PRAGMA foreign_keys`` en cada
        conexión, de modo que sin este recorrido quedarían registros
        huérfanos apuntando a una sesión inexistente.

        Las rutinas generadas a partir de la evaluación se conservan y
        solo pierden la referencia: son un entregable que el cliente
        puede tener en su poder.

        Las series temporales residen en DuckDB y se eliminan por
        separado desde
        `myofit_pro.gui.app_state.AppState.delete_evaluation`, que es la
        capa con acceso a ambos almacenes.
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

            for routine in s.scalars(select(Routine).where(Routine.session_id == session_id)):
                routine.session_id = None

            s.delete(session_obj)
            s.commit()

    def find_in_progress(self, trainer_id: int) -> EvaluationSession | None:
        """Busca la evaluación en curso más reciente de un entrenador.

        Parameters
        ----------
        trainer_id : int
            Entrenador.

        Returns
        -------
        EvaluationSession or None
            La sesión en curso más reciente, o `None` si no hay
            ninguna. La interfaz la usa para ofrecer retomarla al entrar
            al asistente.
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
        """Cuenta las evaluaciones en curso de un entrenador.

        Parameters
        ----------
        trainer_id : int
            Entrenador.

        Returns
        -------
        int
            Sesiones abiertas, que la barra lateral muestra como aviso.
        """
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
        """Enlaza una calibración a una sesión ya abierta.

        Parameters
        ----------
        session_id : int
            Sesión a enlazar. Si no existe, la llamada no hace nada.
        mvc_calibration_id : int
            Calibración de referencia.

        Notes
        -----
        La sesión se abre al principio del asistente, pero la
        calibración no se obtiene hasta varios pasos después, de ahí que
        el enlace sea una operación independiente.
        """
        with self._session_factory() as s:
            session_obj = s.get(EvaluationSession, session_id)
            if session_obj:
                session_obj.mvc_calibration_id = mvc_calibration_id
                s.commit()

    def add_exercise_result(
        self, session_id: int, exercise_id: int | None,
        series_count: int, avg_activation_pct: float, peak_activation_pct: float,
        load_kg: float | None = None,
    ) -> ExerciseResult:
        """Registra el resultado de un ejercicio de la batería.

        Parameters
        ----------
        session_id : int
            Sesión a la que pertenece.
        exercise_id : int or None
            Ejercicio del catálogo medido.
        series_count : int
            Series ejecutadas.
        avg_activation_pct, peak_activation_pct : float
            Activación media y máxima, en porcentaje de la contracción
            voluntaria máxima.
        load_kg : float, optional
            Carga empleada, en kilogramos. Sin ella, la comparación de
            activación entre sesiones no es interpretable.

        Returns
        -------
        ExerciseResult
            El resultado creado, con su identificador asignado.
        """
        with self._session_factory() as s:
            result = ExerciseResult(
                session_id=session_id, exercise_id=exercise_id,
                series_count=series_count, avg_activation_pct=avg_activation_pct,
                peak_activation_pct=peak_activation_pct, load_kg=load_kg,
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
        """Registra una serie medida.

        Parameters
        ----------
        exercise_result_id : int
            Ejercicio al que pertenece la serie.
        series_number : int
            Número de serie dentro del ejercicio, empezando en 1.
        channel_a_mv, channel_b_mv : float
            Amplitud de cada canal, en milivoltios.
        activation_a_pct, activation_b_pct : float
            Activación de cada canal, en porcentaje.
        duration_sec : float
            Duración de la serie, en segundos.
        burst_id : str, optional
            Identificador de la ráfaga en el almacén DuckDB, devuelto
            por
            `myofit_pro.database.duckdb_store.EmgBurstStore.save_burst`.

        Returns
        -------
        EmgReading
            La lectura creada, con su identificador asignado.
        """
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
        """Lista todas las sesiones de un cliente.

        Parameters
        ----------
        client_id : int
            Cliente.

        Returns
        -------
        list of EvaluationSession
            Sesiones de cualquier estado, de la más reciente a la más
            antigua, sin sus resultados cargados.
        """
        with self._session_factory() as s:
            stmt = (
                select(EvaluationSession)
                .where(EvaluationSession.client_id == client_id)
                .order_by(EvaluationSession.started_at.desc())
            )
            return list(s.scalars(stmt))

    def list_completed_for_client(
        self, client_id: int, muscle_id: int | None = None
    ) -> list[EvaluationSession]:
        """Lista las sesiones completadas de un cliente.

        Parameters
        ----------
        client_id : int
            Cliente.
        muscle_id : int, optional
            Restringe el resultado a un músculo.

        Returns
        -------
        list of EvaluationSession
            Sesiones completadas, con sus resultados y lecturas ya
            cargados, de la más reciente a la más antigua.

        Notes
        -----
        Solo se devuelven las sesiones completadas: una evaluación en
        curso o cancelada no tiene puntuación cerrada y compararla con
        otra produciría un progreso ficticio.

        El filtro por músculo es el modo habitual de uso, ya que la
        comparación entre sesiones solo tiene sentido dentro del mismo
        músculo.

        See Also
        --------
        myofit_pro.progress : Consumidor de estas sesiones.
        """
        with self._session_factory() as s:
            stmt = (
                select(EvaluationSession)
                .where(
                    EvaluationSession.client_id == client_id,
                    EvaluationSession.status == EvaluationStatus.COMPLETED.value,
                )
                .options(
                    selectinload(EvaluationSession.results).selectinload(
                        ExerciseResult.readings
                    )
                )
                .order_by(EvaluationSession.started_at.desc())
            )
            if muscle_id is not None:
                stmt = stmt.where(EvaluationSession.muscle_id == muscle_id)
            return list(s.scalars(stmt))

    def set_session_measurements(
        self,
        session_id: int,
        circumference_cm: float | None = None,
        repeatability_cv: float | None = None,
    ) -> None:
        """Registra la circunferencia y la repetibilidad de una sesión.

        Parameters
        ----------
        session_id : int
            Sesión a modificar. Si no existe, la llamada no hace nada.
        circumference_cm : float, optional
            Perímetro del músculo, en centímetros.
        repeatability_cv : float, optional
            Coeficiente de variación observado al repetir un ejercicio.

        Notes
        -----
        Ambos parámetros se escriben solo si traen valor, de modo que
        pueda actualizarse uno sin borrar el otro. Los dos se capturan
        en momentos distintos del asistente.
        """
        with self._session_factory() as s:
            session_obj = s.get(EvaluationSession, session_id)
            if session_obj is None:
                return
            if circumference_cm is not None:
                session_obj.circumference_cm = circumference_cm
            if repeatability_cv is not None:
                session_obj.repeatability_cv = repeatability_cv
            s.commit()

    def get_with_results(self, session_id: int) -> EvaluationSession | None:
        """Recupera una sesión con sus resultados y lecturas cargados.

        Parameters
        ----------
        session_id : int
            Sesión.

        Returns
        -------
        EvaluationSession or None
            La sesión con sus relaciones resueltas, o `None` si no
            existe.

        Notes
        -----
        Las relaciones se cargan con `sqlalchemy.orm.selectinload` para
        que sigan siendo accesibles una vez cerrada la sesión de
        SQLAlchemy. Sin ello, la interfaz provocaría un
        ``DetachedInstanceError`` al recorrer los resultados.
        """
        with self._session_factory() as s:
            stmt = (
                select(EvaluationSession)
                .where(EvaluationSession.id == session_id)
                .options(selectinload(EvaluationSession.results).selectinload(ExerciseResult.readings))
            )
            return s.scalars(stmt).first()

    def activation_by_exercise(self, client_id: int) -> list[tuple[int, int, float, int]]:
        """Calcula la activación media de cada ejercicio medido.

        Parameters
        ----------
        client_id : int
            Cliente.

        Returns
        -------
        list of tuple
            Tuplas ``(muscle_id, exercise_id, activación media, número
            de mediciones)``. Es la entrada con la que
            `myofit_pro.routine_engine` ordena los ejercicios de cada
            músculo.

        Notes
        -----
        La media abarca todas las sesiones completadas del cliente y no
        solo la última: cada repetición de un mismo ejercicio aumenta la
        precisión de la estimación, y el recuento devuelto permite al
        generador desempatar a favor del ejercicio mejor medido.

        Quedan fuera los resultados sin ejercicio asociado, procedentes
        de versiones anteriores que no registraban qué ejercicio se
        estaba realizando: contribuyen a la puntuación de su sesión pero
        no son ordenables.
        """
        with self._session_factory() as s:
            stmt = (
                select(
                    EvaluationSession.muscle_id,
                    ExerciseResult.exercise_id,
                    func.avg(ExerciseResult.avg_activation_pct),
                    func.count(ExerciseResult.id),
                )
                .join(EvaluationSession, ExerciseResult.session_id == EvaluationSession.id)
                .where(
                    EvaluationSession.client_id == client_id,
                    EvaluationSession.status == EvaluationStatus.COMPLETED.value,
                    ExerciseResult.exercise_id.is_not(None),
                )
                .group_by(EvaluationSession.muscle_id, ExerciseResult.exercise_id)
            )
            return [
                (int(muscle_id), int(exercise_id), float(mean), int(count))
                for muscle_id, exercise_id, mean, count in s.execute(stmt)
            ]

    def list_for_trainer_with_results(self, trainer_id: int) -> list[EvaluationSession]:
        """Lista las sesiones de todos los clientes de un entrenador.

        Parameters
        ----------
        trainer_id : int
            Entrenador.

        Returns
        -------
        list of EvaluationSession
            Sesiones de cualquier estado con sus resultados cargados, de
            la más reciente a la más antigua. Alimenta la vista de
            historial.
        """
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
    """Acceso a las rutinas generadas y sus ejercicios.

    Parameters
    ----------
    session_factory : callable
        Fábrica de sesiones de SQLAlchemy.
    """

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def create(self, client_id: int, name: str, session_id: int | None = None) -> Routine:
        """Crea una rutina vacía.

        Parameters
        ----------
        client_id : int
            Cliente destinatario.
        name : str
            Nombre de la rutina.
        session_id : int, optional
            Evaluación que la originó.

        Returns
        -------
        Routine
            La rutina creada, sin ejercicios.

        See Also
        --------
        save_plan : Alternativa que guarda rutina y ejercicios a la vez.
        """
        with self._session_factory() as s:
            routine = Routine(client_id=client_id, name=name, session_id=session_id)
            s.add(routine)
            s.commit()
            s.refresh(routine)
            return routine

    def add_exercise(
        self, routine_id: int, exercise_id: int, sets: int, reps: int, order_index: int,
    ) -> RoutineExercise:
        """Añade un ejercicio a una rutina existente.

        Parameters
        ----------
        routine_id : int
            Rutina de destino.
        exercise_id : int
            Ejercicio del catálogo.
        sets : int
            Series prescritas.
        reps : int
            Repeticiones por serie.
        order_index : int
            Posición dentro de la rutina.

        Returns
        -------
        RoutineExercise
            El ejercicio creado.
        """
        with self._session_factory() as s:
            re = RoutineExercise(
                routine_id=routine_id, exercise_id=exercise_id,
                sets=sets, reps=reps, order_index=order_index,
            )
            s.add(re)
            s.commit()
            s.refresh(re)
            return re

    def save_plan(
        self,
        client_id: int,
        name: str,
        plan,
        session_id: int | None = None,
        source_session_ids: list[int] | None = None,
    ) -> Routine:
        """Guarda un plan completo en una sola transacción.

        Parameters
        ----------
        client_id : int
            Cliente destinatario.
        name : str
            Nombre de la rutina.
        plan : myofit_pro.routine_engine.RoutinePlan
            Plan generado, con sus días, ejercicios y avisos.
        session_id : int, optional
            Evaluación principal que lo originó.
        source_session_ids : list of int, optional
            Todas las evaluaciones empleadas. Se almacenan separadas por
            comas porque una rutina puede abarcar varios músculos y cada
            músculo es una evaluación distinta.

        Returns
        -------
        Routine
            La rutina guardada, con su identificador asignado.

        Notes
        -----
        La escritura es atómica en lugar de ejercicio a ejercicio: una
        rutina guardada a medias resulta peor que ninguna, porque el
        entrenador vería dos días de un plan de cuatro sin ninguna
        indicación de que faltan los otros dos.

        Los ejercicios sin identificador de catálogo se omiten, ya que
        `RoutineExercise.exercise_id` no admite nulo.
        """
        with self._session_factory() as s:
            routine = Routine(
                client_id=client_id,
                name=name,
                session_id=session_id,
                goal=plan.goal,
                experience_level=plan.experience,
                days_per_week=plan.days_per_week,
                notes="\n".join(plan.warnings) or None,
                source_session_ids=(
                    ",".join(str(i) for i in source_session_ids)
                    if source_session_ids
                    else None
                ),
            )
            s.add(routine)
            s.flush()  # Asigna el identificador sin cerrar la transacción.

            order_index = 0
            for day in plan.days:
                for exercise in day.exercises:
                    if exercise.exercise_id is None:
                        continue
                    s.add(
                        RoutineExercise(
                            routine_id=routine.id,
                            exercise_id=exercise.exercise_id,
                            sets=exercise.prescription.sets,
                            reps=exercise.prescription.reps_min,
                            reps_max=exercise.prescription.reps_max,
                            rest_sec=exercise.prescription.rest_sec,
                            rir=exercise.prescription.rir,
                            load_pct_min=exercise.prescription.load_pct_min,
                            load_pct_max=exercise.prescription.load_pct_max,
                            day_index=day.index,
                            activation_pct=exercise.activation_pct,
                            source=exercise.source.value,
                            is_rotation=exercise.is_rotation,
                            order_index=order_index,
                        )
                    )
                    order_index += 1

            s.commit()
            s.refresh(routine)
            return routine

    def get_for_client(self, client_id: int) -> Routine | None:
        """Recupera la rutina más reciente de un cliente.

        Parameters
        ----------
        client_id : int
            Cliente.

        Returns
        -------
        Routine or None
            La última rutina con sus ejercicios cargados, o `None` si el
            cliente no tiene ninguna.
        """
        with self._session_factory() as s:
            stmt = (
                select(Routine)
                .where(Routine.client_id == client_id)
                .options(selectinload(Routine.exercises))
                .order_by(Routine.created_at.desc())
            )
            return s.scalars(stmt).first()

    def list_for_client(self, client_id: int) -> list[Routine]:
        """Lista todas las rutinas de un cliente.

        Parameters
        ----------
        client_id : int
            Cliente.

        Returns
        -------
        list of Routine
            Rutinas con sus ejercicios cargados, de la más reciente a la
            más antigua.

        Notes
        -----
        Las rutinas se conservan todas y no solo la vigente: cada una
        documenta lo que el cliente entrenó durante esas semanas, y su
        sucesión permite seguir la evolución de su programación.
        """
        with self._session_factory() as s:
            stmt = (
                select(Routine)
                .where(Routine.client_id == client_id)
                .options(selectinload(Routine.exercises))
                .order_by(Routine.created_at.desc())
            )
            return list(s.scalars(stmt))

    def replace_exercises(self, routine_id: int, items: list[dict]) -> None:
        """Sustituye por completo los ejercicios de una rutina.

        Parameters
        ----------
        routine_id : int
            Rutina a modificar. Si no existe, la llamada no hace nada.
        items : list of dict
            Ejercicios nuevos. Cada diccionario contiene los campos de
            `myofit_pro.database.models.RoutineExercise`: ``exercise_id``,
            ``sets``, ``reps``, ``reps_max``, ``rest_sec``, ``rir``,
            ``load_pct_min``, ``load_pct_max``, ``day_index``,
            ``activation_pct`` y ``source``. La posición dentro de la
            lista fija el orden.

        Notes
        -----
        Es la operación que persiste la edición manual del entrenador.
        Se reconstruye el conjunto completo en lugar de aplicar
        diferencias campo a campo porque una misma edición puede
        eliminar ejercicios, añadir otros y cambiar series a la vez; la
        reconstrucción es más simple y no puede quedar parcialmente
        aplicada.
        """
        with self._session_factory() as s:
            routine = s.get(Routine, routine_id)
            if routine is None:
                return
            for viejo in s.scalars(
                select(RoutineExercise).where(RoutineExercise.routine_id == routine_id)
            ):
                s.delete(viejo)
            s.flush()

            for order_index, item in enumerate(items):
                s.add(RoutineExercise(routine_id=routine_id, order_index=order_index, **item))
            s.commit()

    def get(self, routine_id: int) -> Routine | None:
        """Recupera una rutina por su identificador.

        Parameters
        ----------
        routine_id : int
            Rutina.

        Returns
        -------
        Routine or None
            La rutina con sus ejercicios cargados, o `None` si no
            existe.
        """
        with self._session_factory() as s:
            stmt = (
                select(Routine)
                .where(Routine.id == routine_id)
                .options(selectinload(Routine.exercises))
            )
            return s.scalars(stmt).first()

    def delete(self, routine_id: int) -> None:
        """Elimina una rutina y sus ejercicios.

        Parameters
        ----------
        routine_id : int
            Rutina a eliminar. Si no existe, la llamada no hace nada.
        """
        with self._session_factory() as s:
            routine = s.get(Routine, routine_id)
            if routine is None:
                return
            for item in s.scalars(
                select(RoutineExercise).where(RoutineExercise.routine_id == routine_id)
            ):
                s.delete(item)
            s.delete(routine)
            s.commit()

    def delete_for_client(self, client_id: int) -> int:
        """Elimina todas las rutinas de un cliente.

        Parameters
        ----------
        client_id : int
            Cliente.

        Returns
        -------
        int
            Rutinas eliminadas.
        """
        with self._session_factory() as s:
            routines = list(s.scalars(select(Routine).where(Routine.client_id == client_id)))
            if not routines:
                return 0

            routine_ids = [r.id for r in routines]
            for item in s.scalars(
                select(RoutineExercise).where(RoutineExercise.routine_id.in_(routine_ids))
            ):
                s.delete(item)
            for routine in routines:
                s.delete(routine)
            s.commit()
            return len(routines)