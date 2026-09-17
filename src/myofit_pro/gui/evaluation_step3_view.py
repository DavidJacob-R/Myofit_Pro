"""
Paso 3 del wizard — Verificación de conexión de sensores.

No deja avanzar a la calibración MVC (Paso 4) si el receptor no está
conectado, si alguno de los 2 sensores no está enviando señal viva, o
si alguno perdió contacto con la piel. Reusa el mismo MyoBlueService
compartido (state.sensors) que ya usa SensorsView, no crea una conexión
aparte.

Cada sensor muestra su señal en vivo. Es la forma más directa de
confirmar que el electrodo quedó bien: una línea que responde cuando el
cliente contrae dice más que cualquier etiqueta de "conectado", y una
línea que brinca de extremo a extremo se reconoce a simple vista como
electrodo despegado.

Los tres requisitos para continuar se muestran como lista con su estado,
en vez de un solo mensaje de texto: si el botón está bloqueado, se ve
exactamente cuál de los tres falta.
"""

from __future__ import annotations

import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.wizard_step import WizardStep
from myofit_pro.gui.theme import (
    ACCENT_BLUE,
    ACCENT_LIME,
    ACCENT_RED,
    ACCENT_TEAL,
    BG_CARD,
    BG_ELEVATED,
    BORDER,
    RADIUS_CARD,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    Card,
    IconBadge,
    Pill,
)
from myofit_pro.sensors.channel import SATURATION_LIMIT

_LIVE_TIMEOUT_SEC = 1.5
_PREVIEW_SEC = 4.0
_LOW_BATTERY_V = 2.6


class _MetricChip(QWidget):
    """Dato pequeño bajo la gráfica: valor grande, etiqueta chica."""

    def __init__(self, caption: str, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.value_label = QLabel("—")
        self.value_label.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 15px; font-weight: 800; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(self.value_label)

        caption_label = QLabel(caption)
        caption_label.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 10px; font-weight: 600; "
            f"letter-spacing: 0.3px; background: transparent; border: none;"
        )
        layout.addWidget(caption_label)

    def set_value(self, text: str, color: str = TEXT_PRIMARY) -> None:
        self.value_label.setText(text)
        self.value_label.setStyleSheet(
            f"color: {color}; font-size: 15px; font-weight: 800; "
            f"background: transparent; border: none;"
        )


class _SensorStatusCard(Card):
    """Estado de un sensor: etiqueta, señal en vivo, batería y contacto."""

    def __init__(self, label: str, accent: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.accent = accent

        head = QHBoxLayout()
        head.setSpacing(11)
        head.addWidget(IconBadge(label, accent, size=38))

        title = QLabel(f"Sensor {label}")
        title.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 16px; font-weight: 750; "
            f"background: transparent; border: none;"
        )
        head.addWidget(title)
        head.addStretch(1)

        self.status_label = Pill("Verificando...", TEXT_SECONDARY)
        head.addWidget(self.status_label)
        self.body.addLayout(head)

        # Vista previa de la señal. Sin ejes ni interacción: aquí no se
        # mide nada, solo se confirma que la señal se mueve y no está
        # pegada a los topes.
        self.plot = pg.PlotWidget(background=BG_ELEVATED)
        self.plot.setFixedHeight(96)
        self.plot.hideAxis("bottom")
        self.plot.hideAxis("left")
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.setMenuEnabled(False)
        self.plot.setYRange(-400, 400)
        self.curve = self.plot.plot(pen=pg.mkPen(accent, width=1.5))
        self.body.addWidget(self.plot)

        metrics = QHBoxLayout()
        metrics.setSpacing(18)
        self.rms_chip = _MetricChip("RMS ACTUAL")
        self.battery_chip = _MetricChip("BATERÍA")
        self.contact_chip = _MetricChip("CONTACTO")
        metrics.addWidget(self.rms_chip)
        metrics.addWidget(self.battery_chip)
        metrics.addWidget(self.contact_chip)
        metrics.addStretch(1)
        self.body.addLayout(metrics)

    def set_status(self, live: bool, signal_valid: bool) -> None:
        if live and signal_valid:
            self._set_pill("Conectado", self.accent, self.accent)
        elif live:
            self._set_pill("Electrodo despegado", ACCENT_RED, ACCENT_RED)
        else:
            self._set_pill("Sin señal", TEXT_SECONDARY, BORDER)

    def _set_pill(self, text: str, pill_color: str, border: str) -> None:
        self.status_label.setText(text)
        self.status_label.set_color(pill_color)
        self.setStyleSheet(
            f"QFrame#card {{ background-color: {BG_CARD}; "
            f"border-radius: {RADIUS_CARD}px; border: 1px solid {border}; }}"
        )


class _RequirementRow(QWidget):
    """Un requisito para poder continuar, con su estado actual."""

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(11)

        self.mark = QLabel("")
        self.mark.setFixedSize(22, 22)
        self.mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.mark)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: 600; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(self.title_label)

        self.detail_label = QLabel("")
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12px; "
            f"background: transparent; border: none;"
        )
        layout.addWidget(self.detail_label, stretch=1)

        self.set_state(False, "")

    def set_state(self, ok: bool, detail: str) -> None:
        self.mark.setText("✓" if ok else "")
        color = ACCENT_LIME if ok else BORDER
        self.mark.setStyleSheet(
            f"background-color: {color if ok else 'transparent'}; "
            f"color: {BG_CARD if ok else TEXT_MUTED}; "
            f"border: 1px solid {color}; border-radius: 11px; "
            f"font-size: 12px; font-weight: 800;"
        )
        self.detail_label.setText(detail)


class EvaluationStep3View(WizardStep):
    connection_verified = Signal()
    CONTINUE_LABEL = "Continuar a calibración  →"

    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.sensors = state.sensors

        self._last_packet = [0.0, 0.0]
        self._ready = False

        # Buffer circular por canal para la vista previa
        n = int(_PREVIEW_SEC * self.sensors.sample_rate_hz)
        self._buffers = [np.zeros(n), np.zeros(n)]
        self._positions = [0, 0]

        self._build_ui()
        self.sensors.samples_received.connect(self._on_samples_received)

        self._timer = QTimer(self)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start()

        self.destroyed.connect(lambda: self._timer.stop())

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(14)
        self.cards = [
            _SensorStatusCard("A", ACCENT_TEAL),
            _SensorStatusCard("B", ACCENT_BLUE),
        ]
        for card in self.cards:
            cards_row.addWidget(card)
        outer.addLayout(cards_row)

        checks_card = Card()
        checks_card.add_title(
            "Para continuar", "Los tres tienen que cumplirse antes de calibrar"
        )
        self.req_receiver = _RequirementRow("Receptor USB conectado")
        self.req_live = _RequirementRow("Ambos sensores enviando señal")
        self.req_contact = _RequirementRow("Buen contacto con la piel")
        for row in (self.req_receiver, self.req_live, self.req_contact):
            checks_card.body.addWidget(row)
        outer.addWidget(checks_card)
        outer.addStretch(1)

    # ── Señal en vivo ────────────────────────────────────────────────

    def _on_samples_received(self, block) -> None:
        index = block.sensor_index
        if index not in (0, 1):
            return

        self._last_packet[index] = time.monotonic()

        buf = self._buffers[index]
        samples = block.filtered
        n = len(samples)
        start = self._positions[index]
        end = start + n
        if end <= len(buf):
            buf[start:end] = samples
        else:
            first = len(buf) - start
            buf[start:] = samples[:first]
            buf[: end - len(buf)] = samples[first:]
        self._positions[index] = end % len(buf)

        self.cards[index].curve.setData(buf)

    # ── Estado ───────────────────────────────────────────────────────

    def _refresh_status(self) -> None:
        now = time.monotonic()
        connected = self.sensors.is_connected

        live = [(now - stamp) < _LIVE_TIMEOUT_SEC for stamp in self._last_packet]
        valid = [self.sensors.channels[i].signal_is_valid for i in (0, 1)]

        for index, card in enumerate(self.cards):
            channel = self.sensors.channels[index]
            card.set_status(live[index], valid[index])
            self._refresh_metrics(card, channel, live[index], valid[index])

        self._refresh_requirements(connected, live, valid)

        ready = connected and all(live) and all(valid)
        if ready != self._ready:
            self._ready = ready
            self.continue_state_changed.emit()

    @staticmethod
    def _refresh_metrics(card, channel, live: bool, valid: bool) -> None:
        if not live:
            card.rms_chip.set_value("—", TEXT_MUTED)
            card.battery_chip.set_value("—", TEXT_MUTED)
            card.contact_chip.set_value("—", TEXT_MUTED)
            return

        card.rms_chip.set_value(f"{channel.latest_rms:.0f} µV")

        volts = channel.battery_volts
        if volts > 0:
            card.battery_chip.set_value(
                f"{volts:.2f} V",
                ACCENT_RED if volts < _LOW_BATTERY_V else ACCENT_LIME,
            )
        else:
            card.battery_chip.set_value("—", TEXT_MUTED)

        # La saturación es la fracción de muestras pegadas a los topes
        # del convertidor. Se muestra en claro porque es exactamente el
        # número por el que se bloquea el paso.
        saturation = channel.latest_saturation
        card.contact_chip.set_value(
            "Bueno" if valid else f"{saturation * 100:.1f}% saturado",
            ACCENT_LIME if valid else ACCENT_RED,
        )

    def _refresh_requirements(self, connected: bool, live: list[bool], valid: list[bool]) -> None:
        self.req_receiver.set_state(
            connected,
            f"Puerto {self.sensors.current_port}"
            if connected
            else "Ve a 'Sensores sEMG' para conectarlo",
        )

        missing_live = [name for name, ok in zip("AB", live) if not ok]
        self.req_live.set_state(
            all(live),
            "Los dos están transmitiendo"
            if all(live)
            else f"{self._sensor_phrase(missing_live)} sin transmitir. Enciéndelo si no lo has hecho.",
        )

        # El contacto solo puede darse por bueno si hay señal que juzgar.
        # `signal_is_valid` devuelve True con la ventana vacía, así que
        # sin esta condición el requisito saldría en verde con los
        # sensores apagados, que es justo cuando menos se sabe.
        detached = [name for name, ok in zip("AB", valid) if not ok]
        contact_ok = all(live) and all(valid)
        if contact_ok:
            detail = f"Saturación por debajo del {SATURATION_LIMIT * 100:.1f}% en ambos"
        elif not all(live):
            detail = "Se mide en cuanto los sensores empiecen a transmitir"
        else:
            detail = (
                f"{self._sensor_phrase(detached)} sin contacto. Limpia la zona con "
                "alcohol y vuelve a colocar el electrodo: si continúas, el MVC se "
                "calcularía con ruido y quedaría inservible."
            )
        self.req_contact.set_state(contact_ok, detail)

    @staticmethod
    def _sensor_phrase(names: list[str]) -> str:
        """'El sensor A' o 'Los sensores A y B', según cuántos sean."""
        if len(names) == 1:
            return f"El sensor {names[0]} está"
        return f"Los sensores {' y '.join(names)} están"

    def can_continue(self) -> bool:
        return self._ready

    def blocked_reason(self) -> str:
        return (
            "Espera a que los tres requisitos de la tarjeta 'Para continuar' "
            "estén en verde."
        )
