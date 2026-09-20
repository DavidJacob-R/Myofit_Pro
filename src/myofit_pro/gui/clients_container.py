"""Sección de clientes: lista, ficha y progreso.

Posición en el flujo
--------------------
Ocupa una sola entrada de la barra lateral y alberga tres pantallas:
`myofit_pro.gui.clients_view.ClientsView` con la lista,
`myofit_pro.gui.client_profile_view.ClientProfileView` con la ficha, y
`myofit_pro.gui.client_progress_view.ClientProgressView` con la
comparación entre evaluaciones.

Emite hacia `myofit_pro.gui.main_window.MainWindow` las acciones que
cruzan a otras secciones: iniciar una evaluación y abrir el informe de
una pasada.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.client_profile_view import ClientProfileView
from myofit_pro.gui.client_progress_view import ClientProgressView
from myofit_pro.gui.clients_view import ClientsView


class ClientsContainer(QWidget):
    """Contenedor de la sección de clientes.

    Parameters
    ----------
    state : myofit_pro.gui.app_state.AppState
        Estado compartido.
    parent : PySide6.QtWidgets.QWidget, optional
        Widget padre.

    Attributes
    ----------
    start_evaluation_requested : PySide6.QtCore.Signal
        Emite el `myofit_pro.database.models.Client` para el que debe
        abrirse el asistente de evaluación.
    view_report_requested : PySide6.QtCore.Signal
        Emite el identificador de la evaluación cuyo informe debe
        abrirse.
    data_changed : PySide6.QtCore.Signal
        Se emite al eliminarse una evaluación desde la ficha, ya que
        altera cifras que otras secciones tienen dibujadas.
    """

    start_evaluation_requested = Signal(object)
    view_report_requested = Signal(int)
    data_changed = Signal()

    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state

        self.stack = QStackedWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

        self.list_view = ClientsView(state)
        self.profile_view = ClientProfileView(state)
        self.progress_view = ClientProgressView(state)

        self.stack.addWidget(self.list_view)
        self.stack.addWidget(self.profile_view)
        self.stack.addWidget(self.progress_view)

        self.list_view.client_selected.connect(self._show_profile)
        self.profile_view.back_requested.connect(self._show_list)
        self.profile_view.start_evaluation_requested.connect(self.start_evaluation_requested.emit)
        self.profile_view.view_report_requested.connect(self.view_report_requested.emit)
        self.profile_view.edit_requested.connect(self._edit_client)
        self.profile_view.view_progress_requested.connect(self._show_progress)
        self.progress_view.back_requested.connect(self._show_profile_again)
        self.profile_view.data_changed.connect(self.data_changed.emit)

        self.stack.setCurrentWidget(self.list_view)

    def _edit_client(self, client) -> None:
        """Abre el formulario de edición de un cliente.

        Parameters
        ----------
        client : myofit_pro.database.models.Client
            Cliente a editar.

        Notes
        -----
        El formulario pertenece a la lista, que lo abre también desde su
        menú contextual. La ficha se limita a solicitarlo y a recargarse
        si hubo cambios.
        """
        if self.list_view.edit_client(client):
            self.profile_view.reload()

    def _show_profile(self, client) -> None:
        """Muestra la ficha de un cliente."""
        self.profile_view.load_client(client)
        self.stack.setCurrentWidget(self.profile_view)

    def _show_progress(self, client) -> None:
        """Muestra la comparación entre evaluaciones de un cliente."""
        self.progress_view.load_client(client)
        self.stack.setCurrentWidget(self.progress_view)

    def _show_profile_again(self) -> None:
        """Vuelve del progreso a la ficha, recargándola.

        La recarga es necesaria porque el progreso pudo consultarse
        después de una evaluación nueva, en cuyo caso las cifras de la
        ficha —número de evaluaciones, última puntuación— han cambiado.
        """
        self.profile_view.reload()
        self.stack.setCurrentWidget(self.profile_view)

    def _show_list(self) -> None:
        """Vuelve a la lista de clientes, recargándola."""
        self.list_view.reload()
        self.stack.setCurrentWidget(self.list_view)

    def show_list(self) -> None:
        """Muestra la lista de clientes.

        Punto de entrada para la ventana principal, que la invoca al
        navegar a esta sección desde la barra lateral.
        """
        self._show_list()

    def show_profile(self, client) -> None:
        """Abre la ficha de un cliente desde otra sección.

        Parameters
        ----------
        client : myofit_pro.database.models.Client
            Cliente cuya ficha debe mostrarse.
        """
        self._show_profile(client)
        