"""Sección de historial: lista de evaluaciones e informe de detalle.

Posición en el flujo
--------------------
Ocupa una sola entrada de la barra lateral y alberga dos pantallas:
`myofit_pro.gui.history_view.HistoryView`, que lista las evaluaciones de
todos los clientes del entrenador, y
`myofit_pro.gui.report_view.ReportView`, que muestra una de ellas en
detalle.

Motivo de la unificación
------------------------
Historial e informe fueron en su momento dos secciones hermanas que
presentaban la misma información con distinto nivel de detalle. El
informe abierto por su cuenta mostraba un estado vacío que remitía al
historial, y el historial no conducía a ninguna parte sin el informe.

Al convertir el informe en la pantalla de detalle del historial, la
navegación refleja la relación real entre ambos: de una lista se entra a
un detalle y se regresa. Es el mismo patrón de
`myofit_pro.gui.clients_container` y
`myofit_pro.gui.routines_container`.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from myofit_pro.gui.history_view import HistoryView
from myofit_pro.gui.report_view import ReportView


class HistoryContainer(QWidget):
    """Contenedor de la sección de historial.

    Parameters
    ----------
    state : myofit_pro.gui.app_state.AppState
        Estado compartido.
    parent : PySide6.QtWidgets.QWidget, optional
        Widget padre.

    Attributes
    ----------
    resume_session_requested : PySide6.QtCore.Signal
        Emite el identificador de una evaluación sin terminar que debe
        retomarse en el asistente.
    data_changed : PySide6.QtCore.Signal
        Se emite al eliminarse o cancelarse una evaluación, para que el
        resto de secciones se actualicen.
    report_closed : PySide6.QtCore.Signal
        Se emite al cerrarse el informe, para que
        `myofit_pro.gui.main_window.MainWindow` decida el destino.
    """

    resume_session_requested = Signal(int)
    data_changed = Signal()
    report_closed = Signal()

    def __init__(self, state, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state

        self.stack = QStackedWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

        self.list_view = HistoryView(state)
        self.report_view = ReportView(state)

        self.stack.addWidget(self.list_view)
        self.stack.addWidget(self.report_view)

        self.list_view.session_selected.connect(self.show_report)
        self.list_view.resume_session_requested.connect(self.resume_session_requested.emit)
        self.list_view.data_changed.connect(self.data_changed.emit)
        self.report_view.back_requested.connect(self._on_back)

        self.stack.setCurrentWidget(self.list_view)

    # ── Navegación interna ───────────────────────────────────────────

    def show_report(self, session_id: int, back_label: str = "Historial") -> None:
        """Abre el informe de una evaluación.

        Parameters
        ----------
        session_id : int
            Evaluación a mostrar.
        back_label : str, default="Historial"
            Sección a la que regresa el botón de retroceso. Lo fija
            quien abre el informe, ya que se llega a él desde tres
            secciones distintas.
        """
        self.report_view.set_back_label(back_label)
        self.report_view.load_session(session_id)
        self.stack.setCurrentWidget(self.report_view)

    def show_list(self) -> None:
        """Vuelve a la lista de evaluaciones, recargándola."""
        self.list_view.reload()
        self.stack.setCurrentWidget(self.list_view)

    def is_showing_report(self) -> bool:
        """Si el informe está visible.

        La ventana principal lo consulta para no recargar la lista
        mientras hay un detalle abierto, lo que lo cerraría.
        """
        return self.stack.currentWidget() is self.report_view

    def reload(self) -> None:
        """Recarga la lista de evaluaciones."""
        self.list_view.reload()

    def _on_back(self) -> None:
        """Cierra el informe y vuelve a la lista.

        El contenedor regresa a su lista aunque la evaluación se haya
        abierto desde otra sección, de modo que quede en ese estado la
        próxima vez que se entre por la barra lateral. Si procede
        devolver al usuario a su sección de origen, lo decide
        `myofit_pro.gui.main_window.MainWindow` al recibir
        `report_closed`.
        """
        self.show_list()
        self.report_closed.emit()
