"""
Vista general — equivalente a DashboardView.xaml. Resumen de actividad
del entrenador, calculado de la base de datos real y sin datos
inventados.

La pantalla está organizada por lo que el entrenador hace, no por lo
que la base de datos tiene. Arriba el saludo y las cifras del mes.
Abajo, dos columnas: a la izquierda la actividad (una gráfica de
barras de las últimas ocho semanas y las evaluaciones recientes), a la
derecha las acciones que se usan a diario y el estado de los sensores.

La versión anterior era una sola columna de tarjetas informativas: se
podía leer, pero no se podía hacer nada desde ahí. Desde aquí se
arranca una evaluación, se abre un reporte o se va a conectar los
sensores sin pasar por el menú lateral.
"""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import PushButton

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
    ActionTile,
    ActivityChart,
    Avatar,
    Card,
    EmptyState,
    IconBadge,
    ListRow,
    Pill,
    StatCard,
    clear_layout,
    score_color,
)
from myofit_pro.sensors import ConnectionState

_GREETING_CUTOFFS = ((12, "Buenos días"), (19, "Buenas tardes"), (24, "Buenas noches"))

# Semanas que abarca la gráfica de actividad. Ocho entra cómodo a lo
# ancho de la tarjeta y alcanza para ver una tendencia de dos meses.
_ACTIVITY_WEEKS = 8

# A partir de cuántos días sin evaluar un cliente aparece en la lista
# de seguimiento.
_STALE_DAYS = 21


class DashboardView(QWidget):
    session_selected = Signal(int)            # session_id — abrir su reporte
    client_selected = Signal(object)          # Client — abrir su perfil
    new_evaluation_requested = Signal()
    clients_requested = Signal()
    sensors_requested = Signal()

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
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

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

        columns = QHBoxLayout()
        columns.setSpacing(16)
        columns.addLayout(self._build_left_column(), stretch=3)
        columns.addLayout(self._build_right_column(), stretch=2)
        layout.addLayout(columns)

        scroll.setWidget(host)
        outer.addWidget(scroll)

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

    # ── Columna izquierda: actividad ─────────────────────────────────

    def _build_left_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(16)
        column.addWidget(self._build_activity_card())
        column.addWidget(self._build_recent_card())
        column.addStretch(1)
        return column

    def _build_activity_card(self) -> Card:
        card = Card()
        card.add_title("Actividad", f"Evaluaciones por semana, últimas {_ACTIVITY_WEEKS}")

        self.activity_chart = ActivityChart(color=ACCENT_VIOLET)
        card.body.addWidget(self.activity_chart)

        self.activity_summary = QLabel("")
        self.activity_summary.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12px; background: transparent; border: none;"
        )
        card.body.addWidget(self.activity_summary)
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
            "Usa 'Nueva evaluación' para hacer la primera.",
        )
        card.body.addWidget(self.recent_empty)
        return card

    # ── Columna derecha: acciones y estado ───────────────────────────

    def _build_right_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(16)
        column.addWidget(self._build_actions_card())
        column.addWidget(self._build_sensor_card())
        column.addWidget(self._build_followup_card())
        column.addStretch(1)
        return column

    def _build_actions_card(self) -> Card:
        card = Card()
        card.add_title("Acciones rápidas")

        tiles = (
            (
                FIF.ADD,
                "Nueva evaluación",
                "Cliente, músculo, calibración y medición",
                ACCENT_VIOLET,
                self.new_evaluation_requested,
            ),
            (
                FIF.PEOPLE,
                "Mis clientes",
                "Dar de alta o completar una ficha",
                ACCENT_BLUE,
                self.clients_requested,
            ),
        )
        for icon, title, caption, accent, signal in tiles:
            tile = ActionTile(icon, title, caption, accent)
            tile.clicked.connect(signal.emit)
            card.body.addWidget(tile)

        return card

    def _build_sensor_card(self) -> Card:
        """
        Estado de los sensores, con su propio acceso a la sección.

        No hay una tarjeta de acción aparte para sensores: sería decir
        dos veces lo mismo en la misma columna. Esta tarjeta ya tiene
        que estar aquí para informar del estado, así que también lleva
        el botón.
        """
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
        self.sensor_status_label.setWordWrap(True)
        self.sensor_status_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12px; background: transparent; border: none;"
        )
        text_col.addWidget(self.sensor_status_label)

        row.addLayout(text_col, stretch=1)
        card.body.addLayout(row)

        bottom = QHBoxLayout()
        bottom.setSpacing(7)

        self._battery_row = QHBoxLayout()
        self._battery_row.setSpacing(7)
        self._battery_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        bottom.addLayout(self._battery_row)
        bottom.addStretch(1)

        sensors_btn = PushButton("Abrir sensores")
        sensors_btn.setIcon(FIF.SPEED_HIGH)
        sensors_btn.clicked.connect(self.sensors_requested.emit)
        bottom.addWidget(sensors_btn)

        card.body.addLayout(bottom)
        return card

    def _build_followup_card(self) -> Card:
        card = Card()
        card.add_title(
            "Dar seguimiento",
            f"Sin evaluar o con más de {_STALE_DAYS} días desde la última",
        )

        self.followup_list = QVBoxLayout()
        self.followup_list.setSpacing(8)
        card.body.addLayout(self.followup_list)

        self.followup_empty = EmptyState(
            "", "Todos tus clientes tienen una evaluación reciente."
        )
        card.body.addWidget(self.followup_empty)
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
        self.evals_month_card.set_caption(MONTHS_ES[now.month - 1])

        scored = [s.overall_score for s in sessions if s.overall_score is not None]
        if scored:
            average = sum(scored) / len(scored)
            self.avg_score_card.set_value(f"{average:.0f}%")
            self.avg_score_card.set_value_color(score_color(average))
            self.avg_score_card.set_caption(f"sobre {len(scored)} evaluaciones")
        else:
            self.avg_score_card.set_value("—")
            self.avg_score_card.set_caption("sin evaluaciones completadas")

        self._refresh_activity(sessions)
        self._refresh_sensors()
        self._refresh_recent(sessions[:5])
        self._refresh_followup(clients, sessions)

    def _refresh_activity(self, sessions) -> None:
        values, labels = self._weekly_activity(sessions)
        self.activity_chart.set_data(values, labels)

        total = int(sum(values))
        if total == 0:
            self.activity_summary.setText(
                "Sin evaluaciones en este periodo."
            )
            return

        this_week = int(values[-1])
        previous = values[:-1]
        average = sum(previous) / len(previous) if previous else 0.0

        if this_week > average:
            comparison = "por encima de tu promedio"
        elif this_week < average:
            comparison = "por debajo de tu promedio"
        else:
            comparison = "igual que tu promedio"

        self.activity_summary.setText(
            f"{total} evaluaciones en {_ACTIVITY_WEEKS} semanas  ·  "
            f"{this_week} esta semana, {comparison} de {average:.1f}"
        )

    @staticmethod
    def _weekly_activity(sessions) -> tuple[list[float], list[str]]:
        """
        Cuenta evaluaciones por semana, de la más vieja a la actual.

        Las semanas empiezan en lunes (`weekday()` da 0 para lunes), que
        es como se lee un calendario aquí. La última posición siempre es
        la semana en curso, aunque vaya a la mitad: la gráfica marca esa
        barra distinto justamente para que se note que aún no termina.
        """
        today = dt.date.today()
        this_monday = today - dt.timedelta(days=today.weekday())

        starts = [
            this_monday - dt.timedelta(weeks=offset)
            for offset in range(_ACTIVITY_WEEKS - 1, -1, -1)
        ]

        counts = [0.0] * _ACTIVITY_WEEKS
        for session in sessions:
            session_date = session.started_at.date()
            session_monday = session_date - dt.timedelta(days=session_date.weekday())
            if session_monday in starts:
                counts[starts.index(session_monday)] += 1

        labels = [f"{start.day}/{start.month}" for start in starts]
        labels[-1] = "Esta"
        return counts, labels

    def _refresh_sensors(self) -> None:
        sensors = self.state.sensors
        connected = sensors.state == ConnectionState.CONNECTED

        if connected:
            self.sensor_status_label.setText(f"Receptor conectado en {sensors.current_port}")
        else:
            self.sensor_status_label.setText(
                "Receptor desconectado. Ve a 'Sensores sEMG' para conectarlo."
            )

        clear_layout(self._battery_row)
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
        clear_layout(self.recent_list)
        self.recent_empty.setVisible(len(recent) == 0)

        for session in recent:
            client = self.state.client_repo.get(session.client_id)
            muscle = self.state.muscle_repo.get(session.muscle_id)
            client_name = client.full_name if client else "—"

            # Una evaluación sin score todavía no tiene número que
            # mostrar. Poner un guion en el lugar del porcentaje, en ese
            # tamaño, se lee como una raya suelta; la píldora dice lo
            # mismo sin fingir que hay un dato.
            scored = session.overall_score is not None

            row = ListRow(
                title=client_name,
                subtitle=(
                    f"{muscle.name if muscle else '—'}   ·   "
                    f"{session.started_at.strftime('%d/%m · %H:%M')}"
                ),
                value=f"{session.overall_score:.0f}%" if scored else "",
                value_caption="score" if scored else "",
                value_color=score_color(session.overall_score),
                leading=Avatar(client_name, size=40),
                pill=None if scored else ("En curso", ACCENT_AMBER),
                clickable=scored,
            )
            if scored:
                row.clicked.connect(lambda sid=session.id: self.session_selected.emit(sid))
            self.recent_list.addWidget(row)

    def _refresh_followup(self, clients, sessions) -> None:
        clear_layout(self.followup_list)

        last_seen: dict[int, dt.datetime] = {}
        for session in sessions:
            current = last_seen.get(session.client_id)
            if current is None or session.started_at > current:
                last_seen[session.client_id] = session.started_at

        now = dt.datetime.now()
        pending = []
        for client in clients:
            when = last_seen.get(client.id)
            if when is None:
                pending.append((client, None, 10**6))   # sin evaluar: hasta arriba
            else:
                days = (now - when).days
                if days >= _STALE_DAYS:
                    pending.append((client, when, days))

        pending.sort(key=lambda item: item[2], reverse=True)
        pending = pending[:4]

        self.followup_empty.setVisible(not pending)
        if not clients:
            self.followup_empty.set_message(
                "Agrega tu primer cliente para empezar a evaluar."
            )

        for client, when, days in pending:
            if when is None:
                subtitle = "Nunca evaluado"
                accent = ACCENT_AMBER
            else:
                subtitle = f"Última evaluación hace {days} días"
                accent = ACCENT_RED if days >= _STALE_DAYS * 2 else ACCENT_AMBER

            row = ListRow(
                title=client.full_name,
                subtitle=subtitle,
                leading=Avatar(client.full_name, size=40),
                pill=("Sin evaluar", accent) if when is None else None,
            )
            row.clicked.connect(lambda c=client: self.client_selected.emit(c))
            self.followup_list.addWidget(row)

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
