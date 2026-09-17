"""
Paso 5 del wizard — Evaluación en vivo.

Decisión de diseño ya acordada: ambos sensores se muestran superpuestos
en la misma gráfica (A verde, B azul), y la activación % de cada canal
se calcula contra el MVC guardado en el Paso 4:

    activacion_pct = envelope_actual / mvc_channel_uv * 100

Las repeticiones se cuentan usando el detector de contracciones que ya
vive en MyoBlueChannel (histéresis por umbral), vía la señal
`contraction_detected` del servicio.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    BodyLabel,
    PrimaryPushButton,
    ProgressBar,
    StrongBodyLabel,
)

from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.wizard_step import WizardStep
from myofit_pro.gui.theme import ACCENT_BLUE, ACCENT_TEAL, Card

_WAVE_WINDOW_SEC = 8.0


class EvaluationStep5View(WizardStep):
    """Evaluación en vivo — emite `evaluation_finished` al terminar la serie."""

    evaluation_finished = Signal()
    CONTINUE_LABEL = "Terminar y ver reporte  →"

    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.sensors = state.sensors

        mvc = state.active_mvc
        self.mvc_a = mvc.mvc_channel_a_uv if mvc else 100.0
        self.mvc_b = mvc.mvc_channel_b_uv if mvc else 100.0

        self._running = False
        self._reps_a = 0
        self._reps_b = 0
        self._activation_history_a: list[float] = []
        self._activation_history_b: list[float] = []
        self._recorded_a: list[np.ndarray] = []
        self._recorded_b: list[np.ndarray] = []
        self._session_start_time = 0.0

        n = int(_WAVE_WINDOW_SEC * self.sensors.sample_rate_hz)
        self._buf_a = np.zeros(n)
        self._buf_b = np.zeros(n)
        self._buf_pos = 0

        self._build_ui()
        self.sensors.samples_received.connect(self._on_samples_received)
        self.sensors.contraction_detected.connect(self._on_contraction_detected)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        client_name = self.state.active_client.full_name if self.state.active_client else "—"
        muscle_name = self.state.active_muscle.name if self.state.active_muscle else "—"
        layout.addWidget(BodyLabel(f"{client_name}  ·  {muscle_name}"))

        plot_card = Card()
        self.plot_widget = pg.PlotWidget(background="#1E1B2E")
        self.plot_widget.setYRange(-600, 600)
        self.plot_widget.hideAxis("bottom")
        self.curve_a = self.plot_widget.plot(pen=pg.mkPen(ACCENT_TEAL, width=1.6), name="Sensor A")
        self.curve_b = self.plot_widget.plot(pen=pg.mkPen(ACCENT_BLUE, width=1.6), name="Sensor B")
        plot_card.body.addWidget(self.plot_widget)
        layout.addWidget(plot_card, stretch=1)

        activation_row = QHBoxLayout()
        activation_row.setSpacing(14)

        card_a = Card()
        card_a.body.addWidget(StrongBodyLabel("🟢  Sensor A"))
        self.activation_bar_a = ProgressBar(card_a)
        self.activation_bar_a.setRange(0, 150)  # permite ver sobre-100% si excede el MVC
        card_a.body.addWidget(self.activation_bar_a)
        self.activation_label_a = BodyLabel("0% del MVC")
        card_a.body.addWidget(self.activation_label_a)
        self.reps_label_a = BodyLabel("Repeticiones: 0")
        card_a.body.addWidget(self.reps_label_a)
        activation_row.addWidget(card_a)

        card_b = Card()
        card_b.body.addWidget(StrongBodyLabel("🔵  Sensor B"))
        self.activation_bar_b = ProgressBar(card_b)
        self.activation_bar_b.setRange(0, 150)
        card_b.body.addWidget(self.activation_bar_b)
        self.activation_label_b = BodyLabel("0% del MVC")
        card_b.body.addWidget(self.activation_label_b)
        self.reps_label_b = BodyLabel("Repeticiones: 0")
        card_b.body.addWidget(self.reps_label_b)
        activation_row.addWidget(card_b)

        layout.addLayout(activation_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.start_btn = PrimaryPushButton("Iniciar serie")
        self.start_btn.setIcon(FIF.PLAY_SOLID)
        self.start_btn.clicked.connect(self._on_start_clicked)
        btn_row.addWidget(self.start_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

    # ── Control ──────────────────────────────────────────────────────

    def _on_start_clicked(self) -> None:
        import time as _time
        self._running = True
        self._reps_a = 0
        self._reps_b = 0
        self._activation_history_a.clear()
        self._activation_history_b.clear()
        # Acumuladores de la señal completa de la serie, para guardarla
        # en DuckDB al terminar (alimenta el sparkline del historial).
        self._recorded_a: list[np.ndarray] = []
        self._recorded_b: list[np.ndarray] = []
        self._session_start_time = _time.monotonic()
        self.sensors.reset_counters()
        self.start_btn.setEnabled(False)
        self.continue_state_changed.emit()

    def can_continue(self) -> bool:
        return self._running or bool(self._activation_history_a)

    def blocked_reason(self) -> str:
        return "Presiona Iniciar serie y graba al menos una repetición."

    def on_continue(self) -> bool:
        self._finish()
        return True

    def _finish(self) -> None:
        import time as _time
        self._running = False
        duration_sec = _time.monotonic() - self._session_start_time

        hist_a = self._activation_history_a or [0.0]
        hist_b = self._activation_history_b or [0.0]
        avg_pct = (float(np.mean(hist_a)) + float(np.mean(hist_b))) / 2.0
        peak_pct = max(float(np.max(hist_a)), float(np.max(hist_b)))

        if self.state.active_session_id is not None:
            burst_id = self._save_burst()

            result = self.state.evaluation_repo.add_exercise_result(
                session_id=self.state.active_session_id,
                exercise_id=None,
                series_count=max(self._reps_a, self._reps_b),
                avg_activation_pct=avg_pct,
                peak_activation_pct=peak_pct,
            )
            self.state.evaluation_repo.add_reading(
                exercise_result_id=result.id,
                series_number=1,
                channel_a_mv=self.mvc_a / 1000.0,
                channel_b_mv=self.mvc_b / 1000.0,
                activation_a_pct=float(np.mean(hist_a)),
                activation_b_pct=float(np.mean(hist_b)),
                duration_sec=duration_sec,
                burst_id=burst_id,
            )
            self.state.evaluation_repo.finish_session(
                session_id=self.state.active_session_id,
                overall_score=avg_pct,
            )

        self.evaluation_finished.emit()

    def _save_burst(self) -> str | None:
        """
        Guarda la señal completa del Sensor A en DuckDB. Devuelve el
        burst_id para enlazarlo desde EmgReading, o None si no se
        capturó nada (por ejemplo si se terminó la serie sin señal).
        """
        if not self._recorded_a:
            return None
        if not (self.state.active_client and self.state.active_muscle):
            return None

        filtered = np.concatenate(self._recorded_a)
        if len(filtered) < 2:
            return None

        fs = self.sensors.sample_rate_hz
        times = np.arange(len(filtered)) / fs
        envelope = np.abs(filtered)

        try:
            return self.state.burst_store.save_burst(
                client_id=self.state.active_client.id,
                session_id=self.state.active_session_id,
                muscle_id=self.state.active_muscle.id,
                sensor_index=0,
                sample_rate_hz=fs,
                times=times,
                micro_volts=filtered,
                filtered=filtered,
                envelope=envelope,
                rms=envelope,
            )
        except Exception:
            # Si DuckDB falla, la evaluación igual se guarda en SQLite;
            # solo se pierde el sparkline del historial.
            return None

    # ── Datos en vivo ────────────────────────────────────────────────

    def _on_samples_received(self, block) -> None:
        if block.sensor_index == 0:
            self._append(self._buf_a, block.filtered)
            self._update_activation(0, block.envelope[-1] if len(block.envelope) else 0.0)
            if self._running:
                self._recorded_a.append(block.filtered.copy())
        elif block.sensor_index == 1:
            self._append(self._buf_b, block.filtered)
            self._update_activation(1, block.envelope[-1] if len(block.envelope) else 0.0)
        else:
            return

        x = np.linspace(0, _WAVE_WINDOW_SEC, len(self._buf_a))
        self.curve_a.setData(x, self._buf_a)
        self.curve_b.setData(x, self._buf_b)

    def _update_activation(self, sensor_index: int, envelope_uv: float) -> None:
        mvc = self.mvc_a if sensor_index == 0 else self.mvc_b
        pct = 0 if mvc <= 0 else (envelope_uv / mvc) * 100.0
        pct_clamped = int(max(0, min(150, pct)))

        if sensor_index == 0:
            self.activation_bar_a.setValue(pct_clamped)
            self.activation_label_a.setText(f"{pct:.0f}% del MVC")
            if self._running:
                self._activation_history_a.append(pct)
        else:
            self.activation_bar_b.setValue(pct_clamped)
            self.activation_label_b.setText(f"{pct:.0f}% del MVC")
            if self._running:
                self._activation_history_b.append(pct)

    def _on_contraction_detected(self, sensor_index: int, total_count: int, _time_sec: float) -> None:
        if not self._running:
            return
        if sensor_index == 0:
            self._reps_a = total_count
            self.reps_label_a.setText(f"Repeticiones: {self._reps_a}")
        elif sensor_index == 1:
            self._reps_b = total_count
            self.reps_label_b.setText(f"Repeticiones: {self._reps_b}")

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