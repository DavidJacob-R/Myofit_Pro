"""Generador de la base de datos de demostración.

Posición en el flujo
--------------------
Fuera del flujo normal de la aplicación. Construye una base de datos con
historial ya acumulado y arranca la interfaz contra ella, sin pasar por
la pantalla de acceso.

Motivo
------
Las vistas de progreso y de rutinas solo muestran contenido significativo
cuando existen varias evaluaciones del mismo músculo separadas en el
tiempo.

Aislamiento de los datos reales
-------------------------------
Escribe en ``~/.myofit_pro/demo.db`` y ``~/.myofit_pro/demo.duckdb``,
archivos distintos de los de producción. Las rutas por defecto de ambos
almacenes se redirigen antes de que nada los abra, y cada ejecución
elimina la base anterior y la reconstruye, de modo que el estado de
partida sea siempre el mismo.

Contenido generado
------------------
Tres clientes con objetivo, nivel de experiencia y disponibilidad
distintos —las tres variables de las que depende la prescripción—, cada
uno con varias evaluaciones separadas en el tiempo y las rutinas
correspondientes. Así la demostración muestra rutinas realmente
diferentes entre sí.

Uso
---
::

    uv run python -m myofit_pro.demo_data

La cuenta de demostración es ``demo@myofit.pro`` con contraseña
``demostracion``, aunque la aplicación entra directamente sin solicitar
credenciales.
"""

from __future__ import annotations

import datetime as dt
import random
import sys
from pathlib import Path

import numpy as np

DEMO_DB = Path.home() / ".myofit_pro" / "demo.db"

DEMO_DUCKDB = Path.home() / ".myofit_pro" / "demo.duckdb"

DEMO_EMAIL = "demo@myofit.pro"
DEMO_PASSWORD = "demostracion"


#: Clientes de ejemplo. Los perfiles difieren deliberadamente en
#: objetivo, nivel y disponibilidad, que son las tres variables de las
#: que depende la prescripción, para que la demostración produzca
#: rutinas distintas entre sí.
CLIENTES = (
    {
        "first_name": "Ana", "last_name": "López", "sex": "Femenino",
        "age_years": 28, "height_cm": 165.0, "weight_kg": 60.0,
        "neck_cm": 31.0, "waist_cm": 70.0, "hip_cm": 95.0,
        "goal": "Hipertrofia", "experience_level": "Intermedio", "days_per_week": 4,
        "notes": "Sin lesiones. Entrena por la mañana.",
        "musculos": (
            "Pectoral mayor", "Dorsal ancho", "Bíceps braquial",
            "Tríceps braquial", "Cuádriceps",
        ),
        "evaluaciones": 3,
    },
    {
        "first_name": "Diego", "last_name": "Ramírez", "sex": "Masculino",
        "age_years": 35, "height_cm": 178.0, "weight_kg": 84.0,
        "neck_cm": 39.0, "waist_cm": 92.0,
        "goal": "Fuerza", "experience_level": "Avanzado", "days_per_week": 5,
        "notes": "Molestia antigua en hombro derecho.",
        "musculos": (
            "Pectoral mayor", "Deltoides", "Tríceps braquial", "Dorsal ancho",
        ),
        "evaluaciones": 2,
    },
    {
        "first_name": "Sofía", "last_name": "Hernández", "sex": "Femenino",
        "age_years": 42, "height_cm": 160.0, "weight_kg": 72.0,
        "goal": "Definición", "experience_level": "Principiante", "days_per_week": 3,
        "notes": "Empieza ahora. Cuidar la técnica.",
        "musculos": ("Recto abdominal", "Cuádriceps"),
        "evaluaciones": 1,
    },
)


def _reset_files() -> None:
    """Elimina las bases de demostración anteriores y sus archivos auxiliares."""
    DEMO_DB.parent.mkdir(parents=True, exist_ok=True)
    for path in (DEMO_DB, DEMO_DUCKDB, Path(f"{DEMO_DUCKDB}.wal")):
        if path.exists():
            path.unlink()


def _signal(rng: random.Random, fatiga: bool) -> np.ndarray:
    """Genera la señal sintética de una serie.
    """
    generador = np.random.default_rng(rng.randint(0, 10_000))
    frecuencias = (130, 115, 100, 85, 70, 55) if fatiga else (100, 98, 101, 99, 100, 97)
    tramos = []
    for hz in frecuencias:
        t = np.arange(500) / 1000.0
        tramos.append(np.sin(2 * np.pi * hz * t) * 210 + 45 * generador.normal(size=500))
    return np.concatenate(tramos)


def build() -> object:
    """Construye la base de demostración completa.

    Redirige ambos almacenes a los archivos de demostración, siembra el
    catálogo, crea la cuenta y los clientes, y genera para cada uno sus
    evaluaciones y rutinas con fechas retrospectivas.

    -----
    Las importaciones son diferidas y las rutas por defecto se
    reasignan antes de que ningún módulo abra una conexión. De otro
    modo, el primer acceso crearía los almacenes de producción.
    """
    import myofit_pro.database.engine as engine_mod
    import myofit_pro.database.duckdb_store as duckdb_mod

    _reset_files()

    engine_mod.DEFAULT_DB_PATH = DEMO_DB
    engine_mod._default_engine = None
    duckdb_mod.DEFAULT_DUCKDB_PATH = DEMO_DUCKDB
    duckdb_mod._default_store = None

    from myofit_pro.database.engine import get_engine
    from myofit_pro import seed_data

    get_engine(DEMO_DB)
    seed_data.seed()

    from myofit_pro.database import (
        CalibrationRepository, ClientRepository, EvaluationRepository,
        ExerciseRepository, MuscleRepository, RoutineRepository, TrainerRepository,
    )
    from myofit_pro.database.duckdb_store import get_burst_store
    from myofit_pro.database.models import EvaluationSession
    from myofit_pro.routine_engine import build_plan

    engine = get_engine()
    trainers = TrainerRepository(engine.get_session)
    clients = ClientRepository(engine.get_session)
    muscles = MuscleRepository(engine.get_session)
    exercises = ExerciseRepository(engine.get_session)
    calibs = CalibrationRepository(engine.get_session)
    evals = EvaluationRepository(engine.get_session)
    routines = RoutineRepository(engine.get_session)
    bursts = get_burst_store(DEMO_DUCKDB)

    trainer = trainers.register("David Flores", DEMO_EMAIL, DEMO_PASSWORD)
    rng = random.Random(7)
    hoy = dt.datetime.now()
    por_nombre = {m.name: m for m in muscles.list_muscles()}

    for perfil in CLIENTES:
        datos = {k: v for k, v in perfil.items() if k not in ("musculos", "evaluaciones")}
        nombre = f"{perfil['first_name']} {perfil['last_name']}"
        cliente = clients.create(trainer_id=trainer.id, full_name=nombre, **datos)

        sesiones_por_musculo: dict[int, list[int]] = {}

        for nombre_musculo in perfil["musculos"]:
            muscle = por_nombre.get(nombre_musculo)
            if muscle is None:
                continue
            # Cinco medidos por músculo: la rutina usa dos o tres, así
            # que quedan alternativas para que el sorteo de rotación
            # tenga entre qué elegir. Es también el caso realista — se
            # mide una batería más amplia de la que se prescribe.
            catalogo = exercises.list_for_muscle(muscle.id)[:5]

            # Cada ejercicio tiene su nivel propio en esta persona, que
            # es lo que la batería debe descubrir.
            base = {e.id: rng.uniform(44.0, 76.0) for e in catalogo}
            carga = {e.id: float(rng.randrange(8, 40, 2)) for e in catalogo}
            perimetro = rng.uniform(28.0, 42.0)

            # Cómo evoluciona cada ejercicio entre evaluaciones. Se
            # reparten los cuatro casos a propósito para que la pantalla
            # de progreso enseñe los distintos veredictos y no cinco
            # filas verdes iguales. El caso "eficiente" es el importante:
            # mismo peso con menos activación es progreso, aunque el
            # número baje.
            tipos = ("mas_peso", "eficiente", "recluta", "sin_cambio")
            evolucion = {
                e.id: tipos[i % len(tipos)]
                for i, e in enumerate(rng.sample(catalogo, len(catalogo)))
            }

            for vuelta in range(perfil["evaluaciones"]):
                # De la más vieja a la más reciente, cada 4 semanas.
                cuando = hoy - dt.timedelta(days=28 * (perfil["evaluaciones"] - 1 - vuelta))

                calib = calibs.save(
                    cliente.id, muscle.id,
                    mvc_value_uv=rng.uniform(820, 980),
                    mvc_channel_a_uv=rng.uniform(800, 960),
                    mvc_channel_b_uv=rng.uniform(800, 960),
                )
                sesion = evals.start_session(
                    cliente.id, muscle.id, perfil["goal"], calib.id
                )

                burst_id = None
                try:
                    señal = _signal(rng, fatiga=vuelta == perfil["evaluaciones"] - 1)
                    burst_id = bursts.save_burst(
                        client_id=cliente.id, session_id=sesion.id, muscle_id=muscle.id,
                        sensor_index=0, sample_rate_hz=1000.0,
                        times=np.arange(len(señal)) / 1000.0,
                        micro_volts=señal, filtered=señal,
                        envelope=np.abs(señal), rms=np.abs(señal),
                    )
                except Exception:
                    burst_id = None

                promedios = []
                for ejercicio in catalogo:
                    tipo = evolucion[ejercicio.id]
                    kilos = carga[ejercicio.id]
                    nivel = base[ejercicio.id]

                    if tipo == "mas_peso":
                        kilos += 2.0 * vuelta
                        nivel -= 1.5 * vuelta
                    elif tipo == "eficiente":
                        nivel -= 16.0 * vuelta
                    elif tipo == "recluta":
                        nivel += 16.0 * vuelta
                    else:
                        nivel += rng.uniform(-0.8, 0.8) * vuelta

                    for _ in range(2): 
                        valor = max(5.0, min(100.0, nivel + rng.uniform(-2.5, 2.5)))
                        promedios.append(valor)
                        resultado = evals.add_exercise_result(
                            sesion.id, ejercicio.id,
                            series_count=rng.randint(8, 12),
                            avg_activation_pct=valor,
                            peak_activation_pct=min(100.0, valor + rng.uniform(4, 10)),
                            load_kg=kilos,
                        )
                        evals.add_reading(
                            exercise_result_id=resultado.id, series_number=1,
                            channel_a_mv=0.9, channel_b_mv=0.85,
                            activation_a_pct=valor + rng.uniform(1, 6),
                            activation_b_pct=max(1.0, valor - rng.uniform(1, 6)),
                            duration_sec=rng.uniform(26, 38),
                            burst_id=burst_id,
                        )

                evals.set_session_measurements(
                    sesion.id,
                    circumference_cm=round(perimetro + 0.7 * vuelta, 1),
                    repeatability_cv=rng.uniform(0.03, 0.05),
                )
                evals.finish_session(sesion.id, sum(promedios) / len(promedios))

                with engine.get_session() as s:
                    obj = s.get(EvaluationSession, sesion.id)
                    obj.started_at = cuando
                    s.commit()

                sesiones_por_musculo.setdefault(muscle.id, []).append(sesion.id)

        # Una rutina por cada evaluación completada, para que la lista de
        # rutinas tenga varias fechas y se pueda comparar entre ellas.
        from myofit_pro.gui.app_state import AppState

        estado = AppState(current_trainer=trainer)
        vueltas = perfil["evaluaciones"]
        for vuelta in range(vueltas):
            candidatos = estado.routine_candidates(cliente.id)
            if not candidatos:
                continue
            plan = build_plan(
                goal=cliente.goal,
                experience=cliente.experience_level,
                days_per_week=cliente.days_per_week,
                candidates=candidatos,
            )
            if plan.is_empty:
                continue
            rutina = routines.save_plan(
                client_id=cliente.id,
                name=f"Rutina de {plan.goal.lower()} — {plan.days_per_week} días",
                plan=plan,
                source_session_ids=estado.sessions_behind_routine(cliente.id, plan),
            )
            with engine.get_session() as s:
                from myofit_pro.database.models import Routine

                obj = s.get(Routine, rutina.id)
                obj.created_at = hoy - dt.timedelta(days=28 * (vueltas - 1 - vuelta) - 1)
                s.commit()
        estado.shutdown()

    return trainer


def main() -> int:
    """Construye la base de demostración y abre la aplicación contra ella.
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("MyoFit Pro — demostración")

    from myofit_pro.gui.theme import apply_app_theme

    apply_app_theme()

    print("Construyendo la base de demostración...")
    trainer = build()

    from myofit_pro.gui.main_window import MainWindow

    window = MainWindow(trainer)
    window.setWindowTitle("MyoFit Pro — DEMOSTRACIÓN (datos de ejemplo)")
    window.show()

    print(f"\nBase de demostración: {DEMO_DB}")
    print(f"Entrenador: {DEMO_EMAIL} / {DEMO_PASSWORD}")
    print("\nQué ver:")
    print("  Mis clientes  -> Ana López -> Ver progreso   (tres evaluaciones)")
    print("  Rutinas       -> Ana López                   (tres rutinas por fecha)")
    print("  Historial sEMG-> cualquier evaluación        (ranking, balance y fatiga)")
    print("\nTus datos reales no se tocaron.\n")

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
