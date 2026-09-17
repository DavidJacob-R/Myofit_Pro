"""
Paso 5 del wizard — Batería de ejercicios en vivo.

Antes este paso grababa UNA serie y cerraba la sesión. Ahora graba
varias, cada una etiquetada con el ejercicio que se hizo, todas contra
la MISMA calibración MVC del Paso 4.

POR QUÉ IMPORTA QUE SEA LA MISMA CALIBRACIÓN
============================================

El objetivo del producto es comparar a la persona consigo misma: probar
todos los ejercicios posibles de un músculo y ver cuáles la activan
más. Esa comparación solo es válida si todas las mediciones comparten
la misma referencia.

Cada vez que se quitan y se vuelven a poner los electrodos cambia la
ganancia de todo lo que se mida, así que dos series calibradas por
separado no son comparables entre sí aunque salgan del mismo cliente.
Con una sola calibración para toda la batería, ese factor está presente
por igual en todas las series y se cancela al compararlas.

QUÉ SE REGISTRA Y POR QUÉ
=========================

Cada serie guarda su `exercise_id`. Antes se guardaba None, así que la
base sabía cuánto se activó pero no de qué ejercicio: inservible para
ordenar ejercicios, que es justo lo que hace falta.

REPETIBILIDAD
=============

Medir el mismo ejercicio varias veces seguidas sirve para dos cosas: da
un promedio más confiable, y permite calcular el coeficiente de
variación de la medición. Ese número es el que decide cuánta diferencia
entre dos ejercicios se puede tomar en serio, así que la pantalla lo
calcula en cuanto hay dos o más mediciones del mismo ejercicio.
"""

from __future__ import annotations

import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import BodyLabel, ComboBox, PrimaryPushButton, ProgressBar, PushButton

from myofit_pro.gui.app_state import AppState
from myofit_pro.gui.theme import (
    ACCENT_AMBER,
    ACCENT_BLUE,
    ACCENT_LIME,
    ACCENT_RED,
    ACCENT_TEAL,
    BG_ELEVATED,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    Card,
    IconBadge,
    ListRow,
    Pill,
    clear_layout,
)
from myofit_pro.gui.wizard_step import WizardStep

_WAVE_WINDOW_SEC = 8.0

# A partir de cuántas mediciones del mismo ejercicio tiene sentido
# calcular su coeficiente de variación. Con dos ya sale un número, pero
# es muy inestable; con tres empieza a significar algo.
_MIN_PARA_CV = 2


def _plural_mediciones(n: int) -> str:
    """El plural de "medición" pierde el acento: mediciones, no mediciónes."""
    return f"{n} medición" if n == 1 else f"{n} mediciones"


class _SeriesRecord:
    """Una serie ya grabada y guardada."""

    def __init__(self, exercise_id: int | None, exercise_name: str,
                 activation_pct: float, reps: int, attempt: int):
        self.exercise_id = exercise_id
        self.exercise_name = exercise_name
        self.activation_pct = activation_pct
        self.reps = reps
        self.attempt = attempt


class EvaluationStep5View(WizardStep):
    """Batería de ejercicios en vivo, todos contra la misma calibración."""

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
        self._series_start_time = 0.0

        self._series: list[_SeriesRecord] = []
        self._exercises = self._load_exercises()

        n = int(_WAVE_WINDOW_SEC * self.sensors.sample_rate_hz)
        self._buf_a = np.zeros(n)
        self._buf_b = np.zeros(n)
        # Un índice por canal. Antes era uno solo compartido, así que el
        # bloque del Sensor A lo avanzaba y el del Sensor B volvía a
        # avanzarlo: las dos curvas se escribían en posiciones distintas
        # del buffer y quedaban desfasadas entre sí en pantalla.
        self._buf_pos = {0: 0, 1: 0}

        self._build_ui()
        self.sensors.samples_received.connect(self._on_samples_received)
        self.sensors.contraction_detected.connect(self._on_contraction_detected)

    def _load_exercises(self) -> list:
        muscle = self.state.active_muscle
        if muscle is None:
            return []
        return self.state.exercise_repo.list_for_muscle(muscle.id)

    # ── Construcción ─────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        columns = QHBoxLayout()
        columns.setSpacing(14)
        columns.addLayout(self._build_capture_column(), stretch=3)
        columns.addWidget(self._build_series_card(), stretch=2)
        layout.addLayout(columns)

    def _build_capture_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(14)

        column.addWidget(self._build_exercise_card())

        plot_card = Card()
        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel("Señal en vivo")
        title.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 700; "
            f"background: transparent; border: none;"
        )
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(Pill("Sensor A", ACCENT_TEAL))
        head.addWidget(Pill("Sensor B", ACCENT_BLUE))
        self.recording_pill = Pill("En espera", TEXT_MUTED)
        head.addWidget(self.recording_pill)
        plot_card.body.addLayout(head)

        self.plot_widget = pg.PlotWidget(background=BG_ELEVATED)
        self.plot_widget.setYRange(-600, 600)
        self.plot_widget.hideAxis("bottom")
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.setMenuEnabled(False)
        self.curve_a = self.plot_widget.plot(pen=pg.mkPen(ACCENT_TEAL, width=1.6))
        self.curve_b = self.plot_widget.plot(pen=pg.mkPen(ACCENT_BLUE, width=1.6))
        plot_card.body.addWidget(self.plot_widget)
        column.addWidget(plot_card, stretch=1)

        activation_row = QHBoxLayout()
        activation_row.setSpacing(14)
        self.card_a, self.activation_bar_a, self.activation_label_a, self.reps_label_a = (
            self._build_sensor_card("A", ACCENT_TEAL)
        )
        self.card_b, self.activation_bar_b, self.activation_label_b, self.reps_label_b = (
            self._build_sensor_card("B", ACCENT_BLUE)
        )
        activation_row.addWidget(self.card_a)
        activation_row.addWidget(self.card_b)
        column.addLayout(activation_row)

        return column

    def _build_exercise_card(self) -> Card:
        card = Card()

        row = QHBoxLayout()
        row.setSpacing(12)

        col = QVBoxLayout()
        col.setSpacing(5)

        label = QLabel("EJERCICIO QUE SE VA A MEDIR")
        label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; font-weight: 700; "
            f"letter-spacing: 0.3px; background: transparent; border: none;"
        )
        col.addWidget(label)

        self.exercise_combo = ComboBox(card)
        if self._exercises:
            self.exercise_combo.addItems([e.name for e in self._exercises])
        else:
            # Sin catálogo no se puede etiquetar la serie, y una serie
            # sin ejercicio no sirve para ordenar nada después.
            self.exercise_combo.addItem("Sin ejercicios en el catálogo")
            self.exercise_combo.setEnabled(False)
        col.addWidget(self.exercise_combo)

        row.addLayout(col, stretch=1)

        buttons = QVBoxLayout()
        buttons.setSpacing(6)
        self.start_btn = PrimaryPushButton("Iniciar serie")
        self.start_btn.setIcon(FIF.PLAY_SOLID)
        self.start_btn.setEnabled(bool(self._exercises))
        self.start_btn.clicked.connect(self._on_start_clicked)
        buttons.addWidget(self.start_btn)

        self.stop_btn = PushButton("Detener y guardar")
        self.stop_btn.setIcon(FIF.PAUSE_BOLD)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        buttons.addWidget(self.stop_btn)

        row.addLayout(buttons)
        card.body.addLayout(row)

        self.hint_label = QLabel(
            "Puedes medir el mismo ejercicio varias veces: el promedio queda "
            "más confiable y la app calcula qué tan repetible es tu medición."
        )
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 11px; background: transparent; border: none;"
        )
        card.body.addWidget(self.hint_label)
        return card

    @staticmethod
    def _build_sensor_card(label: str, accent: str):
        card = Card()
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(IconBadge(label, accent, size=32))
        title = QLabel(f"Sensor {label}")
        title.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 700; "
            f"background: transparent; border: none;"
        )
        head.addWidget(title)
        head.addStretch(1)
        card.body.addLayout(head)

        bar = ProgressBar(card)
        bar.setRange(0, 150)   # permite ver sobre 100% si excede el MVC
        card.body.addWidget(bar)

        activation = BodyLabel("0% del MVC")
        card.body.addWidget(activation)
        reps = BodyLabel("Repeticiones: 0")
        card.body.addWidget(reps)
        return card, bar, activation, reps

    def _build_series_card(self) -> Card:
        card = Card()
        card.add_title("Series grabadas", "Ordenadas por activación, de mayor a menor")

        scroll = QScrollArea(card)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        host = QWidget()
        host.setStyleSheet("background: transparent;")
        self.series_list = QVBoxLayout(host)
        self.series_list.setSpacing(8)
        self.series_list.setContentsMargins(0, 0, 0, 0)
        self.series_list.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(host)
        card.body.addWidget(scroll, stretch=1)

        self.empty_label = QLabel(
            "Todavía no hay series.\nElige un ejercicio y presiona Iniciar serie."
        )
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 12px; background: transparent; border: none;"
        )
        card.body.addWidget(self.empty_label)

        self.repeatability_label = QLabel("")
        self.repeatability_label.setWordWrap(True)
        self.repeatability_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; "
            f"background: transparent; border: none;"
        )
        card.body.addWidget(self.repeatability_label)
        return card

    # ── Control de la captura ────────────────────────────────────────

    def _current_exercise(self):
        index = self.exercise_combo.currentIndex()
        if 0 <= index < len(self._exercises):
            return self._exercises[index]
        return None

    def _on_start_clicked(self) -> None:
        self._running = True
        self._reps_a = 0
        self._reps_b = 0
        self._activation_history_a.clear()
        self._activation_history_b.clear()
        self._recorded_a = []
        self._series_start_time = time.monotonic()
        self.sensors.reset_counters()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.exercise_combo.setEnabled(False)
        self.recording_pill.setText("Grabando")
        self.recording_pill.set_color(ACCENT_RED)

    def _on_stop_clicked(self) -> None:
        self._running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.exercise_combo.setEnabled(True)
        self.recording_pill.setText("En espera")
        self.recording_pill.set_color(TEXT_MUTED)

        if not self._activation_history_a and not self._activation_history_b:
            self.hint_label.setText(
                "No se registró señal en esa serie. Revisa que los sensores "
                "sigan transmitiendo antes de volver a intentar."
            )
            return

        self._save_series()

    def _save_series(self) -> None:
        exercise = self._current_exercise()
        hist_a = self._activation_history_a or [0.0]
        hist_b = self._activation_history_b or [0.0]
        avg_pct = (float(np.mean(hist_a)) + float(np.mean(hist_b))) / 2.0
        peak_pct = max(float(np.max(hist_a)), float(np.max(hist_b)))
        reps = max(self._reps_a, self._reps_b)
        duration = time.monotonic() - self._series_start_time

        if self.state.active_session_id is not None:
            burst_id = self._save_burst()
            result = self.state.evaluation_repo.add_exercise_result(
                session_id=self.state.active_session_id,
                # Sin esto la base sabría cuánto se activó pero no de qué
                # ejercicio, y no se podría ordenar nada después.
                exercise_id=exercise.id if exercise else None,
                series_count=reps,
                avg_activation_pct=avg_pct,
                peak_activation_pct=peak_pct,
            )
            self.state.evaluation_repo.add_reading(
                exercise_result_id=result.id,
                series_number=len(self._series) + 1,
                channel_a_mv=self.mvc_a / 1000.0,
                channel_b_mv=self.mvc_b / 1000.0,
                activation_a_pct=float(np.mean(hist_a)),
                activation_b_pct=float(np.mean(hist_b)),
                duration_sec=duration,
                burst_id=burst_id,
            )

        name = exercise.name if exercise else "Sin ejercicio"
        attempt = sum(1 for s in self._series if s.exercise_name == name) + 1
        self._series.append(_SeriesRecord(
            exercise_id=exercise.id if exercise else None,
            exercise_name=name,
            activation_pct=avg_pct,
            reps=reps,
            attempt=attempt,
        ))

        self._refresh_series_list()
        self.continue_state_changed.emit()

    # ── Lista de series y repetibilidad ──────────────────────────────

    def _refresh_series_list(self) -> None:
        clear_layout(self.series_list)
        self.empty_label.setVisible(not self._series)

        # Promedio por ejercicio, que es lo que de verdad se compara.
        # Una sola serie puede salir alta por casualidad.
        by_exercise: dict[str, list[float]] = {}
        for record in self._series:
            by_exercise.setdefault(record.exercise_name, []).append(record.activation_pct)

        ranking = sorted(
            by_exercise.items(), key=lambda item: float(np.mean(item[1])), reverse=True
        )

        for position, (name, values) in enumerate(ranking, start=1):
            mean = float(np.mean(values))
            accent = ACCENT_LIME if position <= 3 else TEXT_SECONDARY
            subtitle = _plural_mediciones(len(values))
            if len(values) >= _MIN_PARA_CV:
                subtitle += f"   ·   varía {self._cv(values) * 100:.0f}%"

            self.series_list.addWidget(
                ListRow(
                    title=name,
                    subtitle=subtitle,
                    value=f"{mean:.0f}%",
                    value_caption="activación",
                    value_color=accent,
                    leading=IconBadge(str(position), accent, size=34),
                    clickable=False,
                )
            )

        self._refresh_repeatability(by_exercise)

    def _refresh_repeatability(self, by_exercise: dict[str, list[float]]) -> None:
        """
        Muestra la repetibilidad medida en esta sesión.

        Es el número que decide cuánta diferencia entre dos ejercicios se
        puede tomar en serio. Sin él, una diferencia de 4 puntos entre el
        primero y el segundo no se sabe si es real o ruido.
        """
        repetidos = {k: v for k, v in by_exercise.items() if len(v) >= _MIN_PARA_CV}
        if not repetidos:
            self.repeatability_label.setText(
                "Mide algún ejercicio dos o más veces para saber qué tan "
                "repetible es tu medición."
            )
            return

        cvs = [self._cv(v) for v in repetidos.values()]
        cv_medio = float(np.mean(cvs))
        # Cambio mínimo detectable al 95%, con una medición por ejercicio.
        # Misma fórmula que ml/within_subject.minimal_detectable_change.
        medias = [float(np.mean(v)) for v in repetidos.values()]
        umbral = 1.96 * np.sqrt(2) * float(np.mean(medias)) * cv_medio

        self.repeatability_label.setText(
            f"Tu medición varía un {cv_medio * 100:.0f}% al repetir el mismo "
            f"ejercicio. Con eso, dos ejercicios tienen que diferir en más de "
            f"{umbral:.0f} puntos para que la diferencia sea real y no ruido."
        )

    @staticmethod
    def _cv(values: list[float]) -> float:
        """
        Coeficiente de variación: desviación estándar entre la media.

        Se usa la desviación muestral (ddof=1) y no la poblacional. Con
        tres o cuatro mediciones la diferencia importa: dividir entre n
        en vez de entre n-1 subestima la dispersión, que es justo el
        error que haría ver la medición más confiable de lo que es.

        La longitud se revisa antes de promediar, porque `np.mean([])`
        devuelve NaN y además avisa por consola.
        """
        if len(values) < 2:
            return 0.0
        mean = float(np.mean(values))
        if mean <= 0:
            return 0.0
        return float(np.std(values, ddof=1)) / mean

    # ── Contrato del asistente ───────────────────────────────────────

    def can_continue(self) -> bool:
        return bool(self._series)

    def blocked_reason(self) -> str:
        return "Graba al menos una serie antes de terminar la evaluación."

    def on_continue(self) -> bool:
        if self._running:
            self._on_stop_clicked()

        if self.state.active_session_id is not None and self._series:
            overall = float(np.mean([s.activation_pct for s in self._series]))
            self.state.evaluation_repo.finish_session(
                session_id=self.state.active_session_id,
                overall_score=overall,
            )

        self.evaluation_finished.emit()
        return True

    # ── Señal ────────────────────────────────────────────────────────

    def _save_burst(self) -> str | None:
        """
        Guarda la señal completa del Sensor A en DuckDB. Devuelve el
        burst_id para enlazarlo desde EmgReading, o None si no se
        capturó nada.
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
            # Si DuckDB falla, la serie igual se guarda en SQLite; solo
            # se pierde el sparkline del historial.
            return None

    def _on_samples_received(self, block) -> None:
        if block.sensor_index == 0:
            self._append(self._buf_a, block.filtered, 0)
            self._update_activation(0, block.envelope[-1] if len(block.envelope) else 0.0)
            if self._running:
                self._recorded_a.append(block.filtered.copy())
        elif block.sensor_index == 1:
            self._append(self._buf_b, block.filtered, 1)
            self._update_activation(1, block.envelope[-1] if len(block.envelope) else 0.0)
        else:
            return

        x = np.linspace(0, _WAVE_WINDOW_SEC, len(self._buf_a))
        self.curve_a.setData(x, self._buf_a)
        self.curve_b.setData(x, self._buf_b)

    def _update_activation(self, sensor_index: int, envelope_uv: float) -> None:
        mvc = self.mvc_a if sensor_index == 0 else self.mvc_b
        pct = 0.0 if mvc <= 0 else (envelope_uv / mvc) * 100.0
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
            self.reps_label_a.setText(f"Repeticiones: {total_count}")
        elif sensor_index == 1:
            self._reps_b = total_count
            self.reps_label_b.setText(f"Repeticiones: {total_count}")

    def _append(self, buf: np.ndarray, samples: np.ndarray, sensor_index: int) -> None:
        """Escribe el bloque en el buffer circular de ESE canal."""
        start = self._buf_pos[sensor_index]
        n = len(samples)
        end = start + n
        if end <= len(buf):
            buf[start:end] = samples
        else:
            first = len(buf) - start
            buf[start:] = samples[:first]
            buf[: end - len(buf)] = samples[first:]
        self._buf_pos[sensor_index] = end % len(buf)
