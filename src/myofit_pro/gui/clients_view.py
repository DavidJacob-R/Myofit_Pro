"""
Mis clientes — cuadrícula de tarjetas (ClientCard) en vez de tabla.
Cada tarjeta muestra avatar con iniciales, objetivo, número de
evaluaciones, último score y cuándo fue la última actividad.
Clic en una tarjeta abre el perfil del cliente.
"""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import ComboBox, LineEdit, PrimaryPushButton, PushButton

from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.theme import ClientCard, EmptyState, PageHeader

GOALS = ["Hipertrofia", "Fuerza", "Rehabilitación", "Resistencia", "Postura"]

_CARD_MIN_WIDTH = 290   # ancho cómodo de una ClientCard, define cuántas caben


class AddEditClientDialog(QDialog):
    """Modal de alta/edición — equivalente a AddEditClientView.xaml."""

    def __init__(self, parent: QWidget | None = None, client=None):
        super().__init__(parent)
        self.client = client
        self.setWindowTitle("Editar cliente" if client else "Nuevo cliente")
        self.setMinimumWidth(380)

        form = QFormLayout(self)
        form.setSpacing(10)

        self.name_input = LineEdit(self)
        self.goal_input = ComboBox(self)
        self.goal_input.addItems(GOALS)
        self.notes_input = LineEdit(self)

        if client:
            self.name_input.setText(client.full_name)
            if client.goal in GOALS:
                self.goal_input.setCurrentText(client.goal)
            self.notes_input.setText(client.notes or "")

        form.addRow("Nombre completo:", self.name_input)
        form.addRow("Objetivo:", self.goal_input)
        form.addRow("Notas:", self.notes_input)

        buttons = QHBoxLayout()
        save_btn = PrimaryPushButton("Guardar")
        cancel_btn = PushButton("Cancelar")
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        form.addRow(buttons)

    def values(self) -> dict:
        return {
            "full_name": self.name_input.text().strip(),
            "goal": self.goal_input.currentText(),
            "notes": self.notes_input.text().strip() or None,
        }


class ClientsView(QWidget):
    client_selected = Signal(object)   # Client — para abrir el perfil

    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._clients_cache = []
        self._laid_out_columns = 0
        self._relaying_out = False
        self._build_ui()
        self.reload()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 28)
        layout.setSpacing(18)

        header_row = QHBoxLayout()
        self.header = PageHeader("Mis clientes")
        header_row.addWidget(self.header)
        header_row.addStretch(1)
        add_btn = PrimaryPushButton("＋   Nuevo cliente")
        add_btn.clicked.connect(self._on_add_clicked)
        header_row.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(header_row)

        # Área desplazable con la cuadrícula de tarjetas
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet(f"QScrollArea {{ background: transparent; border: none; }}")

        self._grid_host = QWidget()
        self._grid_host.setStyleSheet("background: transparent;")
        self.grid = QGridLayout(self._grid_host)
        self.grid.setSpacing(14)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll.setWidget(self._grid_host)
        layout.addWidget(scroll, stretch=1)

        self.empty_state = EmptyState(
            "👥",
            "Todavía no tienes clientes registrados.\n"
            "Usa el botón de arriba para agregar el primero.",
        )
        layout.addWidget(self.empty_state)

    def reload(self) -> None:
        self._relaying_out = True
        try:
            self._reload()
        finally:
            self._relaying_out = False

    def _reload(self) -> None:
        clients = self.state.client_repo.list_for_trainer(self.state.current_trainer.id)
        self._clients_cache = clients

        self.empty_state.setVisible(len(clients) == 0)
        self._grid_host.setVisible(len(clients) > 0)
        self.header.set_subtitle(
            f"{len(clients)} cliente{'s' if len(clients) != 1 else ''}  ·  "
            "clic para ver el perfil, clic derecho para editar"
        )

        # Limpiar tarjetas anteriores
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        columns = self._column_count()
        self._laid_out_columns = columns

        for index, client in enumerate(clients):
            sessions = self.state.evaluation_repo.list_for_client(client.id)
            completed = [s for s in sessions if s.overall_score is not None]
            score_value = completed[0].overall_score if completed else None

            card = ClientCard(
                full_name=client.full_name,
                goal=client.goal,
                evaluations_count=len(sessions),
                last_score=f"{score_value:.0f}%" if score_value is not None else "—",
                last_activity=(
                    self._relative_date(sessions[0].started_at) if sessions else "Sin evaluar"
                ),
                score_value=score_value,
            )
            card.clicked.connect(lambda c=client: self.client_selected.emit(c))
            card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            card.customContextMenuRequested.connect(
                lambda _pos, c=client: self._show_card_menu(c)
            )

            row, col = divmod(index, columns)
            self.grid.addWidget(card, row, col)

    def _column_count(self) -> int:
        """Cuántas tarjetas caben a lo ancho, para que la rejilla no se
        deforme al cambiar el tamaño de la ventana."""
        return max(1, min(4, (self.width() - 56) // _CARD_MIN_WIDTH))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # Sin la guardia, reload() agrega tarjetas -> cambia el tamaño ->
        # vuelve a entrar aquí -> recursión infinita (desborda la pila).
        if self._relaying_out or not self._clients_cache:
            return
        if self._column_count() != self._laid_out_columns:
            self.reload()

    @staticmethod
    def _relative_date(when: dt.datetime) -> str:
        delta = dt.datetime.now() - when
        days = delta.days
        if days == 0:
            return "Hoy"
        if days == 1:
            return "Ayer"
        if days < 7:
            return f"Hace {days} días"
        if days < 30:
            weeks = days // 7
            return f"Hace {weeks} semana{'s' if weeks > 1 else ''}"
        months = days // 30
        return f"Hace {months} mes{'es' if months > 1 else ''}"

    def _show_card_menu(self, client) -> None:
        """Menú contextual (clic derecho) con editar / eliminar."""
        from qfluentwidgets import RoundMenu, Action

        menu = RoundMenu(parent=self)
        edit_action = Action("Editar")
        edit_action.triggered.connect(lambda: self._on_edit_clicked(client))
        delete_action = Action("Eliminar")
        delete_action.triggered.connect(lambda: self._on_delete_clicked(client))
        menu.addAction(edit_action)
        menu.addAction(delete_action)
        menu.exec(self.cursor().pos())

    def _on_add_clicked(self) -> None:
        dialog = AddEditClientDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            values = dialog.values()
            if not values["full_name"]:
                QMessageBox.warning(self, "Dato requerido", "El nombre es obligatorio.")
                return
            self.state.client_repo.create(self.state.current_trainer.id, **values)
            self.reload()

    def _on_edit_clicked(self, client) -> None:
        dialog = AddEditClientDialog(self, client=client)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            values = dialog.values()
            self.state.client_repo.update(client.id, **values)
            self.reload()

    def _on_delete_clicked(self, client) -> None:
        confirm = QMessageBox.question(
            self,
            "Eliminar cliente",
            f"¿Eliminar a {client.full_name}?\n\n"
            "Esto también borra sus evaluaciones y calibraciones. No se puede deshacer.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.state.client_repo.delete(client.id)
            self.reload()