"""
Comparación del progreso de un cliente entre dos evaluaciones.

QUÉ CONTESTA Y QUÉ NO
=====================

Contesta: ¿este cliente mejoró en este ejercicio desde la última vez, y
la diferencia es lo bastante grande para distinguirla del ruido de
medición?

NO contesta: ¿creció el músculo? El sEMG mide actividad eléctrica, no
tamaño. Esa pregunta la contesta la cinta métrica
(`EvaluationSession.circumference_cm`), y por eso la comparativa la
muestra al lado en vez de deducirla de la señal.

LA TRAMPA QUE ESTE MÓDULO EVITA
===============================

La intuición natural es "más activación = mejor". Es falsa a carga
absoluta fija:

    Semana 0:  MVC 900 µV,  curl con 20 kg → 630 µV → 70% del MVC
    Semana 4:  MVC 1000 µV, curl con 20 kg → 600 µV → 60% del MVC

Ese cliente progresó: está más fuerte (MVC más alto) y hace el mismo
trabajo con menos actividad eléctrica (adaptación neural: el sistema
nervioso aprende a reclutar con menos co-activación). Una app que solo
mire el porcentaje diría que empeoró 10 puntos.

Por eso el veredicto se decide con DOS variables, no una:

    el progreso se lee en el peso;
    la activación dice CÓMO lo está logrando.

Y cuando no hay peso anotado, el módulo lo dice en vez de inventar una
interpretación.

EL UMBRAL
=========

Ninguna diferencia significa nada si es más chica que el error de
medición. El umbral es el cambio mínimo detectable al 95%, calculado con
la repetibilidad del propio cliente (ver `EvaluationSession.repeatability_cv`),
no con un número de la literatura.

Este módulo es lógica pura, sin Qt ni base de datos, para poder probarlo
(ver tests/test_progress.py).
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from enum import Enum

# Repetibilidad de respaldo mientras el cliente no tenga ninguna medida
# propia. Es el valor que la literatura reporta para amplitud sEMG
# normalizada al MVC con electrodos re-colocados, y es deliberadamente
# pesimista: con él la app exige más diferencia para declarar progreso.
CV_POR_DEFECTO = 0.20

# Cuánto más variable es medir en dos días distintos que medir dos veces
# el mismo día.
#
# La app solo puede medir lo segundo sin pedir un protocolo dedicado: el
# Paso 5 calcula el coeficiente de variación de repetir un ejercicio con
# los electrodos ya puestos. Pero la comparativa es entre sesiones, y ahí
# se suma el ruido de haber quitado y vuelto a poner los electrodos, que
# es el dominante.
#
# La literatura reporta del orden de 10% dentro de sesión contra 20%
# entre sesiones, de ahí el factor 2. Es una aproximación explícita, y
# está aquí y no escondida en una fórmula porque es la suposición más
# fuerte del módulo: usar el CV de dentro de sesión tal cual daría un
# umbral demasiado permisivo y la app declararía progreso donde solo hay
# recolocación de electrodos.
FACTOR_ENTRE_SESIONES = 2.0

# Diferencia de peso por debajo de la cual se considera la misma carga.
# Medio kilo es menos que el salto entre mancuernas contiguas.
TOLERANCIA_CARGA_KG = 0.5


class Verdict(str, Enum):
    """
    Lectura de lo que pasó con un ejercicio entre dos evaluaciones.

    El orden de este enum va de mejor a peor noticia, para poder ordenar
    la lista por qué tan buena es la novedad.
    """

    MAS_FUERTE = "mas_fuerte"          # levanta más peso
    MAS_EFICIENTE = "mas_eficiente"    # mismo peso, menos activación
    RECLUTA_MAS = "recluta_mas"        # mismo peso, más activación
    SIN_CAMBIO = "sin_cambio"          # la diferencia no supera el ruido
    MENOS_CARGA = "menos_carga"        # levanta menos peso
    SIN_CARGA = "sin_carga"            # no se puede interpretar: falta el peso
    NUEVO = "nuevo"                    # no se había medido antes


#: Texto que se muestra al entrenador por cada veredicto. `{act}` y
#: `{carga}` se rellenan con las diferencias ya formateadas.
VERDICT_TEXT: dict[Verdict, str] = {
    Verdict.MAS_FUERTE: "Levanta {carga} más",
    Verdict.MAS_EFICIENTE: "Mismo peso con {act} menos de activación: más eficiente",
    Verdict.RECLUTA_MAS: "Mismo peso, {act} más de activación",
    Verdict.SIN_CAMBIO: "Sin cambio detectable (umbral ±{umbral})",
    Verdict.MENOS_CARGA: "Levanta {carga} menos",
    Verdict.SIN_CARGA: "Cambió {act}, pero sin el peso anotado no se puede interpretar",
    Verdict.NUEVO: "Medido por primera vez",
}

#: Qué veredictos son una buena noticia. Se usa para el color y para el
#: resumen de "cuántos ejercicios mejoraron".
VERDICTS_POSITIVOS = frozenset(
    {Verdict.MAS_FUERTE, Verdict.MAS_EFICIENTE, Verdict.RECLUTA_MAS}
)


# ── Fotografía de una sesión ─────────────────────────────────────────


@dataclass(frozen=True)
class ExerciseSnapshot:
    """Un ejercicio tal como quedó medido en una sesión."""

    exercise_id: int
    name: str
    activation_pct: float
    measurements: int = 1
    load_kg: float | None = None
    rank: int = 0  # posición dentro de esa sesión, 1 = el que más activó


@dataclass(frozen=True)
class SessionSnapshot:
    """Una evaluación completa, reducida a lo que hace falta comparar."""

    session_id: int
    date: dt.datetime
    muscle_id: int
    muscle_name: str
    goal: str
    exercises: tuple[ExerciseSnapshot, ...] = ()
    circumference_cm: float | None = None
    repeatability_cv: float | None = None
    balance_gap: float | None = None  # |A − B| promediado en la sesión
    overall_score: float | None = None

    def find(self, exercise_id: int) -> ExerciseSnapshot | None:
        for exercise in self.exercises:
            if exercise.exercise_id == exercise_id:
                return exercise
        return None


# ── Resultado de la comparación ──────────────────────────────────────


@dataclass(frozen=True)
class ExerciseComparison:
    exercise_id: int
    name: str
    before: ExerciseSnapshot | None
    after: ExerciseSnapshot
    threshold: float          # cambio mínimo detectable, en puntos
    verdict: Verdict

    @property
    def delta_activation(self) -> float | None:
        if self.before is None:
            return None
        return self.after.activation_pct - self.before.activation_pct

    @property
    def delta_load(self) -> float | None:
        if self.before is None or self.before.load_kg is None or self.after.load_kg is None:
            return None
        return self.after.load_kg - self.before.load_kg

    @property
    def delta_rank(self) -> int | None:
        """Positivo = subió puestos en el ranking (1 es el mejor)."""
        if self.before is None or not self.before.rank or not self.after.rank:
            return None
        return self.before.rank - self.after.rank

    @property
    def is_significant(self) -> bool:
        """True si la diferencia de activación supera el ruido de medición."""
        delta = self.delta_activation
        return delta is not None and abs(delta) >= self.threshold

    @property
    def is_positive(self) -> bool:
        return self.verdict in VERDICTS_POSITIVOS

    def message(self) -> str:
        delta = self.delta_activation
        carga = self.delta_load
        return VERDICT_TEXT[self.verdict].format(
            act=f"{abs(delta):.0f} puntos" if delta is not None else "—",
            carga=f"{abs(carga):.1f} kg".replace(".0 kg", " kg") if carga is not None else "—",
            umbral=f"{self.threshold:.0f}",
        )


@dataclass(frozen=True)
class ProgressReport:
    """Comparación completa entre las dos últimas evaluaciones de un músculo."""

    muscle_id: int
    muscle_name: str
    before: SessionSnapshot | None
    after: SessionSnapshot
    comparisons: tuple[ExerciseComparison, ...] = ()
    cv_used: float = CV_POR_DEFECTO
    cv_is_measured: bool = False

    @property
    def is_first(self) -> bool:
        """True si todavía no hay con qué comparar."""
        return self.before is None

    @property
    def days_between(self) -> int | None:
        if self.before is None:
            return None
        return (self.after.date - self.before.date).days

    @property
    def delta_circumference(self) -> float | None:
        if (
            self.before is None
            or self.before.circumference_cm is None
            or self.after.circumference_cm is None
        ):
            return None
        return self.after.circumference_cm - self.before.circumference_cm

    @property
    def delta_balance(self) -> float | None:
        """
        Cambio en el desbalance entre canales. Negativo es bueno: las dos
        porciones del músculo se activan más parejo que antes.

        Es de lo más sólido que se puede comparar entre sesiones, porque
        es un cociente entre dos sensores de la MISMA sesión: la ganancia
        del día (piel, colocación de electrodos) afecta igual a los dos y
        se cancela al restarlos.
        """
        if (
            self.before is None
            or self.before.balance_gap is None
            or self.after.balance_gap is None
        ):
            return None
        return self.after.balance_gap - self.before.balance_gap

    @property
    def improved(self) -> tuple[ExerciseComparison, ...]:
        return tuple(c for c in self.comparisons if c.is_positive)

    @property
    def uninterpretable(self) -> tuple[ExerciseComparison, ...]:
        """Los que cambiaron pero sin peso anotado para leer el cambio."""
        return tuple(c for c in self.comparisons if c.verdict is Verdict.SIN_CARGA)

    def headline(self) -> str:
        """
        Una frase para encabezar la comparación, honesta con lo que se
        puede afirmar.
        """
        if self.is_first:
            return (
                "Primera evaluación de este músculo. La próxima ya se podrá "
                "comparar contra esta."
            )

        mejoraron = len(self.improved)
        total = len(self.comparisons)
        if total == 0:
            return "No hay ejercicios medidos en ambas evaluaciones para comparar."

        dias = self.days_between
        cuando = f" en {dias} días" if dias else ""

        if mejoraron == 0:
            return f"Ningún ejercicio mejoró por encima del ruido de medición{cuando}."
        return f"{mejoraron} de {total} ejercicios mejoraron{cuando}."


# ── Cálculo ──────────────────────────────────────────────────────────


def minimal_detectable_change(
    cv: float, baseline: float, repeats: int = 1, between_sessions: bool = True
) -> float:
    """
    Cambio mínimo detectable al 95% de confianza, en puntos de activación.

    Es el umbral por debajo del cual una diferencia NO se puede
    distinguir del ruido. Fórmula estándar de medición clínica repetida:

        CMD95 = 1.96 × √2 × error estándar de medición

    El error estándar baja con la raíz del número de mediciones, que es
    la razón por la que medir dos veces ayuda bastante y medir diez ya
    casi no.

    `between_sessions` aplica `FACTOR_ENTRE_SESIONES`: el CV que la app
    mide es el de repetir dentro de una sesión, y comparar entre sesiones
    tiene más ruido. Ver la nota de esa constante.
    """
    if cv <= 0 or baseline <= 0:
        return 0.0
    efectivo = cv * (FACTOR_ENTRE_SESIONES if between_sessions else 1.0)
    sem = baseline * efectivo / math.sqrt(max(repeats, 1))
    return float(1.96 * math.sqrt(2) * sem)


def classify(
    delta_activation: float,
    delta_load: float | None,
    threshold: float,
) -> Verdict:
    """
    Decide qué pasó con un ejercicio entre dos mediciones.

    El orden de las preguntas importa y es la parte con criterio del
    módulo:

    1. ¿Hay peso anotado? Sin él no se puede interpretar un cambio de
       activación, así que se dice y no se adivina.
    2. ¿Cambió el peso? Entonces el progreso está ahí, sin importar la
       activación: levantar más es levantar más.
    3. Mismo peso: ¿el cambio de activación supera el ruido? Si no, no
       hay nada que reportar.
    4. Mismo peso y cambio real: menos activación es más eficiencia
       (adaptación neural), más activación es más reclutamiento.
    """
    if delta_load is None:
        if abs(delta_activation) < threshold:
            return Verdict.SIN_CAMBIO
        return Verdict.SIN_CARGA

    if delta_load > TOLERANCIA_CARGA_KG:
        return Verdict.MAS_FUERTE
    if delta_load < -TOLERANCIA_CARGA_KG:
        return Verdict.MENOS_CARGA

    if abs(delta_activation) < threshold:
        return Verdict.SIN_CAMBIO
    return Verdict.MAS_EFICIENTE if delta_activation < 0 else Verdict.RECLUTA_MAS


def resolve_cv(sessions: list[SessionSnapshot]) -> tuple[float, bool]:
    """
    La repetibilidad que se usa para este cliente y este músculo.

    Promedia las repetibilidades medidas en sus sesiones. Si nunca repitió
    un ejercicio en la misma sesión, no hay dato propio y se cae al valor
    de la literatura, que es pesimista a propósito: sin saber qué tan
    repetible es tu medición, lo responsable es exigir más diferencia
    antes de declarar progreso.

    Devuelve (cv, es_medido) para que la pantalla pueda decir de dónde
    salió el número.
    """
    medidos = [s.repeatability_cv for s in sessions if s.repeatability_cv]
    if not medidos:
        return (CV_POR_DEFECTO, False)
    return (sum(medidos) / len(medidos), True)


def compare(
    before: SessionSnapshot | None,
    after: SessionSnapshot,
    cv: float = CV_POR_DEFECTO,
    cv_is_measured: bool = False,
) -> ProgressReport:
    """
    Compara dos evaluaciones del mismo músculo, ejercicio por ejercicio.

    Solo entran los ejercicios medidos en la sesión más reciente: la
    comparativa habla del presente. Los que se midieron antes y ya no se
    repitieron simplemente no aparecen, porque no hay nada nuevo que
    decir de ellos.
    """
    comparisons: list[ExerciseComparison] = []

    for actual in after.exercises:
        previo = before.find(actual.exercise_id) if before else None

        if previo is None:
            comparisons.append(
                ExerciseComparison(
                    exercise_id=actual.exercise_id,
                    name=actual.name,
                    before=None,
                    after=actual,
                    threshold=0.0,
                    verdict=Verdict.NUEVO,
                )
            )
            continue

        # La base del umbral es el promedio de las dos mediciones: usar
        # solo una haría que el umbral dependiera de cuál se tomó de
        # referencia.
        baseline = (previo.activation_pct + actual.activation_pct) / 2.0
        threshold = minimal_detectable_change(
            cv, baseline, repeats=min(previo.measurements, actual.measurements)
        )

        delta_act = actual.activation_pct - previo.activation_pct
        delta_load = (
            actual.load_kg - previo.load_kg
            if previo.load_kg is not None and actual.load_kg is not None
            else None
        )

        comparisons.append(
            ExerciseComparison(
                exercise_id=actual.exercise_id,
                name=actual.name,
                before=previo,
                after=actual,
                threshold=threshold,
                verdict=classify(delta_act, delta_load, threshold),
            )
        )

    # Primero las buenas noticias, luego lo que no se pudo interpretar,
    # al final lo que no cambió. Dentro de cada grupo, por activación.
    orden = list(Verdict)
    comparisons.sort(key=lambda c: (orden.index(c.verdict), -c.after.activation_pct))

    return ProgressReport(
        muscle_id=after.muscle_id,
        muscle_name=after.muscle_name,
        before=before,
        after=after,
        comparisons=tuple(comparisons),
        cv_used=cv,
        cv_is_measured=cv_is_measured,
    )


def trend_for(
    sessions: list[SessionSnapshot], exercise_id: int
) -> list[tuple[dt.datetime, float]]:
    """
    Historia completa de un ejercicio: (fecha, activación) de cada sesión
    donde se midió, de la más vieja a la más reciente.

    La comparativa grande solo enseña las dos últimas, pero a la cuarta
    evaluación la trayectoria dice más que el último salto: tres subidas
    seguidas son una tendencia; una subida sola puede ser el día.
    """
    puntos = []
    for session in sorted(sessions, key=lambda s: s.date):
        encontrado = session.find(exercise_id)
        if encontrado is not None:
            puntos.append((session.date, encontrado.activation_pct))
    return puntos
