"""
Pruebas de validez de la señal y del umbral de detección de repeticiones.

Ambas cosas salieron de medir contra el hardware real: un electrodo
despegado satura el ADC y produce un MVC alto pero falso, y un umbral
fijo en µV cuenta distinto en cada canal porque las amplitudes difieren
mucho entre sensores.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from myofit_pro.sensors.channel import (
    ADC_MAX,
    SATURATION_LIMIT,
    SATURATION_WINDOW,
    MyoBlueChannel,
    saturated_fraction,
)

CENTER = 8192


def _clean_signal(n: int = 1000, amplitude: int = 300) -> np.ndarray:
    """Señal centrada y lejos de los topes, como la de un electrodo bien puesto."""
    t = np.linspace(0, 4 * np.pi, n)
    return (CENTER + amplitude * np.sin(t)).astype(np.uint16)


def _detached_signal(n: int = 1000) -> np.ndarray:
    """Entrada flotando: rebota entre los dos extremos del convertidor."""
    return np.where(np.arange(n) % 2 == 0, 1, ADC_MAX - 1).astype(np.uint16)


class TestSaturatedFraction:
    def test_senal_limpia_no_satura(self):
        assert saturated_fraction(_clean_signal()) == 0.0

    def test_electrodo_despegado_satura_por_completo(self):
        assert saturated_fraction(_detached_signal()) == 1.0

    def test_bloque_vacio_no_revienta(self):
        assert saturated_fraction(np.array([], dtype=np.uint16)) == 0.0

    def test_un_pico_aislado_no_marca_saturacion(self):
        # Una muestra contra el tope en 1000 es 0.1%: por debajo del limite,
        # para no descartar la señal por un artefacto puntual.
        signal = _clean_signal()
        signal[500] = ADC_MAX
        assert 0 < saturated_fraction(signal) < SATURATION_LIMIT

    def test_ambos_extremos_cuentan(self):
        bajo = np.full(100, 0, dtype=np.uint16)
        alto = np.full(100, ADC_MAX, dtype=np.uint16)
        assert saturated_fraction(bajo) == 1.0
        assert saturated_fraction(alto) == 1.0


class TestChannelSignalValidity:
    def test_canal_reporta_saturacion_en_el_bloque(self):
        channel = MyoBlueChannel(sensor_index=0)
        block = channel.process_block(_detached_signal(), 0.0)
        assert block.saturation == 1.0
        assert channel.signal_is_valid is False

    def test_canal_con_senal_limpia_es_valido(self):
        channel = MyoBlueChannel(sensor_index=0)
        block = channel.process_block(_clean_signal(), 0.0)
        assert block.saturation == 0.0
        assert channel.signal_is_valid is True

    def test_validez_se_recupera_al_volver_el_contacto(self):
        """La ventana móvil tarda ~1 s en limpiarse, no se recupera de golpe."""
        channel = MyoBlueChannel(sensor_index=0)
        channel.process_block(_detached_signal(), 0.0)
        assert channel.signal_is_valid is False

        for i in range(SATURATION_WINDOW):
            channel.process_block(_clean_signal(), 1.0 + i)
        assert channel.signal_is_valid is True

    def test_una_muestra_suelta_contra_el_tope_no_dispara_la_alarma(self):
        """
        Cada bloque trae 119 muestras, así que una sola contra el tope ya es
        0.84% de su bloque. Sin la ventana móvil eso bastaría para marcar la
        señal como inválida.
        """
        channel = MyoBlueChannel(sensor_index=0)
        for i in range(SATURATION_WINDOW):
            block = _clean_signal(n=119)
            if i == 0:
                block[50] = ADC_MAX
            channel.process_block(block, float(i))
        assert channel.signal_is_valid is True


class TestRealHardwareSignals:
    """
    Regresión contra señal grabada del MYOblue real (en `tests/data/`).

    De estas tres capturas salieron `SATURATION_LIMIT` y `_RAIL_MARGIN`, así
    que si alguien los mueve, estas pruebas lo detectan. El caso crítico es
    la contracción máxima: un umbral demasiado sensible marcaría "electrodo
    despegado" justo durante el MVC, que es cuando más importa.
    """

    DATA = Path(__file__).parent / "data"

    def _classify(self, filename: str) -> MyoBlueChannel:
        raw = np.load(self.DATA / filename)
        channel = MyoBlueChannel(sensor_index=0)
        for start in range(0, len(raw) - 119, 119):
            channel.process_block(raw[start : start + 119], start / 1000.0)
        return channel

    def test_reposo_con_buen_contacto_es_valido(self):
        assert self._classify("real_rest_ok.npy").signal_is_valid is True

    def test_contraccion_maxima_no_da_falso_positivo(self):
        channel = self._classify("real_max_contraction_ok.npy")
        assert channel.latest_saturation == 0.0
        assert channel.signal_is_valid is True

    def test_electrodo_despegado_se_detecta(self):
        channel = self._classify("real_electrode_detached.npy")
        assert channel.latest_saturation > SATURATION_LIMIT
        assert channel.signal_is_valid is False


class TestRepetitionThreshold:
    """
    El umbral debe salir del MVC de CADA canal. Con un valor fijo, dos
    canales con amplitudes distintas cuentan repeticiones distintas para
    el mismo gesto (medido en hardware: 4 contra 7).
    """

    BURST = 1200   # muestras de contracción (1.2 s a 1000 Hz)
    REST = 1200    # muestras de reposo

    @classmethod
    def _burst(cls, amplitude: int) -> np.ndarray:
        """Ráfaga de 25 Hz, dentro de la banda que deja pasar el filtro."""
        t = np.linspace(0, 60 * np.pi, cls.BURST)
        return (CENTER + amplitude * np.sin(t)).astype(np.uint16)

    @classmethod
    def _measure_mvc(cls, amplitude: int) -> float:
        """
        MVC del canal para esa amplitud, igual que el Paso 4: el RMS
        sostenido durante una contracción máxima.
        """
        channel = MyoBlueChannel(sensor_index=0)
        block = channel.process_block(cls._burst(amplitude), 0.0)
        return float(block.rms.max())

    @classmethod
    def _count_reps(cls, channel: MyoBlueChannel, amplitude: int, cycles: int = 4) -> int:
        rest = np.full(cls.REST, CENTER, dtype=np.uint16)
        burst = cls._burst(amplitude)
        t = 0.0
        for _ in range(cycles):
            channel.process_block(burst, t)
            t += cls.BURST / 1000.0
            channel.process_block(rest, t)
            t += cls.REST / 1000.0
        return channel.contraction_count

    def test_umbral_fijo_cuenta_distinto_entre_canales(self):
        """El bug original: mismo umbral absoluto, amplitudes distintas."""
        debil = MyoBlueChannel(sensor_index=0)
        fuerte = MyoBlueChannel(sensor_index=1)
        debil.trigger_threshold_uv = 100.0
        fuerte.trigger_threshold_uv = 100.0

        reps_debil = self._count_reps(debil, amplitude=150)
        reps_fuerte = self._count_reps(fuerte, amplitude=3000)

        assert reps_debil != reps_fuerte

    def test_umbral_relativo_al_mvc_iguala_el_conteo(self):
        """Con el umbral derivado del MVC de cada canal, ambos coinciden."""
        from myofit_pro.gui.app_state import REP_THRESHOLD_MVC_FRACTION

        for amplitude in (150, 3000):
            mvc = self._measure_mvc(amplitude)
            channel = MyoBlueChannel(sensor_index=0)
            channel.trigger_threshold_uv = mvc * REP_THRESHOLD_MVC_FRACTION
            assert self._count_reps(channel, amplitude) == 4, (
                f"amplitud {amplitude}: MVC={mvc:.1f} µV, "
                f"umbral={channel.trigger_threshold_uv:.1f} µV"
            )
