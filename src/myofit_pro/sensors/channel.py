"""
Estado vivo de un canal/sensor: aplica el pipeline completo
(notch -> bandpass -> rectificación -> envolvente -> RMS) sobre
bloques de muestras y detecta contracciones por umbral.

Auditado contra el original de elemyo: cuando el bandpass está
DESACTIVADO, la rectificación pasa por un pasa-altas de respaldo
(HighpassFilter, 1 Hz) antes de rectificar — igual que el original —
para no rectificar una señal con offset de DC crudo. Cuando el
bandpass SÍ está activo, se rectifica directo su salida (el propio
bandpass ya remueve el DC).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from myofit_pro.sensors.filters import (
    BandpassFilter,
    EnvelopeFilter,
    HighpassFilter,
    NotchFilter,
    RmsCalculator,
)


ADC_MAX = 16383           # el convertidor es de 14 bits: 0..16383
_RAIL_MARGIN = 256        # qué tan cerca de cada extremo cuenta como saturado

# Fracción de muestras contra los topes a partir de la cual la señal se
# considera inservible.
#
# Calibrado con hardware real, midiendo los dos extremos:
#   - electrodo bien pegado, contracción MAXIMA : 0.000%
#   - electrodo despegado                       : 2.9% a 25.4%
# El sensor sano da cero absoluto incluso durante el esfuerzo máximo, así
# que 0.5% deja muchísimo margen contra falsos positivos y aun así detecta
# el caso despegado más leve que se llegó a medir.
SATURATION_LIMIT = 0.005

# Bloques sobre los que se promedia la saturación (~1 segundo).
#
# Cada bloque trae 119 muestras, así que una sola muestra contra el tope
# ya representa 0.84% de su bloque: evaluar bloque por bloque haría que un
# artefacto aislado disparara la alarma. Promediar ~1 s lo evita.
SATURATION_WINDOW = 8


def raw_to_microvolts(raw: np.ndarray) -> np.ndarray:
    """Convierte muestras crudas del ADC (0..16383) a microvolts."""
    return ((raw.astype(np.float64) - 8192.0) / 16384.0 * 2.49) * 2000.0


def saturated_fraction(raw: np.ndarray) -> float:
    """
    Fracción de muestras pegadas a los extremos del ADC.

    Sirve para detectar un electrodo despegado: cuando pierde contacto con
    la piel, la entrada del amplificador queda flotando y la señal rebota
    entre ambos extremos del convertidor. Medido contra hardware real, un
    sensor bien colocado se mueve unos 50 counts alrededor del centro,
    mientras que uno despegado recorrió de 1 a 16380.

    Importa detectarlo porque esa señal produce un MVC alto y de apariencia
    normal, y una calibración corrupta invalida en silencio todas las
    evaluaciones posteriores de ese cliente.

    No se usa el recorrido pico a pico como criterio: medido en hardware,
    una contracción máxima legítima llega al 80% de la escala y un
    electrodo despegado al 98%, demasiado cerca para distinguirlos.
    """
    if raw.size == 0:
        return 0.0
    railed = (raw <= _RAIL_MARGIN) | (raw >= ADC_MAX - _RAIL_MARGIN)
    return float(np.count_nonzero(railed) / raw.size)


@dataclass(slots=True)
class ProcessedBlock:
    """Resultado de procesar un bloque de muestras para un sensor."""

    sensor_index: int
    times: np.ndarray          # segundos, absolutos desde inicio de captura
    micro_volts: np.ndarray    # señal sin filtrar
    filtered: np.ndarray       # tras notch + bandpass (lo que se grafica)
    envelope: np.ndarray       # envolvente
    rms: np.ndarray            # RMS deslizante
    contractions_in_block: int # cuántas veces se cruzó el umbral en este bloque
    saturation: float = 0.0    # fracción de muestras contra los topes del ADC


class MyoBlueChannel:
    """Una instancia por sensor (0..7). Mantiene sus propios filtros y contador."""

    def __init__(
        self,
        sensor_index: int,
        sample_rate_hz: float = 1000.0,
        bandpass_low: float = 2.0,     # config.ini: BandPassFilterLF = 2
        bandpass_high: float = 499.0,  # config.ini: BandPassFilterHF = 499
        notch_hz: float = 60.0,
        rms_interval_sec: float = 0.5,
        envelope_alpha: float = 0.95,
    ):
        self.sensor_index = sensor_index
        self.sample_rate_hz = sample_rate_hz

        self.bandpass_enabled = True
        self.notch_enabled = False
        self.trigger_threshold_uv = 100.0

        self._bandpass = BandpassFilter(bandpass_low, bandpass_high, sample_rate_hz)
        self._notch = NotchFilter(notch_hz, sample_rate_hz)
        self._highpass = HighpassFilter(1.0, sample_rate_hz)  # respaldo, ver docstring
        self._envelope = EnvelopeFilter(envelope_alpha)
        self._rms = RmsCalculator(sample_rate_hz, rms_interval_sec)

        # Estado de lectura pública (último valor visto, para la UI)
        self.latest_micro_volts = 0.0
        self.latest_filtered = 0.0
        self.latest_envelope = 0.0
        self.latest_rms = 0.0
        self._saturation_window: deque[float] = deque(maxlen=SATURATION_WINDOW)
        self.battery_volts = 0.0
        self.last_message_number = 0
        self.contraction_count = 0
        self.is_contracting = False

    # ── Configuración en caliente ──────────────────────────────────

    def configure_bandpass(self, low_hz: float, high_hz: float, fs: float) -> None:
        self._bandpass.configure(low_hz, high_hz, fs)

    def configure_notch(self, freq_hz: float, fs: float) -> None:
        self._notch.configure(freq_hz, fs)

    def configure_rms(self, fs: float, interval_sec: float) -> None:
        self._rms.configure(fs, interval_sec)

    def set_envelope_alpha(self, alpha: float) -> None:
        self._envelope.set_alpha(alpha)

    def update_battery(self, volts: float) -> None:
        self.battery_volts = volts

    def update_message_number(self, msg_num: int) -> None:
        self.last_message_number = msg_num

    def reset_counter(self) -> None:
        self.contraction_count = 0

    def reset_filters(self) -> None:
        self._bandpass.reset()
        self._notch.reset()
        self._highpass.reset()
        self._envelope.reset()
        self._rms.reset()
        self._saturation_window.clear()

    # ── Procesamiento ───────────────────────────────────────────────

    def process_block(self, raw_samples: np.ndarray, start_time_sec: float) -> ProcessedBlock:
        """
        Procesa un bloque de N muestras crudas (uint16) del ADC.
        `start_time_sec` es el tiempo absoluto de la primera muestra.
        """
        n = len(raw_samples)
        dt = 1.0 / self.sample_rate_hz
        times = start_time_sec + np.arange(n) * dt

        uv = raw_to_microvolts(raw_samples)
        self.latest_micro_volts = float(uv[-1]) if n else self.latest_micro_volts

        saturation = saturated_fraction(raw_samples)
        self._saturation_window.append(saturation)

        signal = uv
        if self.notch_enabled:
            signal = self._notch.process(signal)

        if self.bandpass_enabled:
            signal = self._bandpass.process(signal)
            rectify_input = signal
        else:
            # Sin bandpass, el pasa-altas de respaldo evita rectificar
            # una señal con DC crudo (igual que el original).
            rectify_input = self._highpass.process(signal)

        self.latest_filtered = float(signal[-1]) if n else self.latest_filtered

        envelope = self._envelope.process(rectify_input)
        self.latest_envelope = float(envelope[-1]) if n else self.latest_envelope

        rms = self._rms.process(envelope)
        self.latest_rms = float(rms[-1]) if n else self.latest_rms

        # Detección de contracciones por umbral con histéresis simple
        contractions = 0
        for r in rms:
            if not self.is_contracting and r >= self.trigger_threshold_uv:
                self.is_contracting = True
                self.contraction_count += 1
                contractions += 1
            elif self.is_contracting and r < self.trigger_threshold_uv:
                self.is_contracting = False

        return ProcessedBlock(
            sensor_index=self.sensor_index,
            times=times,
            micro_volts=uv,
            filtered=signal,
            envelope=envelope,
            rms=rms,
            contractions_in_block=contractions,
            saturation=saturation,
        )

    @property
    def latest_saturation(self) -> float:
        """Saturación promedio del último segundo de señal."""
        if not self._saturation_window:
            return 0.0
        return sum(self._saturation_window) / len(self._saturation_window)

    @property
    def signal_is_valid(self) -> bool:
        """False cuando el electrodo perdió contacto (ver `saturated_fraction`)."""
        return self.latest_saturation < SATURATION_LIMIT
