"""Pruebas de integración de MyoBlueChannel (pipeline completo)."""

import numpy as np

from myofit_pro.sensors.channel import MyoBlueChannel, raw_to_microvolts


def test_raw_to_microvolts_matches_original_formula():
    # ((raw - 8192) / 16384 * 2.49) * 2000 -- fórmula exacta del original
    raw = np.array([8192, 16383, 0], dtype=np.uint16)
    uv = raw_to_microvolts(raw)
    assert np.isclose(uv[0], 0.0, atol=1e-6)
    expected_max = ((16383 - 8192) / 16384.0 * 2.49) * 2000.0
    assert np.isclose(uv[1], expected_max)


def test_channel_with_bandpass_disabled_uses_highpass_fallback():
    """
    Con bandpass desactivado, el canal debe pasar por el highpass de
    respaldo antes de rectificar -- si no lo hiciera, un offset de DC
    grande contaminaría la envolvente indefinidamente.
    """
    fs = 1000.0
    channel = MyoBlueChannel(sensor_index=0, sample_rate_hz=fs)
    channel.bandpass_enabled = False
    channel.notch_enabled = False

    # Simular una señal EMG con bastante offset de DC (ADC descalibrado)
    n = 3000
    t = np.arange(n) / fs
    dc_bias = 8192 + 3000  # bias grande en cuentas del ADC
    raw = (dc_bias + 200 * np.sin(2 * np.pi * 80 * t)).astype(np.uint16)

    block = channel.process_block(raw, 0.0)

    # Tras el highpass de respaldo, la envolvente en régimen permanente
    # NO debe quedar dominada por el offset de DC (debe ser del orden
    # de la amplitud de la señal EMG, no del offset).
    steady_envelope = block.envelope[1000:]
    assert np.mean(steady_envelope) < 500.0  # muy por debajo de lo que daría el DC crudo


def test_channel_contraction_counter_increments_on_threshold_cross():
    fs = 1000.0
    channel = MyoBlueChannel(sensor_index=0, sample_rate_hz=fs)
    channel.trigger_threshold_uv = 50.0

    n = 2000
    t = np.arange(n) / fs
    # Señal grande -> RMS debe subir por encima del umbral
    raw = (8192 + 2000 * np.sin(2 * np.pi * 80 * t)).astype(np.uint16)

    channel.process_block(raw, 0.0)
    assert channel.contraction_count >= 1
    assert channel.is_contracting is True


def test_channel_reset_filters_clears_state():
    fs = 1000.0
    channel = MyoBlueChannel(sensor_index=0, sample_rate_hz=fs)
    raw = np.full(500, 12000, dtype=np.uint16)
    channel.process_block(raw, 0.0)
    channel.reset_filters()

    # Tras el reset, procesar silencio debe dar una envolvente cercana a cero
    silent = np.full(50, 8192, dtype=np.uint16)
    block = channel.process_block(silent, 0.0)
    assert block.envelope[-1] < 50.0
