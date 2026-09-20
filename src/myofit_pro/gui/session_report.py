"""
Cuerpo del reporte de UNA evaluación, en un solo lugar.

Antes esto estaba escrito dos veces: `report_view.py` (la sección
"Reporte muscular" del menú) y `evaluation_step6_view.py` (el último
paso del wizard) armaban el mismo hero, el mismo balance entre canales y
la misma fila de métricas con código duplicado, y ya habían empezado a
divergir: el ranking de ejercicios solo existía en el paso 6 y la
duración de la serie usaba colores distintos en cada uno.

Ahora las dos pantallas montan este widget y le pasan un `session_id`.
Lo único que cambia entre ellas es el `headline` (el paso 6 anuncia
"Evaluación completada"; el reporte no necesita anunciarlo) y de dónde
llega el botón de volver, que lo pone quien lo usa.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon as FIF

from myofit_pro.gui.theme import (
    ACCENT_AMBER,
    ACCENT_BLUE,
    ACCENT_LIME,
    ACCENT_TEAL,
    ACCENT_VIOLET,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    Avatar,
    Card,
    EmptyState,
    IconBadge,
    ListRow,
    MeterBar,
    Pill,
    ScoreRing,
    StatCard,
    clear_layout,
    format_date_es,
    goal_color,
)


def plural_mediciones(n: int) -> str:
    """El plural de "medición" pierde el acento: mediciones, no mediciónes."""
    return f"{n} medición" if n == 1 else f"{n} mediciones"


class SessionReportBody(QWidget):
    """
    Detalle completo de una evaluación: encabezado con score, ranking de
    ejercicios, balance entre canales y métricas de la sesión.

    No tiene navegación ni encabezado de página: es solo el contenido,
    para que quien lo monte decida el marco (una sección del menú, un
    paso de wizard).
    """

    def __init__(self, state, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._headline = ""

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(16)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    # ── API pública ──────────────────────────────────────────────────

    def load(self, session_id: int | None, headline: str = "") -> None:
        """
        Dibuja la evaluación indicada. `headline` es la línea corta que
        va arriba del nombre del cliente ("Evaluación completada" en el
        wizard); vacía la omite.
        """
        self._headline = headline
        clear_layout(self._layout)

        if session_id is None:
            self._layout.addWidget(
                EmptyState(
                    "📄",
                    "Selecciona una evaluación del historial o del perfil\n"
                    "de un cliente para ver su reporte detallado.",
                )
            )
            return

        session = self.state.evaluation_repo.get_with_results(session_id)
        if session is None:
            self._layout.addWidget(EmptyState("❓", "No se encontró esa evaluación."))
            return

        client = self.state.client_repo.get(session.client_id)
        muscle = self.state.muscle_repo.get(session.muscle_id)
        mvc = (
            self.state.calibration_repo.get(session.mvc_calibration_id)
            if session.mvc_calibration_id
            else None
        )
        readings = [r for result in session.results for r in result.readings]

        self._layout.addWidget(self._build_hero(session, client, muscle))

        # El ranking va antes que nada: es lo que el entrenador se lleva
        # de la batería para armar la rutina.
        if len(session.results) > 1:
            self._layout.addWidget(self._build_ranking_card(session.results))

        if readings:
            self._layout.addWidget(self._build_balance_card(readings))

        fatiga = self._fatigue_card(session.id)
        if fatiga is not None:
            self._layout.addWidget(fatiga)

        self._layout.addLayout(self._build_stats_row(session.results, mvc))

        if not session.results:
            self._layout.addWidget(
                EmptyState("📭", "Esta evaluación no tiene resultados registrados.")
            )

        self._layout.addStretch(1)

    # ── Bloques ──────────────────────────────────────────────────────

    def _build_hero(self, session, client, muscle) -> Card:
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(20)

        client_name = client.full_name if client else "Cliente desconocido"
        row.addWidget(Avatar(client_name, size=64), alignment=Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(8)

        if self._headline:
            eyebrow = QLabel(self._headline)
            eyebrow.setStyleSheet(
                f"color: {ACCENT_TEAL}; font-size: 11px; font-weight: 800; "
                f"letter-spacing: 0.8px; background: transparent; border: none;"
            )
            info.addWidget(eyebrow)

        name_label = QLabel(client_name)
        name_label.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 26px; font-weight: 800; "
            f"letter-spacing: -0.6px; background: transparent; border: none;"
        )
        info.addWidget(name_label)

        pills = QHBoxLayout()
        pills.setSpacing(7)
        pills.addWidget(Pill(muscle.name if muscle else "—", ACCENT_TEAL))
        pills.addWidget(Pill(session.goal, goal_color(session.goal)))
        pills.addStretch(1)
        info.addLayout(pills)

        date_label = QLabel(format_date_es(session.started_at, with_time=True))
        date_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 13px; background: transparent; border: none;"
        )
        info.addWidget(date_label)

        if session.results:
            # El promedio es sobre TODAS las series de la batería, no
            # sobre la primera. Con varios ejercicios medidos, enseñar el
            # valor de uno solo y llamarlo "promedio" es sencillamente
            # falso, y además cambia según cuál se haya grabado primero.
            promedio = sum(r.avg_activation_pct for r in session.results) / len(session.results)
            summary = QLabel(
                f"{len(session.results)} "
                f"{'serie registrada' if len(session.results) == 1 else 'series registradas'}"
                f"  ·  activación promedio {promedio:.0f}%"
            )
            summary.setStyleSheet(
                f"color: {TEXT_MUTED}; font-size: 12px; background: transparent; border: none;"
            )
            info.addWidget(summary)

        info.addStretch(1)
        row.addLayout(info, stretch=1)

        row.addWidget(
            ScoreRing(session.overall_score, size=150, caption="score general"),
            alignment=Qt.AlignmentFlag.AlignTop,
        )

        card.body.addLayout(row)
        return card

    def _build_ranking_card(self, results) -> Card:
        """
        Ejercicios ordenados por activación, promediando las mediciones
        repetidas del mismo ejercicio.

        Se destacan los tres primeros y no solo el primero. Medido por
        simulación (`ml/within_subject.py`), con una repetibilidad del
        10% el ejercicio que queda primero es de verdad el mejor solo el
        66% de las veces, pero el mejor real está entre los tres
        primeros el 95% de las veces. Recomendar tres es una afirmación
        que la medición sostiene; recomendar uno no.
        """
        ranking = rank_results(self.state.exercise_repo, results)

        # La etiqueta de recomendado solo tiene sentido si hubo de dónde
        # escoger. Con tres ejercicios medidos, marcar los tres como
        # recomendados no descarta nada y no informa nada.
        hay_donde_escoger = len(ranking) > 3

        card = Card()
        card.add_title("Ranking de ejercicios")

        for position, entry in enumerate(ranking, start=1):
            recomendado = hay_donde_escoger and position <= 3
            accent = ACCENT_LIME if position <= 3 else TEXT_SECONDARY

            subtitle = plural_mediciones(entry.measurements)
            if entry.measurements > 1:
                subtitle += f"   ·   rango de {entry.spread:.0f} puntos entre mediciones"

            card.body.addWidget(
                ListRow(
                    title=entry.name,
                    subtitle=subtitle,
                    value=f"{entry.mean:.0f}%",
                    value_caption="activación",
                    value_color=accent,
                    leading=IconBadge(str(position), accent, size=36),
                    pill=("Recomendado", ACCENT_LIME) if recomendado else None,
                    clickable=False,
                )
            )

        return card

    def _build_balance_card(self, readings) -> Card:
        """
        Balance A/B promediado sobre todas las series de la sesión.

        Un desbalance entre las dos porciones del músculo es una
        característica de cómo esa persona lo recluta, no de una serie
        suelta: promediar la batería completa lo deja ver sin el ruido de
        una repetición mal hecha.
        """
        n = len(readings)
        a = sum(r.activation_a_pct for r in readings) / n
        b = sum(r.activation_b_pct for r in readings) / n

        card = Card()
        card.add_title(
            "Balance entre canales",
            f"Promedio de {n} series" if n > 1 else "",
        )
        card.body.addLayout(self._channel_row("Sensor A", a, ACCENT_TEAL))
        card.body.addLayout(self._channel_row("Sensor B", b, ACCENT_BLUE))

        gap = abs(a - b)
        verdict = QLabel(
            f"Diferencia de {gap:.0f} puntos entre canales"
            + ("  ·  activación pareja" if gap <= 10 else "  ·  revisar compensación")
        )
        verdict.setStyleSheet(
            f"color: {ACCENT_TEAL if gap <= 10 else ACCENT_AMBER}; font-size: 12px; "
            f"font-weight: 600; background: transparent; border: none;"
        )
        card.body.addWidget(verdict)
        return card

    def _fatigue_card(self, session_id: int) -> Card | None:
        """
        Fatiga durante la serie, leída del espectro de la señal grabada.

        La frecuencia mediana del EMG cae conforme el músculo se fatiga.
        Se calcula sobre la ráfaga guardada en DuckDB; si esa sesión no
        tiene señal grabada, la tarjeta no se dibuja.
        """
        import numpy as np

        from myofit_pro.ml.fatigue import fatigue_from_signal

        try:
            df = self.state.burst_store.load_bursts_for_session(session_id)
        except Exception:
            return None
        if df is None or len(df) == 0:
            return None

        fila = df.iloc[0]
        señal = fila.get("filtered")
        if señal is None or len(señal) < 2:
            return None

        fs = float(fila.get("sample_rate_hz") or 1000.0)
        resultado = fatigue_from_signal(np.asarray(señal, dtype=float), fs)
        if resultado.windows == 0:
            return None

        color = ACCENT_AMBER if resultado.is_fatiguing else ACCENT_TEAL

        card = Card()
        card.add_title("Fatiga durante la serie")

        row = QHBoxLayout()
        row.setSpacing(12)

        valor = QLabel(f"{resultado.drop_pct:+.0f}%")
        valor.setStyleSheet(
            f"color: {color}; font-size: 24px; font-weight: 800; "
            f"letter-spacing: -0.4px; background: transparent; border: none;"
        )
        row.addWidget(valor)

        texto = QLabel(resultado.summary)
        texto.setWordWrap(True)
        texto.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12px; "
            f"background: transparent; border: none;"
        )
        row.addWidget(texto, stretch=1)
        card.body.addLayout(row)
        return card

    @staticmethod
    def _channel_row(label: str, value: float, color: str) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(6)

        head = QHBoxLayout()
        name = QLabel(label)
        name.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12px; font-weight: 700; "
            f"background: transparent; border: none;"
        )
        head.addWidget(name)
        head.addStretch(1)

        amount = QLabel(f"{value:.0f}%")
        amount.setStyleSheet(
            f"color: {color}; font-size: 15px; font-weight: 800; "
            f"background: transparent; border: none;"
        )
        head.addWidget(amount)
        col.addLayout(head)
        col.addWidget(MeterBar(value, color))
        return col

    def _build_stats_row(self, results, mvc) -> QHBoxLayout:
        """
        Métricas de la sesión completa.

        Todas se calculan sobre la batería entera y no sobre la primera
        serie: el pico de la sesión es el mayor de todas, y las
        repeticiones son las que se hicieron en total. Leer solo la
        primera daba números que cambiaban según el orden de grabación.
        """
        row = QHBoxLayout()
        row.setSpacing(14)

        pico = max((r.peak_activation_pct for r in results), default=None)
        repeticiones = sum(r.series_count for r in results)
        duracion = sum(
            reading.duration_sec for r in results for reading in r.readings
        )

        row.addWidget(
            StatCard(
                FIF.SPEED_HIGH, ACCENT_TEAL, "MVC de referencia",
                f"{mvc.mvc_value_uv:.0f} µV" if mvc else "—",
            )
        )
        row.addWidget(
            StatCard(
                FIF.HISTORY, ACCENT_BLUE, "Repeticiones",
                str(repeticiones) if results else "—",
            )
        )
        row.addWidget(
            StatCard(
                FIF.MARKET, ACCENT_VIOLET, "Activación pico",
                f"{pico:.0f}%" if pico is not None else "—",
            )
        )
        row.addWidget(
            StatCard(
                FIF.STOP_WATCH, ACCENT_AMBER, "Tiempo medido",
                f"{duracion:.0f} s" if duracion else "—",
            )
        )
        return row


class RankedExercise:
    """Un ejercicio del ranking, ya promediado sobre sus repeticiones."""

    def __init__(self, exercise_id: int | None, name: str, values: list[float]):
        self.exercise_id = exercise_id
        self.name = name
        self.values = values

    @property
    def mean(self) -> float:
        return sum(self.values) / len(self.values)

    @property
    def measurements(self) -> int:
        return len(self.values)

    @property
    def spread(self) -> float:
        return max(self.values) - min(self.values)


def rank_results(exercise_repo, results) -> list[RankedExercise]:
    """
    Agrupa los resultados de una sesión por ejercicio y los ordena por
    activación promedio, de mayor a menor.

    Se promedia antes de ordenar a propósito: una serie suelta puede
    salir alta por casualidad, y el promedio de las repeticiones es lo
    que hace que el orden signifique algo.
    """
    grouped: dict[tuple[int | None, str], list[float]] = {}
    for result in results:
        exercise = (
            exercise_repo.get(result.exercise_id) if result.exercise_id else None
        )
        key = (result.exercise_id, exercise.name if exercise else "Sin ejercicio registrado")
        grouped.setdefault(key, []).append(result.avg_activation_pct)

    ranked = [
        RankedExercise(exercise_id, name, values)
        for (exercise_id, name), values in grouped.items()
    ]
    ranked.sort(key=lambda entry: entry.mean, reverse=True)
    return ranked
