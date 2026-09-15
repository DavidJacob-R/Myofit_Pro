"""
Parser del protocolo binario de los sensores MYOblue v1.2 (elemyo).

Formato de cada paquete (246 bytes):
    [0..1]    Marcador de inicio: 0xFF 0xFF
    [2]       Número de sensor (1..8)
    [3..5]    Número de mensaje (24 bits, little-endian)
    [6..7]    Voltaje de batería raw (16 bits, little-endian)
    [8..245]  119 muestras EMG de 16 bits (little-endian)

Total = 8 bytes header + 119 x 2 = 246 bytes

Esta es la misma lógica que se implementó en C# (MyoBlueProtocol.cs),
solo que usando numpy para vectorizar el parseo de las 119 muestras
en vez de un loop manual.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

PACKET_SIZE = 246
SAMPLES_PER_PACKET = 119
HEADER_SIZE = 8
SYNC_BYTE = 0xFF
SYNC_MARKER = bytes([SYNC_BYTE, SYNC_BYTE])
MAX_SENSORS = 8
DEFAULT_BAUD_RATE = 1_000_000

# Struct format: 119 unsigned shorts little-endian
_SAMPLES_STRUCT = struct.Struct(f"<{SAMPLES_PER_PACKET}H")


@dataclass(frozen=True, slots=True)
class Packet:
    """Un paquete ya parseado proveniente de un sensor MYOblue."""

    sensor_index: int          # 0..7 (ya convertido de 1-based a 0-based)
    message_number: int        # 24-bit, usado para reconstruir el tiempo
    battery_volts: float
    samples: np.ndarray        # dtype=uint16, shape=(119,)


def raw_to_battery_volts(raw: int) -> float:
    """raw / 16384 * 0.6 * 6 * 2 = raw / 16384 * 7.2 V"""
    return round(raw / 16384.0 * 0.6 * 6.0 * 2.0, 2)


def find_next_sync(buf: bytes, start: int) -> int:
    """Busca el próximo 0xFF 0xFF. Devuelve el índice o -1 si no hay."""
    return buf.find(SYNC_MARKER, start)


def try_parse_packet(buf: bytes, offset: int) -> Packet | None:
    """Intenta parsear un paquete completo a partir de offset. None si es inválido."""
    if offset + PACKET_SIZE > len(buf):
        return None
    if buf[offset] != SYNC_BYTE or buf[offset + 1] != SYNC_BYTE:
        return None

    sensor_one_based = buf[offset + 2]
    if not (1 <= sensor_one_based <= MAX_SENSORS):
        return None
    sensor_index = sensor_one_based - 1

    msg_num = buf[offset + 3] | (buf[offset + 4] << 8) | (buf[offset + 5] << 16)

    battery_raw = buf[offset + 6] | (buf[offset + 7] << 8)
    battery = raw_to_battery_volts(battery_raw)

    data_start = offset + HEADER_SIZE
    samples = np.frombuffer(
        buf, dtype="<u2", count=SAMPLES_PER_PACKET, offset=data_start
    ).copy()  # copy: el buffer original puede reciclarse

    return Packet(sensor_index, msg_num, battery, samples)


def parse_available(buf: bytes) -> tuple[list[Packet], bytes]:
    """
    Parsea todos los paquetes completos disponibles en `buf`.

    Devuelve (lista_de_paquetes, residuo_no_consumido). El residuo se
    debe anteponer a la siguiente lectura del puerto serial.
    """
    packets: list[Packet] = []
    length = len(buf)
    pos = 0

    if length < 2:
        return packets, buf

    if buf[0] != SYNC_BYTE or buf[1] != SYNC_BYTE:
        sync = find_next_sync(buf, 0)
        if sync < 0:
            # Nada reconocible; conservar solo el último byte por si el
            # sync llegó partido a la mitad entre dos lecturas.
            return packets, buf[-1:] if length > 0 else buf
        pos = sync

    while pos + PACKET_SIZE <= length:
        pkt = try_parse_packet(buf, pos)
        if pkt is not None:
            packets.append(pkt)
            pos += PACKET_SIZE
        else:
            nxt = find_next_sync(buf, pos + 1)
            if nxt < 0:
                break
            pos = nxt

    return packets, buf[pos:]
