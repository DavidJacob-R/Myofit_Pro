"""
Equivalente a Views/SensorsView.xaml + SensorsView.xaml.cs de la
versión C#. Conecta al MyoBlueService real (compartido vía AppState),
muestra estado y batería en vivo, y abre el modal de prueba.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    FluentIcon as FIF,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    ToolButton,
)

from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.sensor_test_window import SensorTestWindow
from myofit_pro.gui.theme import (
    ACCENT_AMBER,
    ACCENT_BLUE,
    ACCENT_RED,
    ACCENT_TEAL,
    BG_CARD,
    BORDER,
    RADIUS_CARD,
    TEXT_SECONDARY,
    Card,
    IconBadge,
    MeterBar,
    PageHeader,
    Pill,
)
from myofit_pro.sensors import ConnectionState, MyoBlueService

_LIVE_TIMEOUT_SEC = 1.5


class _SensorCard(Card):
    """Tarjeta individual de un sensor (A o B): estado + batería."""

    def __init__(self, label: str, accent_color: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.label = label
        self.accent = accent_color

        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(IconBadge(FIF.SPEED_HIGH, accent_color, size=40))

        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        title_col.addWidget(StrongBodyLabel(f"Sensor {label}"))
        self.detail_label = BodyLabel("Receptor desconectado")
        self.detail_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        title_col.addWidget(self.detail_label)
        top.addLayout(title_col)

        top.addStretch(1)
        self.status_pill = Pill("Sin señal", TEXT_SECONDARY)
        top.addWidget(self.status_pill, alignment=Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(top)

        battery_row = QHBoxLayout()
        battery_label = BodyLabel("Batería")
        battery_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        battery_row.addWidget(battery_label)
        battery_row.addStretch(1)
        self.battery_value = BodyLabel("—")
        self.battery_value.setStyleSheet(
            f"color: {accent_color}; font-size: 13px; font-weight: 700;"
        )
        battery_row.addWidget(self.battery_value)
        self.body.addLayout(battery_row)

        self.battery_bar = MeterBar(0.0, accent_color)
        self.body.addWidget(self.battery_bar)

    def set_live(self, live: bool, connected: bool) -> None:
        if not connected:
            self._set_status("Sin señal", TEXT_SECONDARY, highlighted=False)
        elif live:
            self._set_status("Conectado", self.accent, highlighted=True)
        else:
            self._set_status("Esperando", ACCENT_AMBER, highlighted=False)

    def _set_status(self, text: str, color: str, highlighted: bool) -> None:
        self.status_pill.setText(text)
        self.status_pill.set_color(color)
        border = self.accent if highlighted else BORDER
        self.setStyleSheet(
            f"QFrame#card {{ background-color: {BG_CARD}; "
            f"border-radius: {RADIUS_CARD}px; border: 1px solid {border}; }}"
        )

    def set_battery(self, percent: int) -> None:
        self.battery_bar.set_value(float(percent))
        self.battery_value.setText(f"{percent}%")

    def set_detail(self, text: str) -> None:
        self.detail_label.setText(text)


class SensorsView(QWidget):
    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.sensors: MyoBlueService = state.sensors

        self._last_packet_a = 0.0
        self._last_packet_b = 0.0

        self._build_ui()
        self._connect_signals()

        self._live_timer = QTimer(self)
        self._live_timer.setInterval(500)
        self._live_timer.timeout.connect(self._refresh_live_status)
        self._live_timer.start()

        self.refresh_ports()
        self._update_connection_ui()

    # ── UI ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        layout.addWidget(
            PageHeader(
                "Sensores sEMG",
                "Conecta el dongle USB del MYOblue y verifica el estado de los sensores",
            )
        )

        # ── Tarjeta de conexión ───────────────────────────────────
        conn_card = Card()

        port_row = QHBoxLayout()
        port_row.addWidget(BodyLabel("Puerto:"))
        self.port_combo = ComboBox(conn_card)
        port_row.addWidget(self.port_combo, stretch=1)

        refresh_btn = ToolButton(FIF.SYNC, conn_card)
        refresh_btn.clicked.connect(self.refresh_ports)
        port_row.addWidget(refresh_btn)
        conn_card.body.addLayout(port_row)

        btn_row = QHBoxLayout()
        self.connect_btn = PrimaryPushButton("Conectar")
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        self.disconnect_btn = PushButton("Desconectar")
        self.disconnect_btn.clicked.connect(self._on_disconnect_clicked)
        self.disconnect_btn.setEnabled(False)
        btn_row.addWidget(self.connect_btn)
        btn_row.addWidget(self.disconnect_btn)
        conn_card.body.addLayout(btn_row)

        status_row = QHBoxLayout()
        self.status_pill = Pill("Desconectado", TEXT_SECONDARY)
        status_row.addWidget(self.status_pill)
        status_row.addStretch(1)
        conn_card.body.addLayout(status_row)

        layout.addWidget(conn_card)

        # ── Tarjetas de sensores ──────────────────────────────────
        cards_row = QHBoxLayout()
        cards_row.setSpacing(14)
        self.card_a = _SensorCard("A", ACCENT_TEAL)
        self.card_b = _SensorCard("B", ACCENT_BLUE)
        cards_row.addWidget(self.card_a)
        cards_row.addWidget(self.card_b)
        layout.addLayout(cards_row)

        self.test_sensors_btn = PrimaryPushButton("Probar sensores")
        self.test_sensors_btn.setIcon(FIF.SPEED_HIGH)
        self.test_sensors_btn.setEnabled(False)
        self.test_sensors_btn.clicked.connect(self._on_test_sensors_clicked)
        layout.addWidget(self.test_sensors_btn)

        layout.addStretch(1)

    def _connect_signals(self) -> None:
        self.sensors.connection_state_changed.connect(self._on_connection_state_changed)
        self.sensors.battery_updated.connect(self._on_battery_updated)
        self.sensors.samples_received.connect(self._on_samples_received)

    # ── Puertos ──────────────────────────────────────────────────────

    def refresh_ports(self) -> None:
        current = self.port_combo.currentText()
        self.port_combo.clear()
        ports = MyoBlueService.available_ports()
        self.port_combo.addItems(ports)
        if current in ports:
            self.port_combo.setCurrentText(current)

    # ── Conexión ─────────────────────────────────────────────────────

    def _on_connect_clicked(self) -> None:
        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "Sin puerto", "Selecciona primero un puerto COM.")
            return
        self.connect_btn.setEnabled(False)
        ok = self.sensors.connect_serial(port)
        if ok:
            self.sensors.start()

    def _on_disconnect_clicked(self) -> None:
        self.sensors.disconnect_serial()

    def _on_test_sensors_clicked(self) -> None:
        if not self.sensors.is_connected:
            QMessageBox.warning(self, "Sin conexión", "Conecta primero el receptor USB.")
            return
        window = SensorTestWindow(self.sensors, self)
        window.exec()

    # ── Eventos del servicio ─────────────────────────────────────────

    def _on_connection_state_changed(self, state: ConnectionState, _message: str) -> None:
        self._update_connection_ui()

    def _on_battery_updated(self, sensor_index: int, volts: float) -> None:
        percent = self._volts_to_percent(volts)
        if sensor_index == 0:
            self.card_a.set_battery(percent)
        elif sensor_index == 1:
            self.card_b.set_battery(percent)

    def _on_samples_received(self, block) -> None:
        now = time.monotonic()
        if block.sensor_index == 0:
            self._last_packet_a = now
        elif block.sensor_index == 1:
            self._last_packet_b = now

    def _refresh_live_status(self) -> None:
        now = time.monotonic()
        live_a = (now - self._last_packet_a) < _LIVE_TIMEOUT_SEC
        live_b = (now - self._last_packet_b) < _LIVE_TIMEOUT_SEC
        connected = self.sensors.is_connected

        self.card_a.set_live(live_a, connected)
        self.card_b.set_live(live_b, connected)

        if connected:
            self.card_a.set_detail(
                f"Activo · {self.sensors.channels[0].battery_volts:.2f} V" if live_a
                else "Esperando señal..."
            )
            self.card_b.set_detail(
                f"Activo · {self.sensors.channels[1].battery_volts:.2f} V" if live_b
                else "Esperando señal..."
            )
        else:
            self.card_a.set_detail("Receptor desconectado")
            self.card_b.set_detail("Receptor desconectado")

    def _update_connection_ui(self) -> None:
        state = self.sensors.state
        self.test_sensors_btn.setEnabled(self.sensors.is_connected)

        labels = {
            ConnectionState.DISCONNECTED: ("Desconectado", TEXT_SECONDARY),
            ConnectionState.CONNECTING: ("Conectando...", ACCENT_AMBER),
            ConnectionState.CONNECTED: (
                f"Conectado · {self.sensors.current_port}", ACCENT_TEAL
            ),
            ConnectionState.ERROR: ("Error de conexión", ACCENT_RED),
        }
        text, color = labels.get(state, ("—", TEXT_SECONDARY))
        self.status_pill.setText(text)
        self.status_pill.set_color(color)

        self.connect_btn.setEnabled(state in (ConnectionState.DISCONNECTED, ConnectionState.ERROR))
        self.disconnect_btn.setEnabled(state == ConnectionState.CONNECTED)
        self.port_combo.setEnabled(state in (ConnectionState.DISCONNECTED, ConnectionState.ERROR))

    @staticmethod
    def _volts_to_percent(volts: float) -> int:
        pct = (volts - 2.5) / 0.5 * 100.0
        return int(max(0, min(100, pct)))