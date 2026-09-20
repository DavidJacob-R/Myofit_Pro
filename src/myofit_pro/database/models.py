"""Esquema relacional de la aplicación.

Posición en el flujo
--------------------
Define la persistencia sobre la que operan todas las demás capas.
`myofit_pro.database.engine` crea las tablas aquí declaradas,
`myofit_pro.database.repositories` es la única capa que las consulta y
modifica, y la capa gráfica accede a ellas exclusivamente a través de
esos repositorios.

Estructura
----------
El esquema se organiza en cuatro bloques:

**Cuentas y fichas**
    `Trainer` posee `Client`. Un entrenador solo ve a sus propios
    clientes.

**Catálogo**
    `MuscleGroup` contiene `Muscle`, y cada músculo tiene sus `Exercise`.
    Lo siembra `myofit_pro.seed_data` y es común a todos los
    entrenadores.

**Medición**
    `MvcCalibration` registra la contracción voluntaria máxima de un
    cliente en un músculo. `EvaluationSession` agrupa las series medidas
    contra esa calibración; cada serie es un `ExerciseResult` con sus
    `EmgReading`.

**Prescripción**
    `Routine` y `RoutineExercise` guardan la rutina generada a partir de
    las evaluaciones.

Series temporales
-----------------
La señal en bruto —vectores de tiempo, microvoltios, envolvente y valor
eficaz— no se almacena aquí. Reside en DuckDB, que
`myofit_pro.database.duckdb_store` gestiona, porque SQLite no es adecuado
para series de alta frecuencia. `EmgReading.burst_id` es la referencia
lógica entre ambos almacenes.

Campos opcionales
-----------------
Casi todos los campos de `Client` admiten nulo. Es deliberado: el alta de
un cliente no debe bloquearse porque falte un dato antropométrico. Los
consumidores comprueban su presencia y degradan su comportamiento en vez
de fallar, y `Client.profile_is_complete` permite a la interfaz señalar
las fichas incompletas.

See Also
--------
myofit_pro.database.repositories : Acceso a estas tablas.
myofit_pro.database.duckdb_store : Almacén de las series temporales.
myofit_pro.seed_data : Siembra del catálogo.
"""

from __future__ import annotations

import datetime as dt
from enum import Enum

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Clase base declarativa de la que derivan todos los modelos."""


class Trainer(Base):
    """Cuenta de entrenador.

    Es la raíz de la propiedad de los datos: cada entrenador ve
    únicamente a sus clientes y las evaluaciones de estos.

    Attributes
    ----------
    id : int
        Clave primaria.
    full_name : str
        Nombre completo, mostrado en la interfaz y en los PDF exportados.
    email : str
        Correo electrónico. Es la credencial de acceso y debe ser único.
    password_hash : str
        Contraseña cifrada con bcrypt. La contraseña en claro no se
        almacena en ningún momento.
    created_at : datetime.datetime
        Fecha de alta de la cuenta.
    clients : list of Client
        Clientes a su cargo.
    """

    __tablename__ = "trainers"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str] = mapped_column(String(150), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.now)

    clients: Mapped[list["Client"]] = relationship(back_populates="trainer")


class Client(Base):
    """Ficha de un cliente.

    Los datos antropométricos y de contexto no son informativos: son las
    variables con las que `myofit_pro.routine_engine` ajusta volumen e
    intensidad, y las que permiten contrastar la activación medida con lo
    esperable en un perfil semejante.

    Attributes
    ----------
    id : int
        Clave primaria.
    trainer_id : int
        Entrenador propietario de la ficha.
    full_name : str
        Nombre mostrado en toda la aplicación. Se mantiene sincronizado
        con `first_name` y `last_name`, y se conserva como campo propio
        porque las fichas dadas de alta antes de la separación en dos
        campos solo disponen de él.
    first_name, last_name : str or None
        Nombre y apellidos por separado, para ordenación y búsqueda.
    goal : str
        Objetivo de entrenamiento. Debe coincidir con una clave de
        `myofit_pro.routine_engine.GOAL_SCHEMES`.
    sex : str or None
        Sexo biológico, necesario para las fórmulas de composición
        corporal.
    age_years : int or None
        Edad en años.
    height_cm, weight_kg : float or None
        Estatura en centímetros y masa en kilogramos.
    neck_cm, waist_cm, hip_cm : float or None
        Circunferencias para el método de la Marina de los Estados
        Unidos. Solo son necesarias si se quiere un porcentaje de grasa
        que no sea una estimación estadística; la de cadera únicamente en
        mujeres.
    body_fat_pct : float or None
        Porcentaje de grasa corporal.
    body_fat_source : str or None
        Procedencia del porcentaje, con los valores de
        `myofit_pro.body_composition.BodyFatSource`. Se almacena porque
        de ella depende que el dato sea utilizable como variable
        independiente: una estimación de Deurenberg es una función del
        índice de masa corporal, la edad y el sexo, de modo que no aporta
        información nueva respecto a esos tres.
    experience_level : str or None
        Nivel de experiencia, de
        `myofit_pro.body_composition.EXPERIENCE_LEVELS`. Determina el
        volumen tolerable y la proximidad al fallo muscular.
    days_per_week : int or None
        Días de entrenamiento disponibles, que seleccionan la plantilla
        de `myofit_pro.routine_engine.SPLITS`.
    birth_date : datetime.date or None
        Fecha de nacimiento.
    notes : str or None
        Observaciones libres del entrenador.
    created_at : datetime.datetime
        Fecha de alta.
    trainer : Trainer
        Entrenador propietario.
    evaluations : list of EvaluationSession
        Evaluaciones realizadas.
    calibrations : list of MvcCalibration
        Calibraciones registradas.
    """

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    trainer_id: Mapped[int] = mapped_column(ForeignKey("trainers.id"))
    full_name: Mapped[str] = mapped_column(String(150))
    first_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    goal: Mapped[str] = mapped_column(String(80), default="Hipertrofia")
    sex: Mapped[str | None] = mapped_column(String(20), nullable=True)
    age_years: Mapped[int | None] = mapped_column(nullable=True)
    height_cm: Mapped[float | None] = mapped_column(nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(nullable=True)

    neck_cm: Mapped[float | None] = mapped_column(nullable=True)
    waist_cm: Mapped[float | None] = mapped_column(nullable=True)
    hip_cm: Mapped[float | None] = mapped_column(nullable=True)

    body_fat_pct: Mapped[float | None] = mapped_column(nullable=True)
    body_fat_source: Mapped[str | None] = mapped_column(String(20), nullable=True)

    experience_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    days_per_week: Mapped[int | None] = mapped_column(nullable=True)

    birth_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.now)

    trainer: Mapped["Trainer"] = relationship(back_populates="clients")
    evaluations: Mapped[list["EvaluationSession"]] = relationship(back_populates="client")
    calibrations: Mapped[list["MvcCalibration"]] = relationship(back_populates="client")

    @property
    def bmi(self) -> float | None:
        """Índice de masa corporal, o `None` si falta estatura o masa."""
        from myofit_pro.body_composition import bmi

        return bmi(self.height_cm, self.weight_kg)

    @property
    def body_fat_is_measured(self) -> bool:
        """Si el porcentaje de grasa procede del cuerpo del cliente.

        Cierto cuando se introdujo directamente o se calculó a partir de
        circunferencias; falso cuando es la estimación derivada del
        índice de masa corporal, la edad y el sexo.
        """
        from myofit_pro.body_composition import BodyFatSource

        return self.body_fat_source in (
            BodyFatSource.MEASURED.value,
            BodyFatSource.NAVY.value,
        )

    @property
    def profile_is_complete(self) -> bool:
        """Si la ficha contiene todo lo que usa el generador de rutinas.

        El porcentaje de grasa queda fuera del recuento: siempre puede
        estimarse a partir de los demás datos, de modo que nunca falta
        por completo.
        """
        return all(
            (
                self.sex,
                self.age_years,
                self.height_cm,
                self.weight_kg,
                self.experience_level,
                self.days_per_week,
            )
        )


class MuscleGroup(Base):
    """Agrupación funcional de músculos del catálogo.

    Attributes
    ----------
    id : int
        Clave primaria.
    name : str
        Nombre del grupo, por ejemplo ``"Brazo"`` o ``"Pierna"``.
    muscles : list of Muscle
        Músculos que lo integran.
    """

    __tablename__ = "muscle_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))

    muscles: Mapped[list["Muscle"]] = relationship(back_populates="group")


class Muscle(Base):
    """Músculo evaluable del catálogo.

    Attributes
    ----------
    id : int
        Clave primaria.
    group_id : int
        Grupo al que pertenece.
    name : str
        Nombre anatómico. Debe coincidir con las claves de
        `myofit_pro.routine_engine.MUSCLE_SIZES` y con los músculos que
        enumeran los días de `myofit_pro.routine_engine.SPLITS`.
    placement_guide : str or None
        Indicaciones de colocación de los electrodos sobre este músculo,
        mostradas durante la evaluación.
    group : MuscleGroup
        Grupo al que pertenece.
    """

    __tablename__ = "muscles"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("muscle_groups.id"))
    name: Mapped[str] = mapped_column(String(120))
    placement_guide: Mapped[str | None] = mapped_column(String(500), nullable=True)

    group: Mapped["MuscleGroup"] = relationship(back_populates="muscles")


class MvcCalibration(Base):
    """Calibración de contracción voluntaria máxima.

    Es la referencia contra la que se normaliza toda la activación de una
    sesión. Sin ella, las amplitudes en microvoltios no son comparables
    entre sesiones ni entre clientes.

    Attributes
    ----------
    id : int
        Clave primaria.
    client_id : int
        Cliente calibrado.
    muscle_id : int
        Músculo calibrado. La calibración es específica del músculo.
    mvc_value_uv : float
        Media de los dos canales durante la contracción máxima, en
        microvoltios. Es el denominador del porcentaje de activación.
    mvc_channel_a_uv, mvc_channel_b_uv : float
        Pico de cada canal por separado, en microvoltios. Se conservan
        para analizar el equilibrio entre ambos sensores: una diferencia
        grande indica colocación asimétrica.
    recorded_at : datetime.datetime
        Momento de la calibración.
    client : Client
        Cliente calibrado.

    Notes
    -----
    Ambos sensores se colocan sobre el mismo músculo, en porciones
    distintas, y el valor de referencia es su media. La alternativa
    —un sensor por músculo antagonista— se descartó porque la aplicación
    evalúa un músculo por sesión.
    """

    __tablename__ = "mvc_calibrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    muscle_id: Mapped[int] = mapped_column(ForeignKey("muscles.id"))
    mvc_value_uv: Mapped[float] = mapped_column()
    mvc_channel_a_uv: Mapped[float] = mapped_column()
    mvc_channel_b_uv: Mapped[float] = mapped_column()
    recorded_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.now)

    client: Mapped["Client"] = relationship(back_populates="calibrations")


class EvaluationStatus(str, Enum):
    """Estado de una sesión de evaluación.

    Attributes
    ----------
    IN_PROGRESS : str
        La sesión está abierta. La interfaz ofrece retomarla.
    COMPLETED : str
        La sesión terminó y sus resultados alimentan el generador de
        rutinas y el informe de progreso.
    CANCELLED : str
        La sesión se abandonó de forma explícita. Sus datos se conservan
        pero no se consideran en ningún análisis.

    Notes
    -----
    El estado es un campo propio y no se infiere de ``finished_at IS
    NULL``, que resultaba ambiguo: una sesión sin terminar podía estar en
    curso o haberse abandonado semanas atrás, y la interfaz no podía
    distinguir entre ofrecer retomarla o descartarla.
    """

    IN_PROGRESS = "en_curso"
    COMPLETED = "completada"
    CANCELLED = "cancelada"


class EvaluationSession(Base):
    """Sesión de evaluación de un músculo en un cliente.

    Agrupa la calibración de referencia y todas las series de la batería
    medidas contra ella.

    Attributes
    ----------
    id : int
        Clave primaria.
    client_id : int
        Cliente evaluado.
    muscle_id : int
        Músculo evaluado. Cada sesión cubre un solo músculo.
    mvc_calibration_id : int or None
        Calibración de referencia de la sesión.
    goal : str
        Objetivo vigente en el momento de la evaluación. Se copia de la
        ficha porque esta puede cambiar después.
    status : str
        Estado, con los valores de `EvaluationStatus`.
    overall_score : float or None
        Puntuación global de la sesión, sobre 100.
    circumference_cm : float or None
        Perímetro del músculo medido con cinta métrica. Es la única
        medida directa de hipertrofia que puede tomarse en sala: la
        electromiografía de superficie mide activación eléctrica, no
        tamaño, de modo que sin esta medida no hay forma de responder si
        el músculo creció.
    repeatability_cv : float or None
        Coeficiente de variación observado al repetir un mismo ejercicio
        dentro de la sesión. Sustituye al valor de referencia de la
        literatura por el de este cliente con estos sensores, que es lo
        que determina qué diferencia entre dos mediciones puede tomarse
        en serio.
    started_at : datetime.datetime
        Inicio de la sesión.
    finished_at : datetime.datetime or None
        Fin de la sesión.
    client : Client
        Cliente evaluado.
    results : list of ExerciseResult
        Series medidas.

    See Also
    --------
    myofit_pro.progress : Comparación entre sesiones sucesivas.
    """

    __tablename__ = "evaluation_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    muscle_id: Mapped[int] = mapped_column(ForeignKey("muscles.id"))
    mvc_calibration_id: Mapped[int | None] = mapped_column(
        ForeignKey("mvc_calibrations.id"), nullable=True
    )
    goal: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default=EvaluationStatus.IN_PROGRESS.value)
    overall_score: Mapped[float | None] = mapped_column(nullable=True)
    circumference_cm: Mapped[float | None] = mapped_column(nullable=True)
    repeatability_cv: Mapped[float | None] = mapped_column(nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.now)
    finished_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)

    client: Mapped["Client"] = relationship(back_populates="evaluations")
    results: Mapped[list["ExerciseResult"]] = relationship(back_populates="session")


class Exercise(Base):
    """Ejercicio del catálogo.

    Attributes
    ----------
    id : int
        Clave primaria.
    name : str
        Nombre del ejercicio.
    muscle_id : int
        Músculo principal que trabaja.
    description : str or None
        Descripción de la ejecución.
    is_compound : bool
        Si el movimiento es multiarticular. El generador sitúa los
        compuestos al principio de cada bloque, cuando el músculo está
        descansado y puede movilizar más carga, y de ello depende el
        papel que se les asigna en
        `myofit_pro.routine_engine.role_for`.
    """

    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    muscle_id: Mapped[int] = mapped_column(ForeignKey("muscles.id"))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_compound: Mapped[bool] = mapped_column(default=False)


class ExerciseResult(Base):
    """Resultado de un ejercicio dentro de una sesión de evaluación.

    Attributes
    ----------
    id : int
        Clave primaria.
    session_id : int
        Sesión a la que pertenece.
    exercise_id : int or None
        Ejercicio del catálogo medido.
    series_count : int
        Series ejecutadas.
    avg_activation_pct, peak_activation_pct : float
        Activación media y máxima, en porcentaje de la contracción
        voluntaria máxima de la sesión.
    load_kg : float or None
        Carga empleada, en kilogramos.
    session : EvaluationSession
        Sesión a la que pertenece.
    readings : list of EmgReading
        Lecturas individuales.

    Notes
    -----
    `load_kg` es opcional pero determina que el porcentaje de activación
    sea interpretable entre sesiones. La adaptación neural reduce la
    amplitud sEMG a carga absoluta constante, de modo que un cliente que
    pasó de 20 a 26 kg y bajó del 70 % al 60 % no ha retrocedido: se ha
    vuelto más fuerte y más eficiente. Registrada la carga, el progreso
    se lee en ella y la activación indica cómo se está logrando. Cuando
    falta, la comparativa lo declara en lugar de emitir un veredicto
    infundado.
    """

    __tablename__ = "exercise_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("evaluation_sessions.id"))
    exercise_id: Mapped[int | None] = mapped_column(ForeignKey("exercises.id"), nullable=True)
    series_count: Mapped[int] = mapped_column(default=0)
    avg_activation_pct: Mapped[float] = mapped_column(default=0.0)
    peak_activation_pct: Mapped[float] = mapped_column(default=0.0)
    load_kg: Mapped[float | None] = mapped_column(nullable=True)

    session: Mapped["EvaluationSession"] = relationship(back_populates="results")
    readings: Mapped[list["EmgReading"]] = relationship(back_populates="exercise_result")


class EmgReading(Base):
    """Resumen de una serie medida.

    Attributes
    ----------
    id : int
        Clave primaria.
    exercise_result_id : int
        Ejercicio al que pertenece la serie.
    series_number : int
        Número de serie dentro del ejercicio, empezando en 1.
    channel_a_mv, channel_b_mv : float
        Amplitud de cada canal, en milivoltios.
    activation_a_pct, activation_b_pct : float
        Activación de cada canal, en porcentaje de la contracción
        voluntaria máxima.
    duration_sec : float
        Duración de la serie, en segundos.
    burst_id : str or None
        Referencia lógica al registro de DuckDB que contiene la señal en
        bruto de esta serie. No es una clave foránea real: los dos
        almacenes son independientes.
    recorded_at : datetime.datetime
        Momento de la medición.
    exercise_result : ExerciseResult
        Ejercicio al que pertenece.

    Notes
    -----
    La señal en bruto no se almacena en esta tabla. Los vectores de
    tiempo, microvoltios, envolvente y valor eficaz residen en DuckDB,
    que está diseñado para series temporales de alta frecuencia; este
    registro solo guarda el resumen y la referencia.

    See Also
    --------
    myofit_pro.database.duckdb_store : Almacén de las series en bruto.
    """

    __tablename__ = "emg_readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    exercise_result_id: Mapped[int] = mapped_column(ForeignKey("exercise_results.id"))
    series_number: Mapped[int] = mapped_column()
    channel_a_mv: Mapped[float] = mapped_column()
    channel_b_mv: Mapped[float] = mapped_column()
    activation_a_pct: Mapped[float] = mapped_column()
    activation_b_pct: Mapped[float] = mapped_column()
    duration_sec: Mapped[float] = mapped_column()
    burst_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recorded_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.now)

    exercise_result: Mapped["ExerciseResult"] = relationship(back_populates="readings")


class Routine(Base):
    """Rutina generada para un cliente.

    Attributes
    ----------
    id : int
        Clave primaria.
    client_id : int
        Cliente destinatario.
    session_id : int or None
        Evaluación principal que la originó.
    name : str
        Nombre de la rutina.
    goal, experience_level, days_per_week : str, str, int or None
        Parámetros con los que se generó. Se copian de la ficha en el
        momento de la generación porque esta puede cambiar después: una
        rutina ya entregada no se reescribe sola y debe seguir
        explicándose con los datos que la produjeron.
    source_session_ids : str or None
        Identificadores de las evaluaciones empleadas, separados por
        comas. `session_id` no basta porque una rutina puede abarcar
        varios músculos y cada músculo es una evaluación distinta. Se
        conservan para poder indicar en pantalla de qué lectura procede
        cada ejercicio.
    notes : str or None
        Avisos de la generación, uno por línea: qué se asumió por falta
        de dato y qué se prescribió sin medición. Se almacenan en lugar
        de recalcularse al abrir la rutina, para que siga reflejando la
        información disponible en su momento.
    created_at : datetime.datetime
        Fecha de generación.
    exercises : list of RoutineExercise
        Ejercicios que la componen.

    See Also
    --------
    myofit_pro.routine_engine.build_plan : Generador de la rutina.
    """

    __tablename__ = "routines"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("evaluation_sessions.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(150))
    goal: Mapped[str | None] = mapped_column(String(80), nullable=True)
    experience_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    days_per_week: Mapped[int | None] = mapped_column(nullable=True)
    source_session_ids: Mapped[str | None] = mapped_column(String(300), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.now)

    exercises: Mapped[list["RoutineExercise"]] = relationship(back_populates="routine")


class RoutineExercise(Base):
    """Ejercicio de una rutina, con su dosificación completa.

    Attributes
    ----------
    id : int
        Clave primaria.
    routine_id : int
        Rutina a la que pertenece.
    exercise_id : int
        Ejercicio del catálogo.
    sets : int
        Series prescritas.
    reps : int
        Extremo inferior del rango de repeticiones.
    reps_max : int or None
        Extremo superior del rango. Una prescripción real se expresa como
        un intervalo, no como un número exacto.
    rest_sec : int or None
        Descanso entre series, en segundos.
    rir : int or None
        Repeticiones en reserva: cuántas repeticiones adicionales podría
        completar el cliente al terminar la serie. Cero equivale al fallo
        muscular. Es la variable que fija la carga en la práctica, dado
        que la aplicación no dispone de la repetición máxima real.
    load_pct_min, load_pct_max : int or None
        Intervalo de intensidad, en porcentaje de la repetición máxima
        estimada.
    day_index : int or None
        Día de la semana al que pertenece, empezando en 1.
    activation_pct : float or None
        Activación medida que justificó la elección, o nulo si el
        ejercicio entró del catálogo sin medición.
    source : str or None
        Origen del ejercicio, con los valores de
        `myofit_pro.routine_engine.ExerciseSource`. No se deduce de
        `activation_pct` porque dos de los tres orígenes lo dejan nulo y
        no significan lo mismo para el entrenador: uno indica que el
        músculo se midió pero este ejercicio concreto no, y el otro que
        el músculo carece por completo de mediciones.
    is_rotation : bool
        Si el ejercicio procede del sorteo de rotación en lugar del
        ranking medido. Se almacena porque sin esa marca los datos no
        permitirían analizar después si un ejercicio concreto causó la
        mejora observada.
    order_index : int
        Posición dentro de su día.
    routine : Routine
        Rutina a la que pertenece.
    """

    __tablename__ = "routine_exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    routine_id: Mapped[int] = mapped_column(ForeignKey("routines.id"))
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id"))
    sets: Mapped[int] = mapped_column(default=3)
    reps: Mapped[int] = mapped_column(default=12)
    reps_max: Mapped[int | None] = mapped_column(nullable=True)
    rest_sec: Mapped[int | None] = mapped_column(nullable=True)
    rir: Mapped[int | None] = mapped_column(nullable=True)
    load_pct_min: Mapped[int | None] = mapped_column(nullable=True)
    load_pct_max: Mapped[int | None] = mapped_column(nullable=True)
    day_index: Mapped[int | None] = mapped_column(nullable=True)
    activation_pct: Mapped[float | None] = mapped_column(nullable=True)
    source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_rotation: Mapped[bool] = mapped_column(default=False)
    order_index: Mapped[int] = mapped_column(default=0)

    routine: Mapped["Routine"] = relationship(back_populates="exercises")
