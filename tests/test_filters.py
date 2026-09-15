"""Pruebas del pipeline DSP (myofit_pro.sensors.filters)."""

import numpy as np
import pytest

from myofit_pro.sensors.filters import (
    BandpassFilter,
    EnvelopeFilter,
    HighpassFilter,
    NotchFilter,
    RmsCalculator,
)


def test_bandpass_removes_dc_offset():
    fs = 1000.0
    n = 2000
    t = np.arange(n) / fs
    dc_offset = 500.0
    signal = dc_offset + 50 * np.sin(2 * np.pi * 100 * t)  # 100Hz dentro de la banda

    bp = BandpassFilter(low_hz=20, high_hz=450, fs=fs)
    y = bp.process(signal)

    # Tras estabilizarse el filtro, el DC debe quedar casi eliminado
    steady = y[500:]
    assert abs(np.mean(steady)) < 5.0


def test_bandpass_attenuates_low_frequency_outside_band():
    fs = 1000.0
    n = 4000
    t = np.arange(n) / fs
    low_freq_signal = np.sin(2 * np.pi * 2 * t)  # 2Hz, muy por debajo de 20Hz

    bp = BandpassFilter(low_hz=20, high_hz=450, fs=fs)
    y = bp.process(low_freq_signal)

    steady_in = low_freq_signal[1000:]
    steady_out = y[1000:]
    # La amplitud de salida debe ser mucho menor que la de entrada
    assert np.std(steady_out) < 0.3 * np.std(steady_in)


def test_bandpass_passes_midband_frequency():
    fs = 1000.0
    n = 4000
    t = np.arange(n) / fs
    midband_signal = np.sin(2 * np.pi * 100 * t)  # 100Hz, bien dentro de 20-450Hz

    bp = BandpassFilter(low_hz=20, high_hz=450, fs=fs)
    y = bp.process(midband_signal)

    steady_in = midband_signal[1000:]
    steady_out = y[1000:]
    # La señal en banda debe pasar casi sin atenuar
    assert np.std(steady_out) > 0.7 * np.std(steady_in)


def test_bandpass_reset_clears_state():
    fs = 1000.0
    bp = BandpassFilter(20, 450, fs)
    bp.process(np.ones(500) * 1000)  # llenar el estado interno con algo grande
    bp.reset()
    # Tras reset, el filtro no debe arrastrar memoria de la señal anterior
    y = bp.process(np.zeros(10))
    assert np.allclose(y, 0, atol=1e-6)


def test_notch_attenuates_target_frequency():
    fs = 1000.0
    n = 4000
    t = np.arange(n) / fs
    signal_60hz = np.sin(2 * np.pi * 60 * t)

    notch = NotchFilter(base_freq=60.0, fs=fs)
    y = notch.process(signal_60hz)

    steady_in = signal_60hz[1000:]
    steady_out = y[1000:]
    assert np.std(steady_out) < 0.3 * np.std(steady_in)


def test_notch_passes_other_frequencies():
    fs = 1000.0
    n = 4000
    t = np.arange(n) / fs
    signal_150hz = np.sin(2 * np.pi * 150 * t)  # entre armónicos, no debe atenuarse

    notch = NotchFilter(base_freq=60.0, fs=fs)
    y = notch.process(signal_150hz)

    steady_in = signal_150hz[1000:]
    steady_out = y[1000:]
    assert np.std(steady_out) > 0.7 * np.std(steady_in)


def test_notch_is_wide_bandstop_not_narrow_notch():
    """
    El notch debe atenuar TODA la banda de 4Hz alrededor del armónico
    (48-52Hz para el caso de 50Hz base), no solo la frecuencia exacta
    -- así es como funciona bandstop_filter_50Hz del original de elemyo.
    """
    fs = 1000.0
    n = 4000
    t = np.arange(n) / fs
    # 51Hz está DENTRO de la banda 48-52Hz aunque no sea el armónico exacto
    signal_51hz = np.sin(2 * np.pi * 51 * t)

    notch = NotchFilter(base_freq=50.0, fs=fs)
    y = notch.process(signal_51hz)

    steady_in = signal_51hz[1000:]
    steady_out = y[1000:]
    assert np.std(steady_out) < 0.3 * np.std(steady_in)


def test_highpass_removes_dc_offset():
    fs = 1000.0
    n = 8000  # un pasa-altas de 4to orden a 1Hz tarda ~3-4s en asentarse
    t = np.arange(n) / fs
    dc_offset = 800.0
    signal = dc_offset + 30 * np.sin(2 * np.pi * 100 * t)

    hp = HighpassFilter(low_hz=1.0, fs=fs)
    y = hp.process(signal)

    steady = y[6000:]  # últimos 2s, bien asentado
    assert abs(np.mean(steady)) < 2.0


def test_highpass_passes_emg_range_frequencies():
    fs = 1000.0
    n = 4000
    t = np.arange(n) / fs
    emg_signal = np.sin(2 * np.pi * 100 * t)  # 100Hz, típico de EMG

    hp = HighpassFilter(low_hz=1.0, fs=fs)
    y = hp.process(emg_signal)

    steady_in = emg_signal[1000:]
    steady_out = y[1000:]
    # Un pasa-altas de 1Hz no debe atenuar nada en el rango de EMG (100Hz)
    assert np.std(steady_out) > 0.9 * np.std(steady_in)


def test_highpass_reset_clears_state():
    fs = 1000.0
    hp = HighpassFilter(1.0, fs)
    hp.process(np.ones(500) * 1000)
    hp.reset()
    y = hp.process(np.zeros(10))
    assert np.allclose(y, 0, atol=1e-6)


def test_envelope_is_nonnegative_and_smooths():
    fs = 1000.0
    n = 2000
    rng = np.random.default_rng(42)
    noisy_signal = rng.normal(0, 100, n)

    env = EnvelopeFilter(alpha=0.95)
    y = env.process(noisy_signal)

    assert np.all(y >= 0)
    # La envolvente debe tener mucha menos varianza (más suave) que la señal cruda rectificada
    assert np.var(y) < np.var(np.abs(noisy_signal))


def test_envelope_reset_clears_state():
    env = EnvelopeFilter(alpha=0.95)
    env.process(np.ones(200) * 500)
    env.reset()
    y = env.process(np.zeros(5))
    assert np.allclose(y, 0, atol=1e-6)


def test_rms_zero_for_silent_signal():
    fs = 1000.0
    rms = RmsCalculator(fs=fs, window_sec=0.1)
    silent = np.zeros(500)
    y = rms.process(silent)
    assert np.allclose(y, 0, atol=1e-6)


def test_rms_matches_expected_for_constant_signal():
    fs = 1000.0
    window_sec = 0.1
    rms = RmsCalculator(fs=fs, window_sec=window_sec)
    constant_value = 50.0
    n = int(window_sec * fs) * 3  # suficientes muestras para llenar la ventana varias veces
    signal = np.full(n, constant_value)

    y = rms.process(signal)

    # Una vez llena la ventana, el RMS de una señal constante = el valor constante
    assert np.isclose(y[-1], constant_value, rtol=0.05)


def test_rms_reset_clears_buffer():
    fs = 1000.0
    rms = RmsCalculator(fs=fs, window_sec=0.1)
    rms.process(np.full(200, 100.0))
    rms.reset()
    y = rms.process(np.zeros(5))
    assert np.allclose(y, 0, atol=1e-6)
