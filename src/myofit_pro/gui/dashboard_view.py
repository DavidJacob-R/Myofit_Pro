"""
Vista general — equivalente a DashboardView.xaml. Resumen de actividad
del entrenador: clientes, evaluaciones recientes y estado de sensores.
Todo calculado de la base de datos real, sin datos inventados.

Las últimas evaluaciones se listan como filas-tarjeta clickeables
(`ListRow`), no como rejilla de etiquetas: abrir el reporte de una
evaluación reciente es la acción más frecuente desde aquí.
"""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon as FIF

from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.theme import (
    ACCENT_AMBER,
    ACCENT_BLUE,
    ACCENT_RED,
    ACCENT_TEAL,
    ACCENT_VIOLET,
    MONTHS_ES,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WEEKDAYS_ES,
    Avatar,
    Card,
    EmptyState,
    IconBadge,
    ListRow,
    Pill,
    StatCard,
    score_color,
)
from myofit_pro.sensors import ConnectionState

_GREETING_CUTOFFS = ((12, "Buenos días"), (19, "Buenas tardes"), (24, "Buenas noches"))


class DashboardView(QWidget):
    session_selected = Signal(int)   # session_id — abrir su reporte

    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._build_ui()
        self.refresh()

        # No hay hook de navegación por sección, así que se refresca
        # periódicamente para que el estado de sensores no quede viejo.
        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    # ── Construcción ─────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 28)
        layout.setSpacing(18)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        layout.addLayout(self._build_greeting())

        stats_row = QHBoxLayout()
        stats_row.setSpacing(14)
        self.clients_card = StatCard(FIF.PEOPLE, ACCENT_VIOLET, "Clientes activos")
        self.evals_month_card = StatCard(FIF.CALENDAR, ACCENT_TEAL, "Este mes")
        self.evals_total_card = StatCard(FIF.PIE_SINGLE, ACCENT_BLUE, "Evaluaciones totales")
        self.avg_score_card = StatCard(FIF.CERTIFICATE, ACCENT_AMBER, "Score promedio")
        for card in (
            self.clients_card,
            self.evals_month_card,
            self.evals_total_card,
            self.avg_score_card,
        ):
            stats_row.addWidget(card)
        layout.addLayout(stats_row)

        layout.addWidget(self._build_sensor_card())
        layout.addWidget(self._build_recent_card(), stretch=1)

    def _build_greeting(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)

        trainer_name = self.state.current_trainer.full_name
        row.addWidget(Avatar(trainer_name, size=52))

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        self.greeting_label = QLabel(f"{self._greeting()}, {trainer_name.split()[0]}")
        self.greeting_label.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 27px; font-weight: 800; "
            f"letter-spacing: -0.6px; background: transparent; border: none;"
        )
        text_col.addWidget(self.greeting_label)

        self.date_label = QLabel(self._today_text())
        self.date_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 13px; background: transparent; border: none;"
        )
        text_col.addWidget(self.date_label)

        row.addLayout(text_col)
        row.addStretch(1)
        return row

    def _build_sensor_card(self) -> Card:
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(14)

        self.sensor_badge = IconBadge(FIF.SPEED_HIGH, ACCENT_TEAL)
        row.addWidget(self.sensor_badge)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        title = QLabel("Sensores sEMG")
        title.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 15px; font-weight: 700; "
            f"background: transparent; border: none;"
        )
        text_col.addWidget(title)

        self.sensor_status_label = QLabel("—")
        self.sensor_status_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12px; background: transparent; border: none;"
        )
        text_col.addWidget(self.sensor_status_label)

        row.addLayout(text_col)
        row.addStretch(1)

        self._battery_row = QHBoxLayout()
        self._battery_row.setSpacing(7)
        row.addLayout(self._battery_row)

        card.body.addLayout(row)
        return card

    def _build_recent_card(self) -> Card:
        card = Card()
        card.add_title("Últimas evaluaciones", "Clic en una para abrir su reporte")

        self.recent_list = QVBoxLayout()
        self.recent_list.setSpacing(8)
        card.body.addLayout(self.recent_list)

        self.recent_empty = EmptyState(
            "📈",
            "Todavía no hay evaluaciones registradas.\n"
            "Ve a 'Nueva evaluación' para hacer la primera.",
        )
        card.body.addWidget(self.recent_empty)
        card.body.addStretch(1)
        return card

    # ── Datos ────────────────────────────────────────────────────────

    def refresh(self) -> None:
        trainer_id = self.state.current_trainer.id
        clients = self.state.client_repo.list_for_trainer(trainer_id)
        sessions = self.state.evaluation_repo.list_for_trainer_with_results(trainer_id)

        self.clients_card.set_value(str(len(clients)))
        self.evals_total_card.set_value(str(len(sessions)))

        now = dt.datetime.now()
        this_month = [
            s for s in sessions
            if s.started_at.month == now.month and s.started_at.year == now.year
        ]
        self.evals_month_card.set_value(str(len(this_month)))

        scored = [s.overall_score for s in sessions if s.overall_score is not None]
        if scored:
            average = sum(scored) / len(scored)
            self.avg_score_card.set_value(f"{average:.0f}%")
            self.avg_score_card.set_value_color(score_color(average))
            self.avg_score_card.set_caption(f"sobre {len(scored)} evaluaciones")
        else:
            self.avg_score_card.set_value("—")
            self.avg_score_card.set_caption("sin evaluaciones completadas")

        self._refresh_sensors()
        self._refresh_recent(sessions[:5])

    def _refresh_sensors(self) -> None:
        sensors = self.state.sensors
        connected = sensors.state == ConnectionState.CONNECTED

        if connected:
            self.sensor_status_label.setText(f"Receptor conectado en {sensors.current_port}")
        else:
            self.sensor_status_label.setText(
                "Receptor desconectado — ve a 'Sensores sEMG' para conectarlo"
            )

        self._clear_layout(self._battery_row)
        if connected:
            for index, label in ((0, "A"), (1, "B")):
                volts = sensors.channels[index].battery_volts
                if volts <= 0:
                    continue
                color = ACCENT_RED if volts < 2.6 else ACCENT_TEAL
                self._battery_row.addWidget(Pill(f"{label}  {volts:.2f} V", color))
        else:
            self._battery_row.addWidget(Pill("Sin conexión", ACCENT_AMBER))

    def _refresh_recent(self, recent) -> None:
        self._clear_layout(self.recent_list)
        self.recent_empty.setVisible(len(recent) == 0)

        for session in recent:
            client = self.state.client_repo.get(session.client_id)
            muscle = self.state.muscle_repo.get(session.muscle_id)
            client_name = client.full_name if client else "—"

            row = ListRow(
                title=client_name,
                subtitle=(
                    f"{muscle.name if muscle else '—'}   ·   "
                    f"{session.started_at.strftime('%d/%m · %H:%M')}"
                ),
                value=(
                    f"{session.overall_score:.0f}%"
                    if session.overall_score is not None
                    else "—"
                ),
                value_caption="score" if session.overall_score is not None else "en curso",
                value_color=score_color(session.overall_score),
                leading=Avatar(client_name, size=40),
                clickable=session.overall_score is not None,
            )
            if session.overall_score is not None:
                row.clicked.connect(lambda sid=session.id: self.session_selected.emit(sid))
            self.recent_list.addWidget(row)

    # ── Utilidades ───────────────────────────────────────────────────

    @staticmethod
    def _greeting() -> str:
        hour = dt.datetime.now().hour
        for cutoff, text in _GREETING_CUTOFFS:
            if hour < cutoff:
                return text
        return "Hola"

    @staticmethod
    def _today_text() -> str:
        today = dt.date.today()
        return (
            f"{WEEKDAYS_ES[today.weekday()].capitalize()} "
            f"{today.day} de {MONTHS_ES[today.month - 1]}"
        )

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
