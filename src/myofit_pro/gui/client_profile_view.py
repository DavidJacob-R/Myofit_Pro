"""
Perfil de un cliente — equivalente a ClientProfileView.xaml de la
versión C#.

El historial ya NO es una tabla: cada evaluación es una fila-tarjeta
(`ListRow`) con su estado y su score a color, clickeable para abrir el
reporte y con su propio botón para eliminarla. El encabezado es un
"hero" con avatar, objetivo, los datos físicos del cliente y el anillo
de score de la última evaluación.
"""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import PrimaryPushButton, PushButton, ToolButton

from myofit_pro.database.models import EvaluationStatus
from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.clients_view import bmi_reading
from myofit_pro.gui.theme import (
    ACCENT_AMBER,
    ACCENT_RED,
    ACCENT_TEAL,
    ACCENT_VIOLET,
    BG_ELEVATED,
    BORDER,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    Avatar,
    BackButton,
    Card,
    DataChip,
    EmptyState,
    IconBadge,
    ListRow,
    Pill,
    ScoreRing,
    StatCard,
    clear_layout,
    goal_color,
    score_color,
)


class ClientProfileView(QWidget):
    back_requested = Signal()
    start_evaluation_requested = Signal(object)   # Client
    view_report_requested = Signal(int)           # session_id
    edit_requested = Signal(object)               # Client
    data_changed = Signal()                       # se borró algo, refrescar el resto

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

        back_row = QHBoxLayout()
        back_btn = BackButton("Mis clientes")
        back_btn.clicked.connect(self.back_requested.emit)
        back_row.addWidget(back_btn)
        back_row.addStretch(1)
        layout.addLayout(back_row)

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
        info_col.setSpacing(10)

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

        # Datos físicos: lo que el generador de rutinas consume.
        self._chips_row = QHBoxLayout()
        self._chips_row.setSpacing(8)
        self._chips_row.addStretch(1)
        info_col.addLayout(self._chips_row)

        self.notes_label = QLabel("")
        self.notes_label.setWordWrap(True)
        self.notes_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 13px; background: transparent; border: none;"
        )
        info_col.addWidget(self.notes_label)

        info_col.addStretch(1)

        actions = QHBoxLayout()
        actions.setSpacing(9)

        new_eval_btn = PrimaryPushButton("＋   Nueva evaluación")
        new_eval_btn.clicked.connect(self._on_new_evaluation_clicked)
        actions.addWidget(new_eval_btn)

        edit_btn = PushButton("Editar ficha")
        edit_btn.setIcon(FIF.EDIT)
        edit_btn.clicked.connect(self._on_edit_clicked)
        actions.addWidget(edit_btn)

        actions.addStretch(1)
        info_col.addLayout(actions)

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
        card.add_title(
            "Historial de evaluaciones",
            "Clic para abrir el reporte  ·  la papelera elimina la evaluación",
        )

        self.history_list = QVBoxLayout()
        self.history_list.setSpacing(8)
        card.body.addLayout(self.history_list)

        self.history_empty = EmptyState(
            "", "Este cliente todavía no tiene evaluaciones registradas."
        )
        card.body.addWidget(self.history_empty)
        return card

    def _build_mvc_card(self) -> Card:
        card = Card()
        card.add_title("Calibraciones MVC", "Referencia por músculo, la más reciente de cada uno")

        self.mvc_list = QVBoxLayout()
        self.mvc_list.setSpacing(8)
        card.body.addLayout(self.mvc_list)

        self.mvc_empty = EmptyState("", "Sin calibraciones registradas todavía.")
        card.body.addWidget(self.mvc_empty)
        return card

    # ── Carga de datos ───────────────────────────────────────────────

    def load_client(self, client) -> None:
        self._client = client
        self.name_label.setText(client.full_name)
        self.notes_label.setText(client.notes or "Sin notas.")

        clear_layout(self._avatar_host)
        self._avatar_host.addWidget(Avatar(client.full_name, size=72))

        clear_layout(self._pill_row)
        self._pill_row.addWidget(Pill(client.goal, goal_color(client.goal)))
        if not client.profile_is_complete:
            self._pill_row.addWidget(Pill("Ficha incompleta", ACCENT_AMBER))
        self._pill_row.addStretch(1)

        self._refresh_body_chips(client)

        sessions = self.state.evaluation_repo.list_for_client(client.id)
        self._sessions = sessions

        self._refresh_stats(sessions)
        self._refresh_history(sessions)
        self._refresh_mvc(sessions)

    def reload(self) -> None:
        """Vuelve a leer el cliente de la base y redibuja todo."""
        if self._client is None:
            return
        fresh = self.state.client_repo.get(self._client.id)
        if fresh is not None:
            self.load_client(fresh)

    def _refresh_body_chips(self, client) -> None:
        clear_layout(self._chips_row)

        bmi = client.bmi
        bmi_text, bmi_color = bmi_reading(bmi)

        chips = [
            (client.sex or "—", "SEXO", TEXT_PRIMARY),
            (f"{client.age_years} años" if client.age_years else "—", "EDAD", TEXT_PRIMARY),
            (f"{client.height_cm:.0f} cm" if client.height_cm else "—", "ESTATURA", TEXT_PRIMARY),
            (f"{client.weight_kg:.1f} kg" if client.weight_kg else "—", "PESO", TEXT_PRIMARY),
            (f"{bmi:.1f}" if bmi else "—", f"IMC · {bmi_text.upper()}", bmi_color),
        ]
        for value, caption, color in chips:
            self._chips_row.addWidget(DataChip(value, caption, color))
        self._chips_row.addStretch(1)

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
        clear_layout(self.history_list)
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

            row.add_trailing(self._delete_button(session))
            self.history_list.addWidget(row)

    def _delete_button(self, session) -> ToolButton:
        button = ToolButton(FIF.DELETE)
        button.setFixedSize(32, 32)
        button.setToolTip("Eliminar esta evaluación")
        button.setStyleSheet(
            f"ToolButton {{ background-color: {BG_ELEVATED}; border: 1px solid {BORDER}; "
            f"border-radius: 9px; }}"
            f"ToolButton:hover {{ background-color: {ACCENT_RED}; border-color: {ACCENT_RED}; }}"
        )
        button.clicked.connect(lambda: self._on_delete_session(session))
        return button

    def _on_delete_session(self, session) -> None:
        muscle = self.state.muscle_repo.get(session.muscle_id)
        confirm = QMessageBox.question(
            self,
            "Eliminar evaluación",
            f"¿Eliminar la evaluación de {muscle.name if muscle else 'este músculo'} "
            f"del {session.started_at.strftime('%d/%m/%Y')}?\n\n"
            "Se borran también sus resultados y la señal EMG grabada. "
            "No se puede deshacer.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self.state.delete_evaluation(session.id)
        self.reload()
        self.data_changed.emit()

    def _refresh_mvc(self, sessions) -> None:
        clear_layout(self.mvc_list)

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

    def _on_new_evaluation_clicked(self) -> None:
        if self._client is not None:
            self.start_evaluation_requested.emit(self._client)

    def _on_edit_clicked(self) -> None:
        if self._client is not None:
            self.edit_requested.emit(self._client)
