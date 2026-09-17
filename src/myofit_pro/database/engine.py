from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from myofit_pro.database.models import Base, EvaluationStatus

# Carpeta estándar de datos de la app.
DEFAULT_DB_PATH = Path.home() / ".myofit_pro" / "myofit_pro.db"


class DatabaseEngine:
    """Wrapper delgado sobre el engine y el sessionmaker de SQLAlchemy."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(f"sqlite:///{self.db_path}", echo=False)
        self._session_factory: sessionmaker[Session] = sessionmaker(
            bind=self.engine, expire_on_commit=False
        )

        Base.metadata.create_all(self.engine)
        self._run_migrations()

    # Columnas agregadas después del primer release, por tabla.
    # `Base.metadata.create_all()` crea las tablas que faltan pero no
    # toca las que ya existen, así que cada columna nueva se agrega aquí
    # con el tipo tal como lo espera SQLite.
    _ADDED_COLUMNS: dict[str, dict[str, str]] = {
        "evaluation_sessions": {
            "status": f"VARCHAR(20) DEFAULT '{EvaluationStatus.IN_PROGRESS.value}'",
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
    }

    def _run_migrations(self) -> None:
        """
        Migraciones ligeras para bases de datos creadas con una versión
        anterior del esquema.

        Solo agrega columnas que falten, nunca borra ni renombra: una
        base de un release anterior tiene datos reales de clientes y
        evaluaciones, y abrir la app con la versión nueva no debería
        costarle nada al entrenador.
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
                    # Las sesiones viejas que ya tenían finished_at estaban
                    # completadas; las demás quedan como en_curso (el default).
                    conn.execute(
                        text(
                            "UPDATE evaluation_sessions "
                            f"SET status = '{EvaluationStatus.COMPLETED.value}' "
                            "WHERE finished_at IS NOT NULL"
                        )
                    )

                if table == "clients" and "first_name" in missing:
                    # Las fichas viejas solo tienen el nombre completo. Se
                    # parte en la primera palabra (nombre) y el resto
                    # (apellidos), que es lo correcto en la mayoría de los
                    # casos y deja el resto listo para corregir a mano.
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
        return self._session_factory()


# Instancia compartida a nivel de módulo, análoga a cómo MainShell
# creaba un único DatabaseService para toda la sesión de la app.
_default_engine: DatabaseEngine | None = None


def get_engine(db_path: Path | str | None = None) -> DatabaseEngine:
    global _default_engine
    if _default_engine is None:
        _default_engine = DatabaseEngine(db_path or DEFAULT_DB_PATH)
    return _default_engine