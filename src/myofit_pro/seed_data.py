"""Siembra del catálogo de músculos y ejercicios.

Posición en el flujo
--------------------
Se ejecuta antes del primer uso de la aplicación y cada vez que el
catálogo cambia. Escribe las tablas ``muscle_groups``, ``muscles`` y
``exercises``, que el resto de la aplicación trata como de solo lectura.

Alcance del catálogo
--------------------
No es un atlas kinesiológico. Se limita a los músculos que cumplen la
condición de medida del equipo: masa suficiente para separar los dos
sensores al menos 2 o 3 centímetros sobre porciones distintas del mismo
músculo. Cada músculo incorpora su guía de colocación de electrodos, que
la aplicación muestra durante la evaluación.

Número de ejercicios por músculo
--------------------------------
Cada músculo lleva seis. La batería de tamizaje sirve para ordenar
ejercicios entre sí, y con dos o tres el orden no descarta nada; la
simulación de `myofit_pro.ml.within_subject` asume seis.

Idempotencia
------------
La operación puede repetirse sin duplicar datos: cada elemento se busca
por nombre antes de insertarse, y los existentes se actualizan con los
valores del catálogo. Así, una guía de colocación corregida o una
reclasificación de ejercicio compuesto llegan a las bases de datos ya
creadas.

Poda de huérfanos
-----------------
`_prune_orphans` elimina los ejercicios que ya no figuran en el catálogo,
lo que evita que una reorganización deje copias duplicadas bajo músculos
distintos. La poda respeta todo lo que esté referenciado por un resultado
de evaluación o por una rutina: perder una medición real por reordenar
una lista sería mucho más grave que conservar una fila sobrante.

Uso
---
::

    uv run python -m myofit_pro.seed_data

See Also
--------
myofit_pro.database.models : Tablas que se siembran.
myofit_pro.routine_engine.MUSCLE_SIZES : Clasificación que debe cubrir
    todos los músculos aquí definidos.
myofit_pro.demo_data : Generador de datos de demostración.
"""

from __future__ import annotations

from sqlalchemy import select

from myofit_pro.database.engine import get_engine
from myofit_pro.database.models import (
    Exercise,
    ExerciseResult,
    Muscle,
    MuscleGroup,
    RoutineExercise,
)

#: Catálogo completo, como lista de grupos. Cada grupo contiene sus
#: músculos, y cada músculo su guía de colocación de los dos sensores y
#: sus ejercicios como pares ``(nombre, es compuesto)``.
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
                "exercises": [
                    ("Curl con barra", False),
                    ("Curl con mancuernas", False),
                    ("Curl martillo", False),
                    ("Curl en predicador", False),
                    ("Curl en polea baja", False),
                    ("Curl concentrado", False),
                ],
            },
            {
                "name": "Tríceps braquial",
                "guide": (
                    "Sensor A en la cabeza larga (parte posterior-medial del "
                    "brazo). Sensor B en la cabeza lateral (parte posterior-"
                    "externa), separados 2-3 cm. Brazo extendido y relajado."
                ),
                "exercises": [
                    ("Fondos en paralelas", True),
                    ("Press cerrado", True),
                    ("Press francés", False),
                    ("Extensión en polea alta", False),
                    ("Extensión sobre la cabeza", False),
                    ("Patada de tríceps", False),
                ],
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
                "exercises": [
                    ("Sentadilla", True),
                    ("Sentadilla frontal", True),
                    ("Prensa de piernas", True),
                    ("Zancadas", True),
                    ("Sentadilla búlgara", True),
                    ("Extensión de rodilla", False),
                ],
            },
            {
                "name": "Isquiotibiales",
                "guide": (
                    "Sensor A en la parte media-posterior del muslo (bíceps "
                    "femoral). Sensor B 2-3 cm hacia el lado interno "
                    "(semitendinoso). Boca abajo, rodilla ligeramente flexionada."
                ),
                "exercises": [
                    ("Peso muerto rumano", True),
                    ("Peso muerto piernas rígidas", True),
                    ("Buenos días", True),
                    ("Empuje de cadera", True),
                    ("Curl femoral tumbado", False),
                    ("Curl femoral sentado", False),
                ],
            },
            {
                "name": "Gastrocnemio (pantorrilla)",
                "guide": (
                    "Sensor A en la cabeza medial (lado interno de la pantorrilla, "
                    "la parte más prominente). Sensor B en la cabeza lateral "
                    "(lado externo), a la misma altura."
                ),
                "exercises": [
                    ("Elevación de talones de pie", False),
                    ("Elevación de talones sentado", False),
                    ("Elevación de talones en prensa", False),
                    ("Elevación de talones a una pierna", False),
                    ("Elevación de talones en escalón", False),
                    ("Elevación de talones con barra", False),
                ],
            },
        ],
    },
    {
        "group": "Espalda",
        "muscles": [
            {
                "name": "Dorsal ancho",
                "guide": (
                    "Sensor A sobre el borde externo del dorsal, a la altura del "
                    "ángulo inferior de la escápula. Sensor B 3-4 cm por debajo, "
                    "siguiendo la dirección de las fibras hacia la cintura. Brazo "
                    "relajado a un costado."
                ),
                "exercises": [
                    ("Dominadas", True),
                    ("Jalón al pecho", True),
                    ("Remo con barra", True),
                    ("Remo en polea baja", True),
                    ("Remo con mancuerna", True),
                    ("Pullover en polea", False),
                ],
            },
            {
                "name": "Trapecio",
                "guide": (
                    "Sensor A en la porción superior (entre cuello y hombro). "
                    "Sensor B en la porción media (entre las escápulas), separados "
                    "varios centímetros sobre la misma línea muscular."
                ),
                "exercises": [
                    ("Remo al mentón", True),
                    ("Remo invertido", True),
                    ("Encogimientos con barra", False),
                    ("Encogimientos con mancuernas", False),
                    ("Encogimientos en polea", False),
                    ("Face pull", False),
                ],
            },
        ],
    },
    {
        "group": "Pecho",
        "muscles": [
            {
                "name": "Pectoral mayor",
                "guide": (
                    "Sensor A en la porción clavicular (parte superior del pecho, "
                    "cerca de la clavícula). Sensor B en la porción esternal "
                    "(parte media-baja del pecho), sobre la misma línea."
                ),
                "exercises": [
                    ("Press de banca", True),
                    ("Press inclinado con mancuernas", True),
                    ("Press declinado", True),
                    ("Fondos de pecho", True),
                    ("Aperturas con mancuernas", False),
                    ("Cruce en poleas", False),
                ],
            },
        ],
    },
    {
        "group": "Hombro",
        "muscles": [
            {
                "name": "Deltoides",
                "guide": (
                    "Sensor A en la porción anterior (parte frontal del hombro). "
                    "Sensor B en la porción lateral/media (parte externa del "
                    "hombro), separados 3-4 cm."
                ),
                "exercises": [
                    ("Press militar", True),
                    ("Press Arnold", True),
                    ("Elevaciones laterales", False),
                    ("Elevaciones frontales", False),
                    ("Pájaros", False),
                    ("Elevación posterior en polea", False),
                ],
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
                "exercises": [
                    ("Crunch", False),
                    ("Crunch en polea", False),
                    ("Elevación de piernas", False),
                    ("Plancha", False),
                    ("Rueda abdominal", False),
                    ("Encogimiento en banco declinado", False),
                ],
            },
        ],
    },
]


def _get_or_create_group(session, name: str) -> MuscleGroup:
    """Devuelve el grupo indicado, creándolo si no existe."""
    existing = session.scalar(select(MuscleGroup).where(MuscleGroup.name == name))
    if existing:
        return existing
    group = MuscleGroup(name=name)
    session.add(group)
    session.flush()  # Asigna el identificador sin cerrar la transacción.
    return group


def _get_or_create_muscle(session, group_id: int, name: str, guide: str) -> Muscle:
    """Devuelve el músculo indicado, creándolo si no existe.

    Si ya existe, actualiza su guía de colocación con la del catálogo.
    """
    existing = session.scalar(
        select(Muscle).where(Muscle.group_id == group_id, Muscle.name == name)
    )
    if existing:
        existing.placement_guide = guide
        return existing
    muscle = Muscle(group_id=group_id, name=name, placement_guide=guide)
    session.add(muscle)
    session.flush()
    return muscle


def _get_or_create_exercise(
    session, muscle_id: int, name: str, is_compound: bool
) -> Exercise:
    """Devuelve el ejercicio indicado, creándolo si no existe.

    Si ya existe, actualiza su clasificación como compuesto, de la que
    depende el orden que ocupará dentro de la sesión.
    """
    existing = session.scalar(
        select(Exercise).where(Exercise.muscle_id == muscle_id, Exercise.name == name)
    )
    if existing:
        existing.is_compound = is_compound
        return existing
    exercise = Exercise(muscle_id=muscle_id, name=name, is_compound=is_compound)
    session.add(exercise)
    session.flush()
    return exercise


def _prune_orphans(session) -> int:
    """Elimina los ejercicios que ya no figuran en el catálogo.

    Parameters
    ----------
    session : sqlalchemy.orm.Session
        Sesión abierta. La función no confirma la transacción.

    Returns
    -------
    int
        Ejercicios eliminados.

    Notes
    -----
    Es necesaria porque el catálogo se reorganiza: al trasladar los
    ejercicios de tirón del trapecio al dorsal, sin esta poda la base de
    datos conservaría ambas copias y el entrenador vería el mismo
    ejercicio bajo dos músculos distintos.

    Se conserva todo ejercicio referenciado por un resultado de
    evaluación o por una rutina: perder una medición real por reordenar
    una lista sería mucho más grave que conservar una fila sobrante.
    """
    del_catalogo = {
        (muscle_data["name"], nombre)
        for group_data in CATALOG
        for muscle_data in group_data["muscles"]
        for nombre, _ in muscle_data["exercises"]
    }

    usados = set(session.scalars(select(ExerciseResult.exercise_id)))
    usados |= set(session.scalars(select(RoutineExercise.exercise_id)))

    borrados = 0
    for exercise in session.scalars(select(Exercise)):
        muscle = session.get(Muscle, exercise.muscle_id)
        if muscle is None:
            continue
        if (muscle.name, exercise.name) in del_catalogo:
            continue
        if exercise.id in usados:
            continue
        session.delete(exercise)
        borrados += 1
    return borrados


def seed() -> None:
    """Siembra el catálogo completo y poda los ejercicios huérfanos.

    La operación es idempotente e informa por la salida estándar de los
    elementos procesados y de los ejercicios eliminados.
    """
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

                for exercise_name, is_compound in muscle_data["exercises"]:
                    _get_or_create_exercise(session, muscle.id, exercise_name, is_compound)
                    exercises_created += 1

        removed = _prune_orphans(session)
        session.commit()

    print(
        f"Listo: {groups_created} grupos, {muscles_created} músculos, "
        f"{exercises_created} ejercicios."
    )
    if removed:
        print(f"Se quitaron {removed} ejercicios que ya no están en el catálogo.")


def main() -> None:
    """Punto de entrada de la ejecución como módulo."""
    seed()


if __name__ == "__main__":
    main()
