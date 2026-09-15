"""
Contenedor de "Mis clientes": lista + perfil de detalle, en un único
item del sidebar (mismo patrón que EvaluationWizardContainer). Emite
señales hacia MainWindow para las acciones que cruzan a otras
secciones (nueva evaluación, ver reporte).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.client_profile_view import ClientProfileView
from myofit_pro.gui.clients_view import ClientsView


class ClientsContainer(QWidget):
    start_evaluation_requested = Signal(object)   # Client
    view_report_requested = Signal(int)           # session_id

    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state

        self.stack = QStackedWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

        self.list_view = ClientsView(state)
        self.profile_view = ClientProfileView(state)

        self.stack.addWidget(self.list_view)
        self.stack.addWidget(self.profile_view)

        self.list_view.client_selected.connect(self._show_profile)
        self.profile_view.back_requested.connect(self._show_list)
        self.profile_view.start_evaluation_requested.connect(self.start_evaluation_requested.emit)
        self.profile_view.view_report_requested.connect(self.view_report_requested.emit)

        self.stack.setCurrentWidget(self.list_view)

    def _show_profile(self, client) -> None:
        self.profile_view.load_client(client)
        self.stack.setCurrentWidget(self.profile_view)

    def _show_list(self) -> None:
        self.list_view.reload()
        self.stack.setCurrentWidget(self.list_view)

    def show_list(self) -> None:
        """Método público para que MainWindow regrese aquí al navegar desde el sidebar."""
        self._show_list()
        