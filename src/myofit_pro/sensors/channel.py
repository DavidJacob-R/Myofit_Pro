"""Estado de captura de un canal sEMG.

Posición en el flujo
--------------------
Tercera etapa del procesado, entre `myofit_pro.sensors.protocol` y la
capa gráfica. Se instancia un `MyoBlueChannel` por sensor activo.
`myofit_pro.sensors.service` le entrega las muestras de cada paquete y
recibe un `ProcessedBlock` con todas las representaciones de la señal que
la aplicación necesita.

Cadena aplicada
---------------
Rechazo de banda, paso banda, rectificación, envolvente y valor eficaz
deslizante, en ese orden. Sobre el valor eficaz se detectan las
contracciones por cruce de umbral.

Cuando el paso banda está desactivado, la rectificación se precede de un
paso alto de respaldo a 1 Hz, igual que en la implementación de
referencia, para no rectificar una señal que conserva la componente
continua del convertidor. Con el paso banda activo no hace falta, porque
él mismo la elimina.

See Also
--------
myofit_pro.sensors.filters : Implementación de cada etapa.
myofit_pro.sensors.service : Orquestación de la captura.
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


#: Valor máximo del convertidor analógico-digital, de 14 bits.
ADC_MAX = 16383

#: Distancia a cada extremo de la escala dentro de la cual una muestra se
#: considera saturada.
_RAIL_MARGIN = 256

#: Fracción de muestras saturadas a partir de la cual la señal se
#: considera inservible.
#:
#: Calibrado con hardware real midiendo ambos extremos: un electrodo bien
#: adherido da 0,000 % incluso durante la contracción máxima, mientras que
#: uno despegado dio entre 2,9 % y 25,4 %. El umbral de 0,5 % deja un
#: margen amplio frente a falsos positivos y detecta aun así el caso
#: despegado más leve observado.
SATURATION_LIMIT = 0.005

#: Bloques sobre los que se promedia la saturación, equivalentes a un
#: segundo aproximadamente.
#:
#: Cada bloque trae 119 muestras, de modo que una sola muestra saturada
#: representa ya el 0,84 % de su bloque. Evaluar bloque a bloque haría que
#: un artefacto aislado disparara la alarma.
SATURATION_WINDOW = 8


def raw_to_microvolts(raw: np.ndarray) -> np.ndarray:
    """Convierte muestras del convertidor a microvoltios.

    Parameters
    ----------
    raw : numpy.ndarray
        Muestras sin procesar, de 0 a `ADC_MAX`.

    Returns
    -------
    numpy.ndarray
        Señal en microvoltios, centrada en cero.

    Notes
    -----
    La conversión resta el punto medio de la escala, normaliza al fondo
    de escala, multiplica por la tensión de referencia de 2,49 V y pasa a
    microvoltios considerando la ganancia del amplificador.
    """
    return ((raw.astype(np.float64) - 8192.0) / 16384.0 * 2.49) * 2000.0


def saturated_fraction(raw: np.ndarray) -> float:
    """Calcula la fracción de muestras saturadas contra los extremos.

    Parameters
    ----------
    raw : numpy.ndarray
        Muestras sin procesar del convertidor.

    Returns
    -------
    float
        Fracción de muestras situadas a menos de `_RAIL_MARGIN` de
        cualquiera de los dos extremos de la escala.

    Notes
    -----
    Detecta la pérdida de contacto del electrodo: al despegarse, la
    entrada del amplificador queda flotando y la señal oscila entre
    ambos extremos del convertidor. Con este hardware, un sensor bien
    colocado se mueve unas 50 cuentas en torno al centro de la escala,
    mientras que uno despegado recorrió de 1 a 16380.

    Detectarlo importa porque esa señal produce una contracción máxima
    elevada y de apariencia normal, y una calibración corrupta invalida
    en silencio todas las evaluaciones posteriores de ese cliente.

    El recorrido pico a pico se descartó como criterio: medido con este
    hardware, una contracción máxima legítima alcanza el 80 % de la
    escala y un electrodo despegado el 98 %, valores demasiado próximos
    para discriminar.
    """
    if raw.size == 0:
        return 0.0
    railed = (raw <= _RAIL_MARGIN) | (raw >= ADC_MAX - _RAIL_MARGIN)
    return float(np.count_nonzero(railed) / raw.size)


@dataclass(slots=True)
class ProcessedBlock:
    """Resultado de procesar un bloque de muestras de un sensor.

    Attributes
    ----------
    sensor_index : int
        Índice del sensor, de 0 a 7.
    times : numpy.ndarray
        Instante de cada muestra, en segundos desde el inicio de la
        captura.
    micro_volts : numpy.ndarray
        Señal convertida a microvoltios, sin filtrar.
    filtered : numpy.ndarray
        Señal tras el rechazo de banda y el paso banda. Es la que se
        representa en la gráfica y la que consume
        `myofit_pro.ml.features`.
    envelope : numpy.ndarray
        Envolvente lineal.
    rms : numpy.ndarray
        Valor eficaz deslizante, sobre el que se detectan las
        contracciones.
    contractions_in_block : int
        Cruces ascendentes del umbral producidos en este bloque.
    saturation : float, default=0.0
        Fracción de muestras saturadas del bloque.
    """

    sensor_index: int
    times: np.ndarray
    micro_volts: np.ndarray
    filtered: np.ndarray
    envelope: np.ndarray
    rms: np.ndarray
    contractions_in_block: int
    saturation: float = 0.0


class MyoBlueChannel:
    """Estado de captura de un sensor.

    Mantiene su propia cadena de filtros, su contador de contracciones y
    los últimos valores de cada representación de la señal, que la
    interfaz consulta para refrescar los indicadores.

    Parameters
    ----------
    sensor_index : int
        Índice del sensor, de 0 a 7.
    sample_rate_hz : float, default=1000.0
        Frecuencia de muestreo, en hercios.
    bandpass_low, bandpass_high : float, default=2.0, 499.0
        Frecuencias de corte del paso banda, en hercios. Los valores por
        defecto son los que el fabricante fija en ``config.ini``.
    notch_hz : float, default=60.0
        Frecuencia fundamental de la red eléctrica, en hercios.
    rms_interval_sec : float, default=0.5
        Longitud de la ventana del valor eficaz, en segundos.
    envelope_alpha : float, default=0.95
        Coeficiente de suavizado de la envolvente.

    Attributes
    ----------
    bandpass_enabled, notch_enabled : bool
        Etapas activas. Modificables en caliente desde la interfaz.
    trigger_threshold_uv : float
        Umbral de detección de contracción, en microvoltios de valor
        eficaz.
    latest_micro_volts, latest_filtered, latest_envelope, latest_rms : float
        Último valor de cada representación, para los indicadores en
        vivo.
    battery_volts : float
        Última tensión de batería recibida del sensor.
    last_message_number : int
        Último contador de mensaje recibido.
    contraction_count : int
        Contracciones acumuladas desde el último reinicio del contador.
    is_contracting : bool
        Si la señal se encuentra actualmente por encima del umbral.
    """

    def __init__(
        self,
        sensor_index: int,
        sample_rate_hz: float = 1000.0,
        bandpass_low: float = 2.0,
        bandpass_high: float = 499.0,
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
        self._highpass = HighpassFilter(1.0, sample_rate_hz)
        self._envelope = EnvelopeFilter(envelope_alpha)
        self._rms = RmsCalculator(sample_rate_hz, rms_interval_sec)

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
        """Reconfigura el paso banda."""
        self._bandpass.configure(low_hz, high_hz, fs)

    def configure_notch(self, freq_hz: float, fs: float) -> None:
        """Reconfigura el rechazo de banda de red."""
        self._notch.configure(freq_hz, fs)

    def configure_rms(self, fs: float, interval_sec: float) -> None:
        """Reconfigura la ventana del valor eficaz."""
        self._rms.configure(fs, interval_sec)

    def set_envelope_alpha(self, alpha: float) -> None:
        """Cambia el suavizado de la envolvente."""
        self._envelope.set_alpha(alpha)

    def update_battery(self, volts: float) -> None:
        """Registra la tensión de batería del último paquete."""
        self.battery_volts = volts

    def update_message_number(self, msg_num: int) -> None:
        """Registra el contador de mensaje del último paquete."""
        self.last_message_number = msg_num

    def reset_counter(self) -> None:
        """Pone a cero el contador de contracciones."""
        self.contraction_count = 0

    def reset_filters(self) -> None:
        """Anula el estado de toda la cadena y la ventana de saturación."""
        self._bandpass.reset()
        self._notch.reset()
        self._highpass.reset()
        self._envelope.reset()
        self._rms.reset()
        self._saturation_window.clear()

    # ── Procesamiento ───────────────────────────────────────────────

    def process_block(self, raw_samples: np.ndarray, start_time_sec: float) -> ProcessedBlock:
        """Procesa un bloque de muestras a través de la cadena completa.

        Parameters
        ----------
        raw_samples : numpy.ndarray
            Muestras sin procesar del convertidor.
        start_time_sec : float
            Instante de la primera muestra, en segundos desde el inicio
            de la captura.

        Returns
        -------
        ProcessedBlock
            Todas las representaciones de la señal del bloque, más el
            recuento de contracciones y la saturación.

        Notes
        -----
        La detección de contracciones se realiza sobre el valor eficaz
        con histéresis: el contador avanza al superar el umbral y no
        vuelve a avanzar hasta que la señal desciende por debajo de él.
        Sin esa histéresis, una señal oscilando en torno al umbral
        contaría decenas de contracciones inexistentes.
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
            # Sin paso banda, el paso alto de respaldo evita rectificar
            # una señal que conserva la componente continua.
            rectify_input = self._highpass.process(signal)

        self.latest_filtered = float(signal[-1]) if n else self.latest_filtered

        envelope = self._envelope.process(rectify_input)
        self.latest_envelope = float(envelope[-1]) if n else self.latest_envelope

        rms = self._rms.process(envelope)
        self.latest_rms = float(rms[-1]) if n else self.latest_rms

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
        """Saturación media del último segundo de señal."""
        if not self._saturation_window:
            return 0.0
        return sum(self._saturation_window) / len(self._saturation_window)

    @property
    def signal_is_valid(self) -> bool:
        """Si la señal es utilizable.

        Falso cuando la saturación media supera `SATURATION_LIMIT`, lo
        que indica que el electrodo ha perdido contacto con la piel.
        """
        return self.latest_saturation < SATURATION_LIMIT
