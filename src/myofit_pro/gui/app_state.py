"""
Estado global compartido de la sesión de la app — equivalente a las
propiedades públicas que vivían en MainShell.xaml.cs (ActiveClient,
ActiveMuscle, ActiveMvc, etc). Todas las vistas reciben la misma
instancia de AppState al construirse.
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

# Fracción del MVC de cada canal a partir de la cual se considera que
# empezó una repetición.
#
# Un umbral fijo en µV no funciona: medido contra hardware real, el mismo
# gesto produjo 978 µV en un sensor y 1691 µV en el otro, y con un umbral
# único de 100 µV un canal contó 4 repeticiones y el otro 7. Normalizar
# contra el MVC de cada canal absorbe esas diferencias de amplitud, que
# vienen del músculo, de la colocación del electrodo y de la calidad del
# contacto.
REP_THRESHOLD_MVC_FRACTION = 0.20

# Umbral de respaldo mientras no hay calibración (pantalla de prueba de
# sensores, o una sesión que todavía no llega al Paso 4).
DEFAULT_TRIGGER_UV = 100.0


@dataclass
class AppState:
    """Contenedor único de: sesión de usuario, repositorios y servicio de sensores."""

    current_trainer: Trainer

    # Estado del wizard de evaluación
    active_client: Client | None = None
    active_muscle: Muscle | None = None
    active_goal: str = "Hipertrofia"
    active_session_id: int | None = None
    active_mvc: MvcCalibration | None = None

    def __post_init__(self) -> None:
        engine = get_engine()
        self.trainer_repo = TrainerRepository(engine.get_session)
        self.client_repo = ClientRepository(engine.get_session)
        self.muscle_repo = MuscleRepository(engine.get_session)
        self.exercise_repo = ExerciseRepository(engine.get_session)
        self.calibration_repo = CalibrationRepository(engine.get_session)
        self.evaluation_repo = EvaluationRepository(engine.get_session)
        self.routine_repo = RoutineRepository(engine.get_session)
        self.burst_store = get_burst_store()

        # Servicio de sensores — una sola instancia para toda la app,
        # igual que en MainShell.xaml.cs
        self.sensors = MyoBlueService(sensors_in_use=2)
        self.sensors.notch_hz = 60.0  # México/USA; cambiar a 50.0 para Europa
        for ch in self.sensors.channels:
            ch.bandpass_enabled = True
            # El config.ini original de elemyo trae el notch DESACTIVADO
            # por defecto (BandStopFilter = False) — se respeta ese valor
            # aquí. En un ambiente con mucho ruido eléctrico de 60Hz puede
            # convenir activarlo (ch.notch_enabled = True); queda como
            # ajuste pendiente de exponer en una futura pantalla de
            # configuración, igual que el config.ini lo hacía en el original.
            ch.notch_enabled = False
            ch.trigger_threshold_uv = DEFAULT_TRIGGER_UV

    def set_eval_context(self, client: Client, muscle: Muscle, goal: str) -> None:
        self.active_client = client
        self.active_muscle = muscle
        self.active_goal = goal

    def set_active_mvc(self, calibration: MvcCalibration | None) -> None:
        """
        Fija la calibración activa y reajusta el umbral de detección de
        repeticiones de cada canal a partir de ella. Usar siempre esto en
        vez de asignar `active_mvc` directamente, para que el umbral no se
        quede con el valor de la calibración anterior.
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

    def delete_evaluation(self, session_id: int) -> None:
        """
        Elimina una evaluación por completo: su registro y resultados en
        SQLite, y la señal cruda que le corresponde en DuckDB.

        Vive en AppState y no en un repositorio porque es la única capa
        que tiene acceso a las dos bases a la vez. Si la sesión que se
        borra es la que está abierta en el wizard, también se limpia el
        contexto activo, para no dejar al wizard trabajando contra una
        evaluación que ya no existe.
        """
        self.burst_store.delete_bursts_for_session(session_id)
        self.evaluation_repo.delete_session(session_id)

        if self.active_session_id == session_id:
            self.active_session_id = None
            self.set_active_mvc(None)

    def delete_client(self, client_id: int) -> None:
        """
        Elimina un cliente con todo lo suyo.

        Sus evaluaciones se borran una por una con `delete_evaluation`
        para que también se vayan las señales de DuckDB. Antes el borrado
        solo quitaba la fila del cliente y dejaba las evaluaciones
        apuntando a un cliente inexistente, aunque el mensaje de
        confirmación ya decía que se borraban.
        """
        for session in self.evaluation_repo.list_for_client(client_id):
            self.delete_evaluation(session.id)

        self.client_repo.delete(client_id)

        if self.active_client is not None and self.active_client.id == client_id:
            self.active_client = None
            self.active_muscle = None
            self.set_active_mvc(None)

    def shutdown(self) -> None:
        self.sensors.close()
