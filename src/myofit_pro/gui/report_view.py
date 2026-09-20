"""Informe detallado de una evaluación.

Posición en el flujo
--------------------
Pantalla de detalle de `myofit_pro.gui.history_container`. No constituye
una sección propia de la barra lateral: solo se llega a ella desde una
lista de evaluaciones y carece de contenido sin una seleccionada.

El cuerpo del informe lo construye
`myofit_pro.gui.session_report.SessionReportBody`, compartido con el
último paso del asistente de evaluación. Esta vista aporta únicamente el
marco: el botón de retroceso y el área de desplazamiento.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from myofit_pro.gui.session_report import SessionReportBody
from myofit_pro.gui.theme import BackButton


class ReportView(QWidget):
    """Marco del informe de una evaluación.

    Parameters
    ----------
    state : myofit_pro.gui.app_state.AppState
        Estado compartido.
    parent : PySide6.QtWidgets.QWidget, optional
        Widget padre.

    Attributes
    ----------
    back_requested : PySide6.QtCore.Signal
        Se emite al pulsar el botón de retroceso.
    """

    back_requested = Signal()

    def __init__(self, state, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state

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
        self.back_button = BackButton("Historial")
        self.back_button.clicked.connect(self.back_requested.emit)
        back_row.addWidget(self.back_button)
        back_row.addStretch(1)
        layout.addLayout(back_row)

        self.body = SessionReportBody(state)
        layout.addWidget(self.body)

        scroll.setWidget(host)
        outer.addWidget(scroll)

        self.body.load(None)

    def load_session(self, session_id: int) -> None:
        """Carga el informe de una evaluación.

        Parameters
        ----------
        session_id : int
            Evaluación a mostrar.
        """
        self.body.load(session_id)

    def set_back_label(self, text: str) -> None:
        """Nombra el destino del botón de retroceso.

        Parameters
        ----------
        text : str
            Sección a la que se regresa. Lo fija quien abre el informe,
            ya que se llega a él desde el historial, la vista general y
            la ficha del cliente.
        """
        self.back_button.set_text(text)
