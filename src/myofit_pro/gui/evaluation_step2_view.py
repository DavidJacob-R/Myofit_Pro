"""
Paso 2 del wizard — Guía de colocación de electrodos.

Muestra el texto guía (`Muscle.placement_guide`) del músculo elegido
en el Paso 1. Si el músculo no tiene guía cargada en la base de datos,
se muestra un mensaje genérico en vez de dejar la pantalla en blanco.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, PrimaryPushButton, StrongBodyLabel
from qfluentwidgets import FluentIcon as FIF

from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.theme import ACCENT_TEAL, Card, IconBadge

_GENERIC_GUIDE = (
    "Coloca ambos electrodos sobre el vientre muscular, siguiendo la "
    "dirección de las fibras, separados por 2-3 cm. Limpia la piel con "
    "alcohol antes de colocar los sensores para mejorar el contacto."
)


class EvaluationStep2View(QWidget):
    ready_to_continue = Signal()

    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._outer_layout = QVBoxLayout(self)
        self._outer_layout.setContentsMargins(0, 0, 0, 0)
        self._card: Card | None = None
        self._populate()

    def _populate(self) -> None:
        # Limpiar contenido anterior (por si se llama desde refresh())
        while self._outer_layout.count():
            item = self._outer_layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w:
                w.deleteLater()

        muscle_name = self.state.active_muscle.name if self.state.active_muscle else "—"

        card = Card()

        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(IconBadge(FIF.PIN, ACCENT_TEAL, size=40))
        head.addWidget(StrongBodyLabel(muscle_name))
        head.addStretch(1)
        card.body.addLayout(head)

        guide_text = _GENERIC_GUIDE
        if self.state.active_muscle and self.state.active_muscle.placement_guide:
            guide_text = self.state.active_muscle.placement_guide

        guide_label = BodyLabel(guide_text)
        guide_label.setWordWrap(True)
        card.body.addWidget(guide_label)

        card.body.addStretch(1)

        next_btn = PrimaryPushButton("Ya coloqué los sensores →")
        next_btn.clicked.connect(self.ready_to_continue.emit)
        card.body.addWidget(next_btn)

        self._outer_layout.addWidget(card)
        self._card = card

    def refresh(self) -> None:
        """Llamar cada vez que se navega a este paso, por si cambió el músculo activo."""
        self._populate()