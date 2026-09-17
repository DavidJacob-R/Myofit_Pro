"""
Paso 4 del wizard — Calibración MVC (contracción voluntaria máxima).

Decisiones de diseño ya acordadas:
  - MVC = promedio de Sensor A y Sensor B durante la contracción
    (Filosofía A: ambos sensores sobre el mismo músculo).
  - Captura por botón Iniciar/Detener manual (no automática a 5s).

El pico de cada canal por separado también se guarda (mvc_channel_a_uv,
mvc_channel_b_uv) para poder analizar balance más adelante, aunque el
valor usado como referencia de normalización es el promedio.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import PrimaryPushButton, PushButton

from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.wizard_step import WizardStep
from myofit_pro.gui.theme import (
    ACCENT_AMBER,
    ACCENT_BLUE,
    ACCENT_RED,
    ACCENT_TEAL,
    ACCENT_VIOLET,
    BG_ELEVATED,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    Card,
    IconBadge,
    Pill,
    StatCard,
)
from myofit_pro.sensors.channel import SATURATION_LIMIT

_WAVE_WINDOW_SEC = 6.0


class EvaluationStep4View(WizardStep):
    """Calibración MVC — evento `calibration_saved` cuando termina."""

    calibration_saved = Signal()
    CONTINUE_LABEL = "Guardar y continuar  →"

    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.sensors = state.sensors

        self._recording = False
        self._peak_a = 0.0
        self._peak_b = 0.0
        # Ventana deslizante de RMS por canal, para promediar sobre la
        # contracción completa (no solo el último instante)
        self._rms_history_a: list[float] = []
        self._rms_history_b: list[float] = []
        # Peor saturación vista durante la captura, por canal
        self._saturation_a = 0.0
        self._saturation_b = 0.0
        self._capture_ready = False

        self._build_ui()
        self.sensors.samples_received.connect(self._on_samples_received)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        layout.addWidget(self._build_instructions())
        layout.addWidget(self._build_plot_card(), stretch=1)

        numbers = QHBoxLayout()
        numbers.setSpacing(12)
        self.peak_a_card = StatCard("A", ACCENT_TEAL, "Pico Sensor A", "0 µV")
        self.peak_b_card = StatCard("B", ACCENT_BLUE, "Pico Sensor B", "0 µV")
        self.avg_card = StatCard(
            FIF.SPEED_HIGH, ACCENT_VIOLET, "Promedio (MVC)", "0 µV"
        )
        self.avg_card.set_caption("la referencia con la que se normaliza todo")
        numbers.addWidget(self.peak_a_card)
        numbers.addWidget(self.peak_b_card)
        numbers.addWidget(self.avg_card)
        layout.addLayout(numbers)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.start_btn = PrimaryPushButton("Iniciar captura")
        self.start_btn.setIcon(FIF.PLAY_SOLID)
        self.start_btn.clicked.connect(self._on_start_clicked)
        btn_row.addWidget(self.start_btn)

        self.stop_btn = PushButton("Detener")
        self.stop_btn.setIcon(FIF.PAUSE_BOLD)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        btn_row.addWidget(self.stop_btn)

        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        # Buffers de graficado (solo visual, no se usan para el cálculo del MVC)
        n = int(_WAVE_WINDOW_SEC * self.sensors.sample_rate_hz)
        self._buf_a = np.zeros(n)
        self._buf_b = np.zeros(n)
        self._buf_pos = 0

        # Parpadeo del indicador de grabación: sin él, un "Grabando"
        # fijo se confunde con una etiqueta más de la pantalla.
        self._blink_on = True
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(600)
        self._blink_timer.timeout.connect(self._blink)

    def _build_instructions(self) -> Card:
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(
            IconBadge(FIF.SPEED_HIGH, ACCENT_VIOLET, size=42),
            alignment=Qt.AlignmentFlag.AlignTop,
        )

        col = QVBoxLayout()
        col.setSpacing(2)

        title = QLabel("Contracción voluntaria máxima")
        title.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 16px; font-weight: 750; "
            f"background: transparent; border: none;"
        )
        col.addWidget(title)

        detail = QLabel(
            "Pide al cliente una contracción máxima sostenida de 3 a 5 segundos. "
            "Presiona Iniciar justo antes de que empiece y Detener cuando afloje. "
            "Este valor es la referencia contra la que se mide todo lo demás, "
            "así que conviene que sea un esfuerzo real."
        )
        detail.setWordWrap(True)
        detail.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12px; "
            f"background: transparent; border: none;"
        )
        col.addWidget(detail)

        row.addLayout(col, stretch=1)
        card.body.addLayout(row)
        return card

    def _build_plot_card(self) -> Card:
        card = Card()

        head = QHBoxLayout()
        head.setSpacing(10)

        head_title = QLabel("Señal en vivo")
        head_title.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 700; "
            f"background: transparent; border: none;"
        )
        head.addWidget(head_title)
        head.addStretch(1)

        head.addWidget(Pill("Sensor A", ACCENT_TEAL))
        head.addWidget(Pill("Sensor B", ACCENT_BLUE))

        self.recording_pill = Pill("En espera", TEXT_MUTED)
        head.addWidget(self.recording_pill)
        card.body.addLayout(head)

        self.plot_widget = pg.PlotWidget(background=BG_ELEVATED)
        self.plot_widget.setYRange(0, 500)
        self.plot_widget.hideAxis("bottom")
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.setMenuEnabled(False)
        self.curve_a = self.plot_widget.plot(pen=pg.mkPen(ACCENT_TEAL, width=1.8), name="A")
        self.curve_b = self.plot_widget.plot(pen=pg.mkPen(ACCENT_BLUE, width=1.8), name="B")
        card.body.addWidget(self.plot_widget)
        return card

    def _blink(self) -> None:
        self._blink_on = not self._blink_on
        self.recording_pill.set_color(ACCENT_RED if self._blink_on else TEXT_MUTED)

    # ── Captura ──────────────────────────────────────────────────────

    def _on_start_clicked(self) -> None:
        self._recording = True
        self._peak_a = 0.0
        self._peak_b = 0.0
        self._rms_history_a.clear()
        self._rms_history_b.clear()
        self._saturation_a = 0.0
        self._saturation_b = 0.0
        self._buf_a[:] = 0
        self._buf_b[:] = 0
        self._buf_pos = 0
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._set_capture_ready(False)

        self.recording_pill.setText("Grabando")
        self.recording_pill.set_color(ACCENT_RED)
        self._blink_on = True
        self._blink_timer.start()

    def _on_stop_clicked(self) -> None:
        self._recording = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._blink_timer.stop()
        self.recording_pill.setText("Detenido")
        self.recording_pill.set_color(TEXT_MUTED)

        if not self._rms_history_a or not self._rms_history_b:
            QMessageBox.warning(self, "Sin datos", "No se registró señal suficiente.")
            return

        # Un electrodo despegado produce un MVC alto y de apariencia normal.
        # Guardarlo corrompería en silencio todas las evaluaciones que se
        # normalicen después contra esa referencia.
        despegados = [
            label
            for label, sat in (("A", self._saturation_a), ("B", self._saturation_b))
            if sat >= SATURATION_LIMIT
        ]
        if despegados:
            self.recording_pill.setText("Captura inválida")
            self.recording_pill.set_color(ACCENT_AMBER)
            QMessageBox.critical(
                self, "Señal inválida",
                f"El sensor {' y '.join(despegados)} perdió contacto con la piel "
                "durante la captura, así que la señal registrada es ruido y no "
                "actividad muscular.\n\n"
                "Vuelve a colocar el electrodo y repite la calibración.",
            )
            return

        self.recording_pill.setText("Captura lista")
        self.recording_pill.set_color(ACCENT_TEAL)

        self._peak_a = float(np.mean(sorted(self._rms_history_a)[-10:]))  # promedio del pico sostenido
        self._peak_b = float(np.mean(sorted(self._rms_history_b)[-10:]))
        avg = (self._peak_a + self._peak_b) / 2.0

        self.peak_a_card.set_value(f"{self._peak_a:.0f} µV")
        self.peak_b_card.set_value(f"{self._peak_b:.0f} µV")
        self.avg_card.set_value(f"{avg:.0f} µV")
        self._set_capture_ready(True)

    def _on_samples_received(self, block) -> None:
        if block.sensor_index == 0:
            self._append(self._buf_a, block.filtered)
            if self._recording:
                self._rms_history_a.extend(block.rms.tolist())
                self._saturation_a = max(self._saturation_a, block.saturation)
        elif block.sensor_index == 1:
            self._append(self._buf_b, block.filtered)
            if self._recording:
                self._rms_history_b.extend(block.rms.tolist())
                self._saturation_b = max(self._saturation_b, block.saturation)
        else:
            return

        # Redibujar (barato: son arrays pequeños)
        x = np.linspace(0, _WAVE_WINDOW_SEC, len(self._buf_a))
        self.curve_a.setData(x, np.abs(self._buf_a))
        self.curve_b.setData(x, np.abs(self._buf_b))

    def _append(self, buf: np.ndarray, samples: np.ndarray) -> None:
        n = len(samples)
        end = self._buf_pos + n
        if end <= len(buf):
            buf[self._buf_pos:end] = samples
        else:
            first = len(buf) - self._buf_pos
            buf[self._buf_pos:] = samples[:first]
            buf[: end - len(buf)] = samples[first:]
        self._buf_pos = end % len(buf)

    # ── Guardado ─────────────────────────────────────────────────────

    def _set_capture_ready(self, ready: bool) -> None:
        self._capture_ready = ready
        self.continue_state_changed.emit()

    def can_continue(self) -> bool:
        return self._capture_ready

    def blocked_reason(self) -> str:
        return (
            "Primero registra la contracción máxima: presiona Iniciar captura, "
            "pide el esfuerzo y luego Detener."
        )

    def on_continue(self) -> bool:
        if not (self.state.active_client and self.state.active_muscle):
            return False
        avg = (self._peak_a + self._peak_b) / 2.0
        calib = self.state.calibration_repo.save(
            client_id=self.state.active_client.id,
            muscle_id=self.state.active_muscle.id,
            mvc_value_uv=avg,
            mvc_channel_a_uv=self._peak_a,
            mvc_channel_b_uv=self._peak_b,
        )
        self.state.set_active_mvc(calib)

        if self.state.active_session_id is not None:
            self.state.evaluation_repo.link_calibration(self.state.active_session_id, calib.id)

        return True