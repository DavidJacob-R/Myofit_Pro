"""
Paso 3 del wizard — Verificación de conexión de sensores.

No deja avanzar a la calibración MVC (Paso 4) si el receptor no está
conectado o si alguno de los 2 sensores no está enviando señal viva.
Reusa el mismo MyoBlueService compartido (state.sensors) que ya usa
SensorsView — no crea una conexión aparte.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, PrimaryPushButton, StrongBodyLabel

from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.theme import ACCENT_BLUE, ACCENT_TEAL, Card

_LIVE_TIMEOUT_SEC = 1.5


class _SensorStatusCard(Card):
    def __init__(self, label: str, accent: str, parent=None):
        super().__init__(parent)
        self.accent = accent
        self.body.addWidget(StrongBodyLabel(f"Sensor {label}"))
        self.status_label = BodyLabel("Verificando...")
        self.body.addWidget(self.status_label)

    def set_live(self, live: bool) -> None:
        if live:
            self.status_label.setText("✅ Conectado")
            self.setStyleSheet(
                f"QFrame#card {{ background-color: #2A2640; border-radius: 18px; "
                f"border: 2px solid {self.accent}; }}"
            )
        else:
            self.status_label.setText("⚠️ Sin señal")
            self.setStyleSheet(
                "QFrame#card { background-color: #2A2640; border-radius: 18px; "
                "border: 2px solid transparent; }"
            )


class EvaluationStep3View(QWidget):
    connection_verified = Signal()

    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.sensors = state.sensors

        self._last_packet_a = 0.0
        self._last_packet_b = 0.0

        self._build_ui()
        self.sensors.samples_received.connect(self._on_samples_received)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start()

        self.destroyed.connect(lambda: self._timer.stop())

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)

        outer.addWidget(
            BodyLabel("Confirma que ambos sensores estén conectados y enviando señal antes de calibrar.")
        )

        cards_row = QHBoxLayout()
        cards_row.setSpacing(14)
        self.card_a = _SensorStatusCard("A", ACCENT_TEAL)
        self.card_b = _SensorStatusCard("B", ACCENT_BLUE)
        cards_row.addWidget(self.card_a)
        cards_row.addWidget(self.card_b)
        outer.addLayout(cards_row)

        status_card = Card()
        self.receiver_status = BodyLabel("")
        status_card.body.addWidget(self.receiver_status)
        outer.addWidget(status_card)

        outer.addStretch(1)

        self.next_btn = PrimaryPushButton("Continuar a calibración →")
        self.next_btn.clicked.connect(self._on_next_clicked)
        outer.addWidget(self.next_btn)

    def _on_samples_received(self, block) -> None:
        now = time.monotonic()
        if block.sensor_index == 0:
            self._last_packet_a = now
        elif block.sensor_index == 1:
            self._last_packet_b = now

    def _refresh_status(self) -> None:
        now = time.monotonic()
        live_a = (now - self._last_packet_a) < _LIVE_TIMEOUT_SEC
        live_b = (now - self._last_packet_b) < _LIVE_TIMEOUT_SEC
        connected = self.sensors.is_connected

        self.card_a.set_live(live_a)
        self.card_b.set_live(live_b)

        if not connected:
            self.receiver_status.setText(
                "El receptor USB no está conectado. Ve a 'Sensores sEMG' para conectarlo."
            )
        elif not (live_a and live_b):
            self.receiver_status.setText(
                "Receptor conectado, esperando señal de ambos sensores (enciéndelos si no lo has hecho)."
            )
        else:
            self.receiver_status.setText("✅ Todo listo para continuar.")

        self.next_btn.setEnabled(connected and live_a and live_b)

    def _on_next_clicked(self) -> None:
        if not self.next_btn.isEnabled():
            QMessageBox.warning(
                self, "Sensores no listos",
                "Espera a que ambos sensores muestren señal activa antes de continuar.",
            )
            return
        self.connection_verified.emit()