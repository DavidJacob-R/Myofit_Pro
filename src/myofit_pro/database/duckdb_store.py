"""Almacén de las series temporales de señal sEMG.

Posición en el flujo
--------------------
Segundo almacén de la aplicación, junto al SQLite que gestiona
`myofit_pro.database.engine`. Recibe la señal completa de cada serie
durante la evaluación y la devuelve cuando se consulta el historial o se
analizan los datos a posteriori.

Motivo de la separación
-----------------------
SQLite es adecuado para las entidades relacionales —fichas,
evaluaciones, resultados— pero no para vectores de miles de muestras por
segundo. DuckDB almacena en formato columnar, que es sustancialmente más
rápido de leer para análisis con pandas o numpy que filas serializadas.

Unidad de almacenamiento
------------------------
Una *ráfaga* es la señal completa capturada durante una serie de un
ejercicio o durante una calibración. Cada ráfaga conserva las cuatro
representaciones de la señal —microvoltios sin filtrar, señal filtrada,
envolvente y valor eficaz— junto a su vector de tiempos.

`myofit_pro.database.models.EmgReading.burst_id` es la referencia entre
ambos almacenes. No es una clave foránea: las dos bases de datos son
independientes y se mantienen coherentes desde la capa de aplicación,
motivo por el que existe `EmgBurstStore.delete_bursts_for_session`.

See Also
--------
myofit_pro.database.models : Esquema relacional que referencia estas
    ráfagas.
myofit_pro.ml.features : Consumidor de la señal filtrada.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

#: Ubicación por defecto del archivo DuckDB, junto a la base SQLite en el
#: directorio personal del usuario.
DEFAULT_DUCKDB_PATH = Path.home() / ".myofit_pro" / "emg_bursts.duckdb"


class EmgBurstStore:
    """Almacén de ráfagas de señal sEMG sobre DuckDB.

    Parameters
    ----------
    db_path : pathlib.Path or str, default=DEFAULT_DUCKDB_PATH
        Ruta del archivo. Su directorio se crea si no existe, y el
        esquema se materializa en la primera conexión.

    Attributes
    ----------
    db_path : pathlib.Path
        Ruta del archivo en uso.
    """

    def __init__(self, db_path: Path | str = DEFAULT_DUCKDB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(self.db_path))
        self._create_schema()

    def _create_schema(self) -> None:
        """Crea la tabla de ráfagas si no existe."""
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS emg_bursts (
                burst_id      VARCHAR PRIMARY KEY,
                client_id     INTEGER,
                session_id    INTEGER,
                muscle_id     INTEGER,
                sensor_index  INTEGER,
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
        """Guarda una ráfaga completa.

        Parameters
        ----------
        client_id, session_id, muscle_id : int
            Contexto de la medición, para poder recuperar las ráfagas
            sin consultar la base relacional.
        sensor_index : int
            Sensor que produjo la señal: 0 para el canal A y 1 para el B.
        sample_rate_hz : float
            Frecuencia de muestreo, necesaria para todo análisis
            espectral posterior.
        times : numpy.ndarray
            Instante de cada muestra, en segundos.
        micro_volts : numpy.ndarray
            Señal sin filtrar.
        filtered : numpy.ndarray
            Señal tras la cadena de filtrado.
        envelope : numpy.ndarray
            Envolvente lineal.
        rms : numpy.ndarray
            Valor eficaz deslizante.
        burst_id : str, optional
            Identificador a emplear. Si se omite se genera uno nuevo.

        Returns
        -------
        str
            Identificador de la ráfaga, que debe guardarse en
            `myofit_pro.database.models.EmgReading.burst_id` para poder
            recuperarla.
        """
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
        """Recupera una ráfaga por su identificador.

        Parameters
        ----------
        burst_id : str
            Identificador devuelto por `save_burst`.

        Returns
        -------
        dict or None
            Columnas de la ráfaga indexadas por nombre, o `None` si no
            existe.
        """
        row = self._con.execute(
            "SELECT * FROM emg_bursts WHERE burst_id = ?", [burst_id]
        ).fetchone()
        if row is None:
            return None
        columns = [d[0] for d in self._con.description]
        return dict(zip(columns, row))

    def load_bursts_for_session(self, session_id: int) -> pd.DataFrame:
        """Recupera todas las ráfagas de una sesión.

        Parameters
        ----------
        session_id : int
            Sesión de evaluación.

        Returns
        -------
        pandas.DataFrame
            Una fila por ráfaga, ordenadas por momento de registro.
        """
        return self._con.execute(
            "SELECT * FROM emg_bursts WHERE session_id = ? ORDER BY recorded_at",
            [session_id],
        ).fetchdf()

    def load_bursts_for_client(self, client_id: int) -> pd.DataFrame:
        """Recupera todas las ráfagas históricas de un cliente.

        Parameters
        ----------
        client_id : int
            Cliente.

        Returns
        -------
        pandas.DataFrame
            Una fila por ráfaga, ordenadas por momento de registro.
        """
        return self._con.execute(
            "SELECT * FROM emg_bursts WHERE client_id = ? ORDER BY recorded_at",
            [client_id],
        ).fetchdf()

    def delete_bursts_for_session(self, session_id: int) -> int:
        """Elimina las ráfagas de una sesión.

        Parameters
        ----------
        session_id : int
            Sesión cuyas ráfagas se eliminan.

        Returns
        -------
        int
            Ráfagas eliminadas.

        Notes
        -----
        Se invoca al borrar una evaluación desde el historial. Sin esta
        llamada, eliminar el registro relacional dejaría aquí las series
        temporales ocupando espacio sin que nada las referenciara, ya
        que la integridad entre los dos almacenes no la garantiza el
        motor sino la capa de aplicación.
        """
        row = self._con.execute(
            "SELECT count(*) FROM emg_bursts WHERE session_id = ?", [session_id]
        ).fetchone()
        self._con.execute("DELETE FROM emg_bursts WHERE session_id = ?", [session_id])
        return int(row[0]) if row else 0

    def close(self) -> None:
        """Cierra la conexión con el archivo."""
        self._con.close()


_default_store: EmgBurstStore | None = None


def get_burst_store(db_path: Path | str | None = None) -> EmgBurstStore:
    """Devuelve el almacén compartido, creándolo en la primera llamada.

    Parameters
    ----------
    db_path : pathlib.Path or str, optional
        Ruta del archivo. Solo surte efecto en la primera llamada.

    Returns
    -------
    EmgBurstStore
        Almacén compartido por toda la aplicación.
    """
    global _default_store
    if _default_store is None:
        _default_store = EmgBurstStore(db_path or DEFAULT_DUCKDB_PATH)
    return _default_store
