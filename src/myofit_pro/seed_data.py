"""
Script de datos semilla para MyoFit Pro.

Carga un catálogo SIMPLE de grupos musculares, músculos y ejercicios
-- no es un atlas kinesiológico exhaustivo. Se limita a músculos donde
tiene sentido colocar 2 sensores en 2 porciones del mismo músculo
(Filosofía A), con suficiente masa muscular para separar los
electrodos al menos 2-3 cm.

Idempotente: se puede correr varias veces sin duplicar datos (revisa
por nombre antes de insertar).

Uso:
    uv run python -m myofit_pro.seed_data
"""

from __future__ import annotations

from sqlalchemy import select

from myofit_pro.database.engine import get_engine
from myofit_pro.database.models import Exercise, Muscle, MuscleGroup

# ── Catálogo ────────────────────────────────────────────────────────
# Cada músculo trae su guía de colocación para 2 sensores (Sensor A /
# Sensor B) en dos porciones del mismo músculo.

CATALOG = [
    {
        "group": "Brazo",
        "muscles": [
            {
                "name": "Bíceps braquial",
                "guide": (
                    "Coloca el Sensor A en el vientre del bíceps (porción larga, "
                    "más hacia el lado externo del brazo). Coloca el Sensor B "
                    "2-3 cm más abajo, hacia la porción corta (lado interno). "
                    "Codo apoyado, palma hacia arriba."
                ),
                "exercises": ["Curl con barra", "Curl martillo", "Curl concentrado"],
            },
            {
                "name": "Tríceps braquial",
                "guide": (
                    "Sensor A en la cabeza larga (parte posterior-medial del "
                    "brazo). Sensor B en la cabeza lateral (parte posterior-"
                    "externa), separados 2-3 cm. Brazo extendido y relajado."
                ),
                "exercises": ["Press francés", "Extensión en polea", "Fondos en banco"],
            },
        ],
    },
    {
        "group": "Pierna",
        "muscles": [
            {
                "name": "Cuádriceps",
                "guide": (
                    "Sensor A sobre el vasto medial (parte interna, justo arriba "
                    "de la rodilla). Sensor B sobre el vasto lateral (parte "
                    "externa del muslo, a la misma altura). Rodilla semi-flexionada."
                ),
                "exercises": ["Sentadilla", "Extensión de pierna", "Zancada"],
            },
            {
                "name": "Isquiotibiales",
                "guide": (
                    "Sensor A en la parte media-posterior del muslo (bíceps "
                    "femoral). Sensor B 2-3 cm hacia el lado interno "
                    "(semitendinoso). Boca abajo, rodilla ligeramente flexionada."
                ),
                "exercises": ["Curl femoral", "Peso muerto rumano", "Puente de glúteo"],
            },
            {
                "name": "Gastrocnemio (pantorrilla)",
                "guide": (
                    "Sensor A en la cabeza medial (lado interno de la "
                    "pantorrilla, la parte más prominente). Sensor B en la "
                    "cabeza lateral (lado externo), a la misma altura."
                ),
                "exercises": ["Elevación de talones de pie", "Elevación de talones sentado"],
            },
        ],
    },
    {
        "group": "Espalda",
        "muscles": [
            {
                "name": "Trapecio",
                "guide": (
                    "Sensor A en la porción superior (entre cuello y hombro). "
                    "Sensor B en la porción media (entre las escápulas), "
                    "separados varios centímetros sobre la misma línea muscular."
                ),
                "exercises": ["Encogimiento de hombros", "Remo al mentón"],
            },
        ],
    },
    {
        "group": "Pecho",
        "muscles": [
            {
                "name": "Pectoral mayor",
                "guide": (
                    "Sensor A en la porción clavicular (parte superior del "
                    "pecho, cerca de la clavícula). Sensor B en la porción "
                    "esternal (parte media-baja del pecho), sobre la misma línea."
                ),
                "exercises": ["Press de banca", "Aperturas con mancuerna", "Flexiones"],
            },
        ],
    },
    {
        "group": "Hombro",
        "muscles": [
            {
                "name": "Deltoides",
                "guide": (
                    "Sensor A en la porción anterior (parte frontal del "
                    "hombro). Sensor B en la porción lateral/media (parte "
                    "externa del hombro), separados 3-4 cm."
                ),
                "exercises": ["Press militar", "Elevación lateral", "Elevación frontal"],
            },
        ],
    },
    {
        "group": "Abdomen",
        "muscles": [
            {
                "name": "Recto abdominal",
                "guide": (
                    "Sensor A a la altura del ombligo, 2-3 cm a un lado de la "
                    "línea media. Sensor B a la misma altura, del lado opuesto, "
                    "simétrico al Sensor A."
                ),
                "exercises": ["Crunch abdominal", "Plancha", "Elevación de piernas"],
            },
        ],
    },
]


def _get_or_create_group(session, name: str) -> MuscleGroup:
    existing = session.scalar(select(MuscleGroup).where(MuscleGroup.name == name))
    if existing:
        return existing
    group = MuscleGroup(name=name)
    session.add(group)
    session.flush()  # asigna el id sin cerrar la transacción
    return group


def _get_or_create_muscle(session, group_id: int, name: str, guide: str) -> Muscle:
    existing = session.scalar(
        select(Muscle).where(Muscle.group_id == group_id, Muscle.name == name)
    )
    if existing:
        # Actualizar la guía por si cambió en el catálogo
        existing.placement_guide = guide
        return existing
    muscle = Muscle(group_id=group_id, name=name, placement_guide=guide)
    session.add(muscle)
    session.flush()
    return muscle


def _get_or_create_exercise(session, muscle_id: int, name: str) -> Exercise:
    existing = session.scalar(
        select(Exercise).where(Exercise.muscle_id == muscle_id, Exercise.name == name)
    )
    if existing:
        return existing
    exercise = Exercise(muscle_id=muscle_id, name=name)
    session.add(exercise)
    session.flush()
    return exercise


def seed() -> None:
    engine = get_engine()

    groups_created = 0
    muscles_created = 0
    exercises_created = 0

    with engine.get_session() as session:
        for group_data in CATALOG:
            group = _get_or_create_group(session, group_data["group"])
            groups_created += 1

            for muscle_data in group_data["muscles"]:
                muscle = _get_or_create_muscle(
                    session, group.id, muscle_data["name"], muscle_data["guide"]
                )
                muscles_created += 1

                for exercise_name in muscle_data["exercises"]:
                    _get_or_create_exercise(session, muscle.id, exercise_name)
                    exercises_created += 1

        session.commit()

    print(f"Listo: {groups_created} grupos, {muscles_created} músculos, {exercises_created} ejercicios.")
    print("(Los números cuentan intentos, no inserciones nuevas -- correr de nuevo no duplica nada.)")


def main() -> None:
    seed()


if __name__ == "__main__":
    main()