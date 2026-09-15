"""
Pasos 0 y 1 del wizard de evaluación — equivalentes a
EvaluationStartView.xaml y EvaluationStep1View.xaml.

El título de cada paso ya lo muestra el header persistente del
EvaluationWizardContainer, así que estas vistas solo traen su propio
contenido dentro de una Card, sin repetir el título.

Cliente y músculo se eligen con tarjetas seleccionables (`SelectableCard`)
en vez de un ListWidget: una lista de texto plano no comunica que se
puede hacer clic, y esta es la primera pantalla del flujo principal.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, ComboBox, PrimaryPushButton
from qfluentwidgets import FluentIcon as FIF

from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.clients_view import GOALS
from myofit_pro.gui.theme import (
    Avatar,
    Card,
    EmptyState,
    IconBadge,
    SelectableCard,
    goal_color,
)


class _SelectionList(QWidget):
    """Columna desplazable de SelectableCard con selección única."""

    selection_changed = Signal(int)   # índice elegido

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._cards: list[SelectableCard] = []
        self._selected = -1

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        host = QWidget()
        host.setStyleSheet("background: transparent;")
        self._list = QVBoxLayout(host)
        self._list.setSpacing(8)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll.setWidget(host)
        outer.addWidget(scroll)

    @property
    def selected_index(self) -> int:
        return self._selected

    def clear(self) -> None:
        while self._list.count():
            item = self._list.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards = []
        self._selected = -1

    def add_card(self, card: SelectableCard) -> None:
        index = len(self._cards)
        card.clicked.connect(lambda i=index: self.select(i))
        self._cards.append(card)
        self._list.addWidget(card)

    def select(self, index: int) -> None:
        for i, card in enumerate(self._cards):
            card.set_selected(i == index)
        self._selected = index
        self.selection_changed.emit(index)


class EvaluationStartView(QWidget):
    """Selección de cliente y objetivo antes de iniciar el wizard."""

    started = Signal()

    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._clients = []
        self._build_ui()
        self.reload()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        card = Card()
        card.add_title("Elige un cliente", "Con quién vas a hacer esta evaluación")

        self.client_list = _SelectionList(card)
        self.client_list.selection_changed.connect(self._on_client_selected)
        card.body.addWidget(self.client_list, stretch=1)

        self.empty_state = EmptyState(
            "👥",
            "Todavía no tienes clientes registrados.\n"
            "Agrega uno en 'Mis clientes' para poder evaluar.",
        )
        card.body.addWidget(self.empty_state)

        goal_row = QHBoxLayout()
        goal_row.setSpacing(10)
        goal_row.addWidget(BodyLabel("Objetivo de la sesión:"))
        self.goal_combo = ComboBox(card)
        self.goal_combo.addItems(GOALS)
        goal_row.addWidget(self.goal_combo, stretch=1)
        card.body.addLayout(goal_row)

        self.next_btn = PrimaryPushButton("Continuar  →")
        self.next_btn.setEnabled(False)
        self.next_btn.clicked.connect(self._on_next_clicked)
        card.body.addWidget(self.next_btn)

        layout.addWidget(card)

    def reload(self) -> None:
        self._clients = self.state.client_repo.list_for_trainer(
            self.state.current_trainer.id
        )
        self.client_list.clear()
        self.next_btn.setEnabled(False)

        self.empty_state.setVisible(not self._clients)
        self.client_list.setVisible(bool(self._clients))

        for client in self._clients:
            self.client_list.add_card(
                SelectableCard(
                    title=client.full_name,
                    subtitle=client.goal,
                    leading=Avatar(client.full_name, size=40),
                    accent=goal_color(client.goal),
                )
            )

    def _on_client_selected(self, index: int) -> None:
        self.next_btn.setEnabled(index >= 0)
        if 0 <= index < len(self._clients):
            self.goal_combo.setCurrentText(self._clients[index].goal)

    def _on_next_clicked(self) -> None:
        index = self.client_list.selected_index
        if index < 0:
            return
        self.state.active_client = self._clients[index]
        self.state.active_goal = self.goal_combo.currentText()
        self.started.emit()


class EvaluationStep1View(QWidget):
    """Selección de grupo muscular y músculo específico a evaluar."""

    muscle_selected = Signal()

    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._groups = []
        self._muscles = []
        self._build_ui()
        self.reload()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        card = Card()
        card.add_title("¿Qué músculo vas a evaluar?", "Primero el grupo, luego el músculo")

        group_row = QHBoxLayout()
        group_row.setSpacing(10)
        group_row.addWidget(BodyLabel("Grupo muscular:"))
        self.group_combo = ComboBox(card)
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)
        group_row.addWidget(self.group_combo, stretch=1)
        card.body.addLayout(group_row)

        self.muscle_list = _SelectionList(card)
        self.muscle_list.selection_changed.connect(
            lambda index: self.next_btn.setEnabled(index >= 0)
        )
        card.body.addWidget(self.muscle_list, stretch=1)

        self.next_btn = PrimaryPushButton("Continuar  →")
        self.next_btn.setEnabled(False)
        self.next_btn.clicked.connect(self._on_next_clicked)
        card.body.addWidget(self.next_btn)

        layout.addWidget(card)

    def reload(self) -> None:
        self._groups = self.state.muscle_repo.list_groups()
        self.group_combo.clear()
        self.group_combo.addItems([g.name for g in self._groups])
        if self._groups:
            self._load_muscles(self._groups[0].id)

    def _on_group_changed(self, index: int) -> None:
        if 0 <= index < len(self._groups):
            self._load_muscles(self._groups[index].id)

    def _load_muscles(self, group_id: int) -> None:
        self._muscles = self.state.muscle_repo.list_muscles(group_id)
        self.muscle_list.clear()
        self.next_btn.setEnabled(False)

        for muscle in self._muscles:
            accent = Avatar.color_for(muscle.name)
            self.muscle_list.add_card(
                SelectableCard(
                    title=muscle.name,
                    subtitle=(
                        "Guía de colocación disponible"
                        if muscle.placement_guide
                        else "Sin guía de colocación cargada"
                    ),
                    leading=IconBadge(FIF.CALORIES, accent, size=40),
                    accent=accent,
                )
            )

    def _on_next_clicked(self) -> None:
        index = self.muscle_list.selected_index
        if index < 0 or not self.state.active_client:
            return
        muscle = self._muscles[index]
        self.state.set_eval_context(
            self.state.active_client, muscle, self.state.active_goal
        )

        # Crear la sesión de evaluación en la DB desde este punto, para
        # que Historial/Reporte tengan algo que mostrar incluso si el
        # entrenador abandona el wizard a la mitad.
        session = self.state.evaluation_repo.start_session(
            client_id=self.state.active_client.id,
            muscle_id=muscle.id,
            goal=self.state.active_goal,
        )
        self.state.active_session_id = session.id

        self.muscle_selected.emit()
