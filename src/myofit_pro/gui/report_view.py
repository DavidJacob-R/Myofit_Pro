"""
Reporte muscular — equivalente a ReportView.xaml. Muestra el detalle de
UNA evaluación específica. Se llega aquí desde Historial, desde la Vista
general o desde el perfil de un cliente, vía `load_session()`.

El score es el protagonista (anillo grande), y el balance entre canales
se lee como dos barras comparables en vez de dos porcentajes sueltos:
un desbalance A/B es justo lo que el entrenador busca de un vistazo.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon as FIF

from myofit_pro.gui.theme import (
    ACCENT_AMBER,
    ACCENT_BLUE,
    ACCENT_TEAL,
    ACCENT_VIOLET,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    Avatar,
    Card,
    EmptyState,
    MeterBar,
    PageHeader,
    Pill,
    ScoreRing,
    StatCard,
    format_date_es,
    goal_color,
)


class ReportView(QWidget):
    def __init__(self, state, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(28, 22, 28, 28)
        self._layout.setSpacing(18)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._show_empty_state()

    def _clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _show_empty_state(self) -> None:
        self._clear()
        self._layout.addWidget(PageHeader("Reporte muscular"))
        self._layout.addWidget(
            EmptyState(
                "📄",
                "Selecciona una evaluación del historial o del perfil\n"
                "de un cliente para ver su reporte detallado.",
            )
        )

    def load_session(self, session_id: int) -> None:
        session = self.state.evaluation_repo.get_with_results(session_id)
        self._clear()

        if session is None:
            self._layout.addWidget(PageHeader("Reporte muscular"))
            self._layout.addWidget(EmptyState("❓", "No se encontró esa evaluación."))
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

        client_name = client.full_name if client else "Cliente desconocido"
        row.addWidget(Avatar(client_name, size=64), alignment=Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(8)

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

        if result is not None:
            summary = QLabel(
                f"{result.series_count} repeticiones registradas  ·  "
                f"activación promedio {result.avg_activation_pct:.0f}%"
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
                FIF.HISTORY, ACCENT_BLUE, "Repeticiones",
                str(result.series_count) if result else "—",
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
                FIF.STOP_WATCH, ACCENT_AMBER, "Duración de la serie",
                f"{reading.duration_sec:.1f} s" if reading else "—",
            )
        )
        return row
