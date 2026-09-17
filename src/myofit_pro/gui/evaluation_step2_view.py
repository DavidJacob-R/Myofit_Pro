"""
Paso 2 del wizard — Guía de colocación de electrodos.

Muestra el texto guía (`Muscle.placement_guide`) del músculo elegido
en el Paso 1. Si el músculo no tiene guía cargada en la base de datos,
se muestra un mensaje genérico en vez de dejar la pantalla en blanco.

A la derecha va la preparación de la piel y el aviso de qué pasa si el
contacto queda mal. No es relleno: un electrodo mal pegado satura el
convertidor y produce una calibración MVC alta pero falsa, que después
invalida en silencio todas las evaluaciones de ese cliente. El Paso 3
ya detecta ese caso y no deja avanzar, pero llegar ahí significa
repetir la colocación, y avisarlo antes ahorra ese viaje.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel
from qfluentwidgets import FluentIcon as FIF

from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.wizard_step import WizardStep
from myofit_pro.gui.theme import (
    ACCENT_AMBER,
    ACCENT_BLUE,
    ACCENT_TEAL,
    BG_ELEVATED,
    BORDER,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    Card,
    IconBadge,
    clear_layout,
)

_GENERIC_GUIDE = (
    "Coloca ambos electrodos sobre el vientre muscular, siguiendo la "
    "dirección de las fibras, separados por 2-3 cm. Limpia la piel con "
    "alcohol antes de colocar los sensores para mejorar el contacto."
)

# Pasos de preparación, en el orden en que se hacen.
_CHECKLIST = (
    ("Limpia la piel con alcohol", "Quita grasa y sudor, que son lo que arruina el contacto"),
    ("Espera a que seque", "Con la piel húmeda el electrodo se despega a media serie"),
    ("Sigue la dirección de las fibras", "Los dos electrodos alineados con el músculo, no cruzados"),
    ("Deja 2 a 3 cm entre electrodos", "Más juntos captan poca señal, más separados captan vecinos"),
)


class _ChecklistItem(QWidget):
    """Un paso de la preparación: número, título y por qué importa."""

    def __init__(self, number: int, title: str, why: str, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(11)

        badge = QLabel(str(number))
        badge.setFixedSize(24, 24)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background-color: {BG_ELEVATED}; color: {TEXT_SECONDARY}; "
            f"border: 1px solid {BORDER}; border-radius: 12px; "
            f"font-size: 11px; font-weight: 800;"
        )
        layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)

        title_label = QLabel(title)
        title_label.setWordWrap(True)
        title_label.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: 650; "
            f"background: transparent; border: none;"
        )
        text_col.addWidget(title_label)

        why_label = QLabel(why)
        why_label.setWordWrap(True)
        why_label.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 11px; background: transparent; border: none;"
        )
        text_col.addWidget(why_label)

        layout.addLayout(text_col, stretch=1)


class _SensorLegend(QWidget):
    """
    Recordatorio de qué color es cada sensor.

    Los mismos dos colores se usan en las gráficas de los pasos 4 y 5,
    así que conviene fijarlos desde aquí, cuando el entrenador todavía
    tiene los dos sensores en la mano.
    """

    def __init__(self, label: str, color: str, role: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"background-color: {BG_ELEVATED}; border: 1px solid {color}; "
            f"border-radius: 13px;"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(11)
        layout.addWidget(IconBadge(label, color, size=34))

        text_col = QVBoxLayout()
        text_col.setSpacing(1)

        title = QLabel(f"Sensor {label}")
        title.setStyleSheet(
            f"color: {color}; font-size: 13px; font-weight: 750; "
            f"background: transparent; border: none;"
        )
        text_col.addWidget(title)

        role_label = QLabel(role)
        role_label.setWordWrap(True)
        role_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; "
            f"background: transparent; border: none;"
        )
        text_col.addWidget(role_label)

        layout.addLayout(text_col, stretch=1)


class EvaluationStep2View(WizardStep):
    ready_to_continue = Signal()
    CONTINUE_LABEL = "Ya coloqué los sensores  →"

    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._outer_layout = QVBoxLayout(self)
        self._outer_layout.setContentsMargins(0, 0, 0, 0)
        self._outer_layout.setSpacing(14)
        self._populate()

    def _populate(self) -> None:
        # Limpiar contenido anterior (por si se llama desde refresh())
        clear_layout(self._outer_layout)

        columns = QHBoxLayout()
        columns.setSpacing(14)
        columns.addWidget(self._build_guide_card(), stretch=3)
        columns.addWidget(self._build_prep_card(), stretch=2)
        self._outer_layout.addLayout(columns)

        # Sin esto las tarjetas se estiran hasta el fondo de la ventana y
        # queda un hueco enorme debajo del texto.
        self._outer_layout.addStretch(1)

    def _build_guide_card(self) -> Card:
        muscle = self.state.active_muscle
        muscle_name = muscle.name if muscle else "—"

        card = Card()

        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(IconBadge(FIF.PIN, ACCENT_TEAL, size=42))

        head_col = QVBoxLayout()
        head_col.setSpacing(1)

        title = QLabel(muscle_name)
        title.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 19px; font-weight: 750; "
            f"letter-spacing: -0.3px; background: transparent; border: none;"
        )
        head_col.addWidget(title)

        subtitle = QLabel(
            "Guía de colocación"
            if muscle and muscle.placement_guide
            else "Sin guía específica cargada, se muestra la general"
        )
        subtitle.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12px; "
            f"background: transparent; border: none;"
        )
        head_col.addWidget(subtitle)

        head.addLayout(head_col, stretch=1)
        card.body.addLayout(head)

        guide_text = _GENERIC_GUIDE
        if muscle and muscle.placement_guide:
            guide_text = muscle.placement_guide

        guide_label = BodyLabel(guide_text)
        guide_label.setWordWrap(True)
        card.body.addWidget(guide_label)

        card.body.addSpacing(6)
        card.body.addWidget(
            _SensorLegend("A", ACCENT_TEAL, "Verde en todas las gráficas de la evaluación")
        )
        card.body.addWidget(
            _SensorLegend("B", ACCENT_BLUE, "Azul en todas las gráficas de la evaluación")
        )
        return card

    def _build_prep_card(self) -> Card:
        card = Card()
        card.add_title("Preparación de la piel", "Cuatro cosas, en este orden")

        for index, (title, why) in enumerate(_CHECKLIST, start=1):
            card.body.addWidget(_ChecklistItem(index, title, why))

        card.body.addSpacing(8)
        card.body.addWidget(self._build_warning())
        return card

    @staticmethod
    def _build_warning() -> QWidget:
        box = QWidget()
        box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        box.setStyleSheet(
            f"background-color: rgba(251, 191, 36, 0.08); "
            f"border: 1px solid rgba(251, 191, 36, 0.3); border-radius: 13px;"
        )

        layout = QHBoxLayout(box)
        layout.setContentsMargins(12, 11, 12, 11)
        layout.setSpacing(11)
        layout.addWidget(IconBadge(FIF.INFO, ACCENT_AMBER, size=32), alignment=Qt.AlignmentFlag.AlignTop)

        text = QLabel(
            "Si un electrodo queda mal pegado, la señal que llega es ruido y no "
            "actividad muscular. El siguiente paso lo detecta y no te deja "
            "continuar, porque una calibración hecha con ruido arruina todas las "
            "evaluaciones posteriores de este cliente."
        )
        text.setWordWrap(True)
        text.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(text, stretch=1)
        return box

    def on_enter(self) -> None:
        """El contenido depende del músculo elegido, que pudo cambiar."""
        self._populate()

    def refresh(self) -> None:
        self._populate()
