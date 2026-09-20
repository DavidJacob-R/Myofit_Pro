"""
Generador de rutinas a partir de lo que se midió.

DE DÓNDE SALE CADA COSA
=======================

1. QUÉ ejercicios — del ranking de activación medido con los sensores.
   Se ordenan los ejercicios de ese músculo por la activación promedio
   que produjeron EN ESA PERSONA y se toman los mejores. Es la única
   parte que los sensores pueden contestar, y es la razón de ser del
   producto: comparar a la persona consigo misma.

2. CÓMO se reparte la semana — de una plantilla de división por días
   (ver `SPLITS`). Un día de gimnasio no es un músculo suelto: es un
   bloque de músculos que trabajan juntos. La plantilla de 5 días es
   empuje / tirón / cuádriceps / brazo / femoral, que es como se
   programa de verdad.

3. CUÁNTO — de la ficha del cliente: objetivo, nivel de experiencia y
   días disponibles. Series, repeticiones, descanso e intensidad salen
   de los rangos estándar de entrenamiento de fuerza (ACSM/NSCA) para
   cada objetivo, ajustados por experiencia.

POR QUÉ SE TOMAN HASTA TRES POR MÚSCULO
=======================================

La simulación de `ml/within_subject.py` dice que con una repetibilidad
del 10% el ejercicio que queda primero es realmente el mejor solo el
66% de las veces, pero el mejor está entre los tres primeros el 95% de
las veces. Prescribir el primero sería afirmar más de lo que la medición
sostiene; prescribir los tres mejores, no.

LOS EJERCICIOS SIN MEDIR
========================

Una rutina completa necesita más ejercicios de los que normalmente se
alcanzan a medir. Los que faltan entran del catálogo, pero marcados, y
se distinguen dos casos que no significan lo mismo:

- COMPLEMENTO: el músculo sí tiene mediciones, solo que ese ejercicio en
  concreto no se probó. Se puede decir que encaja, porque se sabe cómo
  responde ese músculo en esta persona.
- SIN LECTURAS: el músculo no tiene ninguna medición. Ahí no hay nada que
  inferir y la app lo dice.

LA ROTACIÓN, Y POR QUÉ NO ES UN CAPRICHO
========================================

El último hueco de cada músculo se sortea entre los candidatos que
quedan justo fuera del corte, en vez de tomar siempre el siguiente del
ranking.

No es para "dar variedad". Es para que los datos sirvan después. Si a
todo el mundo se le asignan siempre sus mejores ejercicios medidos, en un
año habrá cientos de evaluaciones y ninguna forma de saber POR QUÉ unos
clientes mejoraron: no hay con qué comparar, porque nadie hizo otra cosa.
Ese sorteo es lo único que introduce variación independiente del propio
cliente, y es lo que permitirá más adelante preguntar si un ejercicio
causó la mejora o solo la acompañó.

Cuesta poco: los tres primeros de cada músculo —que es hasta donde el
ranking distingue— se respetan siempre, y solo se mueve el último.

Los ejercicios que entran por sorteo quedan marcados (`is_rotation`) y se
guardan así en la base, porque sin esa marca el dato no sirve para la
pregunta que motiva la rotación.

LO QUE ESTE MÓDULO NO HACE
==========================

No estima kilos. El sEMG mide activación eléctrica, no carga. La
intensidad se expresa como porcentaje del PR (repetición máxima) y como
repeticiones en reserva, que es lo que un entrenador puede aplicar sin
que la app se invente nada.

Es lógica pura, sin Qt ni base de datos, para poder probarlo
(ver tests/test_routine_engine.py).
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

from myofit_pro.body_composition import EXPERIENCE_LEVELS

# ── Prescripción ─────────────────────────────────────────────────────


def format_rest(rest_sec: int | None) -> str:
    """
    Descanso en el lenguaje del gimnasio.

    Hasta dos minutos se dice en segundos ("90 s", no "1,5 min"): así es
    como se programa un cronómetro y como lo cuenta la gente. A partir
    de ahí conviene el minuto redondo.
    """
    if not rest_sec:
        return "—"
    if rest_sec < 120:
        return f"{rest_sec} s"
    minutes = rest_sec / 60
    if minutes == int(minutes):
        return f"{int(minutes)} min"
    return f"{minutes:.1f} min".replace(".", ",")


@dataclass(frozen=True)
class Prescription:
    """
    Cuánto se hace de un ejercicio. Los rangos son los estándar de
    entrenamiento de fuerza por objetivo; no salen de la medición, que
    solo decide QUÉ ejercicios entran.
    """

    sets: int
    reps_min: int
    reps_max: int
    rest_sec: int
    load_pct_min: int
    load_pct_max: int
    rir: int  # repeticiones en reserva: cuántas sobran al terminar la serie

    @property
    def reps_text(self) -> str:
        if self.reps_min == self.reps_max:
            return str(self.reps_min)
        return f"{self.reps_min}-{self.reps_max}"

    @property
    def rest_text(self) -> str:
        return format_rest(self.rest_sec)

    @property
    def load_text(self) -> str:
        return f"{self.load_pct_min}-{self.load_pct_max}% de tu PR"

    @property
    def summary(self) -> str:
        return f"{self.sets} × {self.reps_text}"


class ExerciseRole(str, Enum):
    """
    Qué papel juega el ejercicio dentro del trabajo de su músculo.

    De aquí sale la mayor parte de la diferencia entre un ejercicio y
    otro: el primario es el movimiento pesado con el músculo fresco, el
    accesorio es el que se hace al final para acumular trabajo. Darles el
    mismo esquema de series y repeticiones es lo que hace que una rutina
    parezca generada por una plantilla.
    """

    PRIMARIO = "primario"      # compuesto principal, con el músculo fresco
    SECUNDARIO = "secundario"  # otro compuesto o una variante
    ACCESORIO = "accesorio"    # aislamiento, al final


class MuscleSize(str, Enum):
    """
    Tamaño funcional del músculo.

    Un pectoral y un bíceps no se programan igual. Los grandes mueven
    cargas altas y aguantan rangos bajos de repeticiones; los pequeños
    responden mejor a más repeticiones con menos carga, y la pantorrilla
    y el abdomen son el caso extremo.
    """

    GRANDE = "grande"
    MEDIO = "medio"
    PEQUENO = "pequeno"


# Clasificación de cada músculo del catálogo.
MUSCLE_SIZES: dict[str, MuscleSize] = {
    "Pectoral mayor": MuscleSize.GRANDE,
    "Dorsal ancho": MuscleSize.GRANDE,
    "Cuádriceps": MuscleSize.GRANDE,
    "Isquiotibiales": MuscleSize.GRANDE,
    "Deltoides": MuscleSize.MEDIO,
    "Trapecio": MuscleSize.MEDIO,
    "Tríceps braquial": MuscleSize.MEDIO,
    "Bíceps braquial": MuscleSize.PEQUENO,
    "Gastrocnemio (pantorrilla)": MuscleSize.PEQUENO,
    "Recto abdominal": MuscleSize.PEQUENO,
}

DEFAULT_MUSCLE_SIZE = MuscleSize.MEDIO


# Esquema por objetivo y por papel del ejercicio.
#
# Fuerza: el primario va pesado y con descansos largos porque lo que se
# entrena es el sistema nervioso; los accesorios ya no, sirven para
# sostener el volumen sin quemar al cliente.
#
# Hipertrofia: el primario en rango medio-bajo con carga alta, y los
# accesorios en rango alto, que es donde la tensión metabólica hace lo
# suyo.
#
# Definición: todo desplazado a más repeticiones y menos descanso, para
# acumular trabajo con carga moderada.
GOAL_SCHEMES: dict[str, dict[ExerciseRole, Prescription]] = {
    "Fuerza": {
        ExerciseRole.PRIMARIO:   Prescription(5, 3, 5, 180, 85, 92, 2),
        ExerciseRole.SECUNDARIO: Prescription(4, 5, 8, 150, 78, 85, 2),
        ExerciseRole.ACCESORIO:  Prescription(3, 8, 12, 90, 65, 75, 2),
    },
    "Hipertrofia": {
        ExerciseRole.PRIMARIO:   Prescription(4, 6, 8, 120, 75, 85, 2),
        ExerciseRole.SECUNDARIO: Prescription(4, 8, 12, 90, 70, 80, 2),
        ExerciseRole.ACCESORIO:  Prescription(3, 12, 15, 60, 60, 70, 1),
    },
    "Definición": {
        ExerciseRole.PRIMARIO:   Prescription(4, 10, 12, 75, 65, 75, 2),
        ExerciseRole.SECUNDARIO: Prescription(3, 12, 15, 60, 60, 70, 1),
        ExerciseRole.ACCESORIO:  Prescription(3, 15, 20, 45, 50, 60, 1),
    },
    "Resistencia": {
        ExerciseRole.PRIMARIO:   Prescription(3, 12, 15, 60, 55, 65, 2),
        ExerciseRole.SECUNDARIO: Prescription(3, 15, 20, 45, 50, 60, 2),
        ExerciseRole.ACCESORIO:  Prescription(2, 18, 25, 40, 45, 55, 2),
    },
    "Rehabilitación": {
        ExerciseRole.PRIMARIO:   Prescription(3, 10, 12, 90, 45, 60, 4),
        ExerciseRole.SECUNDARIO: Prescription(2, 12, 15, 60, 40, 55, 4),
        ExerciseRole.ACCESORIO:  Prescription(2, 15, 20, 45, 35, 50, 4),
    },
    "Postura": {
        ExerciseRole.PRIMARIO:   Prescription(3, 10, 12, 75, 50, 65, 3),
        ExerciseRole.SECUNDARIO: Prescription(3, 12, 15, 60, 45, 60, 3),
        ExerciseRole.ACCESORIO:  Prescription(2, 15, 20, 45, 40, 55, 3),
    },
}

DEFAULT_GOAL = "Hipertrofia"

# Ajuste por tamaño del músculo, sobre el esquema del papel.
#
# (repeticiones que se suman, puntos de carga que se restan,
#  factor de descanso, series que se suman)
SIZE_ADJUSTMENTS: dict[MuscleSize, tuple[int, int, float, int]] = {
    MuscleSize.GRANDE: (0, 0, 1.0, 0),
    MuscleSize.MEDIO: (2, 5, 0.9, 0),
    MuscleSize.PEQUENO: (3, 8, 0.8, -1),
}

# Límites para que ningún ajuste se dispare. Veinte repeticiones es el
# techo realista de una serie de gimnasio; más allá de eso el ejercicio
# deja de ser trabajo de fuerza.
REPS_MAXIMAS = 20
CARGA_MINIMA = 35

# Activación a partir de la cual un ejercicio se trata como más pesado
# de lo que su papel indicaría, y por debajo de la cual como más ligero.
#
# Es la vía por la que la medición entra en el CUÁNTO y no solo en el
# QUÉ: un ejercicio que recluta casi al máximo se está haciendo a
# intensidad relativa alta y pide rango bajo; uno que apenas recluta es
# un estímulo ligero y pide rango alto.
ACTIVACION_ALTA = 80.0
ACTIVACION_BAJA = 50.0

# Series por músculo y por semana razonables para cada objetivo. El
# generador recorta para no pasarse del tope.
VOLUME_TARGETS: dict[str, tuple[int, int]] = {
    "Fuerza": (8, 16),
    "Hipertrofia": (10, 20),
    "Definición": (10, 20),
    "Resistencia": (8, 16),
    "Rehabilitación": (4, 10),
    "Postura": (6, 12),
}

# Cuántos ejercicios lleva una sesión, según el nivel. Un principiante
# progresa con poco y le sobra técnica que aprender; un avanzado
# necesita más volumen y más variedad para seguir avanzando.
EXERCISES_PER_SESSION: dict[str, int] = {
    "Principiante": 4,
    "Intermedio": 6,
    "Avanzado": 7,
}

# Tope de ejercicios del mismo músculo en una misma sesión. Más allá del
# tercero el ranking medido ya no distingue (ver la nota del
# encabezado), así que el cuarto se elegiría por ruido.
MAX_POR_MUSCULO_POR_DIA = 3

DEFAULT_EXPERIENCE = "Principiante"

# Cuántos candidatos entran al sorteo del último hueco. Tres deja elegir
# entre el 4.º, 5.º y 6.º del ranking: suficiente variación sin bajar a
# ejercicios que el cliente ya demostró que no le sirven.
ROTACION_ALTERNATIVAS = 3


def _round_rest(segundos: float) -> int:
    """
    Redondea el descanso a un valor que se pueda poner en un cronómetro.

    Sin esto los ajustes por tamaño dejaban descansos de "112 s" o "2,2
    min", que nadie programa. Hasta dos minutos se redondea a múltiplos
    de 15 segundos; a partir de ahí, a medios minutos.
    """
    valor = max(40, int(segundos))
    if valor < 120:
        return max(45, int(round(valor / 15)) * 15)
    return int(round(valor / 30)) * 30


def muscle_size(muscle_name: str) -> MuscleSize:
    return MUSCLE_SIZES.get(muscle_name, DEFAULT_MUSCLE_SIZE)


def role_for(
    position: int, is_compound: bool, activation_pct: float | None, size: MuscleSize
) -> ExerciseRole:
    """
    Qué papel le toca a un ejercicio dentro del bloque de su músculo.

    Manda el tipo de movimiento y la posición: el primer compuesto es el
    primario. Encima, la medición corrige — si el ejercicio recluta casi
    al máximo sube de papel, y si apenas recluta baja. Es la vía por la
    que las lecturas deciden también el CUÁNTO.

    Un músculo pequeño nunca hace trabajo de primario: un bíceps no se
    entrena a 3 repeticiones con el 90% por mucho que active.
    """
    if is_compound and position == 1:
        papel = ExerciseRole.PRIMARIO
    elif is_compound:
        papel = ExerciseRole.SECUNDARIO
    else:
        papel = ExerciseRole.ACCESORIO

    if activation_pct is not None:
        if activation_pct >= ACTIVACION_ALTA:
            papel = _subir(papel)
        elif activation_pct < ACTIVACION_BAJA:
            papel = _bajar(papel)

    if size is MuscleSize.PEQUENO and papel is ExerciseRole.PRIMARIO:
        papel = ExerciseRole.SECUNDARIO
    return papel


def _subir(papel: ExerciseRole) -> ExerciseRole:
    if papel is ExerciseRole.ACCESORIO:
        return ExerciseRole.SECUNDARIO
    if papel is ExerciseRole.SECUNDARIO:
        return ExerciseRole.PRIMARIO
    return papel


def _bajar(papel: ExerciseRole) -> ExerciseRole:
    if papel is ExerciseRole.PRIMARIO:
        return ExerciseRole.SECUNDARIO
    if papel is ExerciseRole.SECUNDARIO:
        return ExerciseRole.ACCESORIO
    return papel


def prescription_for(
    goal: str | None,
    experience: str | None,
    role: ExerciseRole = ExerciseRole.SECUNDARIO,
    size: MuscleSize = MuscleSize.GRANDE,
) -> Prescription:
    """
    La prescripción de un ejercicio concreto: objetivo, papel dentro del
    bloque, tamaño del músculo y nivel del cliente.

    El principiante hace una serie menos y se queda más lejos del fallo
    (una repetición más en reserva): tolera menos volumen y todavía está
    aprendiendo el patrón de movimiento, donde llegar al fallo estropea
    la técnica. El avanzado hace una serie más y se acerca más al fallo.
    """
    esquema = GOAL_SCHEMES.get(goal or "", GOAL_SCHEMES[DEFAULT_GOAL])
    base = esquema[role]

    mas_reps, menos_carga, factor_descanso, mas_series = SIZE_ADJUSTMENTS[size]
    sets = base.sets + mas_series
    reps_min = min(base.reps_min + mas_reps, REPS_MAXIMAS)
    reps_max = min(base.reps_max + mas_reps, REPS_MAXIMAS)
    load_min = max(base.load_pct_min - menos_carga, CARGA_MINIMA)
    load_max = max(base.load_pct_max - menos_carga, CARGA_MINIMA + 5)
    rest = _round_rest(base.rest_sec * factor_descanso)
    rir = base.rir

    level = experience if experience in EXPERIENCE_LEVELS else DEFAULT_EXPERIENCE
    if level == "Principiante":
        sets -= 1
        rir += 1
    elif level == "Avanzado":
        sets += 1
        rir = max(0, rir - 1)

    return Prescription(
        sets=max(2, sets),
        reps_min=reps_min,
        reps_max=reps_max,
        rest_sec=rest,
        load_pct_min=load_min,
        load_pct_max=load_max,
        rir=rir,
    )


# ── División de la semana ────────────────────────────────────────────

# Nombres tal como están en el catálogo (ver seed_data.py).
PECHO = "Pectoral mayor"
DORSAL = "Dorsal ancho"
TRAPECIO = "Trapecio"
HOMBRO = "Deltoides"
BICEPS = "Bíceps braquial"
TRICEPS = "Tríceps braquial"
CUADRICEPS = "Cuádriceps"
FEMORAL = "Isquiotibiales"
PANTORRILLA = "Gastrocnemio (pantorrilla)"
ABDOMEN = "Recto abdominal"


@dataclass(frozen=True)
class SplitDay:
    """
    Un día de la plantilla: qué día de la semana es, cómo se llama esa
    sesión y qué músculos entran, en orden de prioridad.

    El orden importa dos veces: decide cuántos ejercicios se lleva cada
    músculo (el primero se lleva más) y el orden en que se hacen dentro
    de la sesión.
    """

    weekday: str
    label: str
    muscles: tuple[str, ...]


# Plantillas por número de días disponibles.
#
# No son días de músculo suelto sino bloques que trabajan juntos: empuje
# (pecho, hombro, tríceps), tirón (dorsal, trapecio, bíceps) y pierna.
# Es como se programa en gimnasio y es lo que permite que una sesión
# tenga seis ejercicios en vez de dos.
#
# Los días de la semana dejan el descanso donde toca: nunca tres bloques
# de pierna seguidos ni la semana entera sin un día libre.
SPLITS: dict[int, tuple[SplitDay, ...]] = {
    1: (
        SplitDay("Lunes", "Cuerpo completo", (PECHO, DORSAL, CUADRICEPS, HOMBRO)),
    ),
    2: (
        SplitDay("Lunes", "Torso", (PECHO, DORSAL, HOMBRO, TRICEPS, BICEPS)),
        SplitDay("Jueves", "Pierna", (CUADRICEPS, FEMORAL, PANTORRILLA, ABDOMEN)),
    ),
    3: (
        SplitDay("Lunes", "Empuje", (PECHO, HOMBRO, TRICEPS)),
        SplitDay("Miércoles", "Tirón", (DORSAL, TRAPECIO, BICEPS)),
        SplitDay("Viernes", "Pierna", (CUADRICEPS, FEMORAL, PANTORRILLA)),
    ),
    4: (
        SplitDay("Lunes", "Empuje", (PECHO, HOMBRO, TRICEPS)),
        SplitDay("Martes", "Tirón", (DORSAL, TRAPECIO, BICEPS)),
        SplitDay("Jueves", "Pierna", (CUADRICEPS, FEMORAL, PANTORRILLA)),
        SplitDay("Viernes", "Brazo y hombro", (TRICEPS, BICEPS, HOMBRO)),
    ),
    5: (
        SplitDay("Lunes", "Empuje", (PECHO, TRICEPS, HOMBRO)),
        SplitDay("Martes", "Tirón", (DORSAL, BICEPS, TRAPECIO, HOMBRO)),
        SplitDay("Miércoles", "Cuádriceps", (CUADRICEPS, PANTORRILLA)),
        SplitDay("Viernes", "Brazo", (TRICEPS, BICEPS)),
        SplitDay("Sábado", "Femoral y abdomen", (FEMORAL, PANTORRILLA, ABDOMEN)),
    ),
    6: (
        SplitDay("Lunes", "Empuje", (PECHO, HOMBRO, TRICEPS)),
        SplitDay("Martes", "Tirón", (DORSAL, TRAPECIO, BICEPS)),
        SplitDay("Miércoles", "Pierna", (CUADRICEPS, FEMORAL, PANTORRILLA)),
        SplitDay("Jueves", "Empuje", (PECHO, HOMBRO, TRICEPS)),
        SplitDay("Viernes", "Tirón", (DORSAL, TRAPECIO, BICEPS)),
        SplitDay("Sábado", "Pierna", (CUADRICEPS, FEMORAL, ABDOMEN)),
    ),
}

WEEKDAYS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")


def split_for(days_per_week: int | None) -> tuple[SplitDay, ...]:
    """La plantilla que corresponde a los días disponibles."""
    return SPLITS[_clamp_days(days_per_week)]


def rest_days(split: tuple[SplitDay, ...]) -> tuple[str, ...]:
    """Los días de la semana que quedan libres en esta plantilla."""
    ocupados = {d.weekday for d in split}
    return tuple(d for d in WEEKDAYS if d not in ocupados)


# ── Entrada: lo que se midió ─────────────────────────────────────────


@dataclass(frozen=True)
class MeasuredExercise:
    """Un ejercicio que sí se midió con los sensores en este cliente."""

    exercise_id: int
    name: str
    activation_pct: float
    measurements: int = 1
    is_compound: bool = False


@dataclass(frozen=True)
class CatalogExercise:
    """Un ejercicio del catálogo que no se ha medido en este cliente."""

    exercise_id: int
    name: str
    is_compound: bool = False


@dataclass(frozen=True)
class MuscleCandidates:
    """Los ejercicios disponibles para un músculo: medidos y de catálogo."""

    muscle_id: int
    muscle_name: str
    measured: tuple[MeasuredExercise, ...] = ()
    catalog: tuple[CatalogExercise, ...] = ()

    @property
    def has_readings(self) -> bool:
        return bool(self.measured)


# ── Salida: el plan ──────────────────────────────────────────────────


class ExerciseSource(str, Enum):
    """
    De dónde salió un ejercicio de la rutina. Las tres cosas que puede
    decir la app, y no significan lo mismo.
    """

    MEASURED = "medido"           # se midió en este cliente
    COMPLEMENT = "complemento"    # su músculo sí se midió, este ejercicio no
    UNMEASURED = "sin_lecturas"   # su músculo no tiene ninguna medición


@dataclass(frozen=True)
class PlannedExercise:
    exercise_id: int | None
    name: str
    muscle_id: int
    muscle_name: str
    prescription: Prescription
    activation_pct: float | None  # None = este ejercicio nunca se midió
    measurements: int
    rank: int  # posición dentro de su músculo, 1 = el que más activó
    source: ExerciseSource = ExerciseSource.MEASURED
    is_compound: bool = False
    role: ExerciseRole = ExerciseRole.SECUNDARIO
    # True si este hueco salió del sorteo y no del ranking. Ver ROTACION.
    is_rotation: bool = False

    @property
    def is_measured(self) -> bool:
        return self.activation_pct is not None


@dataclass(frozen=True)
class PlannedDay:
    index: int  # 1..días de la plantilla
    weekday: str = ""
    label: str = ""
    exercises: tuple[PlannedExercise, ...] = ()

    @property
    def muscle_names(self) -> tuple[str, ...]:
        vistos: list[str] = []
        for e in self.exercises:
            if e.muscle_name not in vistos:
                vistos.append(e.muscle_name)
        return tuple(vistos)


@dataclass(frozen=True)
class RoutinePlan:
    goal: str
    experience: str
    days_per_week: int
    frequency: int  # veces por semana que se entrena el músculo más frecuente
    prescription: Prescription
    days: tuple[PlannedDay, ...] = ()
    weekly_sets: dict[str, int] = field(default_factory=dict)
    volume_target: tuple[int, int] = (10, 20)
    warnings: tuple[str, ...] = ()
    rest_days: tuple[str, ...] = ()

    @property
    def exercises(self) -> tuple[PlannedExercise, ...]:
        """Todas las apariciones de todos los ejercicios en la semana."""
        return tuple(e for day in self.days for e in day.exercises)

    @property
    def unique_exercises(self) -> tuple[PlannedExercise, ...]:
        """Cada ejercicio distinto una sola vez."""
        seen: dict[tuple[int, int | None], PlannedExercise] = {}
        for exercise in self.exercises:
            seen.setdefault((exercise.muscle_id, exercise.exercise_id), exercise)
        return tuple(seen.values())

    @property
    def measured_count(self) -> int:
        return sum(1 for e in self.unique_exercises if e.is_measured)

    @property
    def is_empty(self) -> bool:
        return not self.days


# ── Construcción del plan ────────────────────────────────────────────


def build_plan(
    goal: str | None,
    experience: str | None,
    days_per_week: int | None,
    candidates: list[MuscleCandidates],
    rng: random.Random | None = None,
) -> RoutinePlan:
    """
    Arma la rutina completa a partir de la plantilla de días y de lo que
    se midió en el cliente.

    `rng` activa la rotación del último hueco de cada músculo (ver la
    nota del encabezado). Sin él el resultado es determinista, que es lo
    que quieren las pruebas; la aplicación siempre pasa uno.
    """
    effective_goal = goal if goal in GOAL_SCHEMES else DEFAULT_GOAL
    effective_experience = (
        experience if experience in EXPERIENCE_LEVELS else DEFAULT_EXPERIENCE
    )
    days = _clamp_days(days_per_week)
    prescription = prescription_for(effective_goal, effective_experience)
    target = VOLUME_TARGETS.get(effective_goal, (10, 20))
    split = SPLITS[days]

    warnings: list[str] = []
    if goal not in GOAL_SCHEMES:
        warnings.append(
            f"La ficha no tiene un objetivo reconocido, se prescribió como "
            f"{DEFAULT_GOAL.lower()}."
        )
    if experience not in EXPERIENCE_LEVELS:
        warnings.append(
            "La ficha no dice el nivel de experiencia. Se asumió principiante, "
            "que es lo conservador: menos series y más lejos del fallo."
        )
    if not days_per_week:
        warnings.append(f"La ficha no dice cuántos días entrena. Se repartió en {days}.")

    por_nombre = {c.muscle_name: c for c in candidates if c.measured or c.catalog}
    if not por_nombre:
        return RoutinePlan(
            goal=effective_goal, experience=effective_experience,
            days_per_week=days, frequency=1, prescription=prescription,
            volume_target=target, warnings=tuple(warnings),
        )

    objetivo_sesion = EXERCISES_PER_SESSION[effective_experience]
    planned: list[PlannedDay] = []

    for indice, dia in enumerate(split, start=1):
        disponibles = [por_nombre[m] for m in dia.muscles if m in por_nombre]
        if not disponibles:
            continue

        capacidades = [
            len({e.exercise_id for e in c.measured} | {e.exercise_id for e in c.catalog})
            for c in disponibles
        ]
        reparto = _allocate(objetivo_sesion, capacidades)
        ejercicios: list[PlannedExercise] = []
        for candidato, cuantos in zip(disponibles, reparto):
            if cuantos > 0:
                ejercicios.extend(
                    _pick(
                        candidato, cuantos, effective_goal, effective_experience, rng
                    )
                )

        if ejercicios:
            planned.append(
                PlannedDay(
                    index=indice, weekday=dia.weekday, label=dia.label,
                    exercises=tuple(ejercicios),
                )
            )

    if not planned:
        return RoutinePlan(
            goal=effective_goal, experience=effective_experience,
            days_per_week=days, frequency=1, prescription=prescription,
            volume_target=target, warnings=tuple(warnings),
        )

    planned = _trim_volume(planned, target)

    weekly_sets = _weekly_sets(planned)
    warnings.extend(_volume_warnings(weekly_sets, target))
    warnings.extend(_coverage_warnings(planned, por_nombre))

    apariciones: dict[str, int] = {}
    for dia_plan in planned:
        for muscle in dia_plan.muscle_names:
            apariciones[muscle] = apariciones.get(muscle, 0) + 1

    return RoutinePlan(
        goal=effective_goal,
        experience=effective_experience,
        days_per_week=days,
        frequency=max(apariciones.values(), default=1),
        prescription=prescription,
        days=tuple(planned),
        weekly_sets=weekly_sets,
        volume_target=target,
        warnings=tuple(warnings),
        rest_days=rest_days(split),
    )


def _clamp_days(days_per_week: int | None) -> int:
    """Entre 1 y 6. Sin dato, 3: el reparto más común y el más seguro."""
    if not days_per_week:
        return 3
    return int(min(max(days_per_week, 1), 6))


def _allocate(total: int, capacities: list[int]) -> list[int]:
    """
    Reparte los ejercicios de una sesión entre sus músculos.

    El primero de la lista se lleva más, porque es el músculo que da
    nombre al día: en un día de empuje el pecho manda y el hombro
    acompaña. Con 6 ejercicios y 3 músculos sale 3-2-1, que es
    exactamente como se programa un día de pecho, tríceps y hombro.

    `capacities` es cuántos ejercicios tiene disponibles cada músculo. Si
    uno no llega a su cuota —la pantorrilla suele tener solo dos— lo que
    sobra se reparte entre los demás, en vez de dejar la sesión corta.
    """
    n = len(capacities)
    if n <= 0:
        return []

    reparto = []
    restante = max(total, n)
    for posicion, capacidad in enumerate(capacities):
        faltan_despues = n - posicion - 1
        cuantos = min(MAX_POR_MUSCULO_POR_DIA, restante - faltan_despues, capacidad)
        cuantos = max(0, cuantos)
        reparto.append(cuantos)
        restante -= cuantos

    # Segunda vuelta: lo que quedó sin repartir se ofrece a los músculos
    # que todavía tienen ejercicios sin usar.
    while restante > 0:
        movido = False
        for posicion, capacidad in enumerate(capacities):
            if restante <= 0:
                break
            if reparto[posicion] < min(MAX_POR_MUSCULO_POR_DIA, capacidad):
                reparto[posicion] += 1
                restante -= 1
                movido = True
        if not movido:
            break

    return reparto


def _pick(
    candidate: MuscleCandidates,
    cuantos: int,
    goal: str,
    experience: str,
    rng: random.Random | None = None,
) -> list[PlannedExercise]:
    """
    Elige los ejercicios de un músculo para una sesión y le pone a cada
    uno la prescripción que le toca.

    Primero los medidos por orden de activación —que es lo que el
    producto aporta—, y solo si faltan, los del catálogo. Los que entran
    del catálogo van marcados según si su músculo tiene mediciones o no.

    Dentro del músculo los compuestos van primero: es cuando está fresco
    y son los que más carga mueven. Esa posición, junto con la
    activación medida y el tamaño del músculo, decide el papel de cada
    ejercicio y con él sus series, repeticiones, carga y descanso.

    Con `rng`, el ÚLTIMO hueco se sortea entre los candidatos que quedan
    justo fuera del corte en vez de tomar siempre el siguiente del
    ranking. Ver `ROTACION` al principio del módulo.
    """
    size = muscle_size(candidate.muscle_name)
    medidos = sorted(candidate.measured, key=lambda e: e.activation_pct, reverse=True)

    # (nombre, id, activación, mediciones, compuesto, fuente, por rotación)
    escogidos: list[tuple[str, int | None, float | None, int, bool, ExerciseSource, bool]] = []
    for item in medidos[:cuantos]:
        escogidos.append(
            (item.name, item.exercise_id, item.activation_pct, item.measurements,
             item.is_compound, ExerciseSource.MEASURED, False)
        )

    # El hueco sorteado: se quita el último elegido por ranking y se
    # repone con uno de los que venían detrás.
    if rng is not None and cuantos >= 2 and len(medidos) > cuantos:
        banca = medidos[cuantos : cuantos + ROTACION_ALTERNATIVAS]
        if banca:
            escogidos.pop()
            suplente = rng.choice(banca)
            escogidos.append(
                (suplente.name, suplente.exercise_id, suplente.activation_pct,
                 suplente.measurements, suplente.is_compound,
                 ExerciseSource.MEASURED, True)
            )

    if len(escogidos) < cuantos:
        fuente = (
            ExerciseSource.COMPLEMENT if candidate.has_readings
            else ExerciseSource.UNMEASURED
        )
        ya = {e[1] for e in escogidos}
        respaldo = sorted(candidate.catalog, key=lambda e: (not e.is_compound, e.name))
        disponibles = [e for e in respaldo if e.exercise_id not in ya]

        # Sin nada medido no hay ranking que respetar, así que el sorteo
        # puede tocar cualquiera del catálogo.
        if rng is not None and not medidos and len(disponibles) > cuantos:
            cabeza = disponibles[: max(1, cuantos - 1)]
            banca = disponibles[max(1, cuantos - 1) :]
            disponibles = cabeza + [rng.choice(banca)]

        for item in disponibles:
            if len(escogidos) >= cuantos:
                break
            escogidos.append(
                (item.name, item.exercise_id, None, 0, item.is_compound, fuente, False)
            )

    # Compuestos primero, y entre ellos el que más activa.
    escogidos.sort(key=lambda e: (not e[4], -(e[2] or 0.0), e[0]))

    elegidos: list[PlannedExercise] = []
    for posicion, datos in enumerate(escogidos, start=1):
        nombre, ejercicio_id, activacion, mediciones, compuesto, fuente, rotado = datos
        papel = role_for(posicion, compuesto, activacion, size)
        elegidos.append(
            PlannedExercise(
                exercise_id=ejercicio_id,
                name=nombre,
                muscle_id=candidate.muscle_id,
                muscle_name=candidate.muscle_name,
                prescription=prescription_for(goal, experience, papel, size),
                activation_pct=activacion,
                measurements=mediciones,
                rank=posicion,
                source=fuente,
                is_compound=compuesto,
                role=papel,
                is_rotation=rotado,
            )
        )
    return elegidos


def _weekly_sets(days: list[PlannedDay]) -> dict[str, int]:
    """
    Series por músculo y por semana, sumando las de cada ejercicio.

    No se puede multiplicar por un número fijo: cada ejercicio lleva sus
    propias series según su papel y el tamaño del músculo.
    """
    total: dict[str, int] = {}
    for dia in days:
        for e in dia.exercises:
            total[e.muscle_name] = total.get(e.muscle_name, 0) + e.prescription.sets
    return total


def _trim_volume(days: list[PlannedDay], target: tuple[int, int]) -> list[PlannedDay]:
    """
    Recorta ejercicios hasta que ningún músculo se pase del volumen
    semanal recomendable.

    Se cuentan las series reales de cada ejercicio, no un número fijo,
    porque ahora cada uno lleva las suyas. Se quita siempre el último de
    ese músculo en el último día donde aparece: es el de menor
    prioridad. Se conserva al menos uno por día, porque un día que dice
    "pecho" y no trae ningún ejercicio de pecho no es un recorte, es un
    error.
    """
    _, high = target
    listas = [list(d.exercises) for d in days]

    def series_de(muscle: str) -> int:
        return sum(
            e.prescription.sets
            for items in listas
            for e in items
            if e.muscle_name == muscle
        )

    musculos = {e.muscle_name for items in listas for e in items}
    for muscle in sorted(musculos):
        # Se quita de atrás hacia adelante hasta caber, dejando siempre
        # uno por día.
        guardia = 0
        while series_de(muscle) > high and guardia < 20:
            guardia += 1
            quitado = False
            for indice in range(len(listas) - 1, -1, -1):
                del_musculo = [e for e in listas[indice] if e.muscle_name == muscle]
                if len(del_musculo) > 1:
                    listas[indice].remove(del_musculo[-1])
                    quitado = True
                    break
            if not quitado:
                break

    return [
        PlannedDay(
            index=d.index, weekday=d.weekday, label=d.label, exercises=tuple(items)
        )
        for d, items in zip(days, listas)
        if items
    ]


def _volume_warnings(weekly_sets: dict[str, int], target: tuple[int, int]) -> list[str]:
    low, high = target
    mensajes: list[str] = []
    for muscle, sets in sorted(weekly_sets.items()):
        if sets < low:
            mensajes.append(
                f"{muscle}: {sets} series por semana, por debajo de las {low} "
                f"que suelen hacer falta para este objetivo."
            )
        elif sets > high:
            mensajes.append(
                f"{muscle}: {sets} series por semana, por encima de las {high} "
                f"recomendables."
            )
    return mensajes


def _coverage_warnings(
    days: list[PlannedDay], por_nombre: dict[str, MuscleCandidates]
) -> list[str]:
    """Avisa de los músculos de la rutina que no tienen ninguna medición."""
    sin_lecturas = sorted(
        {
            e.muscle_name
            for d in days
            for e in d.exercises
            if e.source is ExerciseSource.UNMEASURED
        }
    )
    if not sin_lecturas:
        return []
    return [
        f"Sin lecturas de {', '.join(sin_lecturas)}. Esos ejercicios salieron del "
        f"catálogo, no del ranking medido: evalúa esos músculos para afinarlos."
    ]


# ── Utilidades de presentación ───────────────────────────────────────


def weekly_volume_ratio(sets: int, target: tuple[int, int]) -> float:
    """
    Qué tan lleno está el volumen semanal de un músculo, de 0 a 100,
    tomando el tope del rango como el 100%. Para dibujar la barra.
    """
    high = max(target[1], 1)
    return float(min(100.0, 100.0 * sets / high))


def session_minutes(blocks: Iterable[tuple[int, int]]) -> int:
    """
    Duración aproximada de una sesión, en minutos, a partir de pares
    (series, descanso en segundos).

    Cuenta unos 40 segundos de trabajo por serie más su descanso. Es una
    estimación gruesa a propósito: sirve para que el cliente sepa si le
    caben 40 minutos o si va a estar hora y media, no para cronometrar.
    """
    seconds = sum(sets * 40 + sets * rest_sec for sets, rest_sec in blocks)
    return max(1, int(math.ceil(seconds / 60)))
