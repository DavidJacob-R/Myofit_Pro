"""
Perfil de un cliente — equivalente a ClientProfileView.xaml de la
versión C#.

El historial ya NO es una tabla: cada evaluación es una fila-tarjeta
(`ListRow`) con su estado y su score a color, clickeable para abrir el
reporte. El encabezado es un "hero" con avatar, objetivo y el anillo
de score de la última evaluación.
"""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import PrimaryPushButton, PushButton

from myofit_pro.database.models import EvaluationStatus
from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.theme import (
    ACCENT_AMBER,
    ACCENT_RED,
    ACCENT_TEAL,
    ACCENT_VIOLET,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    Avatar,
    Card,
    EmptyState,
    IconBadge,
    ListRow,
    Pill,
    ScoreRing,
    StatCard,
    goal_color,
    score_color,
)


class ClientProfileView(QWidget):
    back_requested = Signal()
    start_evaluation_requested = Signal(object)   # Client
    view_report_requested = Signal(int)           # session_id

    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._client = None
        self._sessions = []
        self._build_ui()

    # ── Construcción ─────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        host = QWidget()
        host.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(28, 22, 28, 28)
        layout.setSpacing(18)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        back_btn = PushButton("←   Volver a clientes")
        back_btn.clicked.connect(self.back_requested.emit)
        back_btn.setMaximumWidth(190)
        layout.addWidget(back_btn)

        layout.addWidget(self._build_hero())
        layout.addLayout(self._build_stats_row())
        layout.addWidget(self._build_history_card(), stretch=1)
        layout.addWidget(self._build_mvc_card())

        scroll.setWidget(host)
        outer.addWidget(scroll)

    def _build_hero(self) -> Card:
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(18)

        self._avatar_host = QVBoxLayout()
        self._avatar_host.setAlignment(Qt.AlignmentFlag.AlignTop)
        row.addLayout(self._avatar_host)

        info_col = QVBoxLayout()
        info_col.setSpacing(8)

        self.name_label = QLabel("—")
        self.name_label.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 28px; font-weight: 800; "
            f"letter-spacing: -0.6px; background: transparent; border: none;"
        )
        info_col.addWidget(self.name_label)

        self._pill_row = QHBoxLayout()
        self._pill_row.setSpacing(7)
        self._pill_row.addStretch(1)
        info_col.addLayout(self._pill_row)

        self.notes_label = QLabel("")
        self.notes_label.setWordWrap(True)
        self.notes_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 13px; background: transparent; border: none;"
        )
        info_col.addWidget(self.notes_label)

        info_col.addStretch(1)

        new_eval_btn = PrimaryPushButton("＋   Nueva evaluación")
        new_eval_btn.clicked.connect(self._on_new_evaluation_clicked)
        new_eval_btn.setMaximumWidth(230)
        info_col.addWidget(new_eval_btn)

        row.addLayout(info_col, stretch=1)

        self.score_ring = ScoreRing(None, size=132, caption="último score")
        row.addWidget(self.score_ring, alignment=Qt.AlignmentFlag.AlignTop)

        card.body.addLayout(row)
        return card

    def _build_stats_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)
        self.evals_card = StatCard(FIF.DOCUMENT, ACCENT_VIOLET, "Evaluaciones", "0")
        self.muscles_card = StatCard(FIF.CALORIES, ACCENT_TEAL, "Músculos evaluados", "0")
        self.last_eval_card = StatCard(FIF.CALENDAR, ACCENT_AMBER, "Última evaluación", "—")
        row.addWidget(self.evals_card)
        row.addWidget(self.muscles_card)
        row.addWidget(self.last_eval_card)
        return row

    def _build_history_card(self) -> Card:
        card = Card()
        card.add_title("Historial de evaluaciones", "Clic en una para abrir su reporte")

        self.history_list = QVBoxLayout()
        self.history_list.setSpacing(8)
        card.body.addLayout(self.history_list)

        self.history_empty = EmptyState(
            "📊", "Este cliente todavía no tiene evaluaciones registradas."
        )
        card.body.addWidget(self.history_empty)
        return card

    def _build_mvc_card(self) -> Card:
        card = Card()
        card.add_title("Calibraciones MVC", "Referencia por músculo, la más reciente de cada uno")

        self.mvc_list = QVBoxLayout()
        self.mvc_list.setSpacing(8)
        card.body.addLayout(self.mvc_list)

        self.mvc_empty = EmptyState("⚡", "Sin calibraciones registradas todavía.")
        card.body.addWidget(self.mvc_empty)
        return card

    # ── Carga de datos ───────────────────────────────────────────────

    def load_client(self, client) -> None:
        self._client = client
        self.name_label.setText(client.full_name)
        self.notes_label.setText(client.notes or "Sin notas.")

        self._clear_layout(self._avatar_host)
        self._avatar_host.addWidget(Avatar(client.full_name, size=72))

        self._clear_layout(self._pill_row)
        self._pill_row.addWidget(Pill(client.goal, goal_color(client.goal)))
        self._pill_row.addStretch(1)

        sessions = self.state.evaluation_repo.list_for_client(client.id)
        self._sessions = sessions

        self._refresh_stats(sessions)
        self._refresh_history(sessions)
        self._refresh_mvc(sessions)

    def _refresh_stats(self, sessions) -> None:
        self.evals_card.set_value(str(len(sessions)))
        self.muscles_card.set_value(str(len({s.muscle_id for s in sessions})))

        if sessions:
            self.last_eval_card.set_value(self._relative_date(sessions[0].started_at))
            self.last_eval_card.set_caption(sessions[0].started_at.strftime("%d/%m/%Y"))
        else:
            self.last_eval_card.set_value("—")
            self.last_eval_card.set_caption("")

        scored = [s for s in sessions if s.overall_score is not None]
        self.score_ring.set_value(scored[0].overall_score if scored else None)

    def _refresh_history(self, sessions) -> None:
        self._clear_layout(self.history_list)
        self.history_empty.setVisible(len(sessions) == 0)

        for session in sessions:
            muscle = self.state.muscle_repo.get(session.muscle_id)
            status_pill = self._status_pill(session.status)

            row = ListRow(
                title=muscle.name if muscle else "—",
                subtitle=(
                    f"{session.started_at.strftime('%d/%m/%Y · %H:%M')}   ·   {session.goal}"
                ),
                value=(
                    f"{session.overall_score:.0f}%"
                    if session.overall_score is not None
                    else ""
                ),
                value_caption="score" if session.overall_score is not None else "",
                value_color=score_color(session.overall_score),
                leading=IconBadge(
                    FIF.CALORIES, Avatar.color_for(muscle.name if muscle else "?"), size=40
                ),
                pill=status_pill,
                clickable=session.status == EvaluationStatus.COMPLETED.value,
            )
            if session.status == EvaluationStatus.COMPLETED.value:
                row.clicked.connect(
                    lambda sid=session.id: self.view_report_requested.emit(sid)
                )
            self.history_list.addWidget(row)

    def _refresh_mvc(self, sessions) -> None:
        self._clear_layout(self.mvc_list)

        seen_muscles: set[int] = set()
        rows = 0
        for session in sessions:
            if session.muscle_id in seen_muscles or session.mvc_calibration_id is None:
                continue
            seen_muscles.add(session.muscle_id)

            calib = self.state.calibration_repo.get(session.mvc_calibration_id)
            muscle = self.state.muscle_repo.get(session.muscle_id)
            if calib is None or muscle is None:
                continue

            self.mvc_list.addWidget(
                ListRow(
                    title=muscle.name,
                    subtitle=(
                        f"Sensor A {calib.mvc_channel_a_uv:.0f} µV   ·   "
                        f"Sensor B {calib.mvc_channel_b_uv:.0f} µV   ·   "
                        f"{calib.recorded_at.strftime('%d/%m/%Y')}"
                    ),
                    value=f"{calib.mvc_value_uv:.0f}",
                    value_caption="µV MVC",
                    value_color=ACCENT_TEAL,
                    leading=IconBadge(FIF.SPEED_HIGH, ACCENT_TEAL, size=40),
                    clickable=False,
                )
            )
            rows += 1

        self.mvc_empty.setVisible(rows == 0)

    # ── Utilidades ───────────────────────────────────────────────────

    @staticmethod
    def _status_pill(status: str) -> tuple[str, str] | None:
        if status == EvaluationStatus.IN_PROGRESS.value:
            return ("En curso", ACCENT_AMBER)
        if status == EvaluationStatus.CANCELLED.value:
            return ("Cancelada", ACCENT_RED)
        return None

    @staticmethod
    def _relative_date(when: dt.datetime) -> str:
        days = (dt.datetime.now() - when).days
        if days == 0:
            return "Hoy"
        if days == 1:
            return "Ayer"
        if days < 7:
            return f"Hace {days} d"
        if days < 30:
            weeks = days // 7
            return f"Hace {weeks} sem"
        return f"Hace {days // 30} mes"

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _on_new_evaluation_clicked(self) -> None:
        if self._client is not None:
            self.start_evaluation_requested.emit(self._client)
