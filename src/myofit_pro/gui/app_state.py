"""Estado compartido de la sesión de la aplicación.

Posición en el flujo
--------------------
Se construye una vez al autenticarse el entrenador, en
`myofit_pro.gui.main_window.MainWindow`, y se entrega a todas las vistas.
Es el punto de acceso a los repositorios, al servicio de sensores y al
contexto de la evaluación en curso: ninguna vista abre sesiones de base
de datos ni instancia el servicio por su cuenta.

Responsabilidades
-----------------
Además de agrupar dependencias, `AppState` alberga las operaciones que
combinan varios repositorios o ambos almacenes de datos, y que por tanto
no pertenecen a ninguno de ellos en particular:

`AppState.routine_candidates`
    Combina el ranking medido con el catálogo para alimentar a
    `myofit_pro.routine_engine.build_plan`.
`AppState.session_snapshots` y `AppState.progress_for_muscle`
    Reducen las evaluaciones a lo que consume `myofit_pro.progress`.
`AppState.delete_evaluation` y `AppState.delete_client`
    Borrado coordinado entre SQLite y DuckDB.

Umbral de detección de repeticiones
-----------------------------------
El umbral se expresa como fracción de la contracción voluntaria máxima
de cada canal, no en microvoltios absolutos. Medido con este hardware, un
mismo gesto produjo 978 µV en un sensor y 1691 µV en el otro; con un
umbral común de 100 µV un canal contaba cuatro repeticiones y el otro
siete. Normalizar contra la calibración de cada canal absorbe esas
diferencias, que proceden del músculo, de la colocación del electrodo y
de la calidad del contacto.

See Also
--------
myofit_pro.database.repositories : Repositorios que agrupa.
myofit_pro.sensors.service : Servicio de captura que instancia.
"""

from __future__ import annotations

from dataclasses import dataclass

from myofit_pro.database import (
    CalibrationRepository,
    ClientRepository,
    EvaluationRepository,
    ExerciseRepository,
    MuscleRepository,
    RoutineRepository,
    TrainerRepository,
    get_engine,
)
from myofit_pro.database.duckdb_store import get_burst_store
from myofit_pro.database.models import Client, Muscle, MvcCalibration, Trainer
from myofit_pro.sensors import MyoBlueService

#: Fracción de la contracción voluntaria máxima de cada canal a partir de
#: la cual se considera iniciada una repetición.
REP_THRESHOLD_MVC_FRACTION = 0.20

#: Umbral en microvoltios aplicado mientras no hay calibración: la
#: pantalla de prueba de sensores, o una evaluación que aún no ha llegado
#: al paso de calibración.
DEFAULT_TRIGGER_UV = 100.0


@dataclass
class AppState:
    """Dependencias y contexto compartidos por todas las vistas.

    Attributes
    ----------
    current_trainer : myofit_pro.database.models.Trainer
        Entrenador autenticado.
    active_client : myofit_pro.database.models.Client or None
        Cliente de la evaluación en curso.
    active_muscle : myofit_pro.database.models.Muscle or None
        Músculo de la evaluación en curso.
    active_goal : str
        Objetivo de la evaluación en curso.
    active_session_id : int or None
        Sesión de evaluación abierta.
    active_mvc : myofit_pro.database.models.MvcCalibration or None
        Calibración de referencia. Debe asignarse mediante
        `set_active_mvc` y no directamente.
    trainer_repo, client_repo, muscle_repo, exercise_repo, calibration_repo, evaluation_repo, routine_repo
        Repositorios de `myofit_pro.database.repositories`.
    burst_store : myofit_pro.database.duckdb_store.EmgBurstStore
        Almacén de las series temporales.
    sensors : myofit_pro.sensors.service.MyoBlueService
        Servicio de captura, único para toda la aplicación.
    """

    current_trainer: Trainer

    active_client: Client | None = None
    active_muscle: Muscle | None = None
    active_goal: str = "Hipertrofia"
    active_session_id: int | None = None
    active_mvc: MvcCalibration | None = None

    def __post_init__(self) -> None:
        """Instancia los repositorios y el servicio de sensores.

        Notes
        -----
        La frecuencia de red se fija en 60 Hz, que corresponde a México y
        Estados Unidos; en Europa debe ser 50 Hz. El rechazo de banda
        queda desactivado por defecto, replicando la configuración de
        fábrica del equipo, y conviene activarlo solo en entornos con
        interferencia eléctrica apreciable. Ambos ajustes están
        pendientes de exponerse en una pantalla de configuración.
        """
        engine = get_engine()
        self.trainer_repo = TrainerRepository(engine.get_session)
        self.client_repo = ClientRepository(engine.get_session)
        self.muscle_repo = MuscleRepository(engine.get_session)
        self.exercise_repo = ExerciseRepository(engine.get_session)
        self.calibration_repo = CalibrationRepository(engine.get_session)
        self.evaluation_repo = EvaluationRepository(engine.get_session)
        self.routine_repo = RoutineRepository(engine.get_session)
        self.burst_store = get_burst_store()

        self.sensors = MyoBlueService(sensors_in_use=2)
        self.sensors.notch_hz = 60.0
        for ch in self.sensors.channels:
            ch.bandpass_enabled = True
            ch.notch_enabled = False
            ch.trigger_threshold_uv = DEFAULT_TRIGGER_UV

    def set_eval_context(self, client: Client, muscle: Muscle, goal: str) -> None:
        """Fija el contexto de una nueva evaluación.

        Parameters
        ----------
        client : myofit_pro.database.models.Client
            Cliente a evaluar.
        muscle : myofit_pro.database.models.Muscle
            Músculo a evaluar.
        goal : str
            Objetivo aplicable a la sesión.
        """
        self.active_client = client
        self.active_muscle = muscle
        self.active_goal = goal

    def set_active_mvc(self, calibration: MvcCalibration | None) -> None:
        """Fija la calibración activa y recalcula los umbrales de detección.

        Parameters
        ----------
        calibration : myofit_pro.database.models.MvcCalibration or None
            Calibración de referencia. Con `None`, los canales vuelven a
            `DEFAULT_TRIGGER_UV`.

        Notes
        -----
        Debe emplearse siempre en lugar de asignar `active_mvc`
        directamente: de otro modo los umbrales conservarían los valores
        de la calibración anterior y el recuento de repeticiones sería
        incorrecto.
        """
        self.active_mvc = calibration
        per_channel = (
            (calibration.mvc_channel_a_uv, calibration.mvc_channel_b_uv)
            if calibration
            else ()
        )
        for index, channel in enumerate(self.sensors.channels[: self.sensors.sensors_in_use]):
            mvc_uv = per_channel[index] if index < len(per_channel) else None
            channel.trigger_threshold_uv = (
                mvc_uv * REP_THRESHOLD_MVC_FRACTION
                if mvc_uv and mvc_uv > 0
                else DEFAULT_TRIGGER_UV
            )

    def routine_candidates(self, client_id: int) -> list:
        """Reúne los candidatos por músculo para generar una rutina.

        Parameters
        ----------
        client_id : int
            Cliente.

        Returns
        -------
        list of myofit_pro.routine_engine.MuscleCandidates
            Un elemento por músculo con ejercicios disponibles, ordenados
            de más a menos ejercicios medidos, de modo que el músculo
            mejor conocido encabece la rutina.

        Notes
        -----
        Combina el ranking de activación procedente de las evaluaciones
        con el catálogo de ejercicios de cada músculo, que solo se emplea
        como relleno. La operación reside aquí porque involucra tres
        repositorios y ninguno de ellos es su propietario natural.

        Entran todos los músculos del catálogo y no solo los evaluados:
        una rutina de gimnasio necesita un día de empuje completo aunque
        únicamente se haya medido el pectoral, y los ejercicios que
        faltan se marcan como procedentes del catálogo.
        """
        from myofit_pro.routine_engine import (
            CatalogExercise,
            MeasuredExercise,
            MuscleCandidates,
        )

        rows = self.evaluation_repo.activation_by_exercise(client_id)

        measured_by_muscle: dict[int, list] = {}
        for muscle_id, exercise_id, mean, count in rows:
            exercise = self.exercise_repo.get(exercise_id)
            if exercise is None:
                continue
            measured_by_muscle.setdefault(muscle_id, []).append(
                MeasuredExercise(
                    exercise_id=exercise_id,
                    name=exercise.name,
                    activation_pct=mean,
                    measurements=count,
                    is_compound=bool(exercise.is_compound),
                )
            )

        candidates = []
        for muscle in self.muscle_repo.list_muscles():
            catalog = self.exercise_repo.list_for_muscle(muscle.id)
            if not catalog and muscle.id not in measured_by_muscle:
                continue
            candidates.append(
                MuscleCandidates(
                    muscle_id=muscle.id,
                    muscle_name=muscle.name,
                    measured=tuple(measured_by_muscle.get(muscle.id, ())),
                    catalog=tuple(
                        CatalogExercise(e.id, e.name, bool(e.is_compound))
                        for e in catalog
                    ),
                )
            )

        candidates.sort(key=lambda c: (-len(c.measured), c.muscle_name))
        return candidates

    # ── Progreso ─────────────────────────────────────────────────────

    def session_snapshots(self, client_id: int, muscle_id: int) -> list:
        """Reduce las evaluaciones de un músculo a instantáneas comparables.

        Parameters
        ----------
        client_id : int
            Cliente.
        muscle_id : int
            Músculo.

        Returns
        -------
        list of myofit_pro.progress.SessionSnapshot
            Una instantánea por sesión completada, de la más reciente a
            la más antigua.

        Notes
        -----
        Las series de un mismo ejercicio se promedian antes de comparar:
        una serie aislada puede resultar alta por azar, mientras que el
        promedio refleja el comportamiento del ejercicio en esa sesión.

        El puesto en el ranking se calcula aquí y no se persiste, porque
        depende de qué ejercicios se midieron ese día: es una propiedad
        de la sesión, no del ejercicio.
        """
        from myofit_pro.progress import ExerciseSnapshot, SessionSnapshot

        muscle = self.muscle_repo.get(muscle_id)
        sessions = self.evaluation_repo.list_completed_for_client(client_id, muscle_id)

        snapshots = []
        for session in sessions:
            por_ejercicio: dict[int, list] = {}
            for result in session.results:
                if result.exercise_id is None:
                    continue
                por_ejercicio.setdefault(result.exercise_id, []).append(result)

            ejercicios = []
            for exercise_id, resultados in por_ejercicio.items():
                exercise = self.exercise_repo.get(exercise_id)
                if exercise is None:
                    continue
                cargas = [r.load_kg for r in resultados if r.load_kg]
                ejercicios.append(
                    ExerciseSnapshot(
                        exercise_id=exercise_id,
                        name=exercise.name,
                        activation_pct=sum(r.avg_activation_pct for r in resultados)
                        / len(resultados),
                        measurements=len(resultados),
                        load_kg=sum(cargas) / len(cargas) if cargas else None,
                    )
                )

            ejercicios.sort(key=lambda e: e.activation_pct, reverse=True)
            ejercicios = [
                ExerciseSnapshot(
                    exercise_id=e.exercise_id,
                    name=e.name,
                    activation_pct=e.activation_pct,
                    measurements=e.measurements,
                    load_kg=e.load_kg,
                    rank=posicion,
                )
                for posicion, e in enumerate(ejercicios, start=1)
            ]

            lecturas = [r for result in session.results for r in result.readings]
            balance = (
                sum(abs(r.activation_a_pct - r.activation_b_pct) for r in lecturas)
                / len(lecturas)
                if lecturas
                else None
            )

            snapshots.append(
                SessionSnapshot(
                    session_id=session.id,
                    date=session.started_at,
                    muscle_id=session.muscle_id,
                    muscle_name=muscle.name if muscle else "—",
                    goal=session.goal,
                    exercises=tuple(ejercicios),
                    circumference_cm=session.circumference_cm,
                    repeatability_cv=session.repeatability_cv,
                    balance_gap=balance,
                    overall_score=session.overall_score,
                )
            )

        return snapshots

    def sessions_behind_routine(self, client_id: int, plan) -> list[int]:
        """Identifica las evaluaciones que originaron una rutina.

        Parameters
        ----------
        client_id : int
            Cliente.
        plan : myofit_pro.routine_engine.RoutinePlan
            Plan generado.

        Returns
        -------
        list of int
            Identificadores de sesión, ordenados. Por cada músculo
            presente en el plan se toma su evaluación completada más
            reciente, que es de donde procede su ranking.

        Notes
        -----
        Se persisten en
        `myofit_pro.database.models.Routine.source_session_ids` para
        poder indicar en pantalla de qué lectura procede cada ejercicio.
        """
        musculos = {e.muscle_id for e in plan.unique_exercises}
        ids = []
        for muscle_id in musculos:
            sesiones = self.evaluation_repo.list_completed_for_client(client_id, muscle_id)
            if sesiones:
                ids.append(sesiones[0].id)
        return sorted(ids)

    def progress_for_muscle(self, client_id: int, muscle_id: int):
        """Compara las dos evaluaciones más recientes de un músculo.

        Parameters
        ----------
        client_id : int
            Cliente.
        muscle_id : int
            Músculo.

        Returns
        -------
        tuple or None
            Par ``(informe, sesiones)`` donde el informe es un
            `myofit_pro.progress.ProgressReport` y las sesiones van de la
            más antigua a la más reciente, para representar la
            tendencia. `None` si el músculo carece de evaluaciones
            completadas.

        Notes
        -----
        El coeficiente de variación se resuelve con
        `myofit_pro.progress.resolve_cv`, que prefiere la repetibilidad
        medida en el propio cliente y recurre al valor de referencia solo
        si no la hay.
        """
        from myofit_pro.progress import compare, resolve_cv

        snapshots = self.session_snapshots(client_id, muscle_id)
        if not snapshots:
            return None

        # El repositorio devuelve de la más reciente a la más antigua; la
        # tendencia necesita el orden inverso.
        ordenadas = list(reversed(snapshots))
        cv, medido = resolve_cv(ordenadas)

        actual = ordenadas[-1]
        anterior = ordenadas[-2] if len(ordenadas) > 1 else None
        return compare(anterior, actual, cv=cv, cv_is_measured=medido), ordenadas

    def muscles_with_history(self, client_id: int) -> list:
        """Lista los músculos evaluados de un cliente.

        Parameters
        ----------
        client_id : int
            Cliente.

        Returns
        -------
        list of tuple
            Pares ``(músculo, número de evaluaciones)``, del músculo con
            más evaluaciones al que menos tiene. Es el índice de la
            pantalla de progreso.
        """
        conteo: dict[int, int] = {}
        for session in self.evaluation_repo.list_completed_for_client(client_id):
            conteo[session.muscle_id] = conteo.get(session.muscle_id, 0) + 1

        musculos = []
        for muscle_id, veces in conteo.items():
            muscle = self.muscle_repo.get(muscle_id)
            if muscle is not None:
                musculos.append((muscle, veces))

        musculos.sort(key=lambda item: (-item[1], item[0].name))
        return musculos

    def delete_evaluation(self, session_id: int) -> None:
        """Elimina una evaluación de ambos almacenes.

        Parameters
        ----------
        session_id : int
            Sesión a eliminar.

        Notes
        -----
        Reside aquí y no en un repositorio porque es la única capa con
        acceso simultáneo a SQLite y a DuckDB.

        Si la sesión eliminada es la que el asistente tiene abierta, se
        limpia también el contexto activo, para no dejarlo trabajando
        contra una evaluación inexistente.
        """
        self.burst_store.delete_bursts_for_session(session_id)
        self.evaluation_repo.delete_session(session_id)

        if self.active_session_id == session_id:
            self.active_session_id = None
            self.set_active_mvc(None)

    def delete_client(self, client_id: int) -> None:
        """Elimina un cliente y todos sus datos.

        Parameters
        ----------
        client_id : int
            Cliente a eliminar.

        Notes
        -----
        Las evaluaciones se eliminan una a una mediante
        `delete_evaluation`, de modo que sus series temporales
        desaparezcan también del almacén DuckDB.
        """
        for session in self.evaluation_repo.list_for_client(client_id):
            self.delete_evaluation(session.id)

        self.client_repo.delete(client_id)

        if self.active_client is not None and self.active_client.id == client_id:
            self.active_client = None
            self.active_muscle = None
            self.set_active_mvc(None)

    def shutdown(self) -> None:
        """Libera el servicio de sensores al cerrar la sesión."""
        self.sensors.close()
