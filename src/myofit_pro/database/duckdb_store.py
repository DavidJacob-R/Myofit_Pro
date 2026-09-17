"""
Almacenamiento de las señales EMG crudas/procesadas ("ráfagas" o
"bursts") usando DuckDB. Esto libera a SQLite (usado por
database/models.py) de guardar series de tiempo de alta frecuencia
— SQLite es ideal para las entidades relacionales (clientes,
evaluaciones, resultados) pero no está pensado para arrays de miles de
muestras por segundo.

Cada burst es toda la señal capturada durante una serie/set de
ejercicio o durante la calibración MVC. `SQLite.EmgReading.burst_id`
apunta a `EmgReading.id` guardado en Sqlite; aquí guardamos el
contenido pesado (arrays de tiempo, µV, envolvente, RMS) indexado por
el mismo id, usando formato columnar (mucho más rápido para análisis
posterior con pandas/numpy que filas JSON en SQLite).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

DEFAULT_DUCKDB_PATH = Path.home() / ".myofit_pro" / "emg_bursts.duckdb"


class EmgBurstStore:
    def __init__(self, db_path: Path | str = DEFAULT_DUCKDB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(self.db_path))
        self._create_schema()

    def _create_schema(self) -> None:
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS emg_bursts (
                burst_id      VARCHAR PRIMARY KEY,
                client_id     INTEGER,
                session_id    INTEGER,
                muscle_id     INTEGER,
                sensor_index  INTEGER,      -- 0 = A, 1 = B
                sample_rate_hz DOUBLE,
                recorded_at   TIMESTAMP DEFAULT current_timestamp,
                time_sec      DOUBLE[],
                micro_volts   DOUBLE[],
                filtered      DOUBLE[],
                envelope      DOUBLE[],
                rms           DOUBLE[]
            )
            """
        )

    def save_burst(
        self,
        client_id: int,
        session_id: int,
        muscle_id: int,
        sensor_index: int,
        sample_rate_hz: float,
        times: np.ndarray,
        micro_volts: np.ndarray,
        filtered: np.ndarray,
        envelope: np.ndarray,
        rms: np.ndarray,
        burst_id: str | None = None,
    ) -> str:
        """Guarda una ráfaga completa y devuelve su burst_id (para enlazar con SQLite)."""
        burst_id = burst_id or str(uuid.uuid4())
        self._con.execute(
            """
            INSERT INTO emg_bursts (
                burst_id, client_id, session_id, muscle_id, sensor_index,
                sample_rate_hz, time_sec, micro_volts, filtered, envelope, rms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                burst_id, client_id, session_id, muscle_id, sensor_index,
                sample_rate_hz,
                times.tolist(), micro_volts.tolist(), filtered.tolist(),
                envelope.tolist(), rms.tolist(),
            ],
        )
        return burst_id

    def load_burst(self, burst_id: str) -> dict | None:
        row = self._con.execute(
            "SELECT * FROM emg_bursts WHERE burst_id = ?", [burst_id]
        ).fetchone()
        if row is None:
            return None
        columns = [d[0] for d in self._con.description]
        return dict(zip(columns, row))

    def load_bursts_for_session(self, session_id: int) -> pd.DataFrame:
        """Devuelve todas las ráfagas de una sesión como DataFrame (para ML/análisis)."""
        return self._con.execute(
            "SELECT * FROM emg_bursts WHERE session_id = ? ORDER BY recorded_at",
            [session_id],
        ).fetchdf()

    def load_bursts_for_client(self, client_id: int) -> pd.DataFrame:
        """Todas las ráfagas históricas de un cliente — insumo típico para entrenar ML."""
        return self._con.execute(
            "SELECT * FROM emg_bursts WHERE client_id = ? ORDER BY recorded_at",
            [client_id],
        ).fetchdf()

    def delete_bursts_for_session(self, session_id: int) -> int:
        """
        Borra las señales guardadas de una evaluación y devuelve cuántas
        eran. Se usa al eliminar la evaluación desde el historial: si
        solo se borrara el registro de SQLite, los arrays de señal se
        quedarían aquí ocupando espacio sin que nada los referencie.
        """
        row = self._con.execute(
            "SELECT count(*) FROM emg_bursts WHERE session_id = ?", [session_id]
        ).fetchone()
        self._con.execute("DELETE FROM emg_bursts WHERE session_id = ?", [session_id])
        return int(row[0]) if row else 0

    def close(self) -> None:
        self._con.close()


_default_store: EmgBurstStore | None = None


def get_burst_store(db_path: Path | str | None = None) -> EmgBurstStore:
    global _default_store
    if _default_store is None:
        _default_store = EmgBurstStore(db_path or DEFAULT_DUCKDB_PATH)
    return _default_store
