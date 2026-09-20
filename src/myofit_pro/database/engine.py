"""Motor de base de datos y migraciones del esquema.

Posición en el flujo
--------------------
Se crea una sola vez al arrancar la aplicación, desde
`myofit_pro.gui.app_state`. Construye el motor de SQLAlchemy, crea las
tablas que falten y aplica las migraciones pendientes. A partir de ahí,
todo el acceso a datos pasa por `myofit_pro.database.repositories`.

Estrategia de migración
-----------------------
``Base.metadata.create_all`` crea las tablas ausentes pero no modifica
las existentes, de modo que una columna añadida después del primer
despliegue nunca aparecería en una base de datos ya creada. El diccionario
`DatabaseEngine._ADDED_COLUMNS` enumera esas columnas y
`DatabaseEngine._run_migrations` las añade si faltan.

Las migraciones solo añaden: nunca eliminan ni renombran. Una base de
datos en uso contiene clientes y evaluaciones reales, y actualizar la
aplicación no debe costarle nada al entrenador.

Notes
-----
No se emplea Alembic. El esquema pertenece a una aplicación de escritorio
monousuario cuya base de datos vive en el equipo del entrenador, sin
despliegues coordinados ni migraciones que revertir, y la sobrecarga de
mantener un historial de revisiones no se justifica.

See Also
--------
myofit_pro.database.models : Esquema que este motor materializa.
myofit_pro.database.repositories : Capa de acceso a los datos.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from myofit_pro.database.models import Base, EvaluationStatus

#: Ubicación por defecto de la base de datos, en el directorio personal
#: del usuario. Contiene datos reales de clientes, por lo que queda fuera
#: del repositorio.
DEFAULT_DB_PATH = Path.home() / ".myofit_pro" / "myofit_pro.db"


class DatabaseEngine:
    """Motor de base de datos y fábrica de sesiones.

    Parameters
    ----------
    db_path : pathlib.Path or str, default=DEFAULT_DB_PATH
        Ruta del archivo SQLite. Su directorio se crea si no existe.

    Attributes
    ----------
    db_path : pathlib.Path
        Ruta del archivo en uso.
    engine : sqlalchemy.Engine
        Motor de SQLAlchemy.

    Notes
    -----
    Las sesiones se crean con ``expire_on_commit=False`` para que los
    objetos sigan siendo legibles después de confirmar la transacción.
    Sin esa opción, la capa gráfica provocaría una consulta adicional
    cada vez que leyera un atributo de un objeto ya guardado, o fallaría
    si la sesión se hubiera cerrado.
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(f"sqlite:///{self.db_path}", echo=False)
        self._session_factory: sessionmaker[Session] = sessionmaker(
            bind=self.engine, expire_on_commit=False
        )

        Base.metadata.create_all(self.engine)
        self._run_migrations()

    #: Columnas añadidas al esquema después del primer despliegue,
    #: indexadas por tabla y con su definición tal como la espera SQLite.
    _ADDED_COLUMNS: dict[str, dict[str, str]] = {
        "evaluation_sessions": {
            "status": f"VARCHAR(20) DEFAULT '{EvaluationStatus.IN_PROGRESS.value}'",
            "circumference_cm": "FLOAT",
            "repeatability_cv": "FLOAT",
        },
        "exercise_results": {
            "load_kg": "FLOAT",
        },
        "exercises": {
            "is_compound": "BOOLEAN DEFAULT 0",
        },
        "clients": {
            "first_name": "VARCHAR(80)",
            "last_name": "VARCHAR(80)",
            "sex": "VARCHAR(20)",
            "age_years": "INTEGER",
            "height_cm": "FLOAT",
            "weight_kg": "FLOAT",
            "neck_cm": "FLOAT",
            "waist_cm": "FLOAT",
            "hip_cm": "FLOAT",
            "body_fat_pct": "FLOAT",
            "body_fat_source": "VARCHAR(20)",
            "experience_level": "VARCHAR(20)",
            "days_per_week": "INTEGER",
        },
        "routines": {
            "goal": "VARCHAR(80)",
            "experience_level": "VARCHAR(20)",
            "days_per_week": "INTEGER",
            "notes": "VARCHAR(2000)",
            "source_session_ids": "VARCHAR(300)",
        },
        "routine_exercises": {
            "reps_max": "INTEGER",
            "rest_sec": "INTEGER",
            "rir": "INTEGER",
            "load_pct_min": "INTEGER",
            "load_pct_max": "INTEGER",
            "day_index": "INTEGER",
            "activation_pct": "FLOAT",
            "source": "VARCHAR(20)",
            "is_rotation": "BOOLEAN DEFAULT 0",
        },
    }

    def _run_migrations(self) -> None:
        """Añade a las tablas existentes las columnas que falten.

        Recorre `_ADDED_COLUMNS`, compara con las columnas presentes y
        ejecuta un ``ALTER TABLE`` por cada ausencia. Las tablas que no
        existen se omiten, ya que ``create_all`` las habrá creado con el
        esquema completo.

        Notes
        -----
        Dos columnas necesitan rellenar los registros anteriores además
        de crearse:

        ``evaluation_sessions.status``
            Las sesiones que ya tenían fecha de finalización se marcan
            como completadas; el resto conserva el valor por defecto.
        ``clients.first_name`` y ``clients.last_name``
            Se derivan del nombre completo partiendo por el primer
            espacio, lo que resuelve correctamente la mayoría de los
            casos y deja el resto listo para corregir a mano.
        """
        inspector = inspect(self.engine)
        existing_tables = set(inspector.get_table_names())

        for table, new_columns in self._ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue

            present = {col["name"] for col in inspector.get_columns(table)}
            missing = {
                name: ddl for name, ddl in new_columns.items() if name not in present
            }
            if not missing:
                continue

            with self.engine.begin() as conn:
                for name, ddl in missing.items():
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))

                if table == "evaluation_sessions" and "status" in missing:
                    conn.execute(
                        text(
                            "UPDATE evaluation_sessions "
                            f"SET status = '{EvaluationStatus.COMPLETED.value}' "
                            "WHERE finished_at IS NOT NULL"
                        )
                    )

                if table == "clients" and "first_name" in missing:
                    conn.execute(
                        text(
                            "UPDATE clients SET "
                            "first_name = TRIM(SUBSTR(full_name, 1, "
                            "  CASE WHEN INSTR(full_name, ' ') > 0 "
                            "       THEN INSTR(full_name, ' ') ELSE LENGTH(full_name) END)), "
                            "last_name = TRIM(SUBSTR(full_name, "
                            "  CASE WHEN INSTR(full_name, ' ') > 0 "
                            "       THEN INSTR(full_name, ' ') ELSE LENGTH(full_name) + 1 END)) "
                            "WHERE first_name IS NULL"
                        )
                    )

    def get_session(self) -> Session:
        """Abre una sesión de SQLAlchemy.

        Returns
        -------
        sqlalchemy.orm.Session
            Sesión nueva. El llamante es responsable de cerrarla,
            normalmente mediante un gestor de contexto.
        """
        return self._session_factory()


_default_engine: DatabaseEngine | None = None


def get_engine(db_path: Path | str | None = None) -> DatabaseEngine:
    """Devuelve el motor compartido, creándolo en la primera llamada.

    Parameters
    ----------
    db_path : pathlib.Path or str, optional
        Ruta de la base de datos. Solo surte efecto en la primera
        llamada; las siguientes devuelven el motor ya creado con
        independencia de este argumento. Las pruebas lo aprovechan para
        apuntar a una base temporal antes de que la aplicación construya
        la suya.

    Returns
    -------
    DatabaseEngine
        Motor compartido por toda la aplicación.
    """
    global _default_engine
    if _default_engine is None:
        _default_engine = DatabaseEngine(db_path or DEFAULT_DB_PATH)
    return _default_engine