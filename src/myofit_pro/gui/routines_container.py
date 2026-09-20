"""Sección de rutinas: lista por fecha y rutina completa.

Posición en el flujo
--------------------
Ocupa una sola entrada de la barra lateral y alberga dos pantallas:
`myofit_pro.gui.routines_list_view.RoutinesListView`, que lista las
rutinas de un cliente ordenadas por fecha y permite generar una nueva, y
`myofit_pro.gui.routine_detail_view.RoutineDetailView`, que muestra y
permite editar una de ellas.

Aplica el mismo patrón que `myofit_pro.gui.clients_container` y
`myofit_pro.gui.history_container`.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from myofit_pro.gui.routine_detail_view import RoutineDetailView
from myofit_pro.gui.routines_list_view import RoutinesListView


class RoutinesContainer(QWidget):
    """Contenedor de la sección de rutinas.

    Parameters
    ----------
    state : myofit_pro.gui.app_state.AppState
        Estado compartido.
    parent : PySide6.QtWidgets.QWidget, optional
        Widget padre.

    Attributes
    ----------
    data_changed : PySide6.QtCore.Signal
        Se emite al generarse, editarse o eliminarse una rutina.
    """

    data_changed = Signal()

    def __init__(self, state, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state

        self.stack = QStackedWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

        self.list_view = RoutinesListView(state)
        self.detail_view = RoutineDetailView(state)

        self.stack.addWidget(self.list_view)
        self.stack.addWidget(self.detail_view)

        self.list_view.routine_selected.connect(self.show_routine)
        self.list_view.data_changed.connect(self.data_changed.emit)
        self.detail_view.back_requested.connect(self.show_list)
        self.detail_view.routine_changed.connect(self.data_changed.emit)

        self.stack.setCurrentWidget(self.list_view)

    def show_routine(self, routine_id: int) -> None:
        """Abre una rutina en la pantalla de detalle.

        Parameters
        ----------
        routine_id : int
            Rutina a mostrar.
        """
        self.detail_view.load_routine(routine_id)
        self.stack.setCurrentWidget(self.detail_view)

    def show_list(self) -> None:
        """Vuelve a la lista de rutinas, recargándola."""
        self.list_view.reload()
        self.stack.setCurrentWidget(self.list_view)

    def is_showing_detail(self) -> bool:
        """Si hay una rutina abierta.

        La ventana principal lo consulta para no recargar la lista
        mientras hay un detalle abierto, lo que lo cerraría.
        """
        return self.stack.currentWidget() is self.detail_view

    def reload(self) -> None:
        """Recarga la lista de rutinas."""
        self.list_view.reload()

    def show_for_client(self, client) -> None:
        """Abre la lista filtrada por un cliente.

        Parameters
        ----------
        client : myofit_pro.database.models.Client
            Cliente por el que filtrar. Se invoca desde su ficha.
        """
        self.list_view.reload()
        self.list_view.select_client(client)
        self.stack.setCurrentWidget(self.list_view)
