"""
Equivalente a Views/SensorTestWindow.xaml(.cs) de la versión C#.

Ventana modal de diagnóstico: NO guarda nada, solo muestra ondas en
vivo (PyQtGraph, igual que el MYOblue_GUI.py original de elemyo),
barras de nivel de activación y un semáforo de calidad de señal por
sensor, para que el entrenador verifique que los sensores están bien
colocados antes de iniciar una evaluación real.
"""

from __future__ import annotations

import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, PrimaryPushButton, ProgressBar, StrongBodyLabel, TitleLabel

from myofit_pro.gui.theme import (
    ACCENT_AMBER,
    ACCENT_BLUE,
    ACCENT_RED,
    ACCENT_TEAL,
    BG_MAIN,
)
from myofit_pro.sensors import MyoBlueService

_WAVE_WINDOW_SEC = 3.0
_RENDER_INTERVAL_MS = 33  # ~30 fps


class _SensorPanel(QWidget):
    """Un panel (onda + números + semáforo + barra) para un sensor."""

    def __init__(self, label: str, color: str, sample_rate_hz: float, parent=None):
        super().__init__(parent)
        self.label = label
        self.color = color
        self.sample_rate_hz = sample_rate_hz
        self.buffer_len = int(_WAVE_WINDOW_SEC * sample_rate_hz)
        self.buffer = np.zeros(self.buffer_len)
        self.write_pos = 0
        self.samples_written = 0

        self.baseline_rms = 0.0
        self.max_rms = 0.0
        self.window_start = time.monotonic()

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        header.addWidget(StrongBodyLabel(f"Sensor {self.label}"))
        header.addStretch(1)
        self.quality_label = BodyLabel("Esperando...")
        self.quality_label.setStyleSheet(
            "background-color: #9CA3AF; color: white; border-radius: 8px; padding: 2px 10px;"
        )
        header.addWidget(self.quality_label)
        layout.addLayout(header)

        numbers = QGridLayout()
        self.peak_label = BodyLabel("0 µV")
        self.rms_label = BodyLabel("0 µV")
        self.state_label = BodyLabel("Reposo")
        numbers.addWidget(BodyLabel("PICO"), 0, 0)
        numbers.addWidget(BodyLabel("RMS"), 0, 1)
        numbers.addWidget(BodyLabel("ESTADO"), 0, 2)
        numbers.addWidget(self.peak_label, 1, 0)
        numbers.addWidget(self.rms_label, 1, 1)
        numbers.addWidget(self.state_label, 1, 2)
        layout.addLayout(numbers)

        self.plot_widget = pg.PlotWidget(background=BG_MAIN)
        self.plot_widget.setYRange(-500, 500)
        self.plot_widget.showGrid(x=False, y=False)
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.hideAxis("bottom")
        self.plot_widget.hideAxis("left")
        self.curve = self.plot_widget.plot(pen=pg.mkPen(self.color, width=1.4))
        layout.addWidget(self.plot_widget, stretch=1)

        layout.addWidget(BodyLabel("Nivel de activación"))
        self.level_bar = ProgressBar(self)
        self.level_bar.setRange(0, 100)
        layout.addWidget(self.level_bar)

    def append_samples(self, samples: np.ndarray) -> None:
        n = len(samples)
        if n == 0:
            return
        end = self.write_pos + n
        if end <= self.buffer_len:
            self.buffer[self.write_pos:end] = samples
        else:
            first_part = self.buffer_len - self.write_pos
            self.buffer[self.write_pos:] = samples[:first_part]
            self.buffer[: end - self.buffer_len] = samples[first_part:]
        self.write_pos = end % self.buffer_len
        self.samples_written += n

    def update_quality_tracking(self, rms: float) -> None:
        elapsed = time.monotonic() - self.window_start
        if elapsed < 3.0:
            self.baseline_rms = max(self.baseline_rms, rms)
        self.max_rms = max(self.max_rms, rms)

    def render(self, envelope: float, rms: float, peak_scale: float) -> None:
        # Números
        self.peak_label.setText(f"{envelope:.0f} µV")
        self.rms_label.setText(f"{rms:.0f} µV")
        if rms > 80:
            self.state_label.setText("Activado")
        elif rms > 30:
            self.state_label.setText("Suave")
        else:
            self.state_label.setText("Reposo")

        # Barra de nivel
        pct = 0 if peak_scale <= 0 else max(0, min(100, int(rms / peak_scale * 100)))
        self.level_bar.setValue(pct)

        # Semáforo de calidad
        if self.baseline_rms < 0.5 and self.max_rms < 0.5:
            color, text = "#9CA3AF", "Sin señal"
        elif self.baseline_rms > 35:
            color, text = ACCENT_RED, "Mucho ruido"
        elif self.baseline_rms > 15:
            color, text = ACCENT_AMBER, "Verifica contacto"
        else:
            color, text = ACCENT_TEAL, "Señal OK"
        self.quality_label.setText(text)
        self.quality_label.setStyleSheet(
            f"background-color: {color}; color: white; border-radius: 8px; padding: 2px 10px;"
        )

        # Onda
        if self.samples_written < 2:
            return
        total = min(self.samples_written, self.buffer_len)
        if self.samples_written >= self.buffer_len:
            ordered = np.concatenate((self.buffer[self.write_pos:], self.buffer[: self.write_pos]))
        else:
            ordered = self.buffer[:total]
        x = np.linspace(0, _WAVE_WINDOW_SEC, len(ordered))
        self.curve.setData(x, ordered)

        y_limit = max(peak_scale, 50)
        self.plot_widget.setYRange(-y_limit, y_limit)


class SensorTestWindow(QDialog):
    def __init__(self, sensors: MyoBlueService, parent: QWidget | None = None):
        super().__init__(parent)
        self.sensors = sensors
        self.setWindowTitle("Prueba de sensores EMG")
        self.resize(900, 620)

        self._peak_window = [100.0, 100.0]

        self._build_ui()

        self.sensors.samples_received.connect(self._on_samples_received)

        self._render_timer = QTimer(self)
        self._render_timer.setInterval(_RENDER_INTERVAL_MS)
        self._render_timer.timeout.connect(self._render_frame)
        self._render_timer.start()

        self.finished.connect(self._on_closed)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(TitleLabel("Prueba de funcionamiento"))
        layout.addWidget(
            BodyLabel(
                "Pide al cliente que realice contracciones del músculo. Verifica que "
                "ambos sensores reaccionen y que la calidad de señal sea aceptable."
            )
        )

        panels_row = QHBoxLayout()
        self.panel_a = _SensorPanel("A", ACCENT_TEAL, self.sensors.sample_rate_hz)
        self.panel_b = _SensorPanel("B", ACCENT_BLUE, self.sensors.sample_rate_hz)
        panels_row.addWidget(self.panel_a)
        panels_row.addWidget(self.panel_b)
        layout.addLayout(panels_row, stretch=1)

        footer = QHBoxLayout()
        footer.addWidget(
            BodyLabel(
                "💡 Pide al cliente que contraiga el músculo varias veces. Las barras "
                "deben subir con cada contracción y la calidad debe quedar en verde."
            ),
            stretch=1,
        )
        close_btn = PrimaryPushButton("Cerrar")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        layout.addLayout(footer)

    def _on_samples_received(self, block) -> None:
        panel = self.panel_a if block.sensor_index == 0 else (
            self.panel_b if block.sensor_index == 1 else None
        )
        if panel is not None:
            panel.append_samples(block.filtered)

    def _render_frame(self) -> None:
        for idx, panel in enumerate((self.panel_a, self.panel_b)):
            channel = self.sensors.channels[idx]
            env = channel.latest_envelope
            rms = channel.latest_rms

            self._peak_window[idx] = max(self._peak_window[idx] * 0.995, env * 1.2, 100.0)
            panel.update_quality_tracking(rms)
            panel.render(env, rms, self._peak_window[idx])

    def _on_closed(self) -> None:
        self._render_timer.stop()
        try:
            self.sensors.samples_received.disconnect(self._on_samples_received)
        except (TypeError, RuntimeError):
            pass