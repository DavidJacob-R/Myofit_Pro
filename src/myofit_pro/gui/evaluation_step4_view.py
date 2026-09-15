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
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, PrimaryPushButton

from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.theme import ACCENT_BLUE, ACCENT_TEAL, ACCENT_VIOLET, Card, StatCard

_WAVE_WINDOW_SEC = 6.0


class EvaluationStep4View(QWidget):
    """Calibración MVC — evento `calibration_saved` cuando termina."""

    calibration_saved = Signal()

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

        self._build_ui()
        self.sensors.samples_received.connect(self._on_samples_received)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        layout.addWidget(
            BodyLabel(
                "Pide al cliente una contracción máxima sostenida de 3-5 segundos. "
                "Presiona Iniciar justo antes y Detener cuando termine."
            )
        )

        plot_card = Card()
        self.plot_widget = pg.PlotWidget(background="#1E1B2E")
        self.plot_widget.setYRange(0, 500)
        self.plot_widget.hideAxis("bottom")
        self.curve_a = self.plot_widget.plot(pen=pg.mkPen(ACCENT_TEAL, width=1.8), name="A")
        self.curve_b = self.plot_widget.plot(pen=pg.mkPen(ACCENT_BLUE, width=1.8), name="B")
        plot_card.body.addWidget(self.plot_widget)
        layout.addWidget(plot_card, stretch=1)

        numbers = QHBoxLayout()
        numbers.setSpacing(12)
        self.peak_a_card = StatCard("A", ACCENT_TEAL, "Pico Sensor A", "0 µV")
        self.peak_b_card = StatCard("B", ACCENT_BLUE, "Pico Sensor B", "0 µV")
        self.avg_card = StatCard("⚡", ACCENT_VIOLET, "Promedio (MVC)", "0 µV")
        numbers.addWidget(self.peak_a_card)
        numbers.addWidget(self.peak_b_card)
        numbers.addWidget(self.avg_card)
        layout.addLayout(numbers)

        btn_row = QHBoxLayout()
        self.start_btn = PrimaryPushButton("●  Iniciar")
        self.start_btn.clicked.connect(self._on_start_clicked)
        self.stop_btn = PrimaryPushButton("■  Detener")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        layout.addLayout(btn_row)

        self.save_btn = PrimaryPushButton("Guardar y continuar →")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._on_save_clicked)
        layout.addWidget(self.save_btn)

        # Buffers de graficado (solo visual, no se usan para el cálculo del MVC)
        n = int(_WAVE_WINDOW_SEC * self.sensors.sample_rate_hz)
        self._buf_a = np.zeros(n)
        self._buf_b = np.zeros(n)
        self._buf_pos = 0

    # ── Captura ──────────────────────────────────────────────────────

    def _on_start_clicked(self) -> None:
        self._recording = True
        self._peak_a = 0.0
        self._peak_b = 0.0
        self._rms_history_a.clear()
        self._rms_history_b.clear()
        self._buf_a[:] = 0
        self._buf_b[:] = 0
        self._buf_pos = 0
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.save_btn.setEnabled(False)

    def _on_stop_clicked(self) -> None:
        self._recording = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        if not self._rms_history_a or not self._rms_history_b:
            QMessageBox.warning(self, "Sin datos", "No se registró señal suficiente.")
            return

        self._peak_a = float(np.mean(sorted(self._rms_history_a)[-10:]))  # promedio del pico sostenido
        self._peak_b = float(np.mean(sorted(self._rms_history_b)[-10:]))
        avg = (self._peak_a + self._peak_b) / 2.0

        self.peak_a_card.set_value(f"{self._peak_a:.0f} µV")
        self.peak_b_card.set_value(f"{self._peak_b:.0f} µV")
        self.avg_card.set_value(f"{avg:.0f} µV")
        self.save_btn.setEnabled(True)

    def _on_samples_received(self, block) -> None:
        if block.sensor_index == 0:
            self._append(self._buf_a, block.filtered)
            if self._recording:
                self._rms_history_a.extend(block.rms.tolist())
        elif block.sensor_index == 1:
            self._append(self._buf_b, block.filtered)
            if self._recording:
                self._rms_history_b.extend(block.rms.tolist())
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

    def _on_save_clicked(self) -> None:
        if not (self.state.active_client and self.state.active_muscle):
            return
        avg = (self._peak_a + self._peak_b) / 2.0
        calib = self.state.calibration_repo.save(
            client_id=self.state.active_client.id,
            muscle_id=self.state.active_muscle.id,
            mvc_value_uv=avg,
            mvc_channel_a_uv=self._peak_a,
            mvc_channel_b_uv=self._peak_b,
        )
        self.state.active_mvc = calib

        if self.state.active_session_id is not None:
            self.state.evaluation_repo.link_calibration(self.state.active_session_id, calib.id)

        self.calibration_saved.emit()