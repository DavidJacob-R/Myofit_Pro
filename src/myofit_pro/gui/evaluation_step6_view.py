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
    ACCENT_TEAL,
    ACCENT_VIOLET,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    Card,
    EmptyState,
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
