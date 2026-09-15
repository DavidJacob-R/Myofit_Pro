"""
Equivalente a DatabaseService.cs: gestiona la conexión SQLite y la
creación de tablas. El resto de la app pide una Session vía
`get_session()` en vez de tocar el engine directamente.
"""

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

    def _run_migrations(self) -> None:
        """
        Migraciones ligeras para bases de datos creadas con una versión
        anterior del esquema. `Base.metadata.create_all()` crea tablas
        que faltan pero NO agrega columnas nuevas a tablas existentes,
        así que las columnas añadidas después del primer release hay
        que agregarlas a mano aquí.

        Es idempotente: revisa si la columna ya existe antes de tocar nada.
        """
        inspector = inspect(self.engine)

        if "evaluation_sessions" not in inspector.get_table_names():
            return

        columns = {col["name"] for col in inspector.get_columns("evaluation_sessions")}

        if "status" not in columns:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE evaluation_sessions "
                        f"ADD COLUMN status VARCHAR(20) DEFAULT '{EvaluationStatus.IN_PROGRESS.value}'"
                    )
                )
                # Las sesiones viejas que ya tenían finished_at estaban
                # completadas; las demás quedan como en_curso (el default).
                conn.execute(
                    text(
                        "UPDATE evaluation_sessions "
                        f"SET status = '{EvaluationStatus.COMPLETED.value}' "
                        "WHERE finished_at IS NOT NULL"
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