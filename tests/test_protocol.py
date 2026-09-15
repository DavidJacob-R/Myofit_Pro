"""Pruebas del parser binario (myofit_pro.sensors.protocol)."""

import struct

import numpy as np
import pytest

from myofit_pro.sensors.protocol import (
    HEADER_SIZE,
    PACKET_SIZE,
    SAMPLES_PER_PACKET,
    Packet,
    find_next_sync,
    parse_available,
    raw_to_battery_volts,
    try_parse_packet,
)


def make_packet_bytes(sensor_one_based: int, msg_num: int, battery_raw: int,
                       samples: list[int]) -> bytes:
    """Construye un paquete de 246 bytes válido para pruebas."""
    assert len(samples) == SAMPLES_PER_PACKET
    header = bytes([
        0xFF, 0xFF,
        sensor_one_based,
        msg_num & 0xFF, (msg_num >> 8) & 0xFF, (msg_num >> 16) & 0xFF,
        battery_raw & 0xFF, (battery_raw >> 8) & 0xFF,
    ])
    body = struct.pack(f"<{SAMPLES_PER_PACKET}H", *samples)
    packet = header + body
    assert len(packet) == PACKET_SIZE
    return packet


def test_raw_to_battery_volts():
    # raw=16384 (fondo de escala) -> 16384/16384*7.2 = 7.2V
    assert raw_to_battery_volts(16384) == 7.2
    assert raw_to_battery_volts(0) == 0.0


def test_try_parse_packet_valid():
    samples = list(range(SAMPLES_PER_PACKET))
    buf = make_packet_bytes(sensor_one_based=1, msg_num=42, battery_raw=8000, samples=samples)

    pkt = try_parse_packet(buf, 0)
    assert pkt is not None
    assert pkt.sensor_index == 0  # 1-based -> 0-based
    assert pkt.message_number == 42
    assert np.array_equal(pkt.samples, np.array(samples, dtype="<u2"))


def test_try_parse_packet_invalid_sync():
    buf = bytearray(make_packet_bytes(1, 1, 8000, [0] * SAMPLES_PER_PACKET))
    buf[0] = 0x00  # romper el sync
    assert try_parse_packet(bytes(buf), 0) is None


def test_try_parse_packet_invalid_sensor():
    buf = make_packet_bytes(sensor_one_based=9, msg_num=1, battery_raw=8000,
                             samples=[0] * SAMPLES_PER_PACKET)
    assert try_parse_packet(buf, 0) is None


def test_find_next_sync():
    buf = b"\x00\x00\x00" + b"\xff\xff" + b"\x00"
    assert find_next_sync(buf, 0) == 3
    assert find_next_sync(b"\x00\x00\x00", 0) == -1


def test_parse_available_single_packet():
    samples = [100] * SAMPLES_PER_PACKET
    buf = make_packet_bytes(1, 5, 8000, samples)

    packets, leftover = parse_available(buf)
    assert len(packets) == 1
    assert leftover == b""
    assert packets[0].message_number == 5


def test_parse_available_two_packets_back_to_back():
    p1 = make_packet_bytes(1, 1, 8000, [10] * SAMPLES_PER_PACKET)
    p2 = make_packet_bytes(2, 2, 8000, [20] * SAMPLES_PER_PACKET)
    buf = p1 + p2

    packets, leftover = parse_available(buf)
    assert len(packets) == 2
    assert leftover == b""
    assert packets[0].sensor_index == 0
    assert packets[1].sensor_index == 1


def test_parse_available_partial_packet_kept_as_residue():
    p1 = make_packet_bytes(1, 1, 8000, [10] * SAMPLES_PER_PACKET)
    partial = p1[:100]  # paquete incompleto al final
    buf = p1 + partial

    packets, leftover = parse_available(buf)
    assert len(packets) == 1
    assert leftover == partial


def test_parse_available_garbage_before_sync_is_skipped():
    garbage = b"\x01\x02\x03\x04"
    p1 = make_packet_bytes(1, 1, 8000, [10] * SAMPLES_PER_PACKET)
    buf = garbage + p1

    packets, leftover = parse_available(buf)
    assert len(packets) == 1
    assert leftover == b""


def test_parse_available_corrupt_packet_resyncs():
    """Un paquete con sensor inválido en medio del buffer no debe tumbar el parseo."""
    good1 = make_packet_bytes(1, 1, 8000, [1] * SAMPLES_PER_PACKET)
    corrupt = make_packet_bytes(9, 2, 8000, [2] * SAMPLES_PER_PACKET)  # sensor=9 inválido
    good2 = make_packet_bytes(2, 3, 8000, [3] * SAMPLES_PER_PACKET)
    buf = good1 + corrupt + good2

    packets, _leftover = parse_available(buf)
    # Debe encontrar al menos el primer paquete bueno; el corrupto se
    # descarta al buscar el siguiente sync.
    assert len(packets) >= 1
    assert packets[0].message_number == 1
