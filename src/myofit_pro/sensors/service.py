"""Servicio de captura de los sensores MYOblue v1.2.

Posición en el flujo
--------------------
Punto de entrada del subsistema de adquisición y única clase con la que
habla la capa gráfica. Lee del puerto serie en un hilo propio, delega la
decodificación en `myofit_pro.sensors.protocol`, el procesado en
`myofit_pro.sensors.channel`, y emite el resultado como señales de Qt.

Transporte
----------
Los sensores se comunican con un receptor USB por radiofrecuencia
propietaria en 2,4 GHz. El sistema operativo expone ese receptor como un
puerto serie virtual, motivo por el que se emplea `pyserial` y no una
biblioteca de Bluetooth: el enlace entre sensor y receptor no es
Bluetooth estándar ni está documentado públicamente.

Concurrencia
------------
La lectura del puerto ocurre en un hilo en segundo plano, mientras que la
interfaz vive en el hilo principal. El servicio hereda de
`PySide6.QtCore.QObject` y publica sus resultados mediante señales: Qt
encola automáticamente las emisiones que cruzan de un hilo a otro, de
modo que la interfaz nunca toca el estado del hilo lector.

Reconstrucción del tiempo
-------------------------
Cada paquete trae un contador de mensaje de 24 bits. El servicio guarda
el primero de cada sensor y calcula el resto de instantes como
desplazamientos relativos a él, lo que sitúa el origen de tiempos en el
inicio de la captura con independencia de cuánto llevara encendido el
sensor.
"""

from __future__ import annotations

import threading
import time
from enum import Enum, auto

import serial
import serial.tools.list_ports
from PySide6.QtCore import QObject, Signal

from myofit_pro.sensors.channel import MyoBlueChannel, ProcessedBlock
from myofit_pro.sensors.protocol import DEFAULT_BAUD_RATE, MAX_SENSORS, Packet, parse_available


class ConnectionState(Enum):
    """Estado del enlace con el receptor USB.

    Attributes
    ----------
    DISCONNECTED : enum.auto
        Sin puerto abierto.
    CONNECTING : enum.auto
        Abriendo el puerto.
    CONNECTED : enum.auto
        Puerto abierto y disponible para capturar.
    ERROR : enum.auto
        El puerto falló al abrirse o durante la lectura. El mensaje que
        acompaña a `MyoBlueService.connection_state_changed` describe la
        causa.
    """

    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    ERROR = auto()


class MyoBlueService(QObject):
    """Servicio de captura de los sensores MYOblue.

    Gestiona el puerto serie, el hilo de lectura y un
    `myofit_pro.sensors.channel.MyoBlueChannel` por sensor.

    Parameters
    ----------
    sensors_in_use : int, default=2
        Sensores cuyos paquetes se procesan. Los de índice superior se
        descartan, aunque el receptor los reciba.
    parent : PySide6.QtCore.QObject, optional
        Padre en la jerarquía de Qt.

    Attributes
    ----------
    samples_received : PySide6.QtCore.Signal
        Emite un `myofit_pro.sensors.channel.ProcessedBlock` por cada
        paquete procesado.
    battery_updated : PySide6.QtCore.Signal
        Emite ``(índice de sensor, voltios)`` cuando la tensión cambia
        de forma apreciable.
    contraction_detected : PySide6.QtCore.Signal
        Emite ``(índice de sensor, total acumulado, segundos)`` al
        detectarse una contracción.
    connection_state_changed : PySide6.QtCore.Signal
        Emite ``(ConnectionState, mensaje)`` en cada transición.
    channels : list of MyoBlueChannel
        Un canal por sensor posible, con sus filtros independientes.
    state : ConnectionState
        Estado actual del enlace.
    current_port : str or None
        Puerto abierto, o `None` si no hay ninguno.

    Examples
    --------
    >>> service = MyoBlueService()                      # doctest: +SKIP
    >>> service.samples_received.connect(on_samples)    # doctest: +SKIP
    >>> service.connect_serial(MyoBlueService.available_ports()[0])
    ...                                                 # doctest: +SKIP
    >>> service.start()                                 # doctest: +SKIP
    >>> service.stop()                                  # doctest: +SKIP
    >>> service.disconnect_serial()                     # doctest: +SKIP
    """

    samples_received = Signal(object)
    battery_updated = Signal(int, float)
    contraction_detected = Signal(int, int, float)
    connection_state_changed = Signal(object, str)

    def __init__(self, sensors_in_use: int = 2, parent: QObject | None = None):
        super().__init__(parent)

        self.sensors_in_use = sensors_in_use
        self.sample_rate_hz = 1000.0
        self.bandpass_low = 2.0
        self.bandpass_high = 499.0
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
        """Enumera los puertos serie del sistema.

        Returns
        -------
        list of str
            Nombres de dispositivo. El receptor USB aparece entre ellos
            cuando está conectado; el servicio no lo identifica por sí
            mismo, así que es el usuario quien lo elige.
        """
        return [p.device for p in serial.tools.list_ports.comports()]

    # ── Conexión ─────────────────────────────────────────────────────

    def connect_serial(self, port_name: str) -> bool:
        """Abre el puerto del receptor USB.

        Parameters
        ----------
        port_name : str
            Nombre de dispositivo, tomado de `available_ports`.

        Returns
        -------
        bool
            Cierto si el puerto quedó abierto. Ante un fallo el estado
            pasa a `ConnectionState.ERROR` con el mensaje del sistema.
        """
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

    def disconnect_serial(self) -> None:
        """Detiene la captura y cierra el puerto."""
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
        """Arranca el hilo de lectura.

        No hace nada si el puerto no está abierto o si el hilo ya está en
        marcha. Reinicia el estado temporal y los filtros de todos los
        canales, de modo que cada captura empiece en cero.
        """
        if self._serial is None or not self._serial.is_open:
            return
        if self._reader_thread is not None and self._reader_thread.is_alive():
            return

        self._reset_timing_state()
        self._stop_event.clear()
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def stop(self) -> None:
        """Detiene el hilo de lectura y espera a que termine."""
        self._stop_event.set()
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=1.0)
        self._reader_thread = None

    def reset_counters(self) -> None:
        """Pone a cero el contador de contracciones de todos los canales."""
        for ch in self.channels:
            ch.reset_counter()

    @property
    def is_connected(self) -> bool:
        """Si hay un puerto abierto y disponible."""
        return self.state == ConnectionState.CONNECTED

    def close(self) -> None:
        """Libera todos los recursos del servicio."""
        self.disconnect_serial()

    # ── Internos ──────────────────────────────────────────────────────

    def _reader_loop(self) -> None:
        """Lee del puerto y procesa paquetes hasta recibir la señal de parada.

        Se ejecuta en el hilo en segundo plano. Conserva entre
        iteraciones el residuo que devuelve
        `myofit_pro.sensors.protocol.parse_available`, ya que un paquete
        puede quedar partido entre dos lecturas.
        """
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
        """Procesa un paquete y emite las señales que correspondan.

        Parameters
        ----------
        pkt : myofit_pro.sensors.protocol.Packet
            Paquete decodificado. Se descarta si su sensor queda fuera de
            `sensors_in_use`.
        """
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
        """Reinicia el origen de tiempos, los filtros y el residuo."""
        for i in range(MAX_SENSORS):
            self._first_packet_seen[i] = False
            self._first_msg_num[i] = 0
            self._accumulated_msg_num[i] = 0
            self.channels[i].reset_filters()
        self._residue = b""

    def _change_state(self, state: ConnectionState, message: str = "") -> None:
        """Actualiza el estado y lo notifica por señal."""
        self.state = state
        self.connection_state_changed.emit(state, message)
