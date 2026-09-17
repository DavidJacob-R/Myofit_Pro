"""
Paso 6 del wizard — Reporte de la evaluación recién completada.

Lee la EvaluationSession + ExerciseResult + EmgReading ya guardados en
el Paso 5 (ver evaluation_step5_view.py) y los muestra con el mismo
lenguaje visual que el Reporte muscular: anillo de score como
protagonista y barras comparables para el balance entre canales. No
inventa datos: si la sesión no se guardó, lo dice claramente.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon as FIF

from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.wizard_step import WizardStep
from myofit_pro.gui.theme import (
    ACCENT_AMBER,
    ACCENT_BLUE,
    ACCENT_LIME,
    ACCENT_TEAL,
    ACCENT_VIOLET,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    Card,
    EmptyState,
    IconBadge,
    ListRow,
    MeterBar,
    Pill,
    ScoreRing,
    StatCard,
    clear_layout,
    goal_color,
)


class EvaluationStep6View(WizardStep):
    start_new_evaluation = Signal()
    # Último paso: el botón del pie ya no avanza, arranca otra evaluación.
    CONTINUE_LABEL = "Nueva evaluación"

    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(16)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._load_report()

    def _load_report(self) -> None:
        clear_layout(self._layout)

        session_id = self.state.active_session_id
        if session_id is None:
            self._layout.addWidget(
                EmptyState("🤔", "No hay una sesión de evaluación activa para mostrar.")
            )
            return

        session = self.state.evaluation_repo.get_with_results(session_id)
        if session is None:
            self._layout.addWidget(
                EmptyState("❓", "No se encontró la sesión en la base de datos.")
            )
            return

        client = self.state.client_repo.get(session.client_id)
        muscle = self.state.muscle_repo.get(session.muscle_id)
        mvc = (
            self.state.calibration_repo.get(session.mvc_calibration_id)
            if session.mvc_calibration_id
            else None
        )
        result = session.results[0] if session.results else None
        reading = result.readings[0] if result and result.readings else None

        self._layout.addWidget(self._build_hero(session, client, muscle, result))

        # El ranking es el resultado de la batería y va antes que nada:
        # es lo que el entrenador se lleva para armar la rutina.
        if len(session.results) > 1:
            self._layout.addWidget(self._build_ranking_card(session.results))

        if reading is not None:
            self._layout.addWidget(self._build_balance_card(reading))

        self._layout.addLayout(self._build_stats_row(result, mvc, reading))

        if result is None:
            self._layout.addWidget(
                EmptyState("📭", "Esta evaluación no tiene resultados registrados.")
            )

        self._layout.addStretch(1)

    # ── Bloques ──────────────────────────────────────────────────────

    def _build_hero(self, session, client, muscle, result) -> Card:
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(20)

        info = QVBoxLayout()
        info.setSpacing(8)

        title = QLabel("Evaluación completada")
        title.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 26px; font-weight: 800; "
            f"letter-spacing: -0.6px; background: transparent; border: none;"
        )
        info.addWidget(title)

        who = QLabel(client.full_name if client else "—")
        who.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 14px; background: transparent; border: none;"
        )
        info.addWidget(who)

        pills = QHBoxLayout()
        pills.setSpacing(7)
        pills.addWidget(Pill(muscle.name if muscle else "—", ACCENT_TEAL))
        pills.addWidget(Pill(session.goal, goal_color(session.goal)))
        pills.addStretch(1)
        info.addLayout(pills)

        if result is not None:
            summary = QLabel(
                f"{result.series_count} repeticiones  ·  "
                f"activación promedio {result.avg_activation_pct:.0f}%"
            )
            summary.setStyleSheet(
                f"color: {TEXT_SECONDARY}; font-size: 12px; "
                f"background: transparent; border: none;"
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
        by_exercise: dict[str, list[float]] = {}
        for result in results:
            exercise = (
                self.state.exercise_repo.get(result.exercise_id)
                if result.exercise_id
                else None
            )
            name = exercise.name if exercise else "Sin ejercicio registrado"
            by_exercise.setdefault(name, []).append(result.avg_activation_pct)

        ranking = sorted(
            by_exercise.items(), key=lambda item: sum(item[1]) / len(item[1]), reverse=True
        )

        # La etiqueta de recomendado solo tiene sentido si hubo de dónde
        # escoger. Con tres ejercicios medidos, marcar los tres como
        # recomendados no descarta nada y no informa nada.
        hay_donde_escoger = len(ranking) > 3

        card = Card()
        card.add_title(
            "Ranking de ejercicios",
            (
                "Para este cliente y este músculo. Los tres primeros son los recomendables."
                if hay_donde_escoger
                else f"Para este cliente y este músculo. Se midieron {len(ranking)}, "
                     "con más ejercicios en el catálogo el orden distingue mejor."
            ),
        )

        for position, (name, values) in enumerate(ranking, start=1):
            mean = sum(values) / len(values)
            recomendado = hay_donde_escoger and position <= 3
            accent = ACCENT_LIME if position <= 3 else TEXT_SECONDARY

            subtitle = (
                f"{len(values)} medición" if len(values) == 1
                else f"{len(values)} mediciones"
            )
            if len(values) > 1:
                spread = max(values) - min(values)
                subtitle += f"   ·   rango de {spread:.0f} puntos entre mediciones"

            card.body.addWidget(
                ListRow(
                    title=name,
                    subtitle=subtitle,
                    value=f"{mean:.0f}%",
                    value_caption="activación",
                    value_color=accent,
                    leading=IconBadge(str(position), accent, size=36),
                    pill=("Recomendado", ACCENT_LIME) if recomendado else None,
                    clickable=False,
                )
            )

        return card

    def _build_balance_card(self, reading) -> Card:
        card = Card()
        card.add_title(
            "Balance entre canales",
            "Qué tanto aportó cada sensor respecto a su MVC de referencia",
        )
        card.body.addLayout(
            self._channel_row("Sensor A", reading.activation_a_pct, ACCENT_TEAL)
        )
        card.body.addLayout(
            self._channel_row("Sensor B", reading.activation_b_pct, ACCENT_BLUE)
        )

        gap = abs(reading.activation_a_pct - reading.activation_b_pct)
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

    def _build_stats_row(self, result, mvc, reading) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(
            StatCard(
                FIF.SPEED_HIGH, ACCENT_TEAL, "MVC de referencia",
                f"{mvc.mvc_value_uv:.0f} µV" if mvc else "—",
            )
        )
        row.addWidget(
            StatCard(
                FIF.MARKET, ACCENT_VIOLET, "Activación pico",
                f"{result.peak_activation_pct:.0f}%" if result else "—",
            )
        )
        row.addWidget(
            StatCard(
                FIF.STOP_WATCH, ACCENT_BLUE, "Duración de la serie",
                f"{reading.duration_sec:.1f} s" if reading else "—",
            )
        )
        return row

    def on_enter(self) -> None:
        self._load_report()

    def on_continue(self) -> bool:
        """
        En el último paso el botón del pie no avanza: arranca una
        evaluación nueva. Devuelve False para que el contenedor no
        intente pasar a un paso 7 que no existe.
        """
        self.start_new_evaluation.emit()
        return False
