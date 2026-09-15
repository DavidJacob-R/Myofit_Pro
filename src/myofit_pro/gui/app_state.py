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
            ch.trigger_threshold_uv = 100.0

    def set_eval_context(self, client: Client, muscle: Muscle, goal: str) -> None:
        self.active_client = client
        self.active_muscle = muscle
        self.active_goal = goal

    def shutdown(self) -> None:
        self.sensors.close()
