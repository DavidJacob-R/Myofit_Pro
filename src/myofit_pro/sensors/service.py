"""
Servicio principal para sensores MYOblue v1.2 de elemyo.

Los MYOblue v1.2 se comunican por RF 2.4GHz propietario a un dongle
USB receptor, que Windows/Linux/macOS expone como un puerto COM/tty
virtual. Por eso este servicio usa `pyserial`, NO `bleak` — el
protocolo RF del sensor al dongle no es Bluetooth estándar y no está
documentado públicamente por elemyo, así que no hay forma de hablarle
directo por BLE sin el dongle.

`bleak` se deja declarado como dependencia del proyecto para el día
que se incorpore un sensor que sí hable BLE nativo (hay líneas de
producto de otros fabricantes que sí lo hacen) — el método
`connect_ble()` queda como stub documentado para ese caso futuro,
sin inventar UUIDs de servicio que no conocemos.

Este servicio se implementa como QObject con señales de PySide6, así
que emitir desde el hilo de lectura en background y consumir desde la
UI en el hilo principal es automático y seguro (Qt encola la señal).
"""

from __future__ import annotations

import threading
import time
from enum import Enum, auto

import numpy as np
import serial
import serial.tools.list_ports
from PySide6.QtCore import QObject, Signal

from myofit_pro.sensors.channel import MyoBlueChannel, ProcessedBlock
from myofit_pro.sensors.protocol import DEFAULT_BAUD_RATE, MAX_SENSORS, Packet, parse_available


class ConnectionState(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    ERROR = auto()


class MyoBlueService(QObject):
    """
    Punto de entrada único para hablar con el receptor USB del MYOblue.

    Uso típico desde la GUI:

        service = MyoBlueService()
        service.samples_received.connect(on_samples)
        service.battery_updated.connect(on_battery)
        service.contraction_detected.connect(on_contraction)
        service.connection_state_changed.connect(on_state)

        ports = MyoBlueService.available_ports()
        service.connect_serial(ports[0])
        service.start()
        ...
        service.stop()
        service.disconnect_serial()
    """

    # ── Señales Qt (equivalentes a los `event` de C#) ──────────────
    samples_received = Signal(object)            # ProcessedBlock
    battery_updated = Signal(int, float)          # sensor_index, volts
    contraction_detected = Signal(int, int, float)  # sensor_index, total_count, time_sec
    connection_state_changed = Signal(object, str)  # ConnectionState, message

    def __init__(self, sensors_in_use: int = 2, parent: QObject | None = None):
        super().__init__(parent)

        self.sensors_in_use = sensors_in_use
        self.sample_rate_hz = 1000.0
        self.bandpass_low = 2.0    # config.ini: BandPassFilterLF = 2
        self.bandpass_high = 499.0  # config.ini: BandPassFilterHF = 499
        self.notch_hz = 60.0
        self.rms_interval_sec = 0.5
        self.envelope_alpha = 0.95

        self.state = ConnectionState.DISCONNECTED
        self.current_port: str | None = None

        self.channels: list[MyoBlueChannel] = [
            MyoBlueChannel(
                i, self.sample_rate_hz, self.bandpass_low, self.bandpass_high,
                self.notch_hz, self.rms_interval_sec, self.envelope_alpha,
            )
            for i in range(MAX_SENSORS)
        ]

        self._serial: serial.Serial | None = None
        self._stop_event = threading.Event()
        self._reader_thread: threading.Thread | None = None
        self._residue = b""

        self._first_msg_num = [0] * MAX_SENSORS
        self._accumulated_msg_num = [0] * MAX_SENSORS
        self._first_packet_seen = [False] * MAX_SENSORS

    # ── Descubrimiento de puertos ───────────────────────────────────

    @staticmethod
    def available_ports() -> list[str]:
        return [p.device for p in serial.tools.list_ports.comports()]

    # ── Conexión ─────────────────────────────────────────────────────

    def connect_serial(self, port_name: str) -> bool:
        if self.state == ConnectionState.CONNECTED:
            return True
        self._change_state(ConnectionState.CONNECTING, f"Abriendo {port_name}")
        try:
            self._serial = serial.Serial(
                port=port_name,
                baudrate=DEFAULT_BAUD_RATE,
                timeout=0.5,
                write_timeout=0.5,
            )
            self.current_port = port_name
            self._change_state(ConnectionState.CONNECTED, f"Conectado a {port_name}")
            return True
        except serial.SerialException as ex:
            self._serial = None
            self._change_state(ConnectionState.ERROR, str(ex))
            return False

    def connect_ble(self, device_address: str) -> None:
        """
        Stub para sensores futuros que hablen BLE nativo (no aplica a
        MYOblue v1.2, que usa dongle USB). No implementado — requiere
        los UUIDs de servicio/característica reales del fabricante,
        que hay que obtener con un sniffer BLE o la hoja de datos.
        """
        raise NotImplementedError(
            "El MYOblue v1.2 usa dongle USB, no BLE directo. "
            "Este método queda listo para un sensor BLE futuro."
        )

    def disconnect_serial(self) -> None:
        self.stop()
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None
        self.current_port = None
        self._change_state(ConnectionState.DISCONNECTED)

    # ── Ciclo de lectura ─────────────────────────────────────────────

    def start(self) -> None:
        if self._serial is None or not self._serial.is_open:
            return
        if self._reader_thread is not None and self._reader_thread.is_alive():
            return

        self._reset_timing_state()
        self._stop_event.clear()
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=1.0)
        self._reader_thread = None

    def reset_counters(self) -> None:
        for ch in self.channels:
            ch.reset_counter()

    @property
    def is_connected(self) -> bool:
        return self.state == ConnectionState.CONNECTED

    def close(self) -> None:
        """Liberar todo (equivalente a Dispose de C#)."""
        self.disconnect_serial()

    # ── Internos ──────────────────────────────────────────────────────

    def _reader_loop(self) -> None:
        assert self._serial is not None
        while not self._stop_event.is_set() and self._serial.is_open:
            try:
                available = self._serial.in_waiting
                if available <= 0:
                    time.sleep(0.005)
                    continue

                chunk = self._serial.read(min(available, 4096))
                combined = self._residue + chunk

                packets, leftover = parse_available(combined)
                self._residue = leftover

                for pkt in packets:
                    self._process_packet(pkt)

            except serial.SerialException as ex:
                self._change_state(ConnectionState.ERROR, str(ex))
                break
            except Exception as ex:  # pragma: no cover - defensivo
                self._change_state(ConnectionState.ERROR, str(ex))
                break

    def _process_packet(self, pkt: Packet) -> None:
        s = pkt.sensor_index
        if s >= self.sensors_in_use:
            return

        channel = self.channels[s]

        if abs(channel.battery_volts - pkt.battery_volts) > 0.01:
            channel.update_battery(pkt.battery_volts)
            self.battery_updated.emit(s, pkt.battery_volts)
        channel.update_message_number(pkt.message_number)

        if not self._first_packet_seen[s]:
            self._first_msg_num[s] = pkt.message_number
            self._accumulated_msg_num[s] = 0
            self._first_packet_seen[s] = True

        relative_msg = (
            pkt.message_number - self._first_msg_num[s]
            if pkt.message_number >= self._first_msg_num[s]
            else self._accumulated_msg_num[s]
        )
        self._accumulated_msg_num[s] = relative_msg

        dt = 1.0 / self.sample_rate_hz
        packet_start_time = relative_msg * len(pkt.samples) * dt

        block: ProcessedBlock = channel.process_block(pkt.samples, packet_start_time)
        self.samples_received.emit(block)

        if block.contractions_in_block > 0:
            self.contraction_detected.emit(
                s, channel.contraction_count, float(block.times[-1])
            )

    def _reset_timing_state(self) -> None:
        for i in range(MAX_SENSORS):
            self._first_packet_seen[i] = False
            self._first_msg_num[i] = 0
            self._accumulated_msg_num[i] = 0
            self.channels[i].reset_filters()
        self._residue = b""

    def _change_state(self, state: ConnectionState, message: str = "") -> None:
        self.state = state
        self.connection_state_changed.emit(state, message)
