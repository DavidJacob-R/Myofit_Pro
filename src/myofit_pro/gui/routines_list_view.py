"""
Lista de rutinas de un cliente, por fecha.

POR QUÉ UNA LISTA Y NO UNA SOLA PANTALLA
========================================

Antes la sección enseñaba la rutina actual completa de un tirón: el
encabezado, la prescripción, un bloque por cada día de la semana, el
volumen y los avisos. Con cuatro días de entrenamiento eso son ocho o
diez tarjetas seguidas, y hay que hacer scroll por todas para encontrar
el martes. Además cada rutina nueva borraba la anterior, así que no
quedaba rastro de qué se le había mandado al cliente el mes pasado.

Ahora esta pantalla es un índice: una fila por rutina generada, con su
fecha. Se entra a una y ahí sí se despliega completa, con la explicación
de qué lectura la originó. Es el mismo patrón que "Mis clientes" e
"Historial sEMG": lista arriba, detalle adentro.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, PrimaryPushButton, ToolButton
from qfluentwidgets import FluentIcon as FIF

from myofit_pro.gui.theme import (
    ACCENT_RED,
    ACCENT_TEAL,
    ACCENT_VIOLET,
    BG_ELEVATED,
    BORDER,
    TEXT_MUTED,
    Card,
    EmptyState,
    IconBadge,
    ListRow,
    PageHeader,
    clear_layout,
    format_date_es,
    goal_color,
)
from myofit_pro.gui.client_picker import ClientPicker
import random

from myofit_pro.routine_engine import build_plan


class RoutinesListView(QWidget):
    routine_selected = Signal(int)  # routine_id
    data_changed = Signal()

    def __init__(self, state, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._clients = []
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
        layout.setContentsMargins(24, 20, 24, 28)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        layout.addWidget(
            PageHeader("Rutinas", "Clic en una para verla completa")
        )

        picker = Card()
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(BodyLabel("Cliente:"))
        self.client_combo = ClientPicker(picker)
        self.client_combo.client_changed.connect(self._on_client_changed)
        row.addWidget(self.client_combo, stretch=1)

        self.generate_btn = PrimaryPushButton("Generar rutina")
        self.generate_btn.setIcon(FIF.ADD)
        self.generate_btn.clicked.connect(self._on_generate_clicked)
        row.addWidget(self.generate_btn)
        picker.body.addLayout(row)
        layout.addWidget(picker)

        self.content = QVBoxLayout()
        self.content.setSpacing(10)
        layout.addLayout(self.content)
        layout.addStretch(1)

        scroll.setWidget(host)
        outer.addWidget(scroll)

    # ── Datos ────────────────────────────────────────────────────────

    def reload(self) -> None:
        self._clients = self.state.client_repo.list_for_trainer(self.state.current_trainer.id)
        self.client_combo.blockSignals(True)
        self.client_combo.set_clients(self._clients)
        self.client_combo.blockSignals(False)
        self.generate_btn.setEnabled(bool(self._clients))
        self._render()

    def _current_client(self):
        return self.client_combo.current_client()

    def _on_client_changed(self, _client) -> None:
        self._render()

    def select_client(self, client) -> None:
        """Deja seleccionado un cliente concreto (al llegar desde su ficha)."""
        self.client_combo.select(client)

    # ── Render ───────────────────────────────────────────────────────

    def _render(self) -> None:
        clear_layout(self.content)
        client = self._current_client()

        if client is None:
            self.content.addWidget(
                EmptyState(
                    "👥",
                    "Todavía no hay clientes registrados.\n"
                    "Da de alta uno en 'Mis clientes'.",
                )
            )
            return

        rutinas = self.state.routine_repo.list_for_client(client.id)
        if not rutinas:
            self.content.addWidget(
                EmptyState(
                    "🗒️",
                    f"{client.full_name} no tiene rutinas generadas.\n"
                    "Usa el botón de arriba para crear la primera.",
                )
            )
            return

        titulo = QLabel(
            f"{len(rutinas)} rutina generada" if len(rutinas) == 1
            else f"{len(rutinas)} rutinas generadas"
        )
        titulo.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 11px; font-weight: 700; "
            f"letter-spacing: 0.5px; background: transparent; border: none;"
        )
        self.content.addWidget(titulo)

        for posicion, rutina in enumerate(rutinas):
            self.content.addWidget(self._build_row(rutina, es_actual=posicion == 0))

    def _build_row(self, rutina, es_actual: bool) -> ListRow:
        dias = {e.day_index or 1 for e in rutina.exercises}
        distintos = {e.exercise_id for e in rutina.exercises}
        series = sum(e.sets for e in rutina.exercises)

        # La hora va siempre, no solo cuando hay dos el mismo día: dos
        # rutinas generadas la misma tarde se verían idénticas en la
        # lista y no habría forma de saber cuál se abrió.
        detalle = (
            f"{rutina.created_at:%H:%M}   ·   {len(dias)} días   ·   "
            f"{len(distintos)} ejercicios   ·   {series} series por semana"
        )
        if rutina.goal:
            detalle = f"{rutina.goal}   ·   " + detalle

        accent = goal_color(rutina.goal or "") if rutina.goal else ACCENT_VIOLET

        row = ListRow(
            title=format_date_es(rutina.created_at),
            subtitle=detalle,
            leading=IconBadge(FIF.CALENDAR, accent, size=40),
            pill=("Vigente", ACCENT_TEAL) if es_actual else None,
            clickable=True,
        )
        row.clicked.connect(lambda rid=rutina.id: self.routine_selected.emit(rid))
        row.add_trailing(self._delete_button(rutina))
        return row

    def _delete_button(self, rutina) -> ToolButton:
        button = ToolButton(FIF.DELETE)
        button.setFixedSize(32, 32)
        button.setToolTip("Eliminar esta rutina")
        button.setStyleSheet(
            f"ToolButton {{ background-color: {BG_ELEVATED}; border: 1px solid {BORDER}; "
            f"border-radius: 9px; }}"
            f"ToolButton:hover {{ background-color: {ACCENT_RED}; border-color: {ACCENT_RED}; }}"
        )
        button.clicked.connect(lambda: self._on_delete(rutina))
        return button

    def _on_delete(self, rutina) -> None:
        confirm = QMessageBox.question(
            self,
            "Eliminar rutina",
            f"¿Eliminar la rutina del {rutina.created_at.strftime('%d/%m/%Y')}?\n\n"
            "No se puede deshacer.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.state.routine_repo.delete(rutina.id)
        self._render()
        self.data_changed.emit()

    # ── Generación ───────────────────────────────────────────────────

    def _on_generate_clicked(self) -> None:
        client = self._current_client()
        if client is None:
            return

        candidates = self.state.routine_candidates(client.id)
        if not candidates:
            QMessageBox.information(
                self,
                "Sin evaluaciones",
                f"{client.full_name} todavía no tiene músculos evaluados.\n\n"
                "Haz una evaluación primero: los ejercicios de la rutina salen "
                "del ranking de activación que se mide ahí.",
            )
            return

        plan = build_plan(
            goal=client.goal,
            experience=client.experience_level,
            days_per_week=client.days_per_week,
            candidates=candidates,
            # Generador nuevo en cada rutina: es lo que hace que el
            # último hueco de cada músculo varíe entre clientes y entre
            # semanas. Ver la nota de ROTACIÓN en routine_engine.
            rng=random.Random(),
        )
        if plan.is_empty:
            QMessageBox.warning(
                self,
                "Catálogo vacío",
                "No hay ejercicios en el catálogo para los músculos evaluados "
                "de este cliente.",
            )
            return

        # Las evaluaciones que alimentaron la rutina se guardan con ella
        # para poder explicar después de qué lectura salió cada ejercicio.
        fuentes = self.state.sessions_behind_routine(client.id, plan)

        rutina = self.state.routine_repo.save_plan(
            client_id=client.id,
            name=f"Rutina de {plan.goal.lower()} — {plan.days_per_week} días",
            plan=plan,
            source_session_ids=fuentes,
        )

        self._render()
        self.data_changed.emit()
        self.routine_selected.emit(rutina.id)
