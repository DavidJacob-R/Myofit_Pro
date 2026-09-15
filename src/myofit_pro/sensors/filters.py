"""
Pipeline de procesamiento de señal (DSP) para EMG de superficie.

Auditado línea por línea contra MYOblue_GUI.py original de elemyo
(clases bandpass_filter, bandstop_filter_50Hz/60Hz, HP_filter,
MovingAverage). Coincide en:

  - Bandpass: Butterworth de 4to orden, mismo btype='bandpass'.
  - Notch: Butterworth de 4to orden 'bandstop' de 4 Hz de ancho en
    cada armónico (NO iirnotch, que es un filtro distinto y más
    angosto — este era un bug en una versión anterior de este archivo).
  - HighpassFilter (antes ausente): respaldo de 1 Hz que el original
    usa antes de rectificar cuando el usuario desactiva notch Y
    bandpass a la vez.
  - Envolvente: rectificación + 3 etapas de promedio móvil exponencial
    en cascada, alpha=0.95, factor x2 final — idéntico a MovingAverage.

Dos diferencias DELIBERADAS respecto al original (no son bugs):

  1. Filtrado streaming con estado (zi) en vez de re-filtrar todo el
     buffer visible desde cero en cada refresco. El original usa
     lfilter() sin zi sobre el array completo cada vez y por eso tiene
     que "apagar" (poner en cero) los primeros 1.5s del buffer en cada
     pasada para esconder el transitorio de arranque del filtro. Nuestra
     versión mantiene el estado del filtro entre bloques de 119 muestras,
     así que no hay transitorio que esconder ni buffer que re-procesar
     completo — es más eficiente y no requiere el parche de "borrar
     1.5s". El comportamiento en régimen permanente es equivalente.

  2. RMS por ventana deslizante con sqrt(mean(x^2)) en vez de la
     fórmula recursiva trapezoidal del original. Ambas aproximan la
     misma cantidad física (RMS en una ventana de tiempo), pero la
     recursiva puede acumular error de punto flotante en sesiones muy
     largas; recalcular sobre el buffer circular en cada paso es más
     costoso mas no acumula ese error. Ver RmsCalculator más abajo.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, lfilter, sosfilt, sosfilt_zi


class BandpassFilter:
    """Butterworth pasa-banda de 4to orden, streaming con estado (sos + zi)."""

    def __init__(self, low_hz: float, high_hz: float, fs: float, order: int = 4):
        self.low_hz = low_hz
        self.high_hz = high_hz
        self.fs = fs
        self.order = order
        self._design()

    def _design(self) -> None:
        nyq = self.fs / 2.0
        self.sos = butter(
            self.order, [self.low_hz / nyq, self.high_hz / nyq],
            btype="band", output="sos",
        )
        # Estado inicial en verdadero cero (no el "steady-state para
        # escalón" de sosfilt_zi, que dejaría memoria residual tras un
        # reset y produciría un falso transitorio al reiniciar captura).
        self._zi = np.zeros_like(sosfilt_zi(self.sos))

    def configure(self, low_hz: float, high_hz: float, fs: float) -> None:
        if (low_hz, high_hz, fs) == (self.low_hz, self.high_hz, self.fs):
            return
        self.low_hz, self.high_hz, self.fs = low_hz, high_hz, fs
        self._design()

    def process(self, x: np.ndarray) -> np.ndarray:
        y, self._zi = sosfilt(self.sos, x, zi=self._zi)
        return y

    def reset(self) -> None:
        self._zi = np.zeros_like(sosfilt_zi(self.sos))


class NotchFilter:
    """
    Filtro notch para interferencia de red eléctrica.

    IMPORTANTE: replica exactamente bandstop_filter_50Hz/60Hz del
    Python original de elemyo — Butterworth de 4to orden en modo
    'bandstop' con una banda de 4 Hz de ancho alrededor de cada
    armónico (ej. para 50Hz: 48-52, 98-102, 148-152, 198-202 Hz), NO
    un notch angosto tipo iirnotch. Usar iirnotch daría una atenuación
    mucho más angosta y no coincidiría con el comportamiento real del
    hardware/software de elemyo.
    """

    def __init__(self, base_freq: float, fs: float, harmonics: int = 4, band_width_hz: float = 4.0):
        self.base_freq = base_freq
        self.fs = fs
        self.harmonics = harmonics
        self.band_width_hz = band_width_hz
        self._design()

    def _design(self) -> None:
        self._sos_list: list[np.ndarray] = []
        self._states: list[np.ndarray] = []
        nyq = self.fs / 2.0
        half_bw = self.band_width_hz / 2.0
        for h in range(self.harmonics):
            f0 = self.base_freq + self.base_freq * h  # 50, 100, 150, 200 (o 60,120,180,240)
            low = (f0 - half_bw) / nyq
            high = (f0 + half_bw) / nyq
            if high >= 1.0 or low <= 0.0:
                continue
            sos = butter(4, [low, high], btype="bandstop", output="sos")
            self._sos_list.append(sos)
            self._states.append(np.zeros_like(sosfilt_zi(sos)))

    def configure(self, base_freq: float, fs: float) -> None:
        if (base_freq, fs) == (self.base_freq, self.fs):
            return
        self.base_freq, self.fs = base_freq, fs
        self._design()

    def process(self, x: np.ndarray) -> np.ndarray:
        y = x
        for i, sos in enumerate(self._sos_list):
            y, self._states[i] = sosfilt(sos, y, zi=self._states[i])
        return y

    def reset(self) -> None:
        for i, sos in enumerate(self._sos_list):
            self._states[i] = np.zeros_like(sosfilt_zi(sos))


class HighpassFilter:
    """
    Pasa-altas Butterworth de 4to orden — equivalente a HP_filter del
    original. Se usa como RESPALDO antes de rectificar cuando el
    usuario desactiva tanto el notch como el bandpass: sin esto, la
    rectificación se haría sobre una señal con offset de DC crudo,
    dando una envolvente sin sentido. El original la aplica con
    lowcut=1Hz fijo.
    """

    def __init__(self, low_hz: float, fs: float, order: int = 4):
        self.low_hz = low_hz
        self.fs = fs
        self.order = order
        self._design()

    def _design(self) -> None:
        nyq = self.fs / 2.0
        self.sos = butter(self.order, self.low_hz / nyq, btype="highpass", output="sos")
        self._zi = np.zeros_like(sosfilt_zi(self.sos))

    def configure(self, low_hz: float, fs: float) -> None:
        if (low_hz, fs) == (self.low_hz, self.fs):
            return
        self.low_hz, self.fs = low_hz, fs
        self._design()

    def process(self, x: np.ndarray) -> np.ndarray:
        y, self._zi = sosfilt(self.sos, x, zi=self._zi)
        return y

    def reset(self) -> None:
        self._zi = np.zeros_like(sosfilt_zi(self.sos))


class EnvelopeFilter:
    """
    Envolvente por rectificación de onda completa + 3 etapas de
    promedio móvil exponencial en cascada, igual que MovingAverage
    del Python original de elemyo:
        y[n] = (1 - alpha) * x[n] + alpha * y[n-1]   (x3, luego *2)
    """

    def __init__(self, alpha: float = 0.95):
        self.alpha = alpha
        # Coeficientes de un filtro IIR de 1 polo: y[n] = (1-a)x[n] + a*y[n-1]
        self._b = np.array([1.0 - alpha])
        self._a = np.array([1.0, -alpha])
        self._zi1 = np.zeros(1)
        self._zi2 = np.zeros(1)
        self._zi3 = np.zeros(1)

    def set_alpha(self, alpha: float) -> None:
        self.alpha = alpha
        self._b = np.array([1.0 - alpha])
        self._a = np.array([1.0, -alpha])

    def process(self, x: np.ndarray) -> np.ndarray:
        rectified = np.abs(x)
        y1, self._zi1 = lfilter(self._b, self._a, rectified, zi=self._zi1)
        y2, self._zi2 = lfilter(self._b, self._a, y1, zi=self._zi2)
        y3, self._zi3 = lfilter(self._b, self._a, y2, zi=self._zi3)
        return y3 * 2.0

    def reset(self) -> None:
        self._zi1 = np.zeros(1)
        self._zi2 = np.zeros(1)
        self._zi3 = np.zeros(1)


class RmsCalculator:
    """
    RMS deslizante sobre una ventana móvil circular. Simplificación
    (más clara y fácil de mantener) del algoritmo trapezoidal recursivo
    del Python original — el resultado numérico es equivalente para
    señales EMG en la práctica: sqrt(mean(x^2)) sobre la ventana.
    """

    def __init__(self, fs: float, window_sec: float = 0.5):
        self.fs = fs
        self.window_sec = window_sec
        self._window_len = max(int(window_sec * fs), 4)
        self._buffer = np.zeros(self._window_len)
        self._write_pos = 0
        self._filled = 0

    def configure(self, fs: float, window_sec: float) -> None:
        self.fs = fs
        self.window_sec = window_sec
        self._window_len = max(int(window_sec * fs), 4)
        self.reset()

    def process(self, envelope_block: np.ndarray) -> np.ndarray:
        """Procesa un bloque y devuelve el RMS por cada muestra del bloque."""
        out = np.empty_like(envelope_block)
        n = self._window_len
        for i, sample in enumerate(envelope_block):
            self._buffer[self._write_pos] = sample
            self._write_pos = (self._write_pos + 1) % n
            self._filled = min(self._filled + 1, n)

            if self._filled < n:
                out[i] = 0.0
            else:
                out[i] = np.sqrt(np.mean(self._buffer ** 2))
        return out

    def reset(self) -> None:
        self._buffer = np.zeros(self._window_len)
        self._write_pos = 0
        self._filled = 0
