"""
Mis clientes — cuadrícula de tarjetas (ClientCard) en vez de tabla.
Cada tarjeta muestra avatar con iniciales, objetivo, número de
evaluaciones, último score y cuándo fue la última actividad.
Clic en una tarjeta abre el perfil del cliente.

El alta y la edición usan el mismo formulario, que vive en
`client_form.py` porque creció a tres pasos. Se re-exporta `GOALS` desde
aquí para no romper lo que ya lo importaba de este módulo.
"""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import PrimaryPushButton

from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.client_form import GOALS, ClientFormDialog
from myofit_pro.gui.theme import (
    ACCENT_AMBER,
    ACCENT_LIME,
    ACCENT_RED,
    ACCENT_TEAL,
    TEXT_MUTED,
    TEXT_SECONDARY,
    ClientCard,
    EmptyState,
    PageHeader,
    clear_layout,
)
from myofit_pro.body_composition import bmi_category

__all__ = ["GOALS", "ClientFormDialog", "ClientsView", "bmi_reading", "body_fat_reading"]

_CARD_MIN_WIDTH = 290   # ancho cómodo de una ClientCard, define cuántas caben

# Color de cada clasificación. El texto lo pone body_composition, que es
# donde viven los cortes; aquí solo se le asigna el color del tema.
_CATEGORY_COLORS = {
    "Bajo peso": ACCENT_AMBER,
    "Normal": ACCENT_LIME,
    "Sobrepeso": ACCENT_AMBER,
    "Obesidad": ACCENT_RED,
    "Esencial": ACCENT_AMBER,
    "Atlético": ACCENT_TEAL,
    "En forma": ACCENT_LIME,
    "Promedio": ACCENT_AMBER,
    "Alto": ACCENT_RED,
}


def bmi_reading(value: float | None) -> tuple[str, str]:
    """Texto y color de la clasificación de IMC."""
    label = bmi_category(value)
    return (label, _CATEGORY_COLORS.get(label, TEXT_SECONDARY))


def body_fat_reading(label: str) -> str:
    """Color de una clasificación de grasa corporal ya calculada."""
    return _CATEGORY_COLORS.get(label, TEXT_SECONDARY)


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

        hint = QLabel("Clic para abrir el perfil  ·  clic derecho para editar o eliminar")
        hint.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 11px; background: transparent; border: none;"
        )
        layout.addWidget(hint)

        # Área desplazable con la cuadrícula de tarjetas
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

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

        incomplete = sum(1 for c in clients if not c.profile_is_complete)
        subtitle = f"{len(clients)} cliente{'s' if len(clients) != 1 else ''}"
        if incomplete:
            subtitle += f"  ·  {incomplete} con la ficha incompleta"
        self.header.set_subtitle(subtitle)

        clear_layout(self.grid)

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
                profile_note="" if client.profile_is_complete else "Ficha incompleta",
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
        from qfluentwidgets import Action, RoundMenu
        from qfluentwidgets import FluentIcon as FIF

        menu = RoundMenu(parent=self)
        edit_action = Action(FIF.EDIT, "Editar ficha")
        edit_action.triggered.connect(lambda: self.edit_client(client))
        delete_action = Action(FIF.DELETE, "Eliminar cliente")
        delete_action.triggered.connect(lambda: self._on_delete_clicked(client))
        menu.addAction(edit_action)
        menu.addAction(delete_action)
        menu.exec(self.cursor().pos())

    def _on_add_clicked(self) -> None:
        dialog = ClientFormDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.state.client_repo.create(
                self.state.current_trainer.id, **dialog.values()
            )
            self.reload()

    def edit_client(self, client) -> bool:
        """
        Abre el formulario de edición. Devuelve True si se guardó, para
        que quien lo llame (la lista o el perfil) recargue lo suyo.
        """
        dialog = ClientFormDialog(self, client=client)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self.state.client_repo.update(client.id, **dialog.values())
        self.reload()
        return True

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
            self.state.delete_client(client.id)
            self.reload()
